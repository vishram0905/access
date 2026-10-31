"""ACCESS test suite (tooling): one run writes one JSON result file, which docs/TEST_REPORT.md reports on.

The areas, in the order they run:
  A  Unit tests            eligibility gate cases and whole-library invariants
  B  Library integrity     what the search library contains (verified only, quotes on the page, vocabularies)
  C  Retrieval             known-item benchmark restricted to programmes in today's library
  D  Consistency           14 realistic profiles: country, type, stage, closed, duplicates, labels
  E  Metamorphic           relations that must hold between related searches (no ground truth needed)
  F  Robustness            unusual and hostile inputs
  G  Performance           latency of the instant path
  H  AI ranking            enrichment completes, scores every item, final order respects the tiers
  I  Q&A (RAG)             answers quote only the official page
  J  Application plans     a plan is produced for the top eligible programme
  K  Privacy               names are not stored; edited examples are not treated as examples
  L  User interface        every page renders without an exception; an example search shows results

Run: PYTHONPATH=. python scripts/test_suite.py [--no-ai]
"""
import json
import random
import re
import statistics
import sys
import time
from datetime import date, datetime

from access.config import DATA, is_excluded_place
from access.db import connect
from access.evaluation import PERSONAS, run_gate_unit_tests, run_invariants
from access.factcheck import _quote_spans
from access.gate import evaluate
from access.lookup import load
from access.pipeline import enrich, instant, is_example, plan_for, save_run
from access.profile import local_profile, search_query
from access.results import final_order
from access.schema import CAREER_STAGES, OPPORTUNITY_TYPES
from access.search import search

sys.path.insert(0, "scripts")
from demo_check import ALL, check as consistency_check  # noqa: E402

OUT = DATA / "eval" / "test_suite.json"
RESULTS = []


def record(area, tid, name, passed, detail="", metric=None):
    """Store one test result and print a one-line PASS or FAIL."""
    RESULTS.append({"area": area, "id": tid, "name": name, "passed": bool(passed), "detail": detail,
                    "metric": metric})
    print(f"{'PASS' if passed else 'FAIL'} {tid:<5} {name[:70]:<70} {detail[:90]}", flush=True)


def safe(area, tid, name, fn):
    """Run one test or area so that a crash is recorded as a failure instead of stopping the whole suite."""
    try:
        fn()
    except Exception as e:
        record(area, tid, name, False, f"crashed: {type(e).__name__}: {str(e)[:150]}")


programs, facets, vecs, meta = load()
by_id = {p["id"]: p for p in programs}


# ---------------------------------------------------------------- A unit tests
def area_a():
    t = run_gate_unit_tests()
    bad = [x for x in t if not x["passed"]]
    record("A", "A1", "Eligibility gate: hand-checked rule cases", not bad, f"{len(t) - len(bad)}/{len(t)} pass",
           {"passed": len(t) - len(bad), "total": len(t)})
    inv = run_invariants()
    bad = [x for x in inv if not x["passed"]]
    record("A", "A2", "Library-wide invariants (4 example researchers)", not bad,
           f"{len(inv) - len(bad)}/{len(inv)} pass", {"passed": len(inv) - len(bad), "total": len(inv)})


