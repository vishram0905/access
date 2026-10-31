"""Evaluation harness (tooling): the reproducible benchmarks behind the numbers in our report.

The main one is a known-item retrieval benchmark that needs no human labels. For a fixed random sample of
programmes, a model writes the query that someone in the programme's target group would type, without naming the
programme or funder (we reject leaky queries). That programme is then the one known relevant item, and we record
where each retrieval method ranks it: recall@k is the share of queries with the programme in the top k, and MRR
the mean of 1 / rank. The query set is generated once and saved to data/eval/known_items.jsonl so every method
sees the same queries. The query writer (Nemotron, with GLM as backup) comes from a different family than the
embedder (Nomic).

The other experiments measure the checking side: judge agreement (Fleiss' kappa), retrieved vs anchored excerpts,
per-judge reliability, the locate step of the claim check and the faithfulness of "Ask about this programme".

Run:  python -m access.bench            (builds the query set on first run, then evaluates)
      python -m access.bench rag | judges [HH:MM] | judges-summary | locate | excerpt
"""
import json
import random
import re
import sys
import time

import numpy as np

from .config import DATA, GLM, GPT_OSS, MUSE, NEMOTRON, PHI_LOCAL, QWEN_LARGE, ROLES
from .llm import LLMError, call_json, embed, set_role
from .lookup import load, search_text
from .retrieval import BM25, FUSION_WEIGHTS, rrf, tokens

EVAL = DATA / "eval"
KNOWN = EVAL / "known_items.jsonl"
SYSTEM = "You write realistic search queries. Reply in JSON."
PROMPT = """A funding programme is described below. Write the search query that a researcher who would qualify for it
might type into a funding search engine, describing THEMSELVES and what they want (career stage, field, where).
Rules: do NOT mention the programme's name, the funder's name, or any acronym of them. Use your OWN words: a real
person describes their situation and needs, they do not copy wording from the programme page. 1-2 sentences.

Programme: {text}

JSON: {{"query": "..."}}"""


def _leaks(query: str, prog: dict) -> bool:
    """True if the query names the programme or funder, by a distinctive word or an acronym."""
    q = set(tokens(query))
    generic = set(tokens("scholarship scholarships fellowship fellowships programme program award awards grant grants "
                         "research graduate postgraduate undergraduate international university foundation national "
                         "phd doctoral postdoctoral masters master science sciences singapore japan china india "
                         "united kingdom states study studies student students scheme early career young"))
    distinct = [t for t in tokens(prog.get("name", "") + " " + (prog.get("provider") or "")) if t not in generic]
    acronyms = [a.lower() for a in re.findall(r"\b[A-Z][A-Z*&]{2,}\b", prog.get("name", "") + " " + (prog.get("provider") or ""))]
    return any(t in q for t in distinct) or any(a.replace("*", "") in query.lower() for a in acronyms)


def build_known_items(n: int = 100, seed: int = 7) -> list[dict]:
    """Generate and save n leak-free known-item queries from a seeded shuffle of the library."""
    programs = load()[0]
    rng = random.Random(seed)
    sample = rng.sample(programs, len(programs))  # we walk the shuffle and replace leaky queries
    set_role("auditor")
    out = []
    for p in sample:
        if len(out) >= n:
            break
        for spec in (NEMOTRON, GLM):
            try:
                q = str(call_json(spec, SYSTEM, PROMPT.format(text=search_text(p)[:1200])).get("query", "")).strip()
                break
            except LLMError:
                q = ""
        if q and not _leaks(q, p):
            out.append({"id": p["id"], "name": p["name"], "query": q})
    EVAL.mkdir(parents=True, exist_ok=True)
    KNOWN.write_text("\n".join(json.dumps(x) for x in out) + "\n")
    return out


def known_items() -> list[dict]:
    """Load the saved query set, building it on first use."""
    if not KNOWN.exists():
        return build_known_items()
    return [json.loads(l) for l in KNOWN.read_text().splitlines() if l.strip()]


# ---------------- retrieval methods under test
# We compare ranking only here, with no filters and no eligibility gate, so the methods are judged on retrieval.

def dense_ranker():
    programs, _, vecs, _ = load()
    ids = [p["id"] for p in programs]

    def rank(query: str) -> list[str]:
        q = np.array(embed(ROLES["embedder"][0], [f"search_query: {query}"])[0], dtype=np.float32)
        q /= np.linalg.norm(q)
        return [ids[i] for i in np.argsort(-(vecs @ q))]
    return rank


