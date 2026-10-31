"""Demo readiness check (tooling): runs many realistic profiles through the instant search and flags results a
viewer would find inconsistent. It uses the instant path only, so no cloud model is called.

For each result we check that the host country fits the chosen countries (or their region, any country, or not
stated), that the programme type is what was asked for, that the career level fits, and that there are no
duplicates, closed programmes, raw codes in labels, excluded places or unverified records. For each profile we
also flag fewer than five eligible results.

Run: PYTHONPATH=. python scripts/demo_check.py [--verbose]
"""
import re
import sys
from collections import Counter

from access.config import is_excluded_place
from access.evaluation import PERSONAS
from access.gate import FUNDED_STAGE, STAGE_EQUIV, next_stage
from access.pipeline import instant
from access.schema import COUNTRY_REGION
from access.search import RELATED_TYPES

# Extra fictional profiles on top of the four example researchers, chosen to cover other countries, stages and
# funding types than the home-page examples do.
EXTRA = {
    "Chen - materials master's (China) seeking a PhD in Singapore, Japan or Australia": {
        "name": "Chen", "nationality": "China", "career_stage": "masters", "highest_degree": "bachelors",
        "age": 24, "gpa": 3.7, "ielts": 7.0, "target_countries": ["Singapore", "Japan", "Australia"],
        "wanted_types": ["phd_scholarship"],
        "about": "Master's student in materials science working on perovskite solar cells and thin-film "
                 "deposition. I want a fully funded PhD in materials engineering or energy materials."},
    "Aisha - Malaysian school leaver seeking an undergraduate scholarship in Singapore": {
        "name": "Aisha", "nationality": "Malaysia", "career_stage": "undergraduate", "highest_degree": None,
        "age": 18, "target_countries": ["Singapore"], "wanted_types": ["undergraduate_scholarship"],
        "about": "I have just finished my A-levels and want to study computer science or engineering at a "
                 "university in Singapore with a scholarship."},
    "Tom - UK history PhD candidate seeking research or travel grants in the US": {
        "name": "Tom", "nationality": "United Kingdom", "career_stage": "phd_candidate", "highest_degree": "masters",
        "age": 27, "publications": 2, "target_countries": ["United States"],
        "wanted_types": ["research_grant", "travel_mobility_grant"],
        "about": "PhD candidate in modern history researching Cold War diplomacy and archives in Washington. "
                 "I need funding for an archival research visit to the United States."},
    "Sofia - Indonesian graduate seeking a master's scholarship in Australia or the UK": {
        "name": "Sofia", "nationality": "Indonesia", "career_stage": "undergraduate", "highest_degree": "bachelors",
        "age": 23, "ielts": 7.5, "gpa": 3.4, "target_countries": ["Australia", "United Kingdom"],
        "wanted_types": ["masters_scholarship"],
        "about": "I graduated in public health and work on maternal health programmes. I want a master's in "
                 "global public health or epidemiology."},
    "Hiroshi - Japanese mid-career researcher seeking research grants": {
        "name": "Hiroshi", "nationality": "Japan", "career_stage": "mid_career", "highest_degree": "phd",
        "years_since_phd": 12, "age": 41, "publications": 40, "target_countries": ["Japan", "United States"],
        "wanted_types": ["research_grant"],
        "about": "Associate professor in neuroscience studying synaptic plasticity and memory in mice with "
                 "two-photon imaging. Looking for project grants and international collaboration funding."},
    "Fatima - Pakistani public health PhD candidate planning a postdoc in North America": {
        "name": "Fatima", "nationality": "Pakistan", "career_stage": "phd_candidate", "highest_degree": "masters",
        "age": 30, "publications": 5, "target_countries": ["Canada", "United States"],
        "wanted_types": ["postdoc_fellowship", "research_fellowship"],
        "about": "Final-year PhD candidate in epidemiology studying tuberculosis transmission with "
                 "genomic surveillance data. I want a postdoctoral fellowship in global health."},
    "Lucas - Brazilian engineering graduate seeking a master's in Europe": {
        "name": "Lucas", "nationality": "Brazil", "career_stage": "undergraduate", "highest_degree": "bachelors",
        "age": 23, "ielts": 7.0, "gpa": 3.3, "target_countries": ["Germany", "Netherlands", "United Kingdom"],
        "wanted_types": ["masters_scholarship"],
        "about": "Mechanical engineering graduate interested in wind energy and aerodynamics. I want a "
                 "funded master's degree in sustainable energy engineering."},
    "Minh - Vietnamese economics graduate seeking a master's in Japan": {
        "name": "Minh", "nationality": "Vietnam", "career_stage": "undergraduate", "highest_degree": "bachelors",
        "age": 24, "gpa": 3.5, "target_countries": ["Japan"], "wanted_types": ["masters_scholarship"],
        "about": "Economics graduate working on development economics and microfinance. I would like a "
                 "master's in public policy or economics in Japan."},
    "Siti - Singaporean undergraduate in Singapore": {
        "name": "Siti", "nationality": "Singapore", "career_stage": "undergraduate", "highest_degree": None,
        "age": 19, "target_countries": ["Singapore"], "wanted_types": ["undergraduate_scholarship"],
        "about": "I am starting a business and computing degree and need a scholarship or bursary."},
    "Arjun - Indian AI researcher, open to any country and any funding type": {
        "name": "Arjun", "nationality": "India", "career_stage": "postdoc", "highest_degree": "phd",
        "years_since_phd": 1, "age": 29, "publications": 6, "target_countries": [], "wanted_types": [],
        "about": "Postdoc in machine learning working on robust reinforcement learning for robotics."},
}
ALL = {**PERSONAS, **EXTRA}
CODE = re.compile(r"\b[a-z]+_[a-z_]+\b")  # a raw schema code such as phd_scholarship leaking into a label


