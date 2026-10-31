"""Memory and quota governor shared by the agents and the app (tooling for Layers 0 to 3).

We size the crawl to the memory that is actually free on the 16 GB laptop, so nothing swaps heavily or times
out: RESERVE_GB stays with macOS, room is kept for the local judge model and the rest goes to crawl workers.
The same module keeps the shared token budgets and cooldowns for the rate-limited cloud models, and picks
judge panels from whatever has quota.
"""
import threading

import os

import psutil

RESERVE_GB = 1.5          # headroom for macOS and foreground apps
LOCAL_MODEL_GB = 3.2      # Phi-4-mini with a 4,096-token context
CRAWL_WORKER_GB = 0.06    # one crawl thread: the request plus HTML parsing of a large page
MIN_CRAWL, MAX_CRAWL = 4, 24
LOCAL_CTX = 4096          # enough for the longest critic prompt (~2,500 tokens)

# We allow one local model call at a time because Ollama reserves extra memory for each parallel request.
local_slot = threading.Semaphore(1)


def available_gb() -> float:
    return psutil.virtual_memory().available / 1e9


def swap_gb() -> float:
    return psutil.swap_memory().used / 1e9


def local_model_loaded() -> bool:
    try:
        import ollama
        return any(m.get("model", "").startswith("phi4-mini") for m in ollama.Client(timeout=5).ps().get("models", []))
    except Exception:
        return False


def crawl_workers() -> int:
    """Return how many sites to crawl in parallel right now, sized to free memory and capped by the Sentinel."""
    from . import runtime
    spare = available_gb() - RESERVE_GB - (0 if local_model_loaded() else LOCAL_MODEL_GB)
    cap = runtime.get()["workers"].get("crawl_cap", MAX_CRAWL)
    return max(MIN_CRAWL, min(MAX_CRAWL, cap, int(spare / CRAWL_WORKER_GB)))


def local_model_ok() -> tuple[bool, str]:
    """Say whether the local judge can run without pushing the Mac into heavy swapping, and why not if it cannot."""
    avail = available_gb()
    need = 0.3 if local_model_loaded() else LOCAL_MODEL_GB
    if avail - need < 0.5:
        return False, f"low memory ({avail:.1f} GB free, needs {need:.1f} GB)"
    return True, ""


def local_timeout() -> int:
    """Give the local model more time when memory is tight, since it may be partly paged out."""
    return 120 if available_gb() > RESERVE_GB + 1 else 240


def snapshot() -> str:
    vm = psutil.virtual_memory()
    return (f"Memory · {vm.available / 1e9:.1f} GB free of {vm.total / 1e9:.0f} GB · swap {swap_gb():.1f} GB · "
            f"local judge {'loaded' if local_model_loaded() else 'not loaded'} · crawl workers {crawl_workers()}")


# ---------------- per-minute token budget for rate-limited cloud models, shared by all processes ----------
import fcntl
import json as _json
import time as _time

from .config import CACHE_DIR

TPM_LIMITS = {"groq": 8000}   # free-tier tokens per minute, per model, read from Groq's rate-limit headers
TPM_SAFETY = 0.85             # we use at most 85% so retries and rough estimates never tip us over
BACKGROUND_TPM = 0.6          # share of each minute for critic, auditor and experiments; the rest is kept for live


def estimate_tokens(*texts: str, output: int = 1200) -> int:
    return sum(len(t) for t in texts) // 4 + output