def bm25_ranker():
    programs = load()[0]
    ids = [p["id"] for p in programs]
    index = BM25([search_text(p) for p in programs])

    def rank(query: str) -> list[str]:
        s = index.scores(query)
        return [ids[i] for i in sorted(range(len(ids)), key=lambda i: -s[i])]
    return rank


def hybrid_ranker(weights=(1.0, 1.0)):
    dense, lexical = dense_ranker(), bm25_ranker()
    return lambda query: rrf([dense(query), lexical(query)], weights=list(weights))


def evaluate_retrieval(methods: dict | None = None, ks=(1, 5, 10)) -> dict:
    """Recall@k, MRR (each with a bootstrap 95% CI) and time per query for each retrieval method."""
    items = known_items()
    methods = methods or {"dense": dense_ranker(), "bm25": bm25_ranker(), "hybrid RRF 1:1": hybrid_ranker(),
                          "hybrid RRF, BM25 2:1 (live)": hybrid_ranker((FUSION_WEIGHTS["dense"], FUSION_WEIGHTS["bm25"]))}
    report = {"queries": len(items), "programmes": len(load()[0]), "methods": {}}
    for name, rank in methods.items():
        ranks, t0 = [], time.time()
        for it in items:
            order = rank(it["query"])
            ranks.append(order.index(it["id"]) + 1 if it["id"] in order else len(order) + 1)
        report["methods"][name] = {
            **{f"recall@{k}": _with_ci([float(r <= k) for r in ranks]) for k in ks},
            "MRR": _with_ci([1 / r for r in ranks]),
            "ms_per_query": round(1000 * (time.time() - t0) / len(ranks), 1)}
    return report


def _with_ci(values: list[float], reps: int = 2000, seed: int = 0) -> str:
    """Mean with a 95% percentile-bootstrap confidence interval, resampling the queries."""
    rng = np.random.default_rng(seed)
    v = np.array(values)
    boots = np.sort(rng.choice(v, size=(reps, len(v)), replace=True).mean(axis=1))
    return f"{v.mean():.3f} [{boots[int(.025 * reps)]:.3f}-{boots[int(.975 * reps)]:.3f}]"


def fleiss_kappa(table: list[list[int]]) -> float | None:
    """Fleiss' kappa, the chance-corrected agreement of a fixed number of raters per item.

    table[i][j] is the number of raters who put item i in category j.
    """
    if not table:
        return None
    n = sum(table[0])
    if n < 2:
        return None
    N, k = len(table), len(table[0])
    p_j = [sum(row[j] for row in table) / (N * n) for j in range(k)]
    P_i = [(sum(c * c for c in row) - n) / (n * (n - 1)) for row in table]
    P_bar, P_e = sum(P_i) / N, sum(p * p for p in p_j)
    return round((P_bar - P_e) / (1 - P_e), 3) if P_e < 1 else None


def judge_kappa() -> dict:
    """Chance-corrected agreement of the three-judge panel on "is this rule supported by the page?"."""
    from .db import all_listings, connect
    table = []
    with connect() as con:
        for l in all_listings(con, include_rejected=True):
            vs = [v for v in (l.get("review") or {}).get("verdicts", []) if "error" not in v]
            if len(vs) != 3:
                continue
            for rid in set.intersection(*[set(v.get("rules", {})) for v in vs]):
                yes = sum(bool(v["rules"][rid]) for v in vs)
                table.append([yes, 3 - yes])
    raw = sum(max(r) == 3 for r in table) / len(table) if table else None
    return {"items": len(table), "fleiss_kappa": fleiss_kappa(table),
            "raw_unanimous": round(raw, 3) if raw is not None else None}


