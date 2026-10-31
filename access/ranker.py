"""Fit ranker (Layer 3): scores each eligible, verified candidate for fit and explains the score in a sentence.

The model only orders the list. Eligibility has already been decided by the gate in Layer 2.
"""
import json

from .config import ROLES
from .llm import LLMError, call_json

SYSTEM = ("You rank research funding opportunities for a specific researcher and explain each "
          "score in one plain-English sentence. Reply in JSON.")

PROMPT = """RESEARCHER:
{profile}

OPPORTUNITIES:
{cands}

Score how well each opportunity fits this researcher's field, career stage and stated goals
(0 = poor fit, 100 = ideal). Return JSON:
{{"rankings": [{{"id": "...", "fit": 0-100, "why": "one sentence"}}]}} with one entry per opportunity."""


# We send ten candidates per request. With all 30 at once the model dropped items (3-4 of 30 came back unranked)
# and we hit per-minute rate limits.
BATCH = 10


def _available(spec) -> bool:
    from . import resources
    if spec.provider == "ollama":
        return resources.local_model_ok()[0] and resources.cooldown_left(spec.model) == 0
    return resources.model_ready(spec.provider, spec.model, "live")[0]


def _score(spec, prof: str, batch: list[dict]) -> dict:
    cands = "\n".join(f'- id={c["id"]} | {c["name"]} | {c["type"]} | {c["host_country"]} | {c["summary"][:250]}'
                      for c in batch)
    data = call_json(spec, SYSTEM, PROMPT.format(profile=prof, cands=cands))
    return {str(r["id"]): r for r in data.get("rankings", []) if isinstance(r, dict) and "id" in r}


def rank(profile: dict, candidates: list[dict], similarity: dict[str, float]) -> list[dict]:
    """Score every candidate in batches of BATCH and return them sorted by the blended score.

    We try to keep one model for the whole list because scores from different models are not on the same scale.
    Items a model skipped get one retry, and the next model in the role takes over only if the current one becomes
    unavailable. Each item records the model that scored it.
    """
    if not candidates:
        return []
    prof = json.dumps({k: profile.get(k) for k in (
        "career_stage", "highest_degree", "fields", "keywords", "research_summary",
        "goals", "target_countries", "wanted_types")})
    chain = [s for s in ROLES["fit_ranker"] if _available(s)] or list(ROLES["fit_ranker"][:1])
    scores, by = {}, {}
    todo = list(candidates)
    for spec in chain:
        for attempt in range(2):  # the second pass retries only the items the model skipped
            batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
            failed = False
            for b in batches:
                try:
                    got = _score(spec, prof, b)
                except LLMError:
                    failed = True
                    break
                for k, v in got.items():
                    scores[k], by[k] = v, spec.label
            todo = [c for c in candidates if c["id"] not in scores]
            if not todo or failed:
                break
        if not todo:
            break
    out = []
    for c in candidates:
        r = scores.get(c["id"], {})
        try:
            fit = max(0, min(100, int(r["fit"])))
        except (KeyError, TypeError, ValueError):
            fit = None  # no score from the ranker for this item, and we do not invent one
        sim = similarity.get(c["id"], 0.0)
        # Late fusion: we blend the ranker's judgement with semantic similarity rescaled to 0-100.
        sim100 = max(0.0, min(100.0, (sim - 0.3) / 0.5 * 100))
        score = round(0.7 * fit + 0.3 * sim100) if fit is not None else round(sim100)
        out.append({**c, "fit": fit, "why": r.get("why", ""), "similarity": round(sim, 3), "score": score,
                    "ranked_by": "ai+similarity" if fit is not None else "similarity", "ranker": by.get(c["id"])})
    return sorted(out, key=lambda x: -x["score"])
