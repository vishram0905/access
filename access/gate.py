"""Eligibility gate and near-miss set (Layer 2).

This is deliberately plain Python with no model calls: we want the same profile to get the same answer every
time, and every yes or no to be traceable to a rule quoted from the funder's page.
"""
from .schema import ATTRIBUTES, CAREER_STAGES, DEGREE_LABELS, DEGREES, FIELD_FAMILY, NEAR_MISS_MARGIN, human

STAGE_ORDER = ["undergraduate", "masters", "phd_candidate", "postdoc", "early_career", "mid_career", "senior"]
# Funders use these stages interchangeably, so we treat a postdoc as an early-career researcher and vice versa.
STAGE_EQUIV = {"postdoc": {"early_career"}, "early_career": {"postdoc"}}
# For scholarships that pay for a degree we need two things: the stage they fund, and the degree a student at
# that stage is about to finish.
FUNDED_STAGE = {"undergraduate_scholarship": "undergraduate", "masters_scholarship": "masters",
                "phd_scholarship": "phd_candidate"}
FINISHING = {"undergraduate": "bachelors", "masters": "masters", "phd_candidate": "phd"}
OPEN_TO_ALL = {"all", "any", "all countries", "all nationalities", "international", "worldwide", "global",
               "any nationality", "open", "no restriction"}


def _list(codes) -> str:
    """Join field codes into readable text, e.g. 'biology & life sciences, chemistry or physics & astronomy'."""
    xs = [human(c) for c in (codes if isinstance(codes, list) else [codes])]
    return ", ".join(xs[:-1]) + " or " + xs[-1] if len(xs) > 1 else (xs[0] if xs else "")


def _degree(code) -> str:
    return DEGREE_LABELS.get(str(code).lower(), human(code))


def _degrees(codes) -> str:
    xs = [_degree(c) for c in (codes if isinstance(codes, list) else [codes])]
    return " or ".join(xs)


def fields_match(mine: list[str], theirs: list[str]) -> bool:
    """True on an exact field overlap, or when both sides fall in the same broad family.

    We count data_science_ai and computer_science as a match, for example, because funders rarely split them.
    """
    if "any" in theirs:
        return True
    if set(mine) & set(theirs):
        return True
    fam = lambda xs: {FIELD_FAMILY.get(x, x) for x in xs}
    return bool(fam(mine) & fam(theirs))


def next_stage(stage: str) -> str | None:
    i = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1
    return STAGE_ORDER[i + 1] if 0 <= i < len(STAGE_ORDER) - 1 else None


def _lower(xs):
    return [str(x).strip().lower() for x in (xs if isinstance(xs, list) else [xs])]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def stage_fits(mine: str, levels: list[str]) -> bool:
    return mine in levels or bool(STAGE_EQUIV.get(mine, set()) & set(levels))


# The degree an applicant must already hold for a degree scholarship. We need this for people in industry:
# "industry" has no next career stage, but an engineer with a master's is still a valid PhD scholarship applicant.
DEGREE_BEFORE = {"phd_candidate": {"masters", "bachelors"}, "masters": {"bachelors"}}


def entering(mine: str, levels: list[str], kind: str | None, degree: str | None = None) -> bool:
    """Decide whether this person is applying to enter the degree a scholarship funds.

    A degree scholarship lists the stage it funds, but its applicants sit one step below (a master's student
    applying for a PhD scholarship). We also accept anyone outside academia who already holds the degree that
    comes before it, such as an engineer with a master's applying for a PhD scholarship.
    """
    funded = FUNDED_STAGE.get(kind)
    if not funded or funded not in levels:
        return False
    if next_stage(mine) == funded:
        return True
    return mine == "industry" and degree in DEGREE_BEFORE.get(funded, set())