def excerpt_experiment(per_type: int = 8, seed: int = 11) -> dict:
    """Compare retrieved excerpts with the quote-anchored baseline as a paired experiment.

    Every planted error (the Auditor's mutations) is judged twice by the same three judges, once with each
    excerpt. We report the catch rate per error type for both, the discordant pairs (caught with one excerpt
    only) and the mean excerpt size, which is what drives prompt cost.
    """
    from . import critics, resources
    from .auditor import plant
    from .db import connect
    from .passages import claim_excerpt
    set_role("auditor")
    rng = random.Random(seed)
    with connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT l.data, s.text FROM listings l JOIN sources s ON s.url = l.source_url "
            "WHERE l.decision IN ('accepted','accepted_with_warning') AND length(s.text) > 1500")]
    rng.shuffle(rows)
    panel, _ = resources.pick_panel(ROLES["judge_pool"], "auditor", 3)
    if len({j.family for j in panel}) < 3:
        return {"error": "a full three-judge panel is not available right now"}
    out = {"panel": [j.label for j in panel], "types": {}, "excerpt_chars": {"anchored": [], "retrieved": []}}
    for kind in ("shifted_deadline", "inflated_funding", "fake_rule", "flipped_nationality"):
        pairs = []
        for row in rows:
            if len(pairs) >= per_type:
                break
            listing = json.loads(row["data"])
            if listing.get("schema_version") != "2.0" or not isinstance(listing.get("funding") or {}, dict) \
                    or not isinstance(listing.get("process") or {}, dict):
                continue  # skip early-format records
            try:
                planted = plant(listing, kind, "")
            except (AttributeError, TypeError, KeyError):
                planted = None
            if not planted:
                continue
            m, _, item = planted
            result = {}
            for mode in ("anchored", "retrieved"):
                critics.EXCERPT_MODE = mode
                out["excerpt_chars"][mode].append(len(claim_excerpt(row["text"], m) if mode == "retrieved"
                                                      else critics._excerpt_anchored(row["text"], m["rules"])))
                judged = critics.review_listing(json.loads(json.dumps(m)), row["text"], judges=panel)
                if item.startswith("r"):
                    result[mode] = any(r["id"] == item for r in judged.get("rules_dropped", []))
                else:
                    result[mode] = any(c.startswith("deadline" if item == "f1" else "funding")
                                       for c in judged.get("facts_unconfirmed", []))
            pairs.append(result)
        critics.EXCERPT_MODE = "retrieved"
        n = len(pairs)
        out["types"][kind] = {
            "tests": n,
            "caught_anchored": round(sum(p["anchored"] for p in pairs) / n, 2) if n else None,
            "caught_retrieved": round(sum(p["retrieved"] for p in pairs) / n, 2) if n else None,
            "only_retrieved_caught": sum(p["retrieved"] and not p["anchored"] for p in pairs),
            "only_anchored_caught": sum(p["anchored"] and not p["retrieved"] for p in pairs)}
    for mode, xs in out["excerpt_chars"].items():
        out["excerpt_chars"][mode] = round(sum(xs) / max(1, len(xs)))
    (EVAL / "excerpt_experiment.json").write_text(json.dumps(out, indent=1))
    return out


# The per-judge experiment's judges were fixed when we wrote its protocol. They stay the same even if the judge
# pool in config.py changes, so results remain comparable.
EXPERIMENT_JUDGES = [GPT_OSS, QWEN_LARGE, NEMOTRON, GLM, PHI_LOCAL, MUSE]
JUDGE_ITEMS = EVAL / "judge_items.jsonl"
JUDGE_RAW = EVAL / "judge_experiment_raw.jsonl"
PLANT_KINDS = ("shifted_deadline", "inflated_funding", "fake_rule", "flipped_nationality")


def _judge_items(per_type: int = 6, n_clean: int = 12, seed: int = 23) -> list[dict]:
    """Fixed test set for the per-judge experiment, built once and saved so every judge sees identical inputs.

    It holds planted errors (the Auditor's mutations) and clean copies of the same records as false-alarm
    controls. For the page we store only the excerpt, because that is all a judge ever sees.
    """
    if JUDGE_ITEMS.exists():
        return [json.loads(l) for l in JUDGE_ITEMS.open()]
    import copy
    from .auditor import plant
    from .db import connect
    from .passages import claim_excerpt
    rng = random.Random(seed)
    with connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT l.data, s.text FROM listings l JOIN sources s ON s.url = l.source_url "
            "WHERE l.decision IN ('accepted','accepted_with_warning') AND length(s.text) > 1500")]
    rng.shuffle(rows)
    items, clean_src = [], []
    for kind in PLANT_KINDS:
        n = 0
        for row in rows:
            if n >= per_type:
                break
            listing = json.loads(row["data"])
            if listing.get("schema_version") != "2.0" or not isinstance(listing.get("funding") or {}, dict) \
                    or not isinstance(listing.get("process") or {}, dict):
                continue  # skip early-format records
            try:
                planted = plant(listing, kind, "")
            except (AttributeError, TypeError, KeyError):
                planted = None
            if not planted:
                continue
            m, _, item = planted
            items.append({"key": f"{kind}:{n}", "kind": kind, "item": item, "listing": m,
                          "excerpt": claim_excerpt(row["text"], m)})
            if len(clean_src) < n_clean and listing["url"] not in {c[0]["url"] for c in clean_src}:
                clean_src.append((listing, row["text"]))
            n += 1
    for i, (listing, text) in enumerate(clean_src):
        m = copy.deepcopy(listing)  # strip it as plant() does, without the mutation
        for k in ("review", "kpis", "trust", "band", "facts_unconfirmed", "confidence", "rules_dropped"):
            m.pop(k, None)
        m["rules"] = [dict(r, votes_supported=0, votes_total=0) for r in m.get("rules", [])]
        items.append({"key": f"clean:{i}", "kind": "clean", "item": None, "listing": m,
                      "excerpt": claim_excerpt(text, m)})
    EVAL.mkdir(parents=True, exist_ok=True)
    JUDGE_ITEMS.write_text("".join(json.dumps(it) + "\n" for it in items))
    return items


