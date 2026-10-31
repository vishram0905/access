"""Application advisor (Layer 3).

Turns the verified facts for each top result into an application plan, and for each near-miss into a plan for
closing the gap. The model sees only facts we pass in, plus passages retrieved from the official page.
"""
import json
from datetime import date

from .config import ROLES
from .llm import LLMError, call_json

SYSTEM = ("You are a research funding advisor. Give practical, specific application advice using ONLY the facts "
          "provided. Never invent requirements, amounts or dates; if something is unknown, tell the applicant to "
          "confirm it on the official page. Write plainly for a non-expert. Reply in JSON.")

PROMPT = """Today is {today}.
APPLICANT: {profile}

OPPORTUNITIES (verified facts from the official pages):
{items}

Base the steps on the facts and on "official_page_passages" (text retrieved from the official page). Do not invent
requirements, documents or dates that appear in neither.

For EVERY opportunity id return advice. JSON:
{{"advice": [{{"id": "...",
  "verdict": one short sentence on how strong a candidate the applicant is,
  "steps": 3-6 concrete next steps in order (e.g. contact a supervisor, prepare documents, book a test),
  "timeline": one sentence working back from the deadline (or "Deadline not stated - check the official page"),
  "close_the_gap": for near-misses only: what exactly to achieve and a realistic route to it; otherwise null,
  "watch_out": one caution (conditional criteria, bonds, things to verify) or null}}]}}"""


def _facts(x: dict, near: bool) -> dict:
    p = x.get("process") or {}
    gaps = [c["why"] for c in x["gate"]["checks"] if c["status"] == "near"]
    unknown = [c["why"] for c in x["gate"]["checks"] if c["status"] == "unknown"]
    return {"id": x["id"], "name": x["name"], "provider": x.get("provider"), "kind": x.get("opportunity_type"),
            "host_country": x.get("host_country"), "near_miss": near, "gaps_to_close": gaps,
            "not_verified_for_applicant": unknown, "conditional_criteria": x.get("conditional_criteria", []),
            "deadline": p.get("next_deadline") or p.get("deadline_text"), "status": p.get("status"),
            "needs_supervisor_or_host": p.get("needs_supervisor_or_host"),
            "proposal_required": p.get("proposal_required"), "references_required": p.get("references_required"),
            "documents_required": p.get("documents_required", [])[:8],
            "obligations": (x.get("obligations") or {}).get("text"),
            "critic_concerns": (x.get("critic") or {}).get("concerns", [])[:2],
            # Passages from the official page about applying, so the steps come from the source, not model memory
            "official_page_passages": _how_to_apply(x)}


def _how_to_apply(x: dict, k: int = 3) -> list[str]:
    from .passages import page_text, retrieve
    try:
        text = page_text(x.get("url", ""))
        return [p[:700] for _, p in retrieve(text, "how to apply: application documents, deadline, eligibility "
                                                     "requirements, selection process", k=k)] if text else []
    except Exception:
        return []


def advise(profile: dict, shortlist: list[dict], near: list[dict]) -> dict:
    """Return advice keyed by programme id for up to five shortlisted programmes and four near-misses."""
    items = [_facts(x, False) for x in shortlist[:5]] + [_facts(x, True) for x in near[:4]]
    if not items:
        return {}
    prof = json.dumps({k: profile.get(k) for k in ("career_stage", "highest_degree", "nationality", "ielts",
                                                   "publications", "fields", "goals")})
    prompt = PROMPT.format(today=date.today().isoformat(), profile=prof, items=json.dumps(items, indent=0))
    data = None
    for spec in ROLES["advisor"]:  # the first provider with quota wins
        try:
            data = call_json(spec, SYSTEM, prompt)
            break
        except LLMError:
            continue
    if data is None:
        return {}
    entries = data.get("advice", []) if isinstance(data, dict) else data  # some models return a bare list
    return {str(a.get("id")): a for a in entries or [] if isinstance(a, dict)}
