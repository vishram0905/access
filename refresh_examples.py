"""Regenerate the example searches shown on the home page (tooling).

We wait until the fit ranker has free quota, run every example researcher and keep a new run only if the ranker
scored and explained every result. Otherwise the previous example stays on the page.

Run:  python refresh_examples.py            (waits for quota, then refreshes all)
      python refresh_examples.py amara      (just one example researcher)
"""
import sys
import time

from access import resources
from access.config import ROLES, RUNS_DIR
from access.evaluation import PERSONAS
from access.pipeline import run


def ready() -> bool:
    needed = [ROLES["fit_ranker"][0]]  # reviewers are optional: a missing review is reported, not waited for
    return all(resources.cooldown_left(m.model) == 0 for m in needed)


def main():
    while not ready():
        print(time.strftime("%H:%M"), "waiting for ranker / reviewer quota...", flush=True)
        time.sleep(900)
    only = {a.lower() for a in sys.argv[1:]}
    for label, p in PERSONAS.items():
        if only and p["name"].lower() not in only:
            continue
        before = set(RUNS_DIR.glob("*.json"))
        try:
            r = run({**p, "provider_types": []})
        except Exception as e:
            print(p["name"], "failed:", str(e)[:150], flush=True)
            continue
        new = set(RUNS_DIR.glob("*.json")) - before
        ok = all(x.get("fit") is not None and x.get("why") for x in r["shortlist"])  # zero matches still counts
        if ok:  # move this persona's earlier runs out of the way
            slug = next(iter(new)).name.split("_", 1)[1] if new else None
            for old in before:
                if slug and old.name.endswith("_" + slug):
                    old.rename(RUNS_DIR / "old" / old.name)
        else:
            for f in new:
                f.rename(RUNS_DIR / "old" / f"incomplete_{f.name}")
        print(f"{p['name']}: {'kept' if ok else 'discarded (ranker incomplete)'} - {len(r['shortlist'])} matches, "
              f"{len(r['near_misses'])} within reach", flush=True)


if __name__ == "__main__":
    (RUNS_DIR / "old").mkdir(parents=True, exist_ok=True)
    main()