def stage_ok(stage, levels, kind):
    """Our own, simpler reading of the gate's stage rules, used to spot results whose career level looks wrong."""
    if not levels or not stage:
        return True
    if stage in levels or STAGE_EQUIV.get(stage, set()) & set(levels):
        return True
    funded = FUNDED_STAGE.get(kind)
    if funded and funded in levels and next_stage(stage) == funded:
        return True
    return stage == "phd_candidate" and bool(set(levels) & {"postdoc", "early_career"})


def check(label, form, verbose=False):
    """Run one profile, print a one-line summary and return the issue counts and any relaxed filters."""
    res = instant(dict(form))
    stats = res["search_stats"]
    applied = stats.get("filters_applied", {})
    targets = form.get("target_countries") or []
    wanted = form.get("wanted_types") or []
    wanted_all = set(wanted) | {r for w in wanted for r in RELATED_TYPES.get(w, [])}
    issues = Counter()
    notes = []
    names = Counter()
    for group, items in (("eligible", res["shortlist"]), ("near", res["near_misses"])):
        for x in items:
            kind = x.get("opportunity_type") or x.get("type")
            hosts = set(x.get("host_countries") or ([x.get("host_country")] if x.get("host_country") else []))
            regions = set(x.get("host_regions") or [])
            scope_ok = x.get("host_anywhere") or x.get("host_country") in (None, "", "Not stated", "Any country", "Multiple")
            if targets and not (hosts & set(targets) or regions & {COUNTRY_REGION.get(t) for t in targets} or scope_ok):
                issues["country"] += 1
                notes.append(f"  country  [{group}] {x['name'][:60]} | host={x.get('host_country')}")
            if x.get("host_country") == "Multiple":
                issues["multiple_label"] += 1
            if wanted and kind not in wanted_all:
                issues["type"] += 1
                notes.append(f"  type     [{group}] {x['name'][:60]} | {kind}")
            if not stage_ok(form.get("career_stage"), [l for l in x.get("career_levels") or []], kind):
                issues["stage"] += 1
                notes.append(f"  stage    [{group}] {x['name'][:60]} | levels={x.get('career_levels')}")
            if (x.get("deadline_status") or {}).get("state") == "closed":
                issues["closed"] += 1
                notes.append(f"  closed   [{group}] {x['name'][:60]} | {x['deadline_status']['label']}")
            for f in ("name", "provider", "host_country"):
                if CODE.search(str(x.get(f) or "")):
                    issues["raw_code"] += 1
                    notes.append(f"  rawcode  [{group}] {f}={x.get(f)}")
            if is_excluded_place(x):
                issues["excluded_place"] += 1
            status = (x.get("verification") or {}).get("status", "unchecked")
            if status != "verified":
                issues["not_verified"] += 1
            names[re.sub(r"\W+", " ", x["name"].lower()).strip()] += 1
    issues["duplicates"] = sum(n - 1 for n in names.values() if n > 1)
    n_el, n_near = len(res["shortlist"]), len(res["near_misses"])
    relaxed = [c for c in ("host_country", "opportunity_type") if (form.get("target_countries") if c == "host_country" else wanted) and c not in applied]
    if n_el < 5:
        issues["few_results"] += 1
    flag = {k: v for k, v in issues.items() if v}
    print(f"{label[:70]:<70} eligible={n_el:>2} near={n_near:>2} pool={stats.get('after_filters')}"
          f"{' RELAXED=' + ','.join(relaxed) if relaxed else ''}  {flag or 'OK'}")
    if verbose:
        for x in res["shortlist"][:12]:
            print(f"     · {x['name'][:70]} | {x.get('host_country')} | {x.get('opportunity_type') or x.get('type')} "
                  f"| {(x.get('deadline_status') or {}).get('label','')[:30]}")
        print("\n".join(notes[:15]))
    return flag, relaxed


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv
    total = Counter()
    for label, form in ALL.items():
        flag, relaxed = check(label, form, verbose)
        total.update(flag)
        total.update({"relaxed": bool(relaxed)})
    print("TOTAL", dict(total))
