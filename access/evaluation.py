"""Evaluation harness (tooling): reports faults in the system rather than fixing them.

It runs unit tests of the eligibility gate on hand-written rules with known answers, invariant checks over the
real dataset for every test persona, and quality metrics for the Layer 0 critic panel (judge agreement, evidence
grounding, official sources). The four example researchers below are fictional and double as the home-page demos.
"""
import itertools
import json

from .config import DATA
from .gate import check_rule, evaluate
from .lookup import load as load_lookup

PERSONAS = {
    "Priya - CS master's student (India) seeking a PhD in Singapore": {
        "name": "Priya", "nationality": "India", "residency": "India", "career_stage": "masters",
        "highest_degree": "bachelors", "age": 24, "ielts": 7.0, "publications": 1, "gpa": 3.6,
        "target_countries": ["Singapore"], "wanted_types": ["phd_scholarship"],
        "about": "I am finishing a master's in computer science. My thesis uses graph neural networks to "
                 "detect fraud in financial transaction networks. I want to do a PhD in trustworthy machine "
                 "learning, ideally in Singapore, and later work in AI research."},
    "Wei Ling - biology PhD candidate (Singapore) planning a postdoc": {
        "name": "Wei Ling", "nationality": "Singapore", "residency": "Singapore", "career_stage": "phd_candidate",
        "highest_degree": "masters", "age": 28, "ielts": None, "publications": 3, "gpa": 3.8,
        "target_countries": ["United Kingdom", "Germany", "Singapore"], "wanted_types": ["postdoc_fellowship"],
        "about": "Final-year PhD candidate in structural biology working on protein engineering of "
                 "enzymes for plastic degradation using cryo-EM. Looking for a postdoctoral fellowship abroad "
                 "in Europe to build independence before returning to Singapore."},
    "Daniel - physics postdoc (USA), 2 years after PhD": {
        "name": "Daniel", "nationality": "United States", "residency": "United States", "career_stage": "postdoc",
        "highest_degree": "phd", "years_since_phd": 2, "age": 31, "publications": 8,
        "target_countries": ["Germany", "Japan", "Singapore"],
        "wanted_types": ["postdoc_fellowship", "research_grant"],
        "about": "Postdoctoral researcher in condensed matter physics studying quantum materials and "
                 "topological superconductors with ultrafast spectroscopy. Seeking an independent fellowship "
                 "or early-career grant to start my own research line in Europe or Asia."},
    "Amara - engineering undergraduate (Nigeria) seeking a funded master's": {
        "name": "Amara", "nationality": "Nigeria", "residency": "Nigeria", "career_stage": "undergraduate",
        "highest_degree": "bachelors", "age": 22, "ielts": 6.5, "publications": 0, "gpa": 3.5,
        "target_countries": ["United Kingdom", "Germany", "France"], "wanted_types": ["masters_scholarship"],
        "about": "Final-year electrical engineering student focused on solar microgrids and battery storage "
                 "for rural electrification. I want a fully funded master's in renewable energy engineering "
                 "in Europe or the UK."},
}

