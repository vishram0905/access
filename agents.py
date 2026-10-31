"""Command line for starting, stopping and watching the data agents (tooling for Layer 0).

We run the Scout, Scraper, Info Critic, Auditor and Sentinel as separate background processes, each with its own
log and pid file in data/agents/, so one crash never takes the others down.

  python agents.py start     # launch every agent that is not running or paused
  python agents.py status    # last log line of each agent, plus database counts
  python agents.py watch     # live dashboard of all agents (Ctrl+C to exit)
  python agents.py stop
"""
import os
import signal
import subprocess
import sys
from pathlib import Path

from access.db import connect
from access.logtail import tail_lines

ROOT = Path(__file__).parent
LOGS = ROOT / "data" / "agents"
NAMES = ["scout", "scraper", "critic", "auditor", "sentinel"]


def start():
    """Launch each agent in its own session, skipping the ones already running or listed in paused_agents."""
    LOGS.mkdir(parents=True, exist_ok=True)
    from access import runtime
    paused = set(runtime.get().get("paused_agents", []))
    for name in NAMES:
        pid_file = LOGS / f"{name}.pid"
        if name in paused:
            print(f"{name:<8} paused (runtime.json paused_agents)")
            continue
        if pid_file.exists() and _alive(int(pid_file.read_text())):
            print(f"{name:<8} already running")
            continue
        log = open(LOGS / f"{name}.log", "a")
        p = subprocess.Popen([sys.executable, "-u", "-m", "access.agents", name], cwd=ROOT,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        pid_file.write_text(str(p.pid))
        print(f"{name:<8} started (pid {p.pid})")


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop():
    for name in NAMES:
        f = LOGS / f"{name}.pid"
        if f.exists():
            try:
                os.killpg(int(f.read_text()), signal.SIGTERM)
                print(f"{name:<8} stopped")
            except OSError:
                print(f"{name:<8} not running")
            f.unlink()


def status():
    for name in NAMES:
        f = LOGS / f"{name}.pid"
        up = f.exists() and _alive(int(f.read_text()))
        last = ""
        lf = LOGS / f"{name}.log"
        if lf.exists():
            lines = [l for l in tail_lines(lf, 400) if l.strip() and "AFC" not in l]
            last = lines[-1][:150] if lines else ""
        print(f"{'●' if up else '○'} {name:<8} {last}")
    with connect() as con:
        sites = dict(con.execute("SELECT status, COUNT(*) FROM sites GROUP BY status").fetchall())
        pages = dict(con.execute("SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall())
        lst = dict(con.execute("SELECT decision, COUNT(*) FROM listings WHERE data LIKE '%\"schema_version\": \"2.0\"%' "
                               "GROUP BY decision").fetchall())
        ptype = con.execute("SELECT json_extract(data,'$.provider_type'), COUNT(*) FROM listings WHERE decision!='rejected' "
                            "AND data LIKE '%\"schema_version\": \"2.0\"%' GROUP BY 1 ORDER BY 2 DESC").fetchall()
        region = con.execute("SELECT json_extract(data,'$.region'), COUNT(*) FROM listings WHERE decision!='rejected' "
                             "AND data LIKE '%\"schema_version\": \"2.0\"%' GROUP BY 1 ORDER BY 2 DESC").fetchall()
    alerts = LOGS / "sentinel_state.json"
    if alerts.exists():
        import json as _j
        open_ = _j.loads(alerts.read_text()).get("alerted", {})
        print(f"\nOpen alerts: {', '.join(open_) if open_ else 'none'}  (history: data/agents/alerts.log)")
    print(f"\nSites:    {sites}\nPages:    {pages}\nVerified: {lst}")
    print("By provider type:", {r[0]: r[1] for r in ptype})
    print("By region:       ", {r[0]: r[1] for r in region})


def watch(every: int = 10, lines: int = 6):
    import time
    try:
        while True:
            out = [f"ACCESS data agents  ·  {time.strftime('%H:%M:%S')}  ·  refreshes every {every}s  ·  Ctrl+C to exit", ""]
            for name in NAMES:
                f = LOGS / f"{name}.pid"
                up = f.exists() and _alive(int(f.read_text()))
                lf = LOGS / f"{name}.log"
                recent = [l for l in tail_lines(lf, 400) if l.strip() and "AFC" not in l][-lines:] \
                    if lf.exists() else []
                out.append(f"{'●' if up else '○'} {name.upper():<8} {'running' if up else 'stopped'}")
                out += [f"    {l[:140]}" for l in recent] or ["    (no activity yet)"]
                out.append("")
            with connect() as con:
                sites = dict(con.execute("SELECT status, COUNT(*) FROM sites GROUP BY status").fetchall())
                pages = dict(con.execute("SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall())
                ok = con.execute("SELECT COUNT(*) FROM listings WHERE decision!='rejected' "
                                 "AND data LIKE '%\"schema_version\": \"2.0\"%'").fetchone()[0]
                hour = con.execute("SELECT COUNT(*) FROM listings WHERE verified_at > datetime('now','-1 hour')").fetchone()[0]
            out.append(f"Sites  · to crawl {sites.get('new', 0)} · crawling {sites.get('crawling', 0)} · "
                       f"done {sites.get('done', 0)} · unreachable {sites.get('failed', 0)}")
            out.append(f"Pages  · waiting {pages.get('candidate', 0)} · annotating {pages.get('annotating', 0)} · "
                       f"awaiting critics {pages.get('annotated', 0)} · not programmes "
                       f"{pages.get('not_programme', 0) + pages.get('index_page', 0) + pages.get('duplicate', 0)}")
            out.append(f"Verified programmes: {ok}   (last hour: {hour})")
            from access.resources import budget_report, snapshot
            out.append(snapshot())
            out.append("Daily cloud tokens · " + budget_report())
            st_file = LOGS / "sentinel_state.json"
            if st_file.exists():
                import json as _j
                open_ = _j.loads(st_file.read_text()).get("alerted", {})
                out.append("⚠️ OPEN ALERTS: " + ", ".join(open_) if open_ else "Sentinel: all healthy")
            print("\033[2J\033[H" + "\n".join(out), flush=True)
            time.sleep(every)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    {"start": start, "stop": stop, "status": status, "watch": watch}[sys.argv[1] if len(sys.argv) > 1 else "status"]()
