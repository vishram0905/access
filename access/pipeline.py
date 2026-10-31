"""Runs one search from the form to the final list, across Layers 1 to 3.

We split the work into three tiers so the user never waits on a cloud model:

  instant()  ~1 s, no cloud model    profile, lookup search and eligibility gate give the answer
  enrich()   ~10-30 s, cloud models  independent reviewers and the fit ranker order and annotate it
  plan_for() on demand               an application plan for the programme the user opens
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .advisor import advise
from .config import ROLES, RUNS_DIR
from .critics import review_shortlist
from .profile import local_profile, search_query
from .llm import set_role
from .ranker import rank
from .results import final_order, tidy
from .search import search

MAX_SHOWN = 30       # eligible programmes we rank and show
REVIEW_BATCH = 10    # candidates per reviewer prompt
# The reviewers only check the most relevant programmes. 15 eligible plus 5 near-misses keeps enrichment to two
# reviewer rounds, about 20-30 s on the free tiers.
REVIEW_TOP = 15
REVIEW_NEAR = 5
# Below either threshold a programme is marked a "weaker fit". We still show it, just at the end.
MIN_RELEVANCE = 2.0  # reviewers' mean relevance
MIN_FIT = 40         # ranker fit score


def _models(role):
    return ", ".join(f"{m.label} ({m.family}, {m.where})" for m in ROLES[role])


class Trace:
    """Records each enrichment step (model used, summary, seconds) and forwards progress to the page."""

    def __init__(self, callback=None):
        self.events, self.callback = [], callback

    def start(self, key):
        self._t = time.time()
        if self.callback:
            self.callback({"key": key, "status": "running"})

    def done(self, key, model, summary, details=None):
        ev = {"key": key, "status": "done", "model": model, "summary": summary,
              "details": details or {}, "seconds": round(time.time() - self._t, 1)}
        self.events.append(ev)
        if self.callback:
            self.callback(ev)


def instant(form: dict) -> dict:
    """Produce the answer in about a second without any cloud model.

    We build the profile from the form with local field inference, search the lookup document, run the
    eligibility gate, merge duplicates and attach deadline status.
    """
    t0 = time.time()
    profile = local_profile(form)
    filters = {"host_country": form.get("target_countries"), "opportunity_type": form.get("wanted_types"),
               "provider_type": form.get("provider_types")}
    found = search(profile, search_query(profile), k=MAX_SHOWN, filters=filters)
    shortlist, near = tidy(found["eligible"]), tidy(found["near_miss"])
    for x in shortlist + near:
        x["score"] = round(max(0.0, min(100.0, (found["similarity"].get(x["id"], 0.3) - 0.3) / 0.5 * 100)))
        x["ranked_by"] = "similarity"
    return {"created": datetime.now().isoformat(timespec="seconds"), "form": form, "profile": profile,
            "shortlist": shortlist, "near_misses": near, "search_stats": found["stats"],
            "similarity": {k: v for k, v in found["similarity"].items()
                           if k in {x["id"] for x in shortlist + near}},
            "enriched": False, "timings": {"instant_s": round(time.time() - t0, 2)}, "trace": []}


def enrich(result: dict, callback=None) -> dict:
    """Add the model-based extras once the answer is on screen: batched independent reviewers and the fit ranker.

    These steps only order and annotate. They never remove an eligible programme, and if any of them fails the
    instant result is still usable.
    """
    set_role("live")  # draw on the share of each model's daily tokens we reserve for live searches
    trace, t0 = Trace(callback), time.time()
    profile, pool, near = result["profile"], result["shortlist"], result["near_misses"]
    from .config import PUBLIC
    # On the hosted demo the reviewer shares a free per-minute token budget, so it reads the top 10 in one call.
    # The ranker has a model of its own there (config.GPT_OSS_LIVE), so it scores the whole list, which is at most
    # 25 programmes, three calls of about 1,500 tokens. Locally the reviewers see more as well.
    top_review, top_near, top_rank = (10, 0, len(pool)) if PUBLIC else (REVIEW_TOP, REVIEW_NEAR, len(pool))
    to_review = pool[:top_review] + near[:top_near]
    trace.start("critic")
    trace.start("ranker")

    def reviewers():
        set_role("live")
        reviews, errors = {}, []
        for i in range(0, len(to_review), REVIEW_BATCH):
            try:
                got = review_shortlist(profile, to_review[i:i + REVIEW_BATCH])
                errors += got.pop("_errors", [])
                reviews.update(got)
            except Exception as e:
                errors.append(f"{type(e).__name__}: {str(e)[:80]}")
        return reviews, errors

    def ranker():
        set_role("live")
        try:
            return rank(profile, pool[:top_rank], result.get("similarity", {})) + pool[top_rank:]
        except Exception as e:
            print(f"[enrich] ranker failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
            return pool  # keep the similarity order

    # The reviewers and the ranker do not depend on each other, so we run them side by side: the visitor waits
    # for the slower of the two instead of their sum.
    with ThreadPoolExecutor(2) as ex:
        f_rev, f_rank = ex.submit(reviewers), ex.submit(ranker)
        reviews, errors = f_rev.result()
        ranked = f_rank.result()
    for x in to_review:
        x["critic"] = reviews.get(x["id"], {})
    trace.done("critic", _models("critic_shortlist"),
               f"Reviewed {len(to_review)} programmes" + (f" ({len(errors)} reviewer errors)" if errors else ""),
               {"errors": errors[:5]})
    for x in ranked:
        rel = (x.get("critic") or {}).get("relevance")
        x["weaker_fit"] = bool((rel is not None and rel < MIN_RELEVANCE) or
                               (x.get("fit") is not None and x["fit"] < MIN_FIT))
    result["shortlist"] = final_order(ranked)
    unranked = sum(x.get("fit") is None for x in ranked)
    used = sorted({x.get("ranker") for x in ranked if x.get("ranker")})
    trace.done("ranker", ", ".join(used) or _models("fit_ranker"),
               f"Ranked {len(ranked)} programmes" + (f"; {unranked} kept in similarity order" if unranked else ""), {})
    result.update(enriched=True, trace=result.get("trace", []) + trace.events)
    result["timings"]["enrich_s"] = round(time.time() - t0, 1)
    # One line per search in the server log, so slow or failing rankings on the hosted demo can be diagnosed.
    print(f"[enrich] {result['timings']['enrich_s']} s, ranked {len(ranked) - unranked}/{len(ranked)} by "
          f"{', '.join(used) or 'none'}, reviewer errors: {errors[:2]}", flush=True)
    return result


def plan_for(result: dict, programme_id: str) -> dict | None:
    """Write the application plan for one programme when the user opens it, and cache it in the result.

    Doing it on demand keeps the search fast and spends model quota only on programmes someone actually reads.
    """
    set_role("live")
    items = {x["id"]: x for x in result["shortlist"] + result["near_misses"]}
    x = items.get(programme_id)
    if not x:
        return None
    if not x.get("advice"):
        near = x in result["near_misses"]
        try:
            got = advise(result["profile"], [] if near else [x], [x] if near else [])
        except Exception:
            got = {}
        x["advice"] = got.get(programme_id) or next(iter(got.values()), None)
    return x.get("advice")


def run(form: dict, callback=None) -> dict:
    """Run a full search (instant answer plus enrichment) and save it. The CLI and the example refresher use this."""
    result = enrich(instant(form), callback)
    save_run(result)
    return result


EXAMPLE_NAMES = {"Priya", "Wei Ling", "Daniel", "Amara"}  # fictional example researchers


KEY_FIELDS = ("nationality", "career_stage", "target_countries", "wanted_types", "about")


def is_example(form: dict) -> bool:
    """Treat a run as an example researcher's only if the form is that example's form, unedited.

    Matching on the name alone let an edited "Wei Ling" search replace the real example on the home page.
    """
    from .evaluation import PERSONAS
    p = next((p for p in PERSONAS.values() if p["name"] == form.get("name")), None)
    return bool(p) and all(form.get(k) == p.get(k) for k in KEY_FIELDS)


def save_run(result: dict) -> None:
    """Save a run for evaluation, keeping data to a minimum: we never store a personal name.

    The public demo stores nothing at all.
    """
    from .config import PUBLIC
    if PUBLIC:
        return
    if not is_example(result["form"]):
        result["form"]["name"] = "you"
        if "profile" in result:
            result["profile"]["name"] = "you"
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^a-z0-9]+", "-", result["form"].get("name", "run").lower()).strip("-")
    path = RUNS_DIR / f'{result["created"].replace(":", "")}_{name}.json'
    path.write_text(json.dumps(result, indent=1, default=str))


EXAMPLES_DIR = RUNS_DIR.parent / "examples"  # example searches shipped with the repo


def list_runs() -> list:
    """List saved searches, newest first, from local runs and the bundled examples."""
    found = [p for d in (RUNS_DIR, EXAMPLES_DIR) if d.exists() for p in d.glob("*.json")]
    return sorted(found, key=lambda p: p.name, reverse=True)