def check_rule(rule: dict, p: dict, kind: str | None = None) -> tuple[str, str]:
    """Check one rule against a profile and return (status, explanation).

    Status is one of pass, conditional, near, fail or unknown. "Conditional" means the rule is met once the
    applicant completes the degree they are finishing now; we count it as eligible but show it as something to
    confirm. kind is the programme's opportunity type, which we need for degree scholarships.
    """
    a, op, v = rule["attribute"], rule["operator"], rule["value"]
    label = ATTRIBUTES[a][2]

    if a in ("nationality", "residency"):
        mine = _lower([p.get("nationality"), p.get("residency")] if a == "residency" else [p.get("nationality")])
        mine = [m for m in mine if m and m != "none"]
        if not mine:
            return "unknown", f"{label} not provided"
        allowed = _lower(v)
        if op == "in" and (not allowed or set(allowed) & OPEN_TO_ALL):
            return "pass", f"No {label.lower()} restriction (open to all)"
        if op != "in" and (not allowed or set(allowed) <= OPEN_TO_ALL):
            return "pass", f"{label} not excluded"
        hit = any(m in allowed or any(m in x or x in m for x in allowed if len(x) > 3) for m in mine)
        if op == "in":
            return ("pass", f"{label} matches") if hit else ("fail", f"Only open to {'residents' if a == 'residency' else 'citizens'} of {', '.join(map(str, v))}")
        return ("fail", f"Not open to {'residents' if a == 'residency' else 'citizens'} of {', '.join(map(str, v))}") if hit else ("pass", f"{label} not excluded")

    if a == "field":
        allowed = _lower(v)
        mine = _lower(p.get("fields") or [])
        if "any" in allowed:
            return "pass", "Open to all fields"
        if not mine or mine == ["any"]:
            return "unknown", "Field not determined"
        return ("pass", "Field matches") if fields_match(mine, allowed) else \
               ("fail", f"Only for {_list(v)}")

    if a == "career_stage":
        mine = p.get("career_stage")
        if not mine:
            return "unknown", "Career stage not provided"
        req = [s for s in _lower(v) if s in CAREER_STAGES]
        if not req or stage_fits(mine, req):
            return "pass", "Career stage matches"
        if entering(mine, req, kind, p.get("highest_degree")):
            return "pass", "Funds the degree you plan to start next"
        if mine == "phd_candidate" and set(req) & {"postdoc", "early_career"}:
            return "conditional", "For researchers with a PhD - met once your PhD is awarded"
        if next_stage(mine) in req:
            return "near", f"For {_list(req)} - you'll reach this at your next career step"
        return "fail", f"Only for {_list(req)}"

    if a == "highest_degree":
        mine = p.get("highest_degree")
        if mine not in DEGREES:
            return "unknown", "Degree not provided"
        rank = DEGREES.index(mine)
        finishing = FINISHING.get(p.get("career_stage"))
        if op == "gte":
            need = DEGREES.index(v) if v in DEGREES else 0
            if rank >= need:
                return "pass", "Degree requirement met"
            if finishing and DEGREES.index(finishing) >= need:
                return "conditional", f"Requires a {_degree(v)} - met once your current degree is completed"
            return ("near", f"Requires a {_degree(v)} - finishing your current degree would qualify") \
                if rank == need - 1 else ("fail", f"Requires at least a {_degree(v)}")
        req = [DEGREES.index(d) for d in _lower(v) if d in DEGREES]
        if rank in req:
            return "pass", "Degree requirement met"
        if finishing and DEGREES.index(finishing) in req:
            return "conditional", f"Requires a {_degrees(v)} - met once your current degree is completed"
        if any(r == rank + 1 for r in req):
            return "near", f"Requires a {_degrees(v)} - finishing your current degree would qualify"
        return "fail", f"Requires a {_degrees(v)}"

    if a == "years_since_phd":
        if p.get("highest_degree") != "phd":
            need = _num(v)
            if p.get("career_stage") == "phd_candidate" and (op == "lte" or not need or need <= 1):
                return "conditional", "Requires a completed PhD - met once your PhD is awarded"
            if p.get("career_stage") == "phd_candidate":
                return "fail", f"Requires at least {need:g} years since PhD"
            return "fail", "Requires a completed PhD"
        mine, need = _num(p.get("years_since_phd")), _num(v)
        if mine is None or need is None:
            return "unknown", "Years since PhD not provided"
        ok = mine <= need if op == "lte" else mine >= need
        word = "at most" if op == "lte" else "at least"
        return ("pass", f"Within {need:g} years of PhD") if ok else ("fail", f"Requires {word} {need:g} years since PhD")

    # Everything left is numeric (age, IELTS, publications, GPA), so we compare numbers.
    mine, need = _num(p.get(a)), _num(v)
    if mine is None or need is None:
        return "unknown", f"{label} not provided"
    if op == "lte":
        return ("pass", f"{label} within limit") if mine <= need else ("fail", f"{label} must be at most {need:g}")
    if mine >= need:
        return "pass", f"{label} requirement met"
    gap = need - mine
    if not ATTRIBUTES[a][1] and gap <= NEAR_MISS_MARGIN.get(a, 0):
        return "near", f"{label}: you have {mine:g}, it needs {need:g} ({gap:g} to go)"
    return "fail", f"{label}: you have {mine:g}, it needs {need:g}"


