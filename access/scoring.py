"""Trust and Completeness scores for each programme row (Layer 0, library building).

Trust asks whether the row is correct and decides its band (high, medium or low). Completeness asks how useful
the row is; we show it as a badge and never hide a row because of it. Both come from measurable KPIs.
The band cut-offs are read from data/lookup/calibration.json, which the Auditor agent writes. Until enough rows
have been audited we fall back to provisional defaults.
"""
import json

from .critics import evidence_grounded
from .config import DATA

TRUST_WEIGHTS = {"authenticity": 0.25, "funding_vote": 0.20, "rule_support": 0.20,
                 "grounding": 0.20, "agreement": 0.10, "validation": 0.05}
PROVISIONAL_BANDS = {"high": 0.75, "medium": 0.5, "provisional": True}
CALIBRATION_FILE = DATA / "lookup" / "calibration.json"


def kpis(listing: dict, page_text: str, exclude_judge: str | None = None) -> dict:
    """Compute the six trust KPIs for one row.

    exclude_judge leaves one judge's votes out. We use it when that model is also the Auditor, so it does not
    get to grade its own work.
    """
    review = listing.get("review", {})
    valid = [v for v in review.get("verdicts", []) if "error" not in v and v.get("judge") != exclude_judge]
    n = max(1, len(valid))
    rules = listing.get("rules", []) + listing.get("rules_dropped", [])
    if exclude_judge:  # recount the rule votes without that judge
        rules = []
        for r in listing.get("rules", []) + listing.get("rules_dropped", []):
            votes = [v["rules"][r["id"]] for v in valid if r["id"] in v.get("rules", {})]
            rules.append({**r, "votes_supported": sum(bool(x) for x in votes), "votes_total": len(votes)})

    page_match = sum(v.get("page_matches_programme", False) for v in valid) / n
    official = 0.5 if listing.get("cert_warning") or listing.get("archived_at") else \
        float(bool(listing.get("official_source")))
    authenticity = 0.5 * official + 0.5 * page_match  # a cert warning or archive copy halves the source credit
    funding_vote = sum(v.get("is_funding_opportunity", True) for v in valid) / n

    yes = sum(r.get("votes_supported", 0) for r in rules)
    tot = sum(r.get("votes_total", 0) for r in rules)
    rule_support = yes / tot if tot else 0.6  # a page with no rules is neutral; we do not push it to zero

    quotes = [r.get("evidence", "") for r in rules]
    quotes += [q for q in ((listing.get("funding") or {}).get("evidence"),
                           (listing.get("process") or {}).get("evidence")) if q]
    quotes = [q for q in quotes if q]
    grounding = sum(evidence_grounded(q, page_text) for q in quotes) / len(quotes) if quotes else 0.5

    # Agreement is the share of items where every available judge voted the same way. With fewer than three
    # judges we discount it, since two judges agreeing says less.
    item_ids = {k for v in valid for k in v.get("rules", {})}
    unanimous = sum(len({v["rules"][k] for v in valid if k in v.get("rules", {})}) == 1 for k in item_ids)
    agreement = (unanimous / len(item_ids) if item_ids else 1.0) * (1.0 if len(valid) >= 3 else 0.8)

    validation = 0.5 if listing.get("validation_issues") else 1.0
    return {k: round(v, 3) for k, v in dict(authenticity=authenticity, funding_vote=funding_vote,
                                             rule_support=rule_support, grounding=grounding,
                                             agreement=agreement, validation=validation).items()}


def trust(k: dict) -> float:
    return round(sum(TRUST_WEIGHTS[x] * k[x] for x in TRUST_WEIGHTS), 3)


def completeness(listing: dict) -> float:
    f, p = listing.get("funding") or {}, listing.get("process") or {}
    checks = [bool(listing.get("rules")), bool(p.get("next_deadline") or p.get("deadline_text")),
              f.get("stipend_amount") is not None or f.get("fully_funded") is not None,
              bool(p.get("documents_required")), bool(p.get("application_url") or listing.get("url"))]
    return round(sum(checks) / len(checks), 2)


def bands() -> dict:
    """Band cut-offs from the Auditor's calibration file, or the provisional defaults if it has not run yet."""
    if CALIBRATION_FILE.exists():
        return json.loads(CALIBRATION_FILE.read_text())
    return dict(PROVISIONAL_BANDS)


def band_of(t: float | None, b: dict | None = None) -> str:
    b = b or bands()
    if t is None:
        return "low"
    return "high" if t >= b["high"] else "medium" if t >= b["medium"] else "low"


def score(listing: dict, page_text: str) -> dict:
    """Attach KPIs, Trust, Completeness and band to a listing (in place) and return it."""
    k = kpis(listing, page_text)
    listing["kpis"] = k
    listing["trust"] = trust(k)
    listing["completeness"] = completeness(listing)
    listing["band"] = band_of(listing["trust"])
    return listing
