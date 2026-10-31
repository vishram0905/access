"""Runtime settings that the agents re-read while they run (tooling for Layer 0).

The Sentinel changes these to fix problems without editing code or restarting anything. They live in
data/agents/runtime.json with these keys:

  disabled_models   {model: reason}   models taken out of rotation because they are incompatible or broken
  workers           {"annotator": n, "critic": n, "crawl_cap": n}
  renderer_paused   bool
  paused_agents     [names]           agents stopped on purpose; the Sentinel never revives them
  repairs_first     bool              every critic worker verifies existing records before judging new ones
  local_for_live    bool              the local model serves live searches only, never the background critic
"""
import json
import time

from .config import DATA

FILE = DATA / "agents" / "runtime.json"
DEFAULTS = {"disabled_models": {}, "workers": {"annotator": 3, "critic": 2, "crawl_cap": 24},
            "renderer_paused": False, "paused_agents": []}
_cache = {"t": 0, "v": None}


def get() -> dict:
    """Return the current settings over the defaults. We re-read the file at most every 15 s."""
    if time.time() - _cache["t"] > 15 or _cache["v"] is None:
        try:
            v = {**DEFAULTS, **json.loads(FILE.read_text())}
            v["workers"] = {**DEFAULTS["workers"], **v.get("workers", {})}
        except Exception:
            v = json.loads(json.dumps(DEFAULTS))
        _cache.update(t=time.time(), v=v)
    return _cache["v"]


def update(**changes) -> dict:
    """Write changes to the settings file. Dict values are merged one level deep, everything else is replaced."""
    v = json.loads(json.dumps(get()))
    for k, val in changes.items():
        if isinstance(val, dict) and isinstance(v.get(k), dict):
            v[k].update(val)
        else:
            v[k] = val
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(v, indent=1))
    _cache.update(t=0, v=None)
    return v


def model_disabled(model: str) -> bool:
    return model in get()["disabled_models"]