def implied_checks(listing: dict, p: dict) -> list[dict]:
    """Infer stage and field checks when the funder's page states no explicit rule for them.

    We fall back on the annotated career levels, programme type and fields. Many pages never say "PhD holders
    only" for a postdoc fellowship because it is obvious to them, so without this the gate would pass everyone.
    The app labels these checks as inferred.
    """
    attrs = {r["attribute"] for r in listing.get("rules", [])}
    out = []
    stage, degree = p.get("career_stage"), p.get("highest_degree")
    kind = listing.get("opportunity_type") or listing.get("type")
    levels = [l for l in listing.get("career_levels", []) if l in CAREER_STAGES]
    if "career_stage" not in attrs and "years_since_phd" not in attrs and stage:
        status = why = None
        if kind in ("postdoc_fellowship",) and not levels:
            levels = ["postdoc", "early_career"]
        if kind == "phd_scholarship" and not levels:
            levels = ["undergraduate", "masters", "phd_candidate", "industry"]
        if kind == "masters_scholarship" and not levels:
            levels = ["undergraduate", "industry"]
        if levels:
            if stage_fits(stage, levels):
                status, why = "pass", "Career stage fits who the programme is for"
            elif entering(stage, levels, kind, degree):
                status, why = "pass", "Funds the degree you plan to start next"
            elif kind == "postdoc_fellowship" and degree == "phd":
                status, why = "pass", "Postdoctoral fellowship - PhD completed"
            elif stage == "phd_candidate" and (kind == "postdoc_fellowship" or set(levels) & {"postdoc", "early_career"}):
                status, why = "conditional", "For researchers with a PhD - met once your PhD is awarded"
            elif next_stage(stage) in levels:
                status, why = "near", f"For {_list(levels)} - you'll reach this at your next career step"
            else:
                status, why = "fail", f"Only for {_list(levels)}"
        if status:
            out.append({"rule_id": "implied-stage", "attribute": "career_stage", "status": status,
                        "why": why + " (inferred from the programme description)", "evidence": "", "implied": True})
    fields = [f for f in listing.get("fields", []) if f != "any"]
    mine = [f for f in (p.get("fields") or []) if f != "any"]
    if "field" not in attrs and fields and mine and "any" not in listing.get("fields", []):
        ok = fields_match(mine, fields)
        out.append({"rule_id": "implied-field", "attribute": "field", "status": "pass" if ok else "fail",
                    "why": ("Field matches" if ok else f"Focused on {_list(fields)}")
                           + " (inferred from the programme description)", "evidence": "", "implied": True})
    return out


# Rough effort to close a gap, in "weeks of work". We only use it to order near-misses easiest-first, so the
# numbers are deliberately coarse: (size of one step, weeks per step).
GAP_EFFORT = {"ielts": (0.5, 4), "toefl": (5, 4), "gpa": (0.1, 8), "publications": (1, 12),
              "work_experience_years": (1, 52)}
STEP_EFFORT = {"career_stage": 26, "highest_degree": 26}


def gap_cost(rule: dict, profile: dict) -> float:
    """Estimate the effort to meet one near-miss rule.

    For scores we count numeric steps; for career stage or degree we charge one fixed step.
    """
    a = rule.get("attribute")
    if a in GAP_EFFORT:
        mine, need = _num(profile.get(a)), _num(rule.get("value"))
        if mine is not None and need is not None:
            step, effort = GAP_EFFORT[a]
            return max(0.0, need - mine) / step * effort
    return float(STEP_EFFORT.get(a, 20))


def evaluate(listing: dict, profile: dict) -> dict:
    """Run every stated and inferred check for one listing and decide eligible, near_miss or excluded.

    One failed rule excludes the listing. Near-misses carry a gap cost so the app can show the easiest ones first.
    """
    checks = []
    kind = listing.get("opportunity_type") or listing.get("type")
    for r in listing.get("rules", []):
        status, why = check_rule(r, profile, kind)
        checks.append({"rule_id": r["id"], "attribute": r["attribute"], "status": status,
                       "why": why, "evidence": r.get("evidence", "")})
    checks += implied_checks(listing, profile)
    fails = [c for c in checks if c["status"] == "fail"]
    nears = [c for c in checks if c["status"] == "near"]
    if fails:
        outcome = "excluded"
    elif nears:
        outcome = "near_miss"
    else:
        outcome = "eligible"
    rules = {r["id"]: r for r in listing.get("rules", [])}
    cost = sum(gap_cost(rules.get(c["rule_id"], {"attribute": c["attribute"]}), profile) for c in nears)
    return {"outcome": outcome, "checks": checks, "gap_cost": round(cost, 1),
            "unknowns": [c for c in checks if c["status"] in ("unknown", "conditional")]}
