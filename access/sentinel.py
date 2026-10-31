"""The Sentinel, our supervisor for the data agents (tooling around Layer 0).

Every five minutes it checks that each agent is making progress, not just running, works out why when one is not,
and applies a fix from a short list of safe actions: restart an agent, bench or disable a model, change the number
of workers, return stuck rows to the queue, pause the renderer or relaunch Ollama. It never edits code, deletes
data or touches anything outside the project. It only pushes to the phone (ntfy) and the Mac when it cannot fix
something by itself.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests

from . import resources, runtime
from .logtail import tail_lines, trim
from .config import GEMINI_FLASH, ROLES, ModelSpec
from .db import connect

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "data" / "agents"
ALERTS = LOGS / "alerts.log"
STATE = LOGS / "sentinel_state.json"
TOPIC_FILE = LOGS / "ntfy_topic.txt"
CHECK_EVERY = 300
QUIET_MIN = {"scout": 20, "scraper": 20, "critic": 25, "auditor": 30}
STALL_MIN = 40
SUMMARY_HOUR = 21


# ------------------------------------------------------------------ reporting

def log(msg):
    print(f"{time.strftime('%H:%M:%S')} [sentinel] {msg}", flush=True)


def notify(title, msg, urgent=False):
    msg = msg.replace('"', "'")[:300]
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}" '
                                       f'sound name "{"Basso" if urgent else "Glass"}"'], capture_output=True)
    if TOPIC_FILE.exists():  # phone push through ntfy; we only send status, never keys or personal data
        try:
            requests.post(f"https://ntfy.sh/{TOPIC_FILE.read_text().strip()}", data=msg.encode(), timeout=10,
                          headers={"Title": title, "Priority": "high" if urgent else "default",
                                   "Tags": "warning" if urgent else "white_check_mark"})
        except requests.RequestException:
            pass


def record(kind, key, msg, state, push=False, urgent=False):
    line = f"{datetime.now():%Y-%m-%d %H:%M} {kind:<9} {key}: {msg}"
    log(line)
    with open(ALERTS, "a") as fh:
        fh.write(line + "\n")
    last = state.setdefault("pushed", {}).get(key, 0)
    if push and time.time() - last > 3600:
        notify("ACCESS: " + ("needs you" if urgent else "fixed automatically"), msg, urgent)
        state["pushed"][key] = time.time()


# ------------------------------------------------------------------ evidence

def _pid(name):
    try:
        pid = int((LOGS / f"{name}.pid").read_text())
        os.kill(pid, 0)
        return pid
    except Exception:
        return None


def restart(name):
    pid = _pid(name)
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
    (LOGS / f"{name}.pid").unlink(missing_ok=True)
    time.sleep(3)
    subprocess.run(["/opt/anaconda3/bin/python3", "agents.py", "start"], cwd=ROOT, capture_output=True)


def lines(name, minutes):
    f = LOGS / f"{name}.log"
    if not f.exists():
        return []
    now = datetime.now()
    cutoff, now_s = (now - timedelta(minutes=minutes)).strftime("%H:%M:%S"), now.strftime("%H:%M:%S")
    wrapped = cutoff > now_s  # the window crosses midnight, say 23:50 to 00:10
    in_window = (lambda t: t >= cutoff or t <= now_s) if wrapped else (lambda t: cutoff <= t <= now_s)
    return [l for l in tail_lines(f, 4000)
            if re.match(r"\d\d:\d\d:\d\d", l) and in_window(l[:8]) and "AFC" not in l]


def count(name, pattern, minutes):
    return sum(bool(re.search(pattern, l)) for l in lines(name, minutes))


def declared_pause(name, tag=""):
    for l in reversed(lines(name, 60)):
        if tag and tag not in l:
            continue
        m = re.search(r"⏸.*?re-checking at (\d\d:\d\d)", l)
        if m:
            return m.group(1) >= time.strftime("%H:%M")
    return False


def probe(spec: ModelSpec, model: str) -> str:
    """Send one tiny request to a model and classify the answer as 'ok', 'quota', 'rate', 'incompatible' or 'down'."""
    from .llm import _raw_call
    try:
        _raw_call(spec, "Reply with JSON only.", 'Return {"ok": true}', model)
        return "ok"
    except Exception as e:
        m = str(e)
        if "PerDay" in m or "per day" in m.lower() or "TPD" in m or "daily budget" in m:
            return "quota"
        if "429" in m or "rate" in m.lower() or "RESOURCE_EXHAUSTED" in m:
            return "rate"
        if re.search(r"\b(400|404|422)\b|not supported|invalid|INVALID_ARGUMENT|Not Found", m):
            return "incompatible"
        return "down"


# ------------------------------------------------------------------ diagnosis + fixes

def fix_stuck_claims(state):
    """Return rows to the queue when the worker that claimed them has gone quiet for 30 minutes."""
    with connect() as con:
        n1 = con.execute("UPDATE sources SET status='candidate' WHERE status='annotating'").rowcount \
            if count("scraper", r"\[annotator\]", 30) == 0 else 0
        n2 = con.execute("UPDATE sources SET status='annotated' WHERE status='judging'").rowcount \
            if count("critic", r"\[critic\] (accepted|rejected|repaired|!)", 30) == 0 else 0
    if n1 or n2:
        record("FIXED", "stuck_claims", f"returned {n1 + n2} stuck rows to the queue", state)


def diagnose_annotator(state, waiting):
    """Work out why the Annotator has made no progress and fix it if we can.

    Returns True when the stall is expected (daily caps, a provider outage) and nothing needs fixing.
    """
    models = [m for m in (GEMINI_FLASH.model, *GEMINI_FLASH.fallbacks) if not runtime.model_disabled(m)]
    results = {}
    for m in models:
        if resources.cooldown_left(m) > 0:
            results[m] = "quota"
            continue
        results[m] = probe(GEMINI_FLASH, m)
        if results[m] == "ok":
            time.sleep(3)
            results[m] = probe(GEMINI_FLASH, m)
        if results[m] == "quota":
            resources.set_cooldown(m, resources.seconds_until_pacific_midnight())
        elif results[m] == "incompatible":
            runtime.update(disabled_models={m: "rejected our request format"})
    ok = [m for m, r in results.items() if r == "ok"]
    rate = [m for m, r in results.items() if r == "rate"]
    down = [m for m, r in results.items() if r == "down"]
    if down and not ok and not rate:
        record("EXPECTED", "annotator_provider_down", f"Google returns server errors for {', '.join(down)} "
                                                      f"(their side); other models at daily cap. Annotator retries "
                                                      f"every 10 min ({waiting} pages waiting)", state)
        return True
    if not ok and not rate:
        hrs = resources.seconds_until_pacific_midnight() / 3600
        record("EXPECTED", "annotator_quota", f"all Google models at their daily cap; resumes in ~{hrs:.1f} h "
                                              f"({waiting} pages waiting)", state)
        return True
    w = runtime.get()["workers"]["annotator"]
    if rate and not ok and w > 1:  # the models left only have per-minute limits, so we slow down
        runtime.update(workers={"annotator": 1})
        record("FIXED", "annotator_rate", f"only {', '.join(rate)} has quota and it rate-limits; "
                                          f"annotator reduced from {w} to 1 worker", state, push=True)
        restart("scraper")
        return
    if time.time() - state.get("annotator_restarted", 0) < 3600:  # we restarted within the hour and it did not help
        record("EXPECTED", "annotator_provider_unstable", f"{', '.join(ok or rate)} answers probes but fails on "
                                                          f"real requests (Google-side errors); waiting, not "
                                                          f"restarting again ({waiting} pages waiting)", state)
        return True
    state["annotator_restarted"] = time.time()
    restart("scraper")
    record("FIXED", "annotator_stalled", f"no progress although {', '.join(ok) or rate[0]} works; "
                                         f"restarted the scraper", state, push=True)


def diagnose_critic(state, waiting):
    """Probe the judge pool, bench the judges that fail, and restart the critic if a full panel is available."""
    pool = ROLES["judge_pool"]
    broken = []
    for spec in pool:
        if spec.provider == "ollama":
            ok, _ = resources.local_model_ok()
            if not ok:
                broken.append(spec.label)
            continue
        live = [m for m in (spec.model, *spec.fallbacks)
                if not runtime.model_disabled(m) and resources.cooldown_left(m) == 0]
        if not live:
            continue
        r = probe(spec, live[0])
        if r == "incompatible":
            runtime.update(disabled_models={live[0]: "rejected our request format"})
            broken.append(spec.label)
        elif r in ("down", "rate", "quota"):
            resources.set_cooldown(live[0], 1800 if r != "quota" else 6 * 3600)
            broken.append(spec.label)
    panel, wait = resources.pick_panel(pool, "critic", 3)
    if len({j.family for j in panel}) < 3:
        record("EXPECTED", "critic_quota", f"fewer than 3 judge companies available "
                                           f"(benched: {', '.join(broken) or 'none'}); resumes in ~{wait / 60:.0f} min "
                                           f"({waiting} rows waiting)", state)
        return True
    restart("critic")
    record("FIXED", "critic_stalled", f"benched {', '.join(broken) or 'no judges'}; restarted critic with panel "
                                      f"{'/'.join(j.family for j in panel)}", state, push=True)


def ai_diagnosis(name, errs, state):
    """Handle an error pattern we have no rule for by asking a free model to pick one of the safe actions.

    The model only reads the recent log lines and can only choose from the fixed action list below.
    """
    from .config import NEMOTRON
    from .llm import LLMError, call_json
    actions = ["restart_agent", "reduce_workers", "pause_renderer", "relaunch_ollama", "none"]
    try:
        d = call_json(NEMOTRON, "You are an SRE assistant. Reply in JSON.",
                      f"Agent '{name}' of a data pipeline keeps logging these errors:\n" + "\n".join(errs[-8:]) +
                      f"\n\nChoose ONE action from {actions} and explain the likely cause in one sentence. "
                      'JSON: {"action": "...", "cause": "..."}')
    except LLMError:
        return None, "AI diagnosis unavailable"
    act, cause = d.get("action"), str(d.get("cause", ""))[:200]
    if act == "restart_agent":
        restart(name)
    elif act == "reduce_workers":
        key = {"scraper": "annotator", "critic": "critic"}.get(name)
        if key:
            runtime.update(workers={key: max(1, runtime.get()["workers"][key] - 1)})
    elif act == "pause_renderer":
        runtime.update(renderer_paused=True)
    elif act == "relaunch_ollama":
        subprocess.run(["open", "-a", "Ollama"])
    return act, cause


def app_check(state, problems):
    """Check that the Streamlit app answers, and force-restart it if it hangs (a hung server can ignore SIGTERM)."""
    if not subprocess.run(["lsof", "-tiTCP:8501", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.strip() \
            and not state.get("app_running"):
        return  # the user has not started the app, so there is nothing to watch
    state["app_running"] = True
    try:
        requests.get("http://localhost:8501/_stcore/health", timeout=20).raise_for_status()
        state.pop("app_fail", None)
        return
    except requests.RequestException:
        state["app_fail"] = state.get("app_fail", 0) + 1
    problems.add("app")
    if state["app_fail"] < 2:  # one slow answer can happen under memory pressure, so we act on the second
        return
    pids = subprocess.run(["lsof", "-tiTCP:8501", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    for pid in set(pids):
        try:
            os.kill(int(pid), signal.SIGKILL)
        except (OSError, ValueError):
            pass
    time.sleep(2)
    subprocess.Popen(["/opt/anaconda3/bin/streamlit", "run", "app.py", "--server.headless", "true",
                      "--server.port", "8501", "--server.address", "localhost"], cwd=ROOT,
                     stdout=open(LOGS / "app.log", "a"), stderr=subprocess.STDOUT, start_new_session=True)
    state["app_fail"] = 0
    record("FIXED", "app_hung", "the web app stopped answering; force-restarted it", state, push=True)


# ------------------------------------------------------------------ main check

def check(state):
    problems = set()
    for name, quiet in QUIET_MIN.items():
        if name in runtime.get().get("paused_agents", []):  # stopped on purpose, so we leave it alone
            continue
        if not _pid(name):
            restart(name)
            record("FIXED", f"{name}_down", f"{name} was not running; restarted it", state, push=True)
            problems.add(f"{name}_down")
        elif not lines(name, quiet) and not declared_pause(name):
            restart(name)
            record("FIXED", f"{name}_silent", f"{name} logged nothing for {quiet}+ min; restarted it", state, push=True)
            problems.add(f"{name}_silent")
    fix_stuck_claims(state)
    for f in LOGS.glob("*.log"):  # a runaway log slows down everything that reads it
        if trim(f):
            record("FIXED", f"log_{f.stem}", f"{f.name} had grown past 50 MB; trimmed to its last 5 MB "
                                             f"(check that agent for a repeating message)", state, push=True)

    with connect() as con:
        q = dict(con.execute("SELECT status, COUNT(*) FROM sources WHERE status IN ('candidate','annotated') "
                             "GROUP BY status").fetchall())
    if q.get("candidate", 0) and count("scraper", r"\[annotator\] (annotated|index_page|not_programme)", STALL_MIN) == 0:
        problems.add("annotator_waiting" if diagnose_annotator(state, q["candidate"]) else "annotator")
    if q.get("annotated", 0) and count("critic", r"\[critic\] (accepted|rejected|repaired)", STALL_MIN) == 0:
        problems.add("critic_waiting" if diagnose_critic(state, q["annotated"]) else "critic")

    # Repeated errors that no rule above covers go to the model-assisted diagnosis, limited to safe actions.
    for name in QUIET_MIN:
        errs = [l for l in lines(name, 30) if (" ! " in l or "Traceback" in l or "Error" in l)
                and "benched" not in l and "⏸" not in l
                and not re.search(r"paused|unavailable|daily budget|quota|cap reached", l, re.I)]
        sig = Counter(re.sub(r"\d+", "#", l[20:110]) for l in errs)
        if sig and sig.most_common(1)[0][1] >= 10:
            key = f"{name}_errors"
            if time.time() - state.setdefault("ai_tried", {}).get(key, 0) > 3600:
                act, cause = ai_diagnosis(name, errs, state)
                state["ai_tried"][key] = time.time()
                record("FIXED" if act and act != "none" else "NEEDS_YOU", key,
                       f"repeated error in {name}: {sig.most_common(1)[0][0][:90]} | diagnosis: {cause} | "
                       f"action: {act}", state, push=True, urgent=not act or act == "none")
            problems.add(key)

    app_check(state, problems)
    try:
        requests.get("http://localhost:11434/api/version", timeout=5)
    except requests.RequestException:
        subprocess.run(["open", "-a", "Ollama"])
        record("FIXED", "ollama_down", "Ollama was not responding; relaunched it", state, push=True)
        problems.add("ollama")
    free, swap = resources.available_gb(), resources.swap_gb()
    if free < 1.0 or swap > 12:
        if not runtime.get()["renderer_paused"]:
            runtime.update(renderer_paused=True, workers={"crawl_cap": 8})
            record("FIXED", "memory", f"memory pressure ({free:.1f} GB free, {swap:.1f} GB swap): paused the "
                                      f"renderer and reduced crawling", state, push=True)
        problems.add("memory")
    elif runtime.get()["renderer_paused"] and free > 3.0:
        runtime.update(renderer_paused=False, workers={"crawl_cap": 24})
        record("RESOLVED", "memory", "memory recovered; renderer and full crawling resumed", state)
    if shutil.disk_usage(ROOT).free / 1e9 < 5:
        record("NEEDS_YOU", "disk", "less than 5 GB of disk space left", state, push=True, urgent=True)
        problems.add("disk")
    try:
        requests.head("https://www.google.com", timeout=10)
        state.pop("offline_since", None)
    except requests.RequestException:
        state["offline_since"] = state.get("offline_since") or time.time()
        if time.time() - state["offline_since"] > 1800:
            record("NEEDS_YOU", "network", "no internet for 30+ min - agents are waiting", state, push=True, urgent=True)
        problems.add("network")

    # We escalate anything that keeps coming back after the automatic fixes.
    hist = state.setdefault("history", {})
    for p in problems:
        if p.endswith("_waiting"):  # expected pauses (quota caps, provider outages) are not failures
            continue
        hist[p] = [t for t in hist.get(p, []) if time.time() - t < 3 * 3600] + [time.time()]
        if len(hist[p]) >= 4 and time.time() - state.setdefault("escalated", {}).get(p, 0) > 6 * 3600:
            state["escalated"][p] = time.time()  # at most one "needs you" per problem every 6 h
            record("NEEDS_YOU", p, f"'{p}' has recurred {len(hist[p])} times in 3 h despite automatic fixes",
                   state, push=True, urgent=True)
    # Once the annotator is healthy again we add workers back one at a time.
    w = runtime.get()["workers"]
    if not {"annotator", "annotator_waiting"} & problems and w["annotator"] < 3 and count("scraper", r"\[annotator\] annotated", 30) >= 5:
        runtime.update(workers={"annotator": w["annotator"] + 1})
        record("RESOLVED", "annotator_rate", f"annotator healthy again; workers {w['annotator']} -> "
                                             f"{w['annotator'] + 1}", state)
    return problems


def daily_summary(state):
    today = time.strftime("%Y-%m-%d")
    if time.localtime().tm_hour < SUMMARY_HOUR or state.get("summary_day") == today:
        return
    with connect() as con:
        n = con.execute("SELECT COUNT(*) FROM listings WHERE decision IN ('accepted','accepted_with_warning') "
                        "AND verified_at >= ?", (today,)).fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM listings WHERE decision IN "
                            "('accepted','accepted_with_warning')").fetchone()[0]
    fixed = sum(1 for l in ALERTS.read_text().splitlines() if l.startswith(today) and "FIXED" in l) \
        if ALERTS.exists() else 0
    notify("ACCESS daily summary", f"{n} programmes verified today, {total} in total. "
                                   f"{fixed} problem(s) fixed automatically.")
    state["summary_day"] = today


def run(stop=None):
    log("sentinel v2 started: detect -> diagnose -> fix -> verify -> escalate, every 5 min")
    notify("ACCESS monitor online", "Sentinel is watching the agents. You'll get a push only when it fixes "
                                    "something important or needs you.")
    while not (stop and stop.is_set()):
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        try:
            problems = check(state)
            daily_summary(state)
            log("all healthy" if not problems else f"handled: {sorted(problems)}")
        except Exception as e:
            log(f"sentinel check failed: {str(e)[:160]}")
        STATE.write_text(json.dumps(state))
        time.sleep(CHECK_EVERY)