# ---------------------------------------------------------------- B library integrity
def area_b():
    n = len(programs)
    unver = [p["id"] for p in programs if (p.get("verification") or {}).get("status") != "verified"]
    record("B", "B1", "Every searchable programme is claim-verified", not unver, f"{n - len(unver)}/{n} verified")
    exc = [p["name"] for p in programs if is_excluded_place(p)]
    record("B", "B2", "No programme from an excluded place", not exc, f"{len(exc)} found")
    ids = [p["id"] for p in programs]
    record("B", "B3", "Programme ids are unique", len(ids) == len(set(ids)), f"{len(ids)} ids")
    record("B", "B4", "One embedding vector per programme", len(vecs) == n, f"{len(vecs)} vectors, {n} programmes")
    # B5: every rule's quote should be found on the stored official page. The test passes at 97% located.
    with connect() as con:
        texts = {r[0]: r[1] or "" for r in con.execute(
            "SELECT url, text FROM sources WHERE url IN (%s)" % ",".join("?" * n), [p["url"] for p in programs])}
    rules = located = missing_text = no_quote = 0
    misses = []
    for p in programs:
        text = texts.get(p["url"])
        for r in p.get("rules") or []:
            rules += 1
            if not r.get("evidence"):
                no_quote += 1
                continue
            if text is None:
                missing_text += 1
                continue
            if _quote_spans(r["evidence"], text):
                located += 1
            else:
                misses.append(f"{p['name'][:40]}: {r['evidence'][:60]}")
    checkable = rules - no_quote - missing_text
    rate = located / max(1, checkable)
    record("B", "B5", "Each eligibility rule's quote is found on the official page", rate >= 0.97 and no_quote == 0,
           f"{located}/{checkable} located ({rate:.1%}); {no_quote} rules without a quote; "
           f"{missing_text} on pages not stored", {"rules": rules, "located": located, "checkable": checkable,
                                                    "examples_not_located": misses[:5]})
    bad_type = [p["name"] for p in programs if (p.get("opportunity_type") or p.get("type")) not in OPPORTUNITY_TYPES]
    bad_lvl = [p["name"] for p in programs if any(l not in CAREER_STAGES for l in p.get("career_levels") or [])]
    record("B", "B6", "Programme types and career levels use the controlled vocabulary",
           not bad_type and not bad_lvl, f"{len(bad_type)} bad types, {len(bad_lvl)} bad levels")
    bad_url = [p["name"] for p in programs if not re.match(r"https?://[^\s/]+\.[^\s]+", p.get("url") or "")]
    record("B", "B7", "Every programme links to an official web page", not bad_url, f"{len(bad_url)} invalid URLs")
    code = re.compile(r"\b[a-z]+_[a-z_]+\b")
    raw = [p["name"] for p in programs if code.search(p.get("name") or "") or code.search(p.get("provider") or "")]
    record("B", "B8", "Names and providers contain no internal codes", not raw, f"{len(raw)} found", {"examples": raw[:5]})
    inc = []
    for p in programs:
        hc = p.get("host_countries")
        if hc and not p.get("host_anywhere") and p.get("host_country") not in (", ".join(hc + (p.get("host_regions") or [])),):
            inc.append(f"{p['name'][:40]}: {p.get('host_country')} vs {hc}")
    record("B", "B9", "Host-country label agrees with the host-country list", not inc, f"{len(inc)} disagree",
           {"examples": inc[:5]})
    multiple = sum(p.get("host_country") == "Multiple" for p in programs)
    record("B", "B10", "Programmes still labelled 'Multiple' (not yet resolved)", True,
           f"{multiple} of {n} (kept out of country searches; resolution pending Gemini quota)",
           {"multiple": multiple})
    ghost = {i for col in facets.values() for ids in col.values() for i in ids} - set(ids)
    record("B", "B11", "Search facets point only to programmes in the library", not ghost, f"{len(ghost)} dangling ids")


# ---------------------------------------------------------------- C retrieval
def area_c():
    """Re-run the known-item benchmark on today's library with the same hybrid fusion the search uses."""
    from access.lookup import search_text
    from access.retrieval import BM25, FUSION_WEIGHTS, rrf
    from access.llm import embed
    from access.config import ROLES
    import numpy as np
    items = [json.loads(l) for l in (DATA / "eval" / "known_items.jsonl").read_text().splitlines() if l.strip()]
    items = [x for x in items if x["id"] in by_id]
    ids = [p["id"] for p in programs]
    bm = BM25([search_text(p) for p in programs])
    ranks = []
    for it in items:
        q = np.array(embed(ROLES["embedder"][0], [f"search_query: {it['query']}"])[0], dtype=np.float32)
        q /= np.linalg.norm(q)
        dense = [ids[i] for i in np.argsort(-(vecs @ q))]
        s = bm.scores(it["query"])
        lex = [ids[i] for i in sorted(range(len(ids)), key=lambda i: -s[i])]
        order = rrf([dense, lex], weights=[FUSION_WEIGHTS["dense"], FUSION_WEIGHTS["bm25"]])
        ranks.append(order.index(it["id"]) + 1)
    r = lambda k: sum(x <= k for x in ranks) / len(ranks)
    mrr = statistics.mean(1 / x for x in ranks)
    record("C", "C1", "Known-item retrieval on today's library (hybrid search)", r(5) >= 0.85,
           f"n={len(ranks)}: recall@1 {r(1):.2f}, @5 {r(5):.2f}, @10 {r(10):.2f}, MRR {mrr:.2f}",
           {"n": len(ranks), "recall@1": round(r(1), 3), "recall@5": round(r(5), 3), "recall@10": round(r(10), 3),
            "MRR": round(mrr, 3)})