# Each case is (rule, profile fields, expected status). We worked these answers out by hand, so they serve as
# ground truth for the gate.
GATE_CASES = [
    ({"attribute": "nationality", "operator": "in", "value": ["Singapore"]}, {"nationality": "India"}, "fail"),
    ({"attribute": "nationality", "operator": "in", "value": ["Singapore"]}, {"nationality": "Singapore"}, "pass"),
    ({"attribute": "nationality", "operator": "not_in", "value": ["Singapore"]}, {"nationality": "Singapore"}, "fail"),
    ({"attribute": "nationality", "operator": "not_in", "value": ["Singapore"]}, {"nationality": "India"}, "pass"),
    ({"attribute": "residency", "operator": "in", "value": ["Singapore", "Singapore PR"]},
     {"nationality": "Malaysia", "residency": "Singapore PR"}, "pass"),
    ({"attribute": "ielts", "operator": "gte", "value": 7.0}, {"ielts": 6.5}, "near"),
    ({"attribute": "ielts", "operator": "gte", "value": 7.0}, {"ielts": 5.5}, "fail"),
    ({"attribute": "ielts", "operator": "gte", "value": 7.0}, {}, "unknown"),
    ({"attribute": "publications", "operator": "gte", "value": 3}, {"publications": 2}, "near"),
    ({"attribute": "years_since_phd", "operator": "lte", "value": 4},
     {"highest_degree": "phd", "years_since_phd": 6}, "fail"),
    # A PhD candidate meets "within N years of PhD" once the PhD is awarded, but never "at least 7 years since PhD".
    ({"attribute": "years_since_phd", "operator": "lte", "value": 2},
     {"career_stage": "phd_candidate", "highest_degree": "masters"}, "conditional"),
    ({"attribute": "years_since_phd", "operator": "gte", "value": 7},
     {"career_stage": "phd_candidate", "highest_degree": "masters"}, "fail"),
    ({"attribute": "years_since_phd", "operator": "lte", "value": 4},
     {"highest_degree": "masters", "career_stage": "phd_candidate"}, "conditional"),
    # "Open to all" must not be read as the name of a country.
    ({"attribute": "nationality", "operator": "in", "value": ["all"]}, {"nationality": "India"}, "pass"),
    ({"attribute": "nationality", "operator": "in", "value": ["International"]}, {"nationality": "Nigeria"}, "pass"),
    # The applicant is finishing the required degree now, so the rule is met on completion.
    ({"attribute": "highest_degree", "operator": "gte", "value": "masters"},
     {"highest_degree": "bachelors", "career_stage": "masters"}, "conditional"),
    ({"attribute": "career_stage", "operator": "in", "value": ["early_career"]}, {"career_stage": "postdoc"}, "pass"),
    ({"attribute": "career_stage", "operator": "in", "value": ["postdoc"]}, {"career_stage": "phd_candidate"},
     "conditional"),
    ({"attribute": "career_stage", "operator": "in", "value": ["phd_candidate"]}, {"career_stage": "masters"}, "near"),
    ({"attribute": "career_stage", "operator": "in", "value": ["phd_candidate"]}, {"career_stage": "postdoc"}, "fail"),
    ({"attribute": "highest_degree", "operator": "gte", "value": "masters"}, {"highest_degree": "bachelors"}, "near"),
    ({"attribute": "field", "operator": "in", "value": ["biology_life_sciences"]}, {"fields": ["computer_science"]}, "fail"),
    ({"attribute": "field", "operator": "in", "value": ["computer_science"]}, {"fields": ["data_science_ai"]}, "pass"),
    ({"attribute": "field", "operator": "in", "value": ["any"]}, {"fields": ["humanities_arts"]}, "pass"),
    ({"attribute": "toefl", "operator": "gte", "value": 100}, {"toefl": 90}, "near"),
    ({"attribute": "age", "operator": "lte", "value": 30}, {"age": 31}, "fail"),
]


# Each case is (programme, profile, expected outcome), for the checks the gate infers from programme type,
# career levels and fields when the page states no rule.
IMPLIED_CASES = [
    # A working professional who holds the preceding degree can apply for a degree scholarship.
    ({"opportunity_type": "phd_scholarship", "career_levels": ["phd_candidate"], "fields": ["any"], "rules": []},
     {"career_stage": "industry", "highest_degree": "masters"}, "eligible"),
    ({"opportunity_type": "phd_scholarship", "career_levels": ["phd_candidate"], "fields": ["any"],
      "rules": [{"id": "r1", "attribute": "career_stage", "operator": "in", "value": ["phd_candidate"]}]},
     {"career_stage": "industry", "highest_degree": "masters"}, "eligible"),
    ({"opportunity_type": "phd_scholarship", "career_levels": ["phd_candidate"], "fields": ["any"], "rules": []},
     {"career_stage": "industry", "highest_degree": "phd"}, "excluded"),
    # Final-year PhD candidates may apply for postdoc fellowships, since the PhD is only needed by the start date.
    ({"opportunity_type": "postdoc_fellowship", "career_levels": [], "fields": ["any"], "rules": []},
     {"career_stage": "phd_candidate", "highest_degree": "masters"}, "eligible"),
    # Degree scholarships list the stage they fund, and the applicant sits one step below it.
    ({"opportunity_type": "phd_scholarship", "career_levels": ["phd_candidate"], "fields": ["any"], "rules": []},
     {"career_stage": "masters", "highest_degree": "bachelors"}, "eligible"),
    ({"opportunity_type": "masters_scholarship", "career_levels": ["masters"], "fields": ["any"], "rules": []},
     {"career_stage": "undergraduate", "highest_degree": "bachelors"}, "eligible"),
    ({"opportunity_type": "masters_scholarship", "career_levels": ["masters"], "fields": ["any"], "rules": []},
     {"career_stage": "postdoc", "highest_degree": "phd"}, "excluded"),
    ({"opportunity_type": "research_grant", "career_levels": ["early_career", "mid_career"], "fields": ["any"],
      "rules": []}, {"career_stage": "postdoc", "highest_degree": "phd"}, "eligible"),
    ({"opportunity_type": "postdoc_fellowship", "career_levels": [], "fields": ["any"], "rules": []},
     {"career_stage": "masters", "highest_degree": "bachelors"}, "excluded"),
    ({"opportunity_type": "postdoc_fellowship", "career_levels": ["postdoc"], "fields": ["biology_life_sciences"],
      "rules": []}, {"career_stage": "postdoc", "highest_degree": "phd", "fields": ["physics_astronomy"]}, "excluded"),
    ({"opportunity_type": "phd_scholarship", "career_levels": ["masters", "undergraduate"], "fields": ["any"],
      "rules": []}, {"career_stage": "masters", "highest_degree": "bachelors"}, "eligible"),
]


