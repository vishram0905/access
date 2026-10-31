"""Fast search over the lookup document (Layer 2 matching and eligibility).

The only model call here is one local embedding of the query (about 50 ms on our development laptop). We apply
the facet filters first, rank the remaining programmes with BM25 and dense similarity fused by Reciprocal Rank
Fusion, and then run the deterministic eligibility gate on every programme. The result is three lists:
eligible, near-miss and excluded.
"""
import re
import time

import numpy as np

from .config import ROLES
from .gate import evaluate
from .llm import embed
from .lookup import load, search_text
from .retrieval import BM25, FUSION_WEIGHTS, rrf
from .schema import COUNTRY_REGION

REGION_OF = {"Singapore": "Asia", "Japan": "Asia", "China": "Asia", "South Korea": "Asia", "India": "Asia",
             "Hong Kong": "Asia", "Malaysia": "Asia", "Australia": "Asia-Pacific",
             "New Zealand": "Asia-Pacific", "United States": "North America", "Canada": "North America",
             "Mexico": "North America", "Brazil": "South America", "Chile": "South America",
             "Argentina": "South America", "Colombia": "South America"}


_BM25 = {}


def _bm25(programs) -> BM25:
    """Build the BM25 index over the same text the embeddings use.

    Building takes about 30 ms, so we keep one index per library version and rebuild only when it changes.
    """
    key = (len(programs), programs[0]["id"] if programs else "", programs[-1]["id"] if programs else "")
    if key not in _BM25:
        _BM25.clear()
        _BM25[key] = BM25([search_text(p) for p in programs])
    return _BM25[key]


def _query_vec(text: str):
    v = np.array(embed(ROLES["embedder"][0], [f"search_query: {text}"])[0], dtype=np.float32)
    return v / np.linalg.norm(v)


# A postdoc asking for "postdoc fellowships" also wants postdoc-level "research fellowships". We can widen the
# type filter safely because the gate still removes the ones meant for senior researchers.
RELATED_TYPES = {"postdoc_fellowship": ["research_fellowship"], "research_fellowship": ["postdoc_fellowship"]}


def _diverse(items: list[dict], per_funder: int = 2) -> list[dict]:
    """Keep the ranking but stop one funder filling the list: its third and later programmes move to the end."""
    seen, head, tail = {}, [], []
    for x in items:
        key = re.sub(r"\s*\(.*?\)", "", (x.get("provider") or "").lower()).strip()
        seen[key] = seen.get(key, 0) + 1
        (head if seen[key] <= per_funder else tail).append(x)
    return head + tail


def _hosted_ids(facets: dict, countries: list) -> set:
    """Return the programmes a researcher targeting `countries` can take up.

    That means held in one of the countries, held in their region ("EU member states" covers Germany), open to
    any country, or not stated on the page. We keep the "not stated" ones rather than guess, and the result card
    says "Not stated". Records whose several host countries are still unresolved (the catch-all "Multiple") are
    left out of country searches, because they would otherwise match every country.
    """
    hc, hr, hs = (facets.get(c, {}) for c in ("host_countries", "host_regions", "host_scope"))
    ids = set()
    for c in countries:
        ids |= set(hc.get(c, [])) | set(hr.get(COUNTRY_REGION.get(c, ""), []))
    for scope in ("anywhere", "not_stated"):
        ids |= set(hs.get(scope, []))
    return ids