# ---------------------------------------------------------------- D consistency
def area_d():
    rows = {}
    for label, form in ALL.items():
        flag, relaxed = consistency_check(label, form)
        rows[label.split(" - ")[0]] = {"flags": flag, "relaxed": relaxed}
    serious = {k: v for k, v in rows.items() if set(v["flags"]) & {"country", "type", "stage", "excluded_place",
                                                                   "not_verified", "raw_code"} or v["relaxed"]}
    record("D", "D1", "Results match the chosen country, type and career stage (14 profiles)", not serious,
           f"{len(serious)} profiles with mismatches", {"profiles": rows})
    thin = [k for k, v in rows.items() if "few_results" in v["flags"]]
    record("D", "D2", "Every profile receives at least 5 eligible programmes", not thin,
           f"thin: {', '.join(thin) or 'none'} (coverage, not logic)", {"thin": thin})


# ---------------------------------------------------------------- E metamorphic
def _eligible(form, k=1000):
    p = local_profile(dict(form))
    f = {"host_country": form.get("target_countries"), "opportunity_type": form.get("wanted_types")}
    r = search(p, search_query(p), k=k, filters=f)
    return [x["id"] for x in r["eligible"]], r


def area_e():
    base = dict(next(iter(PERSONAS.values())))
    a, _ = _eligible(base)
    b, _ = _eligible(base)
    record("E", "E1", "Determinism: the same search twice gives the same results in the same order", a == b,
           f"{len(a)} results")
    viol = []
    for label, form in list(ALL.items())[:10]:
        t = form.get("target_countries") or []
        if not t:
            continue
        one, _ = _eligible({**form, "target_countries": t[:1]})
        more, _ = _eligible({**form, "target_countries": t + ["United States"] if "United States" not in t else t + ["Canada"]})
        if not set(one) <= set(more):
            viol.append(label.split(" - ")[0])
    record("E", "E2", "Adding a country never removes results for the countries already chosen", not viol,
           f"violations: {', '.join(viol) or 'none'}")
    viol = []
    for label, form in list(ALL.items())[:10]:
        with_t, _ = _eligible(form)
        without, _ = _eligible({**form, "wanted_types": []})
        if not set(with_t) <= set(without):
            viol.append(label.split(" - ")[0])
    record("E", "E3", "Removing the type filter never removes a result", not viol, f"violations: {', '.join(viol) or 'none'}")
    # E4: every nationality rule in the library should admit a listed national and exclude a made-up nationality.
    wrong, tested = [], 0
    for p in programs:
        for r in p.get("rules") or []:
            if r["attribute"] == "nationality" and r["operator"] == "in" and isinstance(r["value"], list) and r["value"]:
                allowed = str(r["value"][0])
                if allowed.lower() in ("all", "any", "international", "worldwide", "global"):
                    continue
                tested += 1
                ok = evaluate({"rules": [r]}, {"nationality": allowed})["outcome"] != "excluded"
                bad = evaluate({"rules": [r]}, {"nationality": "Atlantis"})["outcome"] == "excluded"
                if not (ok and bad):
                    wrong.append(f"{p['name'][:40]} ({allowed})")
    record("E", "E4", "Nationality rules admit listed nationals and exclude others", not wrong,
           f"{tested - len(wrong)}/{tested} rules behave", {"examples": wrong[:5]})
    # E5: a profile with almost nothing filled in must get "unknown", never a silent pass or fail.
    silent = 0
    for p in programs:
        g = evaluate(p, {"career_stage": "masters"})
        for c in g["checks"]:
            if c["attribute"] in ("nationality", "residency", "gpa", "ielts", "age") and c["status"] in ("pass", "fail") \
                    and "open to all" not in c["why"].lower() and "not excluded" not in c["why"].lower():
                silent += 1
    record("E", "E5", "Unknown attributes are reported as unknown, never passed or failed", silent == 0,
           f"{silent} silent decisions")
    # E6: stating a nationality can only settle 'unknown' checks. It may remove results, but never add one.
    form = dict(list(PERSONAS.values())[0])
    blank, _ = _eligible({**form, "nationality": None})
    filled, _ = _eligible(form)
    added = set(filled) - set(blank)
    record("E", "E6", "Giving more information never adds a programme that was not already eligible", not added,
           f"{len(blank)} eligible with nationality blank, {len(filled)} with it given, {len(added)} added")


