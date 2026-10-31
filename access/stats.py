"""Live system statistics for the app's optional "Stats" panel (tooling).

Everything here runs every few seconds while the panel is open, so we stick to cheap queries: counts over the
last hour, log tails and process checks.
"""
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import psutil

from . import resources, runtime
from .config import DATA, GEMINI_FLASH, ROLES
from .db import connect
from .fetchlog import HANDSHAKE, LOG_DB
from .logtail import tail_lines

AGENTS = DATA / "agents"
AGENT_NAMES = ["scout", "scraper", "critic", "auditor", "sentinel"]


def _iso_ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _log_count(agent: str, pattern: str, minutes: int = 60) -> int:
    """Count log lines from the last `minutes` that match `pattern`.

    Log lines carry only a clock time, so we compare HH:MM:SS strings and handle the window crossing midnight.
    """
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime("%H:%M:%S")
    now = datetime.now().strftime("%H:%M:%S")
    rx = re.compile(pattern)
    n = 0
    for line in tail_lines(AGENTS / f"{agent}.log", 6000, 4_000_000):
        t = line[:8]
        if re.match(r"\d\d:\d\d:\d\d", t) and (cutoff <= t <= now if cutoff < now else t >= cutoff) and rx.search(line):
            n += 1
    return n


def crawler(window: int = 3600) -> dict:
    """Summarise fetches over the last hour: outcomes, requests per minute and handshake latency percentiles."""
    con = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
    since = time.time() - window
    rows = con.execute("SELECT outcome, ms, at FROM fetches WHERE at > ?", (since,)).fetchall()
    con.close()
    out = {}
    for o, _, _ in rows:
        out[o] = out.get(o, 0) + 1
    lat = sorted(ms for o, ms, _ in rows if ms and o in HANDSHAKE)
    per_min = [0] * 60
    for _, _, at in rows:
        per_min[min(59, int((at - since) / 60))] += 1
    hs = sum(out.get(o, 0) for o in HANDSHAKE)
    return {"requests": len(rows), "per_min": per_min, "handshake_pct": round(100 * hs / max(1, len(rows))),
            "ok": out.get("ok", 0), "refused": out.get("refused", 0), "robots": out.get("robots", 0),
            "timeouts": out.get("timeout", 0) + out.get("connection", 0) + out.get("ssl", 0),
            "not_found": out.get("not_found", 0),
            "p50_ms": lat[len(lat) // 2] if lat else None, "p95_ms": lat[int(len(lat) * .95)] if lat else None}


def pipeline() -> dict:
    """Count sites, pages and judge decisions, plus what the scraper and critic did in the last hour."""
    hour = _iso_ago(3600)
    with connect() as con:
        sites = dict(con.execute("SELECT status, COUNT(*) FROM sites GROUP BY status").fetchall())
        pages = dict(con.execute("SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall())
        new_pages = con.execute("SELECT COUNT(*) FROM sources WHERE first_seen >= ?", (hour,)).fetchone()[0]
        dec = dict(con.execute("SELECT decision, COUNT(*) FROM listings WHERE verified_at >= ? GROUP BY decision",
                               (hour,)).fetchall())
        render_q = con.execute("SELECT COUNT(*) FROM render_queue").fetchone()[0] if con.execute(
            "SELECT name FROM sqlite_master WHERE name='render_queue'").fetchone() else 0
    return {"sites": sites, "pages": pages, "new_pages_1h": new_pages, "decisions_1h": dec, "render_queue": render_q,
            "annotated_1h": _log_count("scraper", r"\[annotator\] (annotated|index_page|not_programme)"),
            "dup_skips_1h": _log_count("critic", r"\[critic\] = "),
            "judge_failures_1h": _log_count("critic", r"\[critic\] ! ")}


def _fmt_wait(s: float) -> str:
    return f"{int(s // 3600)}h{int(s % 3600 // 60):02d}m" if s >= 3600 else f"{int(s // 60)}m{int(s % 60):02d}s"


def models() -> list[dict]:
    """List every model the agents can use with its state: ready, cooling down, out of daily budget or disabled."""
    rows, seen = [], set()
    specs = [("annotator", GEMINI_FLASH)] + [("judge", s) for s in ROLES["judge_pool"]] + \
            [("embedder", s) for s in ROLES["embedder"]]
    for role, spec in specs:
        for m in (spec.model, *spec.fallbacks):
            if m in seen:
                continue
            seen.add(m)
            if runtime.model_disabled(m):
                state, kind = "disabled", "bad"
            elif spec.provider == "ollama":
                ok, why = resources.local_model_ok()
                cd = resources.cooldown_left(m)
                state, kind = ("benched " + _fmt_wait(cd), "warn") if cd else (("ready", "ok") if ok else (why, "warn"))
            elif resources.cooldown_left(m) > 0:
                state, kind = "cooldown " + _fmt_wait(resources.cooldown_left(m)), "warn"
            elif role == "judge" and not resources.model_ready(spec.provider, m, "critic")[0]:
                wait = resources.model_ready(spec.provider, m, "critic")[1]
                state, kind = "daily budget used" + (f" · frees in {_fmt_wait(wait)}" if wait else ""), "warn"
            else:
                state, kind = "ready", "ok"
            used = ""
            if spec.provider == "groq":
                u = resources.daily_used(m)
                cap = int(resources.TPD_LIMITS["groq"] * resources.ROLE_SHARE["critic"] * resources.TPM_SAFETY)
                used = f"{100 * u.get('critic', 0) / cap:.0f}% of daily critic budget"
            rows.append({"role": role, "model": m, "family": spec.family, "provider": spec.provider,
                         "state": state, "kind": kind, "used": used})
    return rows


def system() -> dict:
    """Machine and agent health: memory, load, agents running, database sizes and when the lookup was built."""
    vm = psutil.virtual_memory()
    up = 0
    for a in AGENT_NAMES:
        try:
            os.kill(int((AGENTS / f"{a}.pid").read_text()), 0)
            up += 1
        except Exception:
            pass
    meta = DATA / "lookup" / "meta.json"
    return {"ram_free_gb": vm.available / 1e9, "ram_total_gb": vm.total / 1e9, "swap_gb": resources.swap_gb(),
            "load": os.getloadavg(), "cpus": os.cpu_count(), "agents_up": up, "agents_total": len(AGENT_NAMES),
            "db_mb": (DATA / "access.db").stat().st_size / 1e6, "fetchlog_mb": LOG_DB.stat().st_size / 1e6,
            "lookup_built": datetime.fromtimestamp(meta.stat().st_mtime).strftime("%H:%M:%S") if meta.exists() else "-",
            "workers": runtime.get()["workers"], "renderer_paused": runtime.get()["renderer_paused"]}
