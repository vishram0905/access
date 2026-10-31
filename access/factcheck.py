"""Claim-level verification (Layer 0): every claim a record shows must be confirmed on the official page.
See docs/DECISIONS.md, D22.

The three-judge panel in critics.py reads all of a record's claims in one long prompt. On 575 accepted records
it rejected true numbers (93% of "unconfirmed" deadlines and 91% of "unconfirmed" amounts were on the page) and
still caught only 21-27% of planted false ones. Model judges are weak at checking numbers and at judging many
claims at once, so here we check each claim in two steps.

First we locate it, deterministically and for free. The claim's own evidence (a deadline's day and month, an
amount's digits, a rule's quote) must be on the page, near a deadline or funding keyword as fits. If we cannot
find it, it is not confirmed whatever a model says; this is what catches shifted dates and inflated amounts.
Then we interpret it with a narrow model check. Three judges from three companies see only the located passage
for each claim and answer one question: is the claim stated in, or directly implied by, this passage? The
prompt lists the known traps, and the majority decides.

A recurring deadline with no year on the page ("Closes on 1 April") is rolled forward to its next occurrence,
rather than keeping a year the annotator guessed. A record is "verified" only if the page matches the programme,
at least one eligibility rule is confirmed and every claim shown is confirmed. Unconfirmed claims are removed
from the record and shown as "not stated, see official page", never as fact.
"""
import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from dateutil import parser as dparser

from .critics import evidence_grounded
from .schema import OPPORTUNITY_TYPES
from .llm import LLMError, call_json, current_role, set_role

METHOD = "claimcheck-v1"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
DEADLINE_KW = re.compile(r"deadline|clos(e|es|ed|ing)|due\b|submi|apply by|applications? (period|window|open)|"
                         r"last date|no later than|until|before\b|cut-?off|intake|call", re.I)
FUNDING_KW = re.compile(r"stipend|allowance|salary|bursary|scholarship|fellowship|grant|award|funding|funded|"
                        r"per (month|annum|year|week)|monthly|annual|yearly|tuition|fees?\b|living|value|worth|"
                        r"\$|€|£|¥|₹|S\$|SGD|USD|EUR|GBP|CHF|AUD|CAD|JPY|INR|KRW|CNY|HKD", re.I)
WINDOW = 350  # characters we show either side of a located claim


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " "))


# ---------------- step 1: locate ----------------

def _day_months(*texts) -> set[tuple[int, int]]:
    """Collect the (day, month) pairs a claim names, from free text ("Closes on 1 April") and ISO dates."""
    out = set()
    for t in texts:
        if not t:
            continue
        t = str(t)
        for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", t):
            out.add((int(m.group(3)), int(m.group(2))))
        for m in re.finditer(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2}|\d{4})\b", t):  # 08.02.2026: d.m or m/d
            a1, a2 = int(m.group(1)), int(m.group(2))
            out |= {(a1, a2), (a2, a1)} & {(d, mo) for d in range(1, 32) for mo in range(1, 13)}
        mon = "|".join(m[:3] for m in MONTHS)
        for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({mon})[a-z]*", t, re.I):
            out.add((int(m.group(1)), MONTHS.index(next(x for x in MONTHS if x.startswith(m.group(2).lower()))) + 1))
        for m in re.finditer(rf"\b({mon})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", t, re.I):
            out.add((int(m.group(2)), MONTHS.index(next(x for x in MONTHS if x.startswith(m.group(1).lower()))) + 1))
    return {(d, m) for d, m in out if 1 <= d <= 31}


def _date_spans(day: int, month: int, text: str) -> list[int]:
    """Positions where the page writes this day and month, in any common format."""
    name = MONTHS[month - 1]
    mon = rf"(?:{name}|{name[:3]}\.?)"
    pats = [rf"\b0?{day}(?:st|nd|rd|th)?\s+(?:of\s+)?{mon}\b", rf"\b{mon}\s+0?{day}(?:st|nd|rd|th)?\b",
            rf"\b0?{day}[/.-]0?{month}[/.-](?:\d{{2}}|\d{{4}})\b", rf"\b0?{month}/0?{day}/(?:\d{{2}}|\d{{4}})\b",
            rf"\b\d{{4}}-0?{month}-0?{day}\b"]
    return sorted({m.start() for p in pats for m in re.finditer(p, text, re.I)})


