"""Info Critic panels: model-as-judge panels that mix model families.

Panel 1 (Layer 0) checks each normalised listing against its source page. Panel 2 (Layer 2) checks the eligible
shortlist against the user's profile. Each panel takes a majority vote, so one model's mistake does not decide
a row on its own.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .passages import claim_excerpt
from .config import ROLES
from .llm import LLMError, call_json, current_role, set_role

# ---------- deterministic grounding check ----------

def _tokens(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).split()


def evidence_grounded(quote: str, text: str) -> bool:
    """True if the quote, or most of it, appears word for word in the page text.

    This check is deterministic on purpose. We compare normalised tokens and accept a quote when at least 60% of
    its 4-word runs appear on the page, which tolerates small differences in punctuation and line breaks.
    """
    q = _tokens(quote)
    if len(q) < 3:
        return False
    t = " ".join(_tokens(text))
    if " ".join(q) in t:
        return True
    grams = [" ".join(q[i:i + 4]) for i in range(max(1, len(q) - 3))]
    hits = sum(g in t for g in grams)
    return hits / len(grams) >= 0.6


def _excerpt_anchored(text: str, rules: list[dict], limit: int = 4000) -> str:
    """Page start plus the text around each evidence quote, the quote-anchored baseline excerpt.

    We keep it short because Groq's free tier allows 200,000 tokens per model per day, so every token spent on
    one check lowers the number of rows we can check in a day.
    """
    parts = [text[:1500]]
    low = text.lower()
    for r in rules:
        q = r.get("evidence", "")[:60].lower()
        i = low.find(q[:40]) if q else -1
        if i > 1500:
            parts.append("..." + text[max(0, i - 250): i + 450])
    return "\n".join(parts)[:limit]

# "retrieved" gives the judges passages retrieved for each claim; "anchored" is the quote-anchored baseline,
# kept so we can rerun before/after comparisons.
EXCERPT_MODE = "retrieved"

# ---------- Panel 1: source critic ----------

SRC_SYSTEM = ("You are a strict fact-checker for a research funding database. You compare extracted "
              "data with the source page and reject anything the page does not support. Reply in JSON.")

SRC_PROMPT = """Programme: {name}
Source URL: {url}

SOURCE PAGE (passages retrieved for each claim, plus the page opening):
<<<
{excerpt}
>>>

EXTRACTED DATA (written by a different AI):
summary: {summary}
rules:
{rules}

