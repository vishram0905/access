"""Result clean-up applied to every search (between Layer 2 and Layer 3).

We attach a deadline status, merge duplicate programmes, give generic titles a funder name and pick the one
follow-up question worth asking. All of it is deterministic, with no model calls.
"""
import re
from datetime import date, datetime

CLOSING_SOON_DAYS = 30


def _parse(d):
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def deadline_status(l: dict, today: date | None = None) -> dict:
    """Work out where a programme stands against its deadline.

    Returns {"state", "label", "date", "sort"}. state is one of open, closing_soon, next_round, closed or check,
    label is the short badge text, date is ISO or None, and sort is the number of days to the deadline, with
    large values for unknown dates so they sort last.
    """
    today = today or date.today()
    p = l.get("process") or {}
    nd, cycle, status = _parse(p.get("next_deadline")), p.get("application_cycle"), p.get("status")
    if nd and nd >= today:
        days = (nd - today).days
        state = "closing_soon" if days <= CLOSING_SOON_DAYS else "open"
        label = f"Closes {nd:%-d %b %Y}" + (f" · {days} day{'s' * (days != 1)} left" if state == "closing_soon" else "")
        return {"state": state, "label": label, "date": nd.isoformat(), "sort": days}
    if nd and cycle in ("annual", "rolling"):  # the last round has passed, but it runs every year
        return {"state": "next_round", "label": f"Last deadline {nd:%-d %b %Y} · runs every year",
                "date": nd.isoformat(), "sort": 400}
    if nd or status == "closed":
        if cycle in ("annual", "rolling") or status in ("upcoming", "open"):
            return {"state": "next_round", "label": "Next round expected", "date": None, "sort": 450}
        return {"state": "closed", "label": f"Closed{f' ({nd:%-d %b %Y})' if nd else ''}",
                "date": nd.isoformat() if nd else None, "sort": 9999}
    m = re.findall(r"\b(20\d\d)(?:\s*[-/–]\s*(\d{2,4}))?\b", l.get("name") or "")
    if m:
        last = max(int(b) if len(b) == 4 else int(a[:2] + b) if b else int(a) for a, b in m)
        if last < today.year:  # e.g. "Fellowship 2020-21": an old call, not this year's
            return {"state": "closed", "label": f"Closed ({last} call)", "date": None, "sort": 9999}
    if cycle == "rolling" or status == "open":
        return {"state": "open", "label": "Open · rolling applications" if cycle == "rolling" else "Open",
                "date": None, "sort": 500}
    text = (p.get("deadline_text") or l.get("deadline") or "").strip()
    return {"state": "check", "label": f"Deadline: {text[:40]}" if text else "Check dates on the official page",
            "date": None, "sort": 600}


def _key(l: dict) -> str:
    name = re.sub(r"\b(19|20)\d\d(/\d\d)?\b|\(.*?\)|[^a-z0-9 ]", " ", (l.get("name") or "").lower())
    prov = re.sub(r"\(.*?\)|[^a-z0-9 ]", " ", (l.get("provider") or "").lower())
    return " ".join(name.split()) + "|" + " ".join(prov.split()[:3])


def dedupe(items: list[dict]) -> list[dict]:
    """Show a programme once even when it is published on several pages (one per year or per country, say).

    We keep the copy with the highest trust and count the others on it as also_listed.
    """
    best, order = {}, []
    for x in items:
        k = _key(x)
        if k not in best:
            best[k] = x
            order.append(k)
            x["also_listed"] = 0
        else:
            keep = best[k]
            if (x.get("trust") or 0) > (keep.get("trust") or 0):
                x["also_listed"] = keep.get("also_listed", 0) + 1
                best[k] = x
            else:
                keep["also_listed"] = keep.get("also_listed", 0) + 1
    return [best[k] for k in order]