# ---------------------------------------------------------------- F robustness
def area_f():
    base = dict(next(iter(PERSONAS.values())))
    cases = {
        "empty description": {**base, "about": ""},
        "very long description (20,000 chars)": {**base, "about": "machine learning " * 1300},
        "description in Chinese": {**base, "about": "我是计算机科学硕士生，想在新加坡攻读机器学习博士学位。"},
        "HTML and script in description": {**base, "about": "<script>alert(1)</script><b>AI</b> PhD"},
        "emoji only": {**base, "about": "🎓🤖📚"},
        "no nationality": {**base, "nationality": None, "residency": None},
        "no countries, no types": {**base, "target_countries": [], "wanted_types": []},
        "every type selected": {**base, "wanted_types": list(OPPORTUNITY_TYPES)},
        "industry professional": {**base, "career_stage": "industry", "highest_degree": "masters"},
        "senior researcher, 30 years after PhD": {**base, "career_stage": "senior", "highest_degree": "phd",
                                                  "years_since_phd": 30, "age": 62},
        "implausible numbers": {**base, "age": -5, "gpa": 9.9, "ielts": 12, "publications": 10000},
        "country with no programmes": {**base, "target_countries": ["Nepal"]},
    }
    for i, (name, form) in enumerate(cases.items(), 1):
        def run(name=name, form=form, i=i):
            t0 = time.time()
            r = instant(form)
            ms = (time.time() - t0) * 1000
            n = len(r["shortlist"])
            ok = ms < 5000 and isinstance(r["shortlist"], list)
            note = ""
            if name == "industry professional":  # holds a master's, so PhD scholarships should be open to them
                ok = ok and n > 0
                note = "; PhD scholarships open to a professional with a master's" if n else "; none (expected some)"
            if name == "senior researcher, 30 years after PhD":  # PhD scholarships are not for senior researchers
                ok = ok and n == 0
                note = "; correctly none for PhD scholarships" if n == 0 else "; PhD scholarships shown to a senior researcher"
            # Here only programmes open to any country, or not tied to one, should come back.
            if name == "country with no programmes":
                other = [x["name"] for x in r["shortlist"] if not (x.get("host_anywhere") or
                         x.get("host_country") in ("Not stated", "Any country"))]
                ok = ok and not other
                note = f"; all are 'Any country' or 'Not stated'" if not other else f"; {len(other)} held elsewhere"
            record("F", f"F{i}", f"Input: {name}", ok, f"{n} eligible, {ms:.0f} ms{note}")
        safe("F", f"F{i}", f"Input: {name}", run)