Check the extraction against the source page. Return JSON:
{{"page_matches_programme": true/false (does the page actually describe this programme?),
  "is_funding_opportunity": true/false (does it offer money or a funded place to individual researchers or students -
     e.g. scholarship, fellowship, grant, funded position? General admission guides, news or institutional grants are false),
  "summary_accurate": true/false,
  "rules": [{{"id": "r1", "supported": true/false, "reason": "short"}}  ... one entry per rule AND per fact (f1, f2, ...)],
  "comment": "one short sentence"}}"""


def _facts(listing: dict) -> list[dict]:
    """Key facts that are not rules but that the panel must also confirm (schema v2 rows only)."""
    out = []
    p, f = listing.get("process") or {}, listing.get("funding") or {}
    if p.get("deadline_text") or p.get("next_deadline"):
        out.append({"id": "f1", "claim": f'deadline: {p.get("deadline_text") or p.get("next_deadline")}',
                    "evidence": p.get("evidence") or "", "clears": "deadline"})
    if f.get("stipend_amount") is not None or f.get("fully_funded") is not None:
        out.append({"id": "f2", "claim": f'funding: fully_funded={f.get("fully_funded")}, '
                                         f'stipend={f.get("stipend_amount")} {f.get("currency") or ""}/{f.get("stipend_period") or ""}',
                    "evidence": f.get("evidence") or "", "clears": "funding"})
    if listing.get("opportunity_type"):
        out.append({"id": "f3", "claim": f'type: {listing["opportunity_type"]} for {", ".join(listing.get("career_levels", [])) or "unspecified"}',
                    "evidence": "", "clears": None})
    return out


def _judge_source(spec, listing, excerpt):
    rules_txt = "\n".join(
        f'{r["id"]}: {r["attribute"]} {r["operator"]} {json.dumps(r["value"])}  (quote: "{r["evidence"]}")'
        for r in listing["rules"])
    facts_txt = "\n".join(f'{x["id"]}: {x["claim"]}' + (f' (quote: "{x["evidence"]}")' if x["evidence"] else "")
                          for x in _facts(listing))
    rules_txt = "\n".join(t for t in (rules_txt, facts_txt) if t) or "(none)"
    try:
        v = call_json(spec, SRC_SYSTEM, SRC_PROMPT.format(
            name=listing["name"], url=listing["url"], excerpt=excerpt,
            summary=listing["summary"], rules=rules_txt))
    except LLMError as e:
        return {"judge": spec.label, "family": spec.family, "error": str(e)[:200]}
    return {"judge": spec.label, "family": spec.family,
            "page_matches_programme": bool(v.get("page_matches_programme", False)),
            "is_funding_opportunity": bool(v.get("is_funding_opportunity", True)),
            "summary_accurate": bool(v.get("summary_accurate", False)),
            "rules": {str(x.get("id")): bool(x.get("supported")) for x in v.get("rules", []) if isinstance(x, dict)},
            "comment": str(v.get("comment", ""))[:300]}


def review_listing(listing: dict, page_text: str, judges: list | None = None) -> dict:
    """Run the three-judge source panel and apply its majority votes to the listing.

    judges are the three judges to use, each from a different company; by default we use the standard panel.
    Rules the majority does not support are moved to rules_dropped, and unconfirmed deadline or funding facts are
    cleared rather than shown.
    """
    excerpt = claim_excerpt(page_text, listing) if EXCERPT_MODE == "retrieved" else \
        _excerpt_anchored(page_text, listing["rules"])
    judges = judges or ROLES["critic_sources"]
    role = current_role()  # the role is thread-local, so we hand it to the judge threads

    def judge(s):
        set_role(role)
        return _judge_source(s, listing, excerpt)
    with ThreadPoolExecutor(len(judges)) as ex:
        verdicts = list(ex.map(judge, judges))
    valid = [v for v in verdicts if "error" not in v]
    need = len(valid) // 2 + 1 if valid else 1

    matches = sum(v["page_matches_programme"] for v in valid) >= need
    kept, dropped = [], []
    for r in listing["rules"]:
        votes = [v["rules"].get(r["id"]) for v in valid if r["id"] in v["rules"]]
        r["votes_supported"] = sum(bool(x) for x in votes)
        r["votes_total"] = len(votes)
        r["grounded"] = evidence_grounded(r["evidence"], page_text)
        supported = votes and sum(bool(x) for x in votes) >= len(votes) // 2 + 1
        (kept if supported else dropped).append(r)

    # We clear any fact the majority could not confirm on the page. A blank deadline is better than a wrong one.
    total_votes = sum(r["votes_total"] for r in kept + dropped)
    yes_votes = sum(r["votes_supported"] for r in kept + dropped)
    unconfirmed = []
    for fact in _facts(listing):
        votes = [v["rules"].get(fact["id"]) for v in valid if fact["id"] in v["rules"]]
        total_votes += len(votes)
        yes_votes += sum(bool(x) for x in votes)
        if votes and sum(bool(x) for x in votes) < len(votes) // 2 + 1:
            unconfirmed.append(fact["claim"])
            if fact["clears"] == "deadline":
                listing["process"].update(next_deadline=None, deadline_text=None)
                listing["deadline"] = None
            elif fact["clears"] == "funding":
                for k in ("fully_funded", "stipend_amount", "currency", "stipend_period"):
                    listing["funding"][k] = None
    listing["facts_unconfirmed"] = unconfirmed
    listing["confidence"] = round(yes_votes / total_votes, 2) if total_votes else None

    funding = sum(v.get("is_funding_opportunity", True) for v in valid) >= need
    if not listing.get("about_programme", True) or not matches:
        decision = "rejected"
        reason = "Page does not describe this programme"
    elif not funding:
        decision = "rejected"
        reason = "Not a funding opportunity for individuals (judges' majority)"
    elif not listing.get("official_source"):
        decision = "accepted_with_warning"
        reason = "Third-party source: details should be confirmed on the official site"
    else:
        decision = "accepted"
        reason = "Verified against the official page"
    listing["rules"] = kept
    listing["rules_dropped"] = dropped
    listing["review"] = {"decision": decision, "reason": reason, "verdicts": verdicts,
                         "judges": [f"{s.label} ({s.family})" for s in judges]}
    return listing

# ---------- Panel 2: shortlist critic ----------

SL_SYSTEM = ("You independently audit recommendations made by another AI system for a researcher. "
             "Flag anything irrelevant or any eligibility problem. Reply in JSON.")

SL_PROMPT = """RESEARCHER PROFILE:
{profile}