def _month_year_spans(texts, text: str) -> list[int]:
    """Positions of a month and year on the page, for claims with no day ("Sep 2027", "December 2026")."""
    out = []
    mon = "|".join(m[:3] for m in MONTHS)
    for t in texts:
        for m in re.finditer(rf"\b({mon})[a-z]*\.?\s+(\d{{4}})\b", str(t or ""), re.I):
            name = next(x for x in MONTHS if x.startswith(m.group(1).lower()))
            out += [x.start() for x in re.finditer(rf"\b(?:{name}|{name[:3]}\.?)\s+{m.group(2)}\b", text, re.I)]
    return out


def _amount_spans(amount: float, text: str) -> list[int]:
    """Positions of the amount's digits in any common form ("5000", "5,000", "5 000", "5.000", "5k")."""
    if amount is None:
        return []
    a = float(amount)
    whole = int(round(a))
    forms = {str(whole), f"{whole:,}", f"{whole:,}".replace(",", " "), f"{whole:,}".replace(",", ".")}
    if a != whole:
        forms.add(f"{a:.2f}".rstrip("0").rstrip("."))
    if whole >= 1000 and whole % 1000 == 0:
        forms.add(f"{whole // 1000}k")
        forms.add(f"{whole // 1000}K")
    out = set()
    for f in forms:
        for m in re.finditer(rf"(?<![\d.,]){re.escape(f)}(?![\d]|[.,]\d)", text):
            out.add(m.start())
    return sorted(out)


def _quote_spans(quote: str, text: str) -> list[int]:
    """Where an evidence quote sits on the page. We match its first 6 words and ignore whitespace."""
    words = re.findall(r"\w+", quote or "")
    if len(words) < 3 or not evidence_grounded(quote, text):
        return []
    pat = r"\W+".join(map(re.escape, words[:6]))
    return [m.start() for m in re.finditer(pat, text, re.I)][:3] or [0]


BY_DATE = re.compile(r"\b(by|before|until|till|through)\b[^.\n]{0,25}$", re.I)  # "... by [Tuesday,] 1 Dec"


def _near(spans: list[int], text: str, kw: re.Pattern, reach: int = 200) -> list[int]:
    """Keep the spans that have a keyword of the right kind nearby; a bare date or number proves nothing."""
    return [s for s in spans if kw.search(text[max(0, s - reach): s + reach])
            or (kw is DEADLINE_KW and BY_DATE.search(text[max(0, s - 40): s]))]


def _window(text: str, spans: list[int], limit: int = 2) -> str:
    parts, last = [], -10**9
    for s in spans[:6]:
        if s - last < WINDOW:  # overlapping windows become one passage
            continue
        parts.append(text[max(0, s - WINDOW): s + WINDOW].strip())
        last = s
        if len(parts) == limit:
            break
    return "\n...\n".join(parts)


# ---------------- the claims of a record ----------------