def judge_experiment(until: float | None = None) -> dict:
    """Per-judge reliability, fully crossed: every judge votes on every item of the fixed test set.

    We switch fallback models off so each vote really comes from the named model. The run can be resumed:
    finished (item, judge) votes are kept in JUDGE_RAW, and a judge out of quota waits and retries until `until`
    (epoch seconds). It uses its own "experiment" token share, so the agents' budgets are not touched.
    """
    import dataclasses
    from concurrent.futures import ThreadPoolExecutor
    from . import critics, resources
    items = _judge_items()
    done = set()
    if JUDGE_RAW.exists():
        done = {(r["key"], r["judge"]) for r in map(json.loads, JUDGE_RAW.open())}
    judges = [dataclasses.replace(j, fallbacks=()) for j in EXPERIMENT_JUDGES]

    def run(j):
        set_role("experiment")
        todo = [it for it in items if (it["key"], j.label) not in done]
        while todo and (until is None or time.time() < until):
            if j.provider == "ollama":
                cd = resources.cooldown_left(j.model)  # agents may have benched a slow local judge
                ok, wait = resources.local_model_ok()[0] and cd == 0, max(cd, 300)
            else:
                ok, wait = resources.model_ready(j.provider, j.model, "experiment")
            if not ok:
                time.sleep(min(max(wait, 60), 900))
                continue
            it = todo[0]
            v = critics._judge_source(j, it["listing"], it["excerpt"])
            if "error" in v:
                print(time.strftime("%H:%M:%S"), f"[experiment] {j.label}: {v['error'][:120]}", flush=True)
                time.sleep(120)
                continue
            with JUDGE_RAW.open("a") as fh:
                fh.write(json.dumps({"key": it["key"], "judge": j.label, "family": j.family,
                                     "votes": v["rules"], "at": time.time()}) + "\n")
            todo.pop(0)
            print(time.strftime("%H:%M:%S"), f"[experiment] {j.label}: {it['key']} done, {len(todo)} left",
                  flush=True)
        return j.label, len(todo)

    with ThreadPoolExecutor(len(judges)) as ex:
        left = dict(ex.map(run, judges))
    out = judge_summary()
    out["remaining"] = left
    return out


def _wilson(k: int, n: int) -> list:
    """95% Wilson score interval for k successes out of n."""
    if not n:
        return [None, None]
    z, p = 1.96, k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / (1 + z * z / n)
    return [round(c - h, 2), round(c + h, 2)]