GENERIC_NAME = re.compile(r"^(the )?((post)?doctoral|research|graduate|undergraduate|master'?s|phd|study|travel|"
                          r"international)?\s*(fellowships?|scholarships?|grants?|awards?|stipends?|bursar(y|ies)|"
                          r"funding)( (programmes?|programs?|scheme))?$", re.I)
HOST_LABEL = {"Multiple": "Several countries (see official page)"}


def display_name(l: dict) -> str:
    """Add the funder to a generic title. "Research Fellowships" on its own means nothing in a list of results."""
    name = (l.get("name") or "").strip()
    prov = (l.get("provider") or "").strip()
    if GENERIC_NAME.match(name) and prov and prov.lower() not in name.lower():
        return f"{name} ({prov})"
    return name


def closed_for_good(x: dict) -> bool:
    """True for a one-off call whose deadline has passed. Nobody can apply again, so we never show it as a match."""
    return (x.get("deadline_status") or {}).get("state") == "closed" and \
        (x.get("process") or {}).get("application_cycle") == "one_off"


def by_availability(items: list[dict]) -> list[dict]:
    """Keep the order, but move closed programmes (no next round known) to the end."""
    return sorted(items, key=lambda x: (x.get("deadline_status") or {}).get("state") == "closed")


def final_order(items: list[dict]) -> list[dict]:
    """Order the list after ranking: strong matches by score, then weaker fits by score, closed programmes last.

    We leave the host tier out here. It only orders the similarity list before ranking, and the ranker already
    weighs the researcher's countries.
    """
    closed = lambda x: (x.get("deadline_status") or {}).get("state") == "closed"
    return sorted(items, key=lambda x: (closed(x), bool(x.get("weaker_fit")), x.get("fit") is None,
                                        -(x.get("score") or 0)))


def tidy(items: list[dict]) -> list[dict]:
    """Merge duplicates, attach deadline status and display names, drop closed one-off calls and move other
    closed programmes to the end."""
    items = dedupe(items)
    for x in items:
        x["deadline_status"] = deadline_status(x)
        x["display_name"] = display_name(x)
        if x.get("host_country") in HOST_LABEL:
            x["host_label"] = HOST_LABEL[x["host_country"]]
    same = {}
    # Different programmes can share a title (each university's ASEAN Scholarship, for example), so we add the
    # provider to tell them apart.
    for x in items:
        same.setdefault(x["display_name"].lower(), []).append(x)
    for xs in same.values():
        if len(xs) > 1:
            for x in xs:
                if x.get("provider") and x["provider"].lower() not in x["display_name"].lower():
                    x["display_name"] = f"{x['display_name']} ({x['provider']})"
    return by_availability([x for x in items if not closed_for_good(x)])


# ---------------- the one follow-up question worth asking

FOLLOW_UP = {  # attribute -> question shown to the user
    "ielts": "What is your IELTS score?", "toefl": "What is your TOEFL iBT score?",
    "gpa": "What is your GPA (out of 4.0)?", "publications": "How many publications do you have?",
    "age": "How old are you?", "years_since_phd": "How many years ago did you finish your PhD?",
    "residency": "Where do you currently live (country of residence / PR)?",
    "work_experience_years": "How many years of work experience do you have (including voluntary work)?",
}


def best_follow_up(items: list[dict]) -> dict | None:
    """Pick the one question whose answer settles the most eligibility checks (a greedy information gain).

    Each 'unknown' check is an uncertain outcome, so the missing attribute behind the most unknown checks
    removes the most uncertainty once answered. Returns {"attribute", "question", "programmes"} or None, where
    programmes is how many results the answer would settle.
    """
    from collections import Counter
    count = Counter()
    for x in items:
        for c in (x.get("gate") or {}).get("checks", []):
            if c["status"] == "unknown" and c.get("attribute") in FOLLOW_UP:
                count[c["attribute"]] += 1
    if not count:
        return None
    attr, n = count.most_common(1)[0]
    return {"attribute": attr, "question": FOLLOW_UP[attr], "programmes": n}