def search(profile: dict, query_text: str, k: int = 25, filters: dict | None = None) -> dict:
    """Search the library for one profile and query, and sort every programme through the eligibility gate.

    filters looks like {"host_country": [...], "provider_type": [...], "opportunity_type": [...], "region": [...]}.
    We treat countries and types as preferences: if no programme matches a filter, that filter is relaxed.
    """
    t0 = time.time()
    programs, facets, vecs, meta = load()
    if not programs:
        return {"eligible": [], "near_miss": [], "excluded": [], "similarity": {}, "stats": {"programmes": 0}}
    idx = {p["id"]: i for i, p in enumerate(programs)}
    pool = set(idx)
    applied, relaxed = {}, []
    # We apply every filter the researcher set and relax one only when nothing at all matches. The relaxation
    # goes into stats.relaxed so the page can say so. Quietly adding other countries made the results look
    # inconsistent with what was asked for.
    filters = dict(filters or {})
    # Funders name the same kind of programme differently, so we include close relatives of the chosen type.
    if filters.get("opportunity_type"):
        wanted = list(filters["opportunity_type"])
        filters["opportunity_type"] = wanted + [r for w in wanted for r in RELATED_TYPES.get(w, []) if r not in wanted]
    order_cols = sorted(filters.items(), key=lambda kv: kv[0] != "opportunity_type")
    for col, wanted in order_cols:
        wanted = [w for w in (wanted or []) if w]
        if not wanted or col not in facets:
            continue
        ids = set()
        for w in wanted:
            ids |= set(facets[col].get(w, []))
        # Held in the country, in its region, anywhere, or the page does not say.
        if col == "host_country":
            ids = _hosted_ids(facets, wanted)
        narrowed = pool & ids
        if narrowed:
            pool, applied[col] = narrowed, wanted
        else:
            relaxed.append(col)
    try:
        q = _query_vec(query_text)
    except Exception:  # local embedding model unavailable: we still answer, with lexical ranking only
        q = None
    # Hybrid retrieval: BM25 catches exact names, acronyms and terms, dense similarity catches meaning, and
    # Reciprocal Rank Fusion merges the two. The benchmark (known-item recall@k and MRR) is in access/bench.py.
    bm = _bm25(programs)
    lexical = bm.scores(query_text)
    by_lex = sorted(pool, key=lambda i: -lexical[idx[i]])
    if q is None or len(vecs) != len(programs):  # no usable vectors: lexical ranking alone
        order = by_lex
        q = np.zeros(vecs.shape[1] if len(vecs) else 768, dtype=np.float32)
    else:
        order = rrf([sorted(pool, key=lambda i: -float(vecs[idx[i]] @ q)), by_lex],
                    weights=[FUSION_WEIGHTS["dense"], FUSION_WEIGHTS["bm25"]])
    targets = [c for c in (filters or {}).get("host_country") or [] if c]
    # If the country filter was relaxed, the chosen countries still come first.
    if targets and "host_country" not in applied:
        by_id = {p["id"]: p for p in programs}
        hosted = _hosted_ids(facets, targets)
        order.sort(key=lambda i: i not in hosted)
    confirmed = set()
    # Programmes confirmed in a chosen country, its region or anywhere go ahead of the "not stated" ones.
    if targets and "host_country" in applied:
        hc, hr, hs = (facets.get(c, {}) for c in ("host_countries", "host_regions", "host_scope"))
        for c in targets:
            confirmed |= set(hc.get(c, [])) | set(hr.get(COUNTRY_REGION.get(c, ""), []))
        confirmed |= set(hs.get("anywhere", []))
        order.sort(key=lambda i: i not in confirmed)
    sim = {i: float(vecs[idx[i]] @ q) for i in order}
    eligible, near, excluded = [], [], []
    for i in order:
        p = programs[idx[i]]
        g = evaluate(p, profile)
        item = {**p, "gate": g, "host_tier": int(bool(confirmed) and i not in confirmed)}
        {"eligible": eligible, "near_miss": near, "excluded": excluded}[g["outcome"]].append(item)
    eligible = _diverse(eligible)
    near = sorted(_diverse(near), key=lambda x: x["gate"].get("gap_cost", 0))  # easiest gap to close first
    return {"eligible": eligible[:k], "near_miss": near[:max(5, k // 3)], "excluded": excluded,
            "similarity": sim,
            "stats": {"programmes": len(programs), "after_filters": len(pool), "filters_applied": applied, "relaxed": relaxed,
                      "eligible_total": len(eligible), "near_total": len(near), "excluded_total": len(excluded),
                      "ms": round(1000 * (time.time() - t0))}}