def _next_occurrence(day: int, month: int, today: date | None = None) -> str | None:
    today = today or date.today()
    for y in (today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            return None
        if d >= today:
            return d.isoformat()
    return None


OPS = {"in": "is one of", "not_in": "is NOT one of", ">=": "at least", "<=": "at most", "==": "equals",
       "eq": "equals", "gte": "at least", "lte": "at most", "max": "at most", "min": "at least"}


def _human(v) -> str:
    """Turn category codes into plain words, e.g. earth_climate_sciences becomes "earth climate sciences"."""
    if isinstance(v, list):
        return "[" + ", ".join(_human(x) for x in v) + "]"
    return str(v).replace("_", " ")


def claims(listing: dict, text: str) -> list[dict]:
    """List the checkable claims of a record, each with the passage where we located it (empty if not found)."""
    text = _flat(text)
    out = []
    for r in (listing.get("rules") or []) + (listing.get("rules_dropped") or []):
        spans = _quote_spans(r.get("evidence", ""), text)
        out.append({"id": r["id"], "kind": "rule", "located": bool(spans), "passage": _window(text, spans),
                    "claim": f'eligibility rule: {_human(r["attribute"])} {OPS.get(r["operator"], r["operator"])} '
                             f'{_human(r["value"])} (read from: "{_flat(r.get("evidence", ""))[:300]}")'})
    p = listing.get("process") if isinstance(listing.get("process"), dict) else {}  # legacy rows hold free text here
    if p.get("deadline_text") or p.get("next_deadline"):
        dms = _day_months(p.get("deadline_text"), p.get("next_deadline"))
        spans = sorted({s for d, m in dms for s in _date_spans(d, m, text)} |
                       set(_month_year_spans([p.get("deadline_text")], text)))
        spans = _near(spans, text, DEADLINE_KW)
        out.append({"id": "deadline", "kind": "deadline", "located": bool(spans), "passage": _window(text, spans),
                    "claim": f'the application deadline is: {p.get("deadline_text") or p.get("next_deadline")}'})
    f = listing.get("funding") if isinstance(listing.get("funding"), dict) else {}
    if f.get("stipend_amount") is not None:
        spans = _near(_amount_spans(f["stipend_amount"], text), text, FUNDING_KW)
        per = {"month": " per month", "year": " per year", "total": " in total"}.get(f.get("stipend_period"), "")
        # Judges used to reject "pays X" when the page said "up to X", which removed 44 true amounts, usually on
        # one vote of three. Most awards state their amount as a maximum, so we count it; a range still does not.
        out.append({"id": "amount", "kind": "amount", "located": bool(spans), "passage": _window(text, spans),
                    "claim": f'the page gives the award amount as {f["stipend_amount"]:g} {f.get("currency") or ""}'
                             f'{per} (stated exactly, or as a maximum such as "up to"; a range on the page must not '
                             f'be reported as this single value)'})
    if f.get("fully_funded") is not None:
        spans = _quote_spans(f.get("evidence", ""), text) or \
            [m.start() for m in re.finditer(r"fully[- ]funded|full scholarship|tuition|covers?", text, re.I)][:2]
        out.append({"id": "fully_funded", "kind": "fully_funded", "located": bool(spans),
                    "passage": _window(text, spans),
                    "claim": "the award is FULLY funded (covers tuition/fees and living costs)" if f["fully_funded"]
                    else "the award is NOT fully funded (partial support only)"})
    if listing.get("host_resolved") and listing.get("host_evidence"):  # where the programme is held
        where = ("recipients may choose ANY country (no restriction on destination)" if listing.get("host_anywhere")
                 else ", ".join((listing.get("host_countries") or []) + (listing.get("host_regions") or [])))
        out.append({"id": "host", "kind": "host", "located": bool(_quote_spans(listing["host_evidence"], text)),
                    "passage": _window(text, _quote_spans(listing["host_evidence"], text)),
                    "claim": f"WHERE HELD: the funded study, research or work takes place in: {where} "
                             f"(the complete list of places, not where applicants come from)"})
    if listing.get("opportunity_type"):
        out.append({"id": "type", "kind": "type", "located": True, "passage": text[:900],
                    "claim": f'PROGRAMME TYPE: the best-fitting single category for this programme is '
                             f'"{listing["opportunity_type"]}"'})
    return out


# ---------------- step 2: interpret ----------------

SYSTEM = "You verify single claims against short passages from an official web page. Reply in JSON."
PROMPT = """Programme: {name}

Each claim below comes with the passage of the official page it was located in. For EACH claim decide: is it
stated in, or directly implied by, ITS passage? Be exact. Common errors to reject:
- an opening date, intake/start date, event date or results date given as the application deadline
- a deadline from a past cycle presented as the current one, when the passage shows a later cycle
- a range (e.g. 1,600 to 2,000) reported as one value; per-year reported as per-month or the reverse; wrong currency
- an eligibility rule that inverts, narrows or widens its quote (e.g. "in" vs "not in", PhD vs postdoc)
- a WHERE HELD list that names where applicants come FROM, or is narrower or wider than the passage
  (e.g. one example destination given as the only one)
Rules and programme types use a FIXED list of broad categories. Judge whether the page's wording falls within
the named category (e.g. "sedimentary geology" is within "earth climate sciences"; "students" with no level
stated covers undergraduate, masters and PhD students), not whether the category words appear on the page.
A claim is supported if the passage says it, even in other words. Do not use outside knowledge.

{claims}

A PROGRAMME-TYPE claim is about classification, not exact wording: it is supported if the named category is the
BEST single fit from this fixed list: {types}. A programme spanning several levels (e.g. research master's and PhD)
takes the category of its main or highest level. If another category fits better, mark it unsupported and give that
category as "correct_type" (null if none fits).

JSON: {{"claims": [{{"id": "C1", "supported": true/false, "reason": "short", "correct_type": null}}, ...one per
claim, in order, with the id exactly as given]}}"""


def _ask(spec, listing: dict, items: list[dict], role: str) -> dict:
    """Ask one judge about all located claims of a record and collect its votes and type corrections."""
    set_role(role)
    body = "\n\n".join(f'[C{i + 1}] CLAIM: {c["claim"]}\nPASSAGE:\n<<<\n{c["passage"][:1600]}\n>>>'
                         for i, c in enumerate(items))
    try:
        v = call_json(spec, SYSTEM, PROMPT.format(name=listing.get("name", ""), claims=body,
                                                  types=", ".join(OPPORTUNITY_TYPES)))
    except LLMError as e:
        return {"judge": spec.label, "family": spec.family, "error": str(e)[:200]}
    answers = [x for x in v.get("claims", []) if isinstance(x, dict)]
    votes, corrections = {}, {}
    for k, x in enumerate(answers):  # match on the echoed number, else position
        n = re.search(r"(\d+)", str(x.get("id", "")))
        i = int(n.group(1)) - 1 if n and 0 < int(n.group(1)) <= len(items) else k
        if 0 <= i < len(items):
            votes[items[i]["id"]] = bool(x.get("supported"))
            if items[i]["kind"] == "type" and not x.get("supported") and x.get("correct_type") in OPPORTUNITY_TYPES:
                corrections[items[i]["id"]] = x["correct_type"]
    return {"judge": spec.label, "family": spec.family, "votes": votes, "corrections": corrections}


def check(listing: dict, text: str, judges: list) -> dict:
    """Run both steps for one record.

    Returns the per-claim results (located, yes votes, confirmed) together with the raw verdicts. If any claim was
    located and fewer than three companies answered, we raise an LLMError: a partial panel weakens the majority.
    """
    cs = claims(listing, text)
    located = [c for c in cs if c["located"]]
    role = current_role()
    verdicts = []
    if located:
        with ThreadPoolExecutor(len(judges)) as ex:
            verdicts = list(ex.map(lambda j: _ask(j, listing, located, role), judges))
    valid = [v for v in verdicts if "error" not in v]
    if located and len({v["family"] for v in valid}) < 3:
        err = LLMError("daily budget: claim check needs the full panel: " +
                       "; ".join(f'{v["judge"]}: {v["error"][:60]}' for v in verdicts if "error" in v))
        err.failed = {v["judge"]: v["error"] for v in verdicts if "error" in v}  # the critic rests these judges
        raise err
    result = {}
    for c in cs:
        votes = [v["votes"][c["id"]] for v in valid if c["id"] in v["votes"]]
        result[c["id"]] = {"kind": c["kind"], "located": c["located"], "yes": sum(votes), "of": len(votes),
                           "confirmed": c["located"] and len(votes) >= 2 and sum(votes) >= len(votes) // 2 + 1}
        if c["kind"] == "type" and not result[c["id"]]["confirmed"]:
            # A type the majority rejects can be corrected, by the same standard: a majority of the panel must
            # name the same category from the fixed list.
            fixes = [v.get("corrections", {}).get(c["id"]) for v in valid]
            best = max(set(f for f in fixes if f), key=fixes.count, default=None)
            if best and fixes.count(best) >= len(valid) // 2 + 1 and len(valid) >= 2:
                result[c["id"]]["corrected_to"] = best
    return {"claims": result, "verdicts": verdicts, "judges": [f"{j.label} ({j.family})" for j in judges]}


# ---------------- step 3: apply ----------------

def apply(listing: dict, outcome: dict) -> dict:
    """Keep the confirmed claims, remove the rest, roll recurring deadlines forward and set the verification status.

    Works on a copy, so the input listing is left unchanged.
    """
    m = copy.deepcopy(listing)
    res = outcome["claims"]
    rules = (m.get("rules") or []) + (m.get("rules_dropped") or [])
    m["rules"] = [r for r in rules if res.get(r["id"], {}).get("confirmed")]
    m["rules_dropped"] = [r for r in rules if not res.get(r["id"], {}).get("confirmed")]
    p, f = m.setdefault("process", {}) or {}, m.setdefault("funding", {}) or {}
    unconfirmed = []
    if "deadline" in res:
        if res["deadline"]["confirmed"]:
            dms = _day_months(p.get("deadline_text"))
            has_year = re.search(r"\b20\d{2}\b", p.get("deadline_text") or "")
            if len(dms) == 1 and not has_year:  # no year on the page: use the next occurrence
                p["next_deadline"] = _next_occurrence(*next(iter(dms)))
                p["deadline_recurring"] = True
        else:
            unconfirmed.append(f'deadline: {p.get("deadline_text") or p.get("next_deadline")}')
            p.update(next_deadline=None, deadline_text=None)
            m["deadline"] = None
    if "amount" in res and not res["amount"]["confirmed"]:
        unconfirmed.append(f'amount: {f.get("stipend_amount")} {f.get("currency") or ""}/{f.get("stipend_period") or ""}')
        f.update(stipend_amount=None, currency=None, stipend_period=None)
    if "fully_funded" in res and not res["fully_funded"]["confirmed"]:
        unconfirmed.append(f'fully_funded: {f.get("fully_funded")}')
        f["fully_funded"] = None
    type_ok = "type" not in res or res["type"]["confirmed"] or bool(res["type"].get("corrected_to"))
    if "type" in res and res["type"].get("corrected_to"):
        m["type_corrected_from"] = m.get("opportunity_type")
        m["opportunity_type"] = res["type"]["corrected_to"]
    elif not type_ok:
        unconfirmed.append(f'type: {m.get("opportunity_type")}')
    if "host" in res and not res["host"]["confirmed"]:
        # We fail safe here. An unconfirmed place falls back to "Not stated", which every country search still
        # shows, so an extraction error cannot hide a programme from anyone.
        unconfirmed.append(f'host: {m.get("host_country")}')
        m.update(host_countries=[], host_regions=[], host_anywhere=False, host_resolved=False,
                 host_evidence=None, host_country="Not stated")
    m["facts_unconfirmed"] = unconfirmed
    review = m.get("review") or {}
    ok_page = review.get("decision") in ("accepted", "accepted_with_warning")
    problems = []
    if not ok_page:
        problems.append("page or funding not confirmed by the panel")
    if not m["rules"]:
        problems.append("no confirmed eligibility rule")
    if m["rules_dropped"]:
        problems.append(f"{len(m['rules_dropped'])} eligibility rule(s) quoted from the page but not confirmed")
    if not type_ok:
        problems.append("programme type not confirmed")
    m["verification"] = {"method": METHOD, "status": "verified" if not problems else "incomplete",
                         "problems": problems, "removed": unconfirmed, "claims": res,
                         "judges": outcome["judges"]}
    return m