def judge_summary() -> dict:
    """Score the saved per-judge votes, for each judge and for every possible panel.

    A planted error counts as caught when the judge voted that claim unsupported. A false alarm is a true claim of
    a clean record voted unsupported. We also score every panel of three judges from three companies with the
    production majority rule, reusing the same votes, so this costs no extra calls.
    """
    from itertools import combinations
    from scipy.stats import chi2
    items = {it["key"]: it for it in _judge_items()}
    votes = {}
    for r in map(json.loads, JUDGE_RAW.open()) if JUDGE_RAW.exists() else []:
        votes[(r["key"], r["judge"])] = r["votes"]
    judges = [j.label for j in EXPERIMENT_JUDGES]
    planted = [k for k, it in items.items() if it["kind"] != "clean"]
    clean = [k for k, it in items.items() if it["kind"] == "clean"]

    def caught(key, j):
        v = votes.get((key, j))
        return None if v is None else v.get(items[key]["item"]) is False

    def false_alarms(key, j):  # returns (true claims rejected, true claims voted on)
        v = votes.get((key, j))
        return (0, 0) if v is None else (sum(x is False for x in v.values()), len(v))

    out = {"design": {"planted": len(planted), "clean_records": len(clean), "judges": judges}, "judges": {}}
    for j in judges:
        c = [caught(k, j) for k in planted if caught(k, j) is not None]
        fa = [false_alarms(k, j) for k in clean]
        fk, fn = sum(a for a, _ in fa), sum(b for _, b in fa)
        catch, far = (sum(c) / len(c) if c else None), (fk / fn if fn else None)
        out["judges"][j] = {
            "planted_judged": len(c), "caught": round(catch, 2) if c else None, "caught_ci95": _wilson(sum(c), len(c)),
            "by_type": {t: (lambda xs: f"{sum(xs)}/{len(xs)}")(
                [caught(k, j) for k in planted if items[k]["kind"] == t and caught(k, j) is not None])
                for t in PLANT_KINDS},
            "false_alarm": round(far, 2) if fn else None, "false_alarm_ci95": _wilson(fk, fn), "clean_claims": fn,
            "balanced_accuracy": round((catch + 1 - far) / 2, 2) if c and fn else None}
    # Cochran's Q tests whether the judges differ in catch rate, on the planted items every judge has voted on.
    full = [k for k in planted if all(caught(k, j) is not None for j in judges)]
    if len(full) >= 5:
        X = np.array([[caught(k, j) for j in judges] for k in full], dtype=int)
        kj, C, R = len(judges), X.sum(0), X.sum(1)
        den = kj * R.sum() - (R ** 2).sum()
        if den:
            Q = (kj - 1) * (kj * (C ** 2).sum() - C.sum() ** 2) / den
            out["cochran_q"] = {"items": len(full), "Q": round(float(Q), 2),
                                "p": round(float(chi2.sf(Q, kj - 1)), 4)}
    fam = {j.label: j.family for j in EXPERIMENT_JUDGES}
    default = {j.label for j in ROLES["critic_sources"]}
    panels = []
    for trio in combinations(judges, 3):
        if len({fam[j] for j in trio}) < 3:
            continue
        cs = []
        for k in planted:
            vs = [caught(k, j) for j in trio]
            if None not in vs:
                cs.append(sum(vs) >= 2)  # majority dropped the planted claim
        fk = fn = 0
        for k in clean:
            vs = [votes.get((k, j)) for j in trio]
            if None in vs:
                continue
            for cid in set().union(*vs):
                vv = [v[cid] for v in vs if cid in v]
                fn += 1
                fk += sum(map(bool, vv)) < len(vv) // 2 + 1  # majority dropped a true claim
        if cs and fn:
            panels.append({"panel": list(trio), "default": set(trio) == default, "caught": round(sum(cs) / len(cs), 2),
                           "false_alarm": round(fk / fn, 2),
                           "balanced_accuracy": round((sum(cs) / len(cs) + 1 - fk / fn) / 2, 2), "n": len(cs)})
    out["panels"] = sorted(panels, key=lambda p: -p["balanced_accuracy"])
    (EVAL / "judge_experiment.json").write_text(json.dumps(out, indent=1))
    return out


