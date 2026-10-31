"""Auditor agent (Layer 0): measures how far the library can be trusted, without being one of the judges and
without human labels.

It does three things. In blind re-extraction, a model from a different company than the Annotator (Qwen first)
re-reads a sample of verified pages from scratch, seeing only the page: never the annotation, the judges' votes
or any earlier call. Field-by-field agreement with the stored row is our measured accuracy. Qwen is also a judge,
so we use leave-one-out trust with the auditor's own votes removed, and it never grades itself. In planted-error
tests, code corrupts verified rows (fake rule, shifted deadline, inflated stipend, wrong page, flipped
nationality) and sends them back through the gate; the catch rate tells us how reliable the checking is.
Calibration then sets the trust bands where measured accuracy reaches 90% (high) and 70% (medium).

Results go to the audits and mutation_tests tables and to data/lookup/calibration.json.
"""
import copy
import json
import random
import re
import time
from datetime import date, timedelta

from .config import ROLES, check_role_diversity
from .critics import review_listing
from .db import connect, now
from .gate import fields_match
from .llm import LLMError
from .normalizer import normalize
from .scoring import CALIBRATION_FILE, PROVISIONAL_BANDS, band_of, bands, kpis, trust

BLIND_SYSTEM = ("You are an independent auditor reading this funding programme page for the first time. "
                "Nobody has summarised it for you. Record only what the page itself states; use null when it "
                "does not say. Reply with one JSON object.")

MIN_AUDITS_FOR_CALIBRATION = 30
HIGH_TARGET, MEDIUM_TARGET = 0.90, 0.70

SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (program_id TEXT PRIMARY KEY, trust REAL, agreement REAL,
    details TEXT, auditor TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS mutation_tests (id INTEGER PRIMARY KEY AUTOINCREMENT, program_id TEXT,
    mutation TEXT, detected INTEGER, detail TEXT, at TEXT);
"""


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} [auditor] {msg}", flush=True)


# ---------------------------------------------------------------- 1. blind re-extraction

def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _jaccard(a, b):
    a, b = set(a or []), set(b or [])
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _rule_key(r):
    v = r["value"]
    v = tuple(sorted(_norm(x) for x in v)) if isinstance(v, list) else _norm(v)
    return (r["attribute"], r["operator"], v)


def compare(stored: dict, fresh: dict) -> dict:
    """Compare the verified row with an independent re-extraction, field by field.

    We are lenient where exact equality would be unfair: career levels and rules count as agreeing at a Jaccard
    overlap of 0.5, and stipends within 10% of each other.
    """
    sf, ff = stored.get("funding") or {}, fresh.get("funding") or {}
    sp, fp = stored.get("process") or {}, fresh.get("process") or {}
    amt_s, amt_f = sf.get("stipend_amount"), ff.get("stipend_amount")
    checks = {
        "opportunity_type": stored.get("opportunity_type") == fresh.get("opportunity_type"),
        "provider_type": stored.get("provider_type") == fresh.get("provider_type"),
        "host_country": _norm(stored.get("host_country")) == _norm(fresh.get("host_country")),
        "career_levels": _jaccard(stored.get("career_levels"), fresh.get("career_levels")) >= 0.5,
        "fields": fields_match(stored.get("fields", ["any"]), fresh.get("fields", ["any"])),
        "deadline": sp.get("next_deadline") == fp.get("next_deadline"),
        "stipend": (amt_s is None and amt_f is None) or (
            amt_s is not None and amt_f is not None and abs(amt_s - amt_f) <= 0.1 * max(amt_s, amt_f)),
        "rules": _jaccard({_rule_key(r) for r in stored.get("rules", [])},
                          {_rule_key(r) for r in fresh.get("rules", [])}) >= 0.5,
    }
    return {"agreement": round(sum(checks.values()) / len(checks), 3), "fields": checks}


def auditor_candidates(judged_by: set) -> list:
    """Models allowed to re-check a record: never the annotator's company and never a judge of this record.

    The preferred auditor (Qwen) comes first and then the rest of the judge pool, so one model's daily quota
    cannot stall calibration. Local models are left out.
    """
    annotator = ROLES["normalizer"][0].family
    pool = ROLES["auditor"] + [m for m in ROLES["judge_pool"] if m not in ROLES["auditor"]]
    return [m for m in pool if m.family != annotator and m.label not in judged_by and m.provider != "ollama"]


def audit_one(con_row) -> dict | None:
    """Blind re-read of one stored record; saves the agreement and leave-one-out trust to the audits table."""
    stored = json.loads(con_row["data"])
    from .templates import extract_sections
    text, _ = extract_sections(con_row["text"], stored["url"], keep_intro=4000)
    raw = {"id": stored["id"], "name": stored["name"], "url": stored["url"], "text": text[:8000],
           "official_source": stored.get("official_source"), "fetched_at": stored.get("fetched_at")}
    judged_by = {v.get("judge") for v in (stored.get("review") or {}).get("verdicts", [])}
    fresh, auditor = None, None
    for spec in auditor_candidates(judged_by):  # first model with quota that did not judge this record
        try:
            fresh = normalize(raw, spec=spec, system=BLIND_SYSTEM)  # page only, blind to annotation and votes
            auditor = spec
            break
        except LLMError:
            continue
    if fresh is None:
        raise LLMError("no eligible re-checking model has quota right now")
    res = compare(stored, fresh)
    loo = trust(kpis(stored, con_row["text"], exclude_judge=auditor.label))  # auditor's own votes removed
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO audits VALUES (?,?,?,?,?,?)",
                    (stored["id"], loo, res["agreement"], json.dumps(res["fields"]),
                     f"{auditor.label} (blind)", now()))
    return {"name": stored["name"], "trust": loo, **res}


# ---------------------------------------------------------------- 2. planted errors

def _shift_date(d: str | None) -> str:
    base = date.fromisoformat(d) if d else date.today()
    return (base + timedelta(days=random.choice([-120, 95, 150]))).isoformat()


MUTATIONS = ["fake_rule", "shifted_deadline", "inflated_funding", "wrong_page", "flipped_nationality"]


def plant(listing: dict, kind: str, other_text: str) -> tuple[dict, str, str] | None:
    """Plant one error of the given kind in a copy of the listing.

    Returns (corrupted listing, page text to judge against, id of the planted item), where the page text is None
    unless we swapped in another page. Returns None when the listing has nothing to corrupt for this kind.
    """
    m = copy.deepcopy(listing)
    for k in ("review", "kpis", "trust", "band", "facts_unconfirmed", "confidence", "rules_dropped", "verification"):
        m.pop(k, None)
    m["rules"] = [dict(r, **{"votes_supported": 0, "votes_total": 0}) for r in m.get("rules", [])]
    if kind == "fake_rule":
        rid = f"r{len(m['rules']) + 1}"
        m["rules"].append({"id": rid, "attribute": "nationality", "operator": "in", "value": ["Andorra"],
                           "hard": True, "evidence": "Only citizens of Andorra are eligible to apply."})
        return m, None, rid
    if kind == "flipped_nationality":
        for r in m["rules"]:
            if r["attribute"] in ("nationality", "residency"):
                r["operator"] = "not_in" if r["operator"] == "in" else "in"
                return m, None, r["id"]
        return None
    if kind == "shifted_deadline":
        p = m.get("process") or {}
        if not (p.get("next_deadline") or p.get("deadline_text")):
            return None
        new = _shift_date(p.get("next_deadline"))
        p.update(next_deadline=new, deadline_text=new)
        return m, None, "f1"
    if kind == "inflated_funding":
        f = m.get("funding") or {}
        if f.get("stipend_amount") is None:
            return None
        f["stipend_amount"] = round(f["stipend_amount"] * 4)
        return m, None, "f2"
    if kind == "wrong_page":
        return m, other_text, "page"
    return None


def _survives(final: dict, planted: dict, item: str) -> bool:
    """True if the planted error is still shown in the final record."""
    if item.startswith("r"):
        want = next(r for r in planted["rules"] if r["id"] == item)
        return any(r["id"] == item and r.get("operator") == want.get("operator") for r in final.get("rules", []))
    if item == "f1":
        p, q = final.get("process") or {}, planted.get("process") or {}
        return bool(p.get("next_deadline")) and p.get("next_deadline") == q.get("next_deadline")
    if item == "f2":
        return (final.get("funding") or {}).get("stipend_amount") == (planted.get("funding") or {}).get("stipend_amount")
    return True  # for a wrong page, the record itself is the error


def mutation_test(rows) -> dict | None:
    """Plant one known error in a verified record and run it through the whole gate as deployed.

    That means the panel review and then the claim check (see docs/DECISIONS.md, D22), with a full
    three-company panel from the judge pool. We count the error as caught if users would not see it: the panel
    rejects the page, the claim check removes the claim, or the record is withheld as incomplete.
    """
    from . import factcheck, resources
    a, b = random.sample(rows, 2)
    listing = json.loads(a["data"])
    kind = random.choice(MUTATIONS)
    planted = plant(listing, kind, b["text"])
    if not planted:
        return None
    m, text, item = planted
    panel, _ = resources.pick_panel(ROLES["judge_pool"], "auditor", 3)
    if len({j.family for j in panel}) < 3:
        raise LLMError("daily budget: mutation test needs a full three-company panel")
    page = text or a["text"]
    snapshot = copy.deepcopy(m)  # review_listing edits in place, so keep the planted values
    judged = review_listing(m, page, judges=panel)
    if judged["review"]["decision"] == "rejected" or (item != "page" and not _survives(judged, snapshot, item)):
        detected, by = True, "panel"
    else:
        final = factcheck.apply(judged, factcheck.check(judged, page, panel))
        # We credit the claim check only when it removed the planted claim itself. A record withheld for another
        # reason (say, a genuine rule this panel did not confirm) hides the error too, but we count it separately.
        if item != "page" and not _survives(final, snapshot, item):
            detected, by = True, "claimcheck"
        elif final["verification"]["status"] != "verified":
            detected, by = True, "withheld"
        else:
            detected, by = False, "missed"
    with connect() as con:
        con.execute("INSERT INTO mutation_tests (program_id, mutation, detected, detail, at) VALUES (?,?,?,?,?)",
                    (listing["id"], kind, int(detected), f"{factcheck.METHOD}:{by}", now()))
    return {"mutation": kind, "detected": detected, "name": listing["name"], "by": by}


# ---------------------------------------------------------------- 3. calibration

def calibrate() -> dict:
    """Set the trust band cut-offs from the audits and write them, with the catch rates, to calibration.json.

    The high cut-off is the lowest trust from which audited accuracy reaches 90%, and medium the lowest reaching
    70%, searched in steps of 0.05. Until MIN_AUDITS_FOR_CALIBRATION rows are audited we keep provisional bands.
    """
    with connect() as con:
        rows = [(r["trust"], r["agreement"]) for r in con.execute(
            "SELECT trust, agreement FROM audits WHERE trust IS NOT NULL")]
        # We only count tests of the gate as deployed, with the D22 claim check. Rows without the claimcheck tag
        # tested the panel review alone.
        muts = con.execute("SELECT mutation, AVG(detected), COUNT(*) FROM mutation_tests WHERE detail LIKE ? "
                           "GROUP BY mutation", ("claimcheck-%",)).fetchall()
    catch = {m: {"caught": round(r, 2), "tests": n} for m, r, n in muts}
    if len(rows) < MIN_AUDITS_FOR_CALIBRATION:
        out = {**PROVISIONAL_BANDS, "audited": len(rows), "catch_rate": catch,
               "note": f"provisional until {MIN_AUDITS_FOR_CALIBRATION} rows are audited"}
    else:
        def acc_above(t):
            sel = [a for tr, a in rows if tr >= t]
            return sum(sel) / len(sel) if len(sel) >= 5 else 0

        grid = [x / 100 for x in range(30, 96, 5)]
        high = next((t for t in grid if acc_above(t) >= HIGH_TARGET), 0.95)
        medium = next((t for t in grid if acc_above(t) >= MEDIUM_TARGET), min(high, 0.5))
        medium = min(medium, high)
        bins = {}
        for lo in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9):
            sel = [a for tr, a in rows if lo <= tr < lo + (0.5 if lo == 0 else 0.1)]
            if sel:
                bins[f"{lo:.1f}+"] = {"rows": len(sel), "agreement": round(sum(sel) / len(sel), 2)}
        out = {"high": high, "medium": medium, "provisional": False, "audited": len(rows),
               "accuracy_high": round(acc_above(high), 2), "accuracy_medium_and_up": round(acc_above(medium), 2),
               "by_trust_bin": bins, "catch_rate": catch}
    out["calibrated_at"] = now()
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_FILE.write_text(json.dumps(out, indent=1))
    return out


# ---------------------------------------------------------------- agent loop

def run(stop=None, audits_per_cycle: int = 3, mutations_per_cycle: int = 2, pause: int = 240):
    """Agent loop: each cycle audits a few unaudited records, runs a few planted-error tests and recalibrates."""
    problems = check_role_diversity()
    if problems:
        raise SystemExit("; ".join(problems))
    with connect() as con:
        con.executescript(SCHEMA)
    a = ROLES["auditor"][0]
    log(f"auditor: {a.label} ({a.family}) reading pages blind; calibration excludes its own judge votes")
    while not (stop and stop.is_set()):
        with connect() as con:
            todo = con.execute(
                "SELECT l.id, l.data, s.text FROM listings l JOIN sources s ON s.url = l.source_url "
                "WHERE l.decision != 'rejected' AND l.data LIKE '%\"trust\":%' "
                "AND l.id NOT IN (SELECT program_id FROM audits) ORDER BY RANDOM() LIMIT ?",
                (audits_per_cycle,)).fetchall()
            pool = con.execute(
                "SELECT l.id, l.data, s.text FROM listings l JOIN sources s ON s.url = l.source_url "
                "WHERE l.decision != 'rejected' AND json_extract(l.data, '$.verification.status') = 'verified' "
                "ORDER BY RANDOM() LIMIT 40").fetchall()
        for row in todo:
            try:
                r = audit_one(row)
                log(f"blind re-read agreement {r['agreement']:.2f}  trust {r['trust']}  "
                    f"[{band_of(r['trust'])}]  {r['name'][:50]}")
            except LLMError as e:
                log(f"! re-extraction paused: {str(e)[:160]}")
                if "429" in str(e) or "daily budget" in str(e):
                    break
        for _ in range(mutations_per_cycle if len(pool) >= 2 else 0):
            try:
                r = mutation_test(pool)
                if r:
                    log(f"planted {r['mutation']:<20} {'CAUGHT by ' + r['by'] if r['detected'] else 'missed'}  {r['name'][:45]}")
            except LLMError as e:
                log(f"! mutation test failed: {str(e)[:120]}")
        c = calibrate()
        log(f"calibration: high ≥ {c['high']}, medium ≥ {c['medium']} "
            f"({'provisional' if c.get('provisional') else 'measured'}; {c['audited']} rows audited)")
        time.sleep(pause)