def run_gate_unit_tests() -> list[dict]:
    """Run the inferred-check cases and the single-rule cases, one result row per case."""
    out = []
    for prog, prof, expected in IMPLIED_CASES:
        got = evaluate(prog, prof)["outcome"]
        out.append({"rule": f'inferred: {prog["opportunity_type"]} {prog["career_levels"] or ""} {prog["fields"]}',
                    "profile": json.dumps(prof), "expected": expected, "got": got, "passed": got == expected,
                    "explanation": "; ".join(c["why"] for c in evaluate(prog, prof)["checks"])})
    for rule, prof, expected in GATE_CASES:
        got, why = check_rule({**rule, "id": "t"}, prof)
        out.append({"rule": f'{rule["attribute"]} {rule["operator"]} {rule["value"]}',
                    "profile": json.dumps(prof), "expected": expected, "got": got,
                    "passed": got == expected, "explanation": why})
    return out


def _persona_profile(form: dict) -> dict:
    """Give each persona fixed fields instead of running the profile builder, so the gate tests are repeatable."""
    fields = {"Priya": ["computer_science", "data_science_ai"], "Wei Ling": ["biology_life_sciences"],
              "Daniel": ["physics_astronomy"], "Amara": ["electrical_engineering", "energy_sustainability"]
              }.get(form["name"], ["any"])
    return {**form, "fields": fields}


def run_invariants() -> list[dict]:
    """Check, for every persona and every searchable listing, that the gate's outcome agrees with its own checks."""
    listings = load_lookup()[0]
    results = []
    for label, form in PERSONAS.items():
        p = _persona_profile(form)
        bad = []
        counts = {"eligible": 0, "near_miss": 0, "excluded": 0}
        for l in listings:
            g = evaluate(l, p)
            counts[g["outcome"]] += 1
            st = [c["status"] for c in g["checks"]]
            if g["outcome"] == "eligible" and ("fail" in st or "near" in st):
                bad.append(f'{l["name"]}: marked eligible despite a failed rule')
            if g["outcome"] == "near_miss" and ("fail" in st or "near" not in st):
                bad.append(f'{l["name"]}: near-miss must have only achievable gaps')
            for c, r in zip(g["checks"], l["rules"]):
                if c["status"] == "near" and r["hard"] and r["attribute"] != "years_since_phd":
                    bad.append(f'{l["name"]}: hard rule "{r["attribute"]}" treated as achievable')
        results.append({"persona": label, **counts, "faults": bad, "passed": not bad})
    return results


def critic_metrics() -> dict:
    """Summarise the critic panel over all reviewed listings: decisions, rules dropped, grounding and agreement."""
    from .db import all_listings, connect
    with connect() as con:
        reviewed = [l for l in all_listings(con, include_rejected=True) if l.get("schema_version") == "2.0"]
    if not reviewed:
        return {}
    pair_agree, pair_total = {}, {}
    rules_total = rules_dropped = grounded = 0
    for l in reviewed:
        vs = [v for v in l["review"]["verdicts"] if "error" not in v]
        all_rules = l["rules"] + l.get("rules_dropped", [])
        rules_total += len(all_rules)
        rules_dropped += len(l.get("rules_dropped", []))
        grounded += sum(bool(r.get("grounded")) for r in all_rules)
        for a, b in itertools.combinations(vs, 2):
            key = f'{a["judge"]} vs {b["judge"]}'
            for rid in set(a["rules"]) & set(b["rules"]):
                pair_total[key] = pair_total.get(key, 0) + 1
                pair_agree[key] = pair_agree.get(key, 0) + (a["rules"][rid] == b["rules"][rid])
    decisions = {}
    for l in reviewed:
        decisions[l["review"]["decision"]] = decisions.get(l["review"]["decision"], 0) + 1
    return {
        "listings_reviewed": len(reviewed),
        "decisions": decisions,
        "official_sources_pct": round(100 * sum(l.get("official_source", False) for l in reviewed) / max(1, len(reviewed))),
        "rules_extracted": rules_total,
        "rules_dropped_by_panel_pct": round(100 * rules_dropped / max(1, rules_total)),
        "evidence_found_verbatim_pct": round(100 * grounded / max(1, rules_total)),
        "judge_agreement_pct": {k: round(100 * pair_agree[k] / pair_total[k]) for k in pair_total},
    }