def locate_eval(seed: int = 1) -> dict:
    """Measure the locate step of the claim check (see docs/DECISIONS.md, D22) on every accepted record.

    This costs no model calls. We report the share of true claims (the annotator's originals) located on the
    official page, and the share of planted errors (the Auditor's shifted deadline, amount x4) wrongly located.
    A planted error that is not located is caught before any judge sees it.
    """
    import copy
    from . import factcheck as fc
    from .auditor import _shift_date
    from .db import connect
    random.seed(seed)
    with connect() as con:
        rows = [(json.loads(a), t) for a, t in con.execute(
            "SELECT s.annotation, s.text FROM listings l JOIN sources s ON s.url = l.source_url "
            "WHERE l.decision = 'accepted' AND s.annotation IS NOT NULL")]
    st = {k: [0, 0] for k in ("deadline", "amount", "rule", "fully_funded", "planted_shifted_deadline",
                              "planted_inflated_amount")}
    for a, t in rows:
        a["rules"] = [dict(r, id=r.get("id") or f"r{i + 1}") for i, r in enumerate(a.get("rules") or [])]
        for c in fc.claims(a, t):
            if c["kind"] in st:
                st[c["kind"]][0] += c["located"]
                st[c["kind"]][1] += 1
        p, f = a.get("process") or {}, a.get("funding") or {}
        if p.get("next_deadline") or p.get("deadline_text"):
            m = copy.deepcopy(a)
            new = _shift_date(p.get("next_deadline"))
            m["process"].update(next_deadline=new, deadline_text=new)
            st["planted_shifted_deadline"][0] += [c for c in fc.claims(m, t) if c["id"] == "deadline"][0]["located"]
            st["planted_shifted_deadline"][1] += 1
        if f.get("stipend_amount") is not None:
            m = copy.deepcopy(a)
            m["funding"]["stipend_amount"] = round(f["stipend_amount"] * 4)
            st["planted_inflated_amount"][0] += [c for c in fc.claims(m, t) if c["id"] == "amount"][0]["located"]
            st["planted_inflated_amount"][1] += 1
    out = {"records": len(rows), "located": {k: {"rate": round(h / n, 3) if n else None, "n": n, "ci95": _wilson(h, n)}
                                             for k, (h, n) in st.items()}}
    (EVAL / "locate_eval.json").write_text(json.dumps(out, indent=1))
    return out


RAG_QUESTIONS = ["Can I apply if I am still finishing my current degree?", "What documents do I need to submit?",
                 "Is there an age limit?", "How long does the funding last?", "Can I apply from outside the country?"]


def rag_eval(n_programmes: int = 12, seed: int = 5) -> dict:
    """Faithfulness of "Ask about this programme" on a sample of programmes and stock questions.

    Faithful means every quote in the answer is found on the official page, or the answer says the page does not
    cover the question. We also report latency and how often the page had no answer.
    """
    from .rag import NOT_STATED, ask
    rng = random.Random(seed)
    programs = [p for p in load()[0] if p.get("url")]
    rows = []
    for p in rng.sample(programs, min(n_programmes, len(programs))):
        for q in rng.sample(RAG_QUESTIONS, 2):
            t0 = time.time()
            r = ask(p, q)
            if r.get("model") is None and r["answer"] != NOT_STATED:
                continue  # no writer was available, nothing to score
            rows.append({"programme": p["name"], "question": q, "answer": r["answer"], "verified": r["verified"],
                         "not_stated": r["answer"] == NOT_STATED, "seconds": round(time.time() - t0, 1),
                         "model": r.get("model")})
    answered = [r for r in rows if not r["not_stated"]]
    out = {"answers": len(rows),
           "faithful_rate": _with_ci([float(r["verified"]) for r in rows]) if rows else None,
           "faithful_rate_when_answering": _with_ci([float(r["verified"]) for r in answered]) if answered else None,
           "page_does_not_say_rate": round(sum(r["not_stated"] for r in rows) / max(1, len(rows)), 2),
           "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else None,
           "rows": rows}
    (EVAL / "rag_eval.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["rag"]:
        print(json.dumps({k: v for k, v in rag_eval().items() if k != "rows"}, indent=1))
        raise SystemExit
    if sys.argv[1:2] == ["judges"]:
        # python -m access.bench judges [HH:MM] runs until the next time the clock shows HH:MM, then summarises
        until = None
        if sys.argv[2:]:
            from datetime import datetime, timedelta
            h, m = map(int, sys.argv[2].split(":"))
            t = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
            until = (t if t > datetime.now() else t + timedelta(days=1)).timestamp()
        print(json.dumps(judge_experiment(until), indent=1))
        raise SystemExit
    if sys.argv[1:] == ["locate"]:
        print(json.dumps(locate_eval(), indent=1))
        raise SystemExit
    if sys.argv[1:] == ["judges-summary"]:
        print(json.dumps(judge_summary(), indent=1))
        raise SystemExit
    if sys.argv[1:] == ["excerpt"]:
        print(json.dumps(excerpt_experiment(), indent=1))
        raise SystemExit
    results = {"retrieval": evaluate_retrieval(), "judge_agreement": judge_kappa(),
               "run_at": time.strftime("%Y-%m-%d %H:%M")}
    (EVAL / "results.json").write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1))