def reserve_tokens(provider: str, model: str, tokens: int, role: str = "critic"):
    """Block until `tokens` fit in this model's rolling 60-second budget, then record them.

    A lock file lets the Critic, Auditor, Ranker and app share one budget. Background roles may only fill
    BACKGROUND_TPM of it, so a live request with a researcher waiting on screen never queues behind them. Without
    this split a ranker batch took about 20 s, of which only ~2 s was the model and the rest was waiting for the
    critic's minute to free up.
    """
    limit = TPM_LIMITS.get(provider)
    if not limit:
        return
    cap = int(limit * TPM_SAFETY * (1.0 if ROLE_OF.get(role, role) == "live" else BACKGROUND_TPM))
    tokens = min(tokens, cap)
    path = CACHE_DIR / f"tpm_{model.replace('/', '_')}.json"
    path.touch(exist_ok=True)
    while True:
        with open(path, "r+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                window = [(t, n) for t, n in (_json.loads(fh.read() or "[]")) if _time.time() - t < 60]
                used = sum(n for _, n in window)
                if used + tokens <= cap:
                    window.append((_time.time(), tokens))
                    fh.seek(0), fh.truncate(), fh.write(_json.dumps(window))
                    return
                wait = 60 - (_time.time() - window[0][0]) + 0.5
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        _time.sleep(max(1.0, wait))


# ---------------- daily token budget per role (Groq free tier: 200,000 tokens per day per model) ----------
TPD_LIMITS = {"groq": 200_000}
ROLE_SHARE = {"live": 0.20, "critic": 0.70, "auditor": 0.10,   # live is the app, and its share is always reserved
              # One-off overnight experiments (the access.bench judges) borrow from the critic, which then hits
              # Groq's real limit sooner and pauses. We accepted slower library building on those nights.
              "experiment": 0.45}
from .config import PUBLIC  # noqa: E402
if PUBLIC:
    # The hosted demo runs no critic or auditor, so live searches there may use half of each model's day
    # (about 20 searches) instead of the fifth reserved for them on the research machine.
    ROLE_SHARE = {**ROLE_SHARE, "live": 0.50}
ROLE_OF = {"critic_sources": "critic", "auditor": "auditor", "critic_shortlist": "live",
           "fit_ranker": "live", "profile_builder": "live", "advisor": "live"}


class DailyBudgetExhausted(RuntimeError):
    pass


def _day_file(model: str):
    return CACHE_DIR / f"tpd_{model.replace('/', '_')}.json"


def daily_used(model: str) -> dict:
    """Return the tokens each role has used on this model over the rolling last 24 hours."""
    path = _day_file(model)
    if not path.exists():
        return {}
    used = {}
    for t, role, n in _json.loads(path.read_text() or "[]"):
        if _time.time() - t < 86400:
            used[role] = used.get(role, 0) + n
    return used


def charge_daily(provider: str, model: str, role: str, tokens: int, check_only: bool = False):
    """Record tokens against a role's daily share of a model, or with check_only just test that they fit.

    We raise DailyBudgetExhausted so background agents pause instead of eating into the reserve for live searches.
    """
    limit = TPD_LIMITS.get(provider)
    if not limit:
        return
    share = int(limit * ROLE_SHARE.get(role, 0.70) * TPM_SAFETY)
    path = _day_file(model)
    path.touch(exist_ok=True)
    with open(path, "r+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            rows = [r for r in _json.loads(fh.read() or "[]") if _time.time() - r[0] < 86400]
            used = sum(n for _, r, n in rows if r == role)
            if check_only:
                if used + tokens > share:
                    oldest = min((t for t, r, _ in rows if r == role), default=_time.time())
                    raise DailyBudgetExhausted(f"{role} daily budget for {model} used ({used:,}/{share:,} tokens); "
                                               f"frees up in ~{int((oldest + 86400 - _time.time()) / 60)} min")
                return
            rows.append((_time.time(), role, tokens))
            fh.seek(0), fh.truncate(), fh.write(_json.dumps(rows))
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def budget_report() -> str:
    out = []
    for f in sorted(CACHE_DIR.glob("tpd_*.json")):
        model = f.stem[4:]
        used = daily_used(model)
        out.append(f"{model}: " + ", ".join(f"{r} {n:,}/{int(TPD_LIMITS['groq'] * ROLE_SHARE[r] * TPM_SAFETY):,}"
                                            for r, n in sorted(used.items()) if r in ROLE_SHARE))
    return " | ".join(out) or "no cloud tokens used yet"


# ---------------- cooldowns and judge availability ----------------
import re as _re


def set_cooldown(model: str, seconds: float):
    """Remember that the provider told us to wait, for example Groq's 'Please try again in 16m59s'."""
    f = CACHE_DIR / f"cooldown_{model.replace('/', '_')}.txt"
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(str(_time.time() + seconds))
    os.replace(tmp, f)  # atomic rename, so a reader never sees a half-written file


def bench(model: str, reason: str = "") -> float:
    """Rest a failing model for a time that fits the failure, and return the rest in seconds.

    A rate limit gets a short rest and a timeout or outage a longer one, doubling with each failure in the last
    2 hours up to 1 h. We tried a flat 30 min for every failure first, and it left the critic without a
    three-company panel for hours whenever two of the four non-Groq judges had a brief outage.
    """
    base = 300 if _re.search(r"429|rate", reason, _re.I) else 600
    f = CACHE_DIR / f"strikes_{model.replace('/', '_')}.json"
    try:
        strikes = [t for t in _json.loads(f.read_text()) if _time.time() - t < 7200]
    except (OSError, ValueError):
        strikes = []
    if not strikes or _time.time() - strikes[-1] > 120:  # several workers failing on one outage count as one strike
        strikes.append(_time.time())
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(_json.dumps(strikes))
    os.replace(tmp, f)
    seconds = min(3600, base * 2 ** (len(strikes) - 1))
    set_cooldown(model, max(seconds, cooldown_left(model)))  # we never shorten a quota cooldown that is already set
    return seconds


def cooldown_left(model: str) -> float:
    f = CACHE_DIR / f"cooldown_{model.replace('/', '_')}.txt"
    try:
        return max(0.0, float(f.read_text()) - _time.time())
    except (OSError, ValueError):  # missing, or half-written by a writer that did not use the atomic rename
        return 0.0


def parse_retry_after(msg: str) -> float | None:
    m = _re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", msg)
    if not m:
        return None
    h, mi, sec = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + sec


def model_ready(provider: str, model: str, role: str, need: int = 4000) -> tuple[bool, float]:
    """Return (ready, seconds until ready) for one cloud model, from its cooldown and our daily ledger."""
    cd = cooldown_left(model)
    if cd > 0:
        return False, cd
    limit = TPD_LIMITS.get(provider)
    if not limit:
        return True, 0.0
    share = int(limit * ROLE_SHARE.get(role, 0.70) * TPM_SAFETY)
    path = _day_file(model)
    rows = [r for r in _json.loads(path.read_text() or "[]") if r[1] == role] if path.exists() else []
    rows = sorted(r for r in rows if _time.time() - r[0] < 86400)
    used = sum(n for _, _, n in rows)
    if used + need <= share:
        return True, 0.0
    freed = 0  # rolling window, so we wait until enough of the oldest usage expires
    for t, _, n in rows:
        freed += n
        if used - freed + need <= share:
            return False, max(60.0, t + 86400 - _time.time())
    return False, 3600.0


def judges_ready(specs, role: str) -> tuple[list, float]:
    """Return the judges that can answer now and how long until the next one becomes ready.

    A judge counts as ready if its own model or any same-family backup model is ready.
    """
    ready, waits = [], []
    for sp in specs:
        if sp.provider == "ollama":
            ok, _ = local_model_ok()
            cd = cooldown_left(sp.model)  # a benched local judge stays benched
            (ready.append(sp) if ok and cd == 0 else waits.append(max(cd, 300.0)))
            continue
        from . import runtime
        models = [m for m in (sp.model, *sp.fallbacks) if not runtime.model_disabled(m)]
        if not models:
            continue
        states = [model_ready(sp.provider, m, role) for m in models]
        if any(ok for ok, _ in states):
            ready.append(sp)
        else:
            waits.append(min(w for _, w in states))
    return ready, (min(waits) if waits else 0.0)


def pick_panel(pool, role: str, size: int = 3):
    """Pick the first `size` judges from different companies that have quota now; pool order is our preference."""
    ready, wait = judges_ready(pool, role)
    from . import runtime
    if runtime.get().get("local_for_live") and ROLE_OF.get(role, role) != "live":
        # With local_for_live set, the laptop's model serves live searches only. A busy critic can make it time
        # out on a live search, which then gets it benched.
        ready = [j for j in ready if j.provider != "ollama"]
    panel, seen = [], set()
    for j in ready:
        if j.family not in seen:
            panel.append(j)
            seen.add(j.family)
        if len(panel) == size:
            break
    return panel, wait


def seconds_until_pacific_midnight() -> float:
    """Gemini free-tier daily quotas reset at midnight US Pacific time."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    return ((now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0) - now).total_seconds()