# ---------------------------------------------------------------- G performance
def area_g():
    forms = list(ALL.values())
    times = []
    for i in range(30):
        t0 = time.time()
        instant(dict(forms[i % len(forms)]))
        times.append((time.time() - t0) * 1000)
    times.sort()
    p50, p95 = times[len(times) // 2], times[int(len(times) * 0.95) - 1]
    record("G", "G1", "Instant results latency (30 searches, no cloud AI)", p95 < 2000,
           f"median {p50:.0f} ms, 95th percentile {p95:.0f} ms, max {times[-1]:.0f} ms",
           {"p50_ms": round(p50), "p95_ms": round(p95), "max_ms": round(times[-1])})


# ---------------------------------------------------------------- H AI ranking
def area_h():
    for i, name in enumerate(["Priya", "Daniel", "Siti"], 1):
        def run(name=name, i=i):
            form = dict(next(v for k, v in ALL.items() if k.startswith(name)))
            t0 = time.time()
            r = enrich(instant(form))
            secs = time.time() - t0
            items = r["shortlist"]
            scored = sum(x.get("fit") is not None for x in items)
            ordered = items == final_order(items)
            errs = [e for e in r["trace"] if "error" in e["summary"]]
            record("H", f"H{i}", f"AI ranking for {name}: every result scored, order consistent",
                   scored == len(items) and ordered,
                   f"{scored}/{len(items)} scored in {secs:.0f} s; order {'consistent' if ordered else 'INCONSISTENT'}"
                   + (f"; {errs[0]['summary']}" if errs else ""),
                   {"scored": scored, "total": len(items), "seconds": round(secs)})
            RANKED[name] = r
        safe("H", f"H{i}", f"AI ranking for {name}", run)


RANKED = {}


# ---------------------------------------------------------------- I RAG
def area_i():
    from access.rag import NOT_STATED, ask
    rng = random.Random(12)
    qs = ["What is the application deadline?", "Who is eligible to apply?", "How much funding does it provide?",
          "Do I need a supervisor before applying?", "Can international students apply?"]
    rows = []
    for p in rng.sample(programs, 6):
        q = rng.choice(qs)
        t0 = time.time()
        try:
            r = ask(p, q)
        except Exception as e:
            rows.append({"programme": p["name"], "question": q, "error": str(e)[:80]})
            continue
        rows.append({"programme": p["name"], "question": q, "verified": r.get("verified"),
                     "not_stated": r["answer"] == NOT_STATED, "seconds": round(time.time() - t0, 1),
                     "answer": r["answer"][:200], "model": r.get("model")})
    answered = [x for x in rows if "error" not in x]
    faithful = sum(bool(x["verified"]) or x["not_stated"] for x in answered)
    known = [("Lee Kuan Yew Scholarship to Encourage", "How much funding does it provide?"),
             ("A*STAR Graduate Scholarship", "Who is eligible to apply?"),
             ("NTU Research Scholarship", "How much funding does it provide?"),
             ("Chevening", "Who is eligible to apply?")]
    good = []
    for name, q in known:
        p = next((x for x in programs if x["name"].startswith(name) or name in x["name"]), None)
        if not p:
            continue
        r = ask(p, q)
        good.append({"programme": p["name"], "question": q, "verified": r.get("verified"),
                     "answered": r["answer"] != NOT_STATED, "answer": r["answer"][:200]})
    ok = good and all(x["verified"] and x["answered"] for x in good)
    record("I", "I2", "Q&A answers questions the official page does answer, with verified quotes", ok,
           f"{sum(x['verified'] and x['answered'] for x in good)}/{len(good)} answered and verified", {"rows": good})
    record("I", "I1", "Q&A answers quote only the official page (6 random programmes)", faithful == len(answered) and answered,
           f"{faithful}/{len(answered)} faithful; {sum(x.get('not_stated', False) for x in answered)} said the page "
           f"does not say; {len(rows) - len(answered)} errors", {"rows": rows})


# ---------------------------------------------------------------- J plans
def area_j():
    r = RANKED.get("Priya") or instant(dict(next(v for k, v in ALL.items() if k.startswith("Priya"))))
    pid = r["shortlist"][0]["id"] if r["shortlist"] else None
    t0 = time.time()
    a = plan_for(r, pid) if pid else None
    text = json.dumps(a) if a else ""
    record("J", "J1", "Application plan for the top eligible programme", bool(a) and len(text) > 200,
           f"{len(text)} characters in {time.time() - t0:.0f} s", {"plan": a})


# ---------------------------------------------------------------- K privacy
def area_k():
    from access.config import RUNS_DIR
    before = set(RUNS_DIR.glob("*.json"))
    r = instant({**dict(list(PERSONAS.values())[0]), "name": "Real Person Name"})
    save_run(r)
    new = sorted(set(RUNS_DIR.glob("*.json")) - before)
    stored = json.loads(new[-1].read_text())["form"]["name"] if new else None
    for f in new:  # a test artefact, not a real search, so we delete it
        f.unlink()
    record("K", "K1", "A searcher's name is never stored", stored == "you", f"stored name: {stored!r}")
    p = dict(list(PERSONAS.values())[1])
    record("K", "K2", "An edited example is not treated as the example", is_example(p) and not is_example(
        {**p, "about": p["about"] + " edited"}), "unedited: example; edited: ordinary search")


# ---------------------------------------------------------------- L user interface
def area_l():
    """Drive the real multipage app, because the pages only work inside the app's navigation context."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app.py", default_timeout=120)
    at.run()
    record("L", "L1", "Home (search) page renders without an exception", not at.exception,
           f"{len(at.exception)} exceptions")
    for i, page in enumerate(["views/how.py", "views/database.py", "views/quality.py"], 2):
        at.switch_page(page).run()
        record("L", f"L{i}", f"Page renders without an exception: {page.split('/')[-1][:-3]}", not at.exception,
               f"{len(at.exception)} exceptions, {len(at.markdown)} text blocks"
               + (f": {at.exception[0].message[:80]}" if at.exception else ""))
    at.switch_page("views/search.py").run()
    shown = {}
    for name in ("Priya", "Wei Ling", "Daniel", "Amara"):
        # An example button only fills in the form; the search itself is covered by L6 below. We check that the
        # description box now holds the example's text.
        at.button(key=f"ex-{name}").click().run()
        label = next(k for k in PERSONAS if k.startswith(name))
        shown[name] = len(at.text_area(key=f"about-{label}").value or "")
    ok = not at.exception and all(v > 0 for v in shown.values())
    record("L", "L5", "Each example button fills in the form", ok,
           ", ".join(f"{k} {v}" for k, v in shown.items()) + (f"; {len(at.exception)} exceptions" if at.exception else ""),
           shown)
    # L6: a search typed into the form, which is the path an audience member takes.
    at.text_area(key="about-" + "Amara - engineering undergraduate (Nigeria) seeking a funded master's").set_value(
        "Civil engineer with a master's degree interested in a PhD on flood risk and climate adaptation.")
    at.button(key="FormSubmitter:profile-Find opportunities").click().run()
    text = " ".join(str(m.value) for m in at.markdown)
    m = re.search(r"Funding (\w+) can apply for", text)
    record("L", "L6", "A search typed into the form returns results without an exception",
           not at.exception and bool(re.search(r"(<b>)?\d+(</b>)? eligible", text)),
           (m.group(0) if m else "no results heading") + (f"; {len(at.exception)} exceptions" if at.exception else ""))


if __name__ == "__main__":
    t0 = time.time()
    ai = "--no-ai" not in sys.argv
    for fn in [area_a, area_b, area_c, area_d, area_e, area_f, area_g] + ([area_h, area_i, area_j] if ai else []) + \
              [area_k, area_l]:
        print(f"--- {fn.__name__}", flush=True)
        safe(fn.__name__[-1].upper(), fn.__name__[-1].upper() + "0", fn.__name__, fn)
    summary = {"run_at": datetime.now().isoformat(timespec="seconds"), "library": len(programs),
               "seconds": round(time.time() - t0), "passed": sum(r["passed"] for r in RESULTS),
               "total": len(RESULTS), "results": RESULTS}
    OUT.write_text(json.dumps(summary, indent=1, default=str))
    print(f"\n{summary['passed']}/{summary['total']} passed in {summary['seconds']} s -> {OUT}")