CANDIDATE OPPORTUNITIES (already passed an automated eligibility filter):
{cands}

For EVERY candidate return an entry. JSON:
{{"reviews": [{{"id": "...", "relevance": 1-5 (5 = excellent match to the research and goals),
  "concern": "short eligibility or fit concern, or null"}}]}}"""


def _judge_shortlist(spec, profile_txt, cands_txt, ids):
    try:
        v = call_json(spec, SL_SYSTEM, SL_PROMPT.format(profile=profile_txt, cands=cands_txt))
        out = {}
        for x in v.get("reviews", []):
            if isinstance(x, dict) and str(x.get("id")) in ids:
                try:
                    rel = max(1, min(5, int(x.get("relevance", 3))))
                except (TypeError, ValueError):
                    rel = 3
                c = x.get("concern")
                out[str(x["id"])] = {"relevance": rel,
                                     "concern": c if c and str(c).lower() not in ("null", "none", "") else None}
        return {"judge": spec.label, "family": spec.family, "reviews": out}
    except LLMError as e:
        return {"judge": spec.label, "family": spec.family, "error": str(e)[:200], "reviews": {}}


def review_shortlist(profile: dict, candidates: list[dict]) -> dict:
    """Have the shortlist panel score each candidate's relevance and flag concerns.

    Returns a dict keyed by listing id, each with the mean relevance, the judges' concerns and the per-judge
    reviews, plus "_judges" and "_errors" entries for the UI.
    """
    if not candidates:
        return {}
    profile_txt = json.dumps({k: profile[k] for k in (
        "nationality", "residency", "career_stage", "highest_degree", "fields",
        "research_summary", "goals") if k in profile})
    cands_txt = "\n".join(
        f'- id={c["id"]} | {c["name"]} ({c["type"]}, {c["host_country"]}) | {c["summary"][:280]}'
        for c in candidates)
    ids = {c["id"] for c in candidates}
    judges = ROLES["critic_shortlist"]

    def judge(s):
        set_role("live")
        return _judge_shortlist(s, profile_txt, cands_txt, ids)
    with ThreadPoolExecutor(len(judges)) as ex:
        results = list(ex.map(judge, judges))
    merged = {}
    for cid in ids:
        by = {r["judge"]: r["reviews"][cid] for r in results if cid in r.get("reviews", {})}
        rels = [b["relevance"] for b in by.values()]
        merged[cid] = {"relevance": round(sum(rels) / len(rels), 1) if rels else None,
                       "concerns": [f'{j}: {b["concern"]}' for j, b in by.items() if b["concern"]],
                       "by_judge": by}
    merged["_judges"] = [f"{s.label} ({s.family})" for s in judges]
    merged["_errors"] = [r["error"] for r in results if "error" in r]
    return merged
