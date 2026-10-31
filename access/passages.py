"""Passage retrieval inside one programme's official page, the retrieval half of our RAG.

Every place we use RAG asks about a single programme ("is this claim on the page?", "can I apply in my final
year?"), so we search only that page's passages. There is no global passage index, which keeps it fast (a page is
about 10-40 passages) and cheap. The judge panel in Layer 0 uses claim_excerpt(); questions from users in Layer 3
go through retrieve().

chunk() cuts a sliding window of 110 words with 30 words of overlap, so a sentence cut at one boundary still
appears whole in the next passage. claim_excerpt() retrieves, for each claim, the passages that best match the
claim itself. We use BM25 there because claims are full of exact tokens (dates, amounts, country names), and we
match the claim rather than the annotator's quote because a quote-only excerpt hides the true value whenever the
annotator was wrong. retrieve() is hybrid (BM25 plus dense, fused by RRF) since user questions are phrased
loosely; passage vectors are cached by content hash, so each page is embedded once.
"""
import hashlib
import json
import re
import sqlite3

import numpy as np

from .config import DATA, ROLES
from .retrieval import BM25, rrf

WINDOW, OVERLAP = 110, 30
CACHE = DATA / "cache" / "passage_vectors.db"


def chunk(text: str, window: int = WINDOW, overlap: int = OVERLAP) -> list[str]:
    """Split text into overlapping word windows."""
    words = (text or "").split()
    if len(words) <= window:
        return [" ".join(words)] if words else []
    step = window - overlap
    return [" ".join(words[i:i + window]) for i in range(0, max(1, len(words) - overlap), step)]


def page_text(url: str) -> str:
    """Return the stored text of a programme's official page, as the crawler, renderer or archive read it."""
    from .db import connect
    with connect() as con:
        r = con.execute("SELECT text FROM sources WHERE url=?", (url,)).fetchone()
    return r[0] if r and r[0] else ""


def _claims(listing: dict) -> list[str]:
    from .critics import _facts
    out = [f'{r["attribute"]} {r["operator"]} {json.dumps(r["value"])} {r.get("evidence", "")}'
           for r in listing.get("rules", [])]
    return out + [f'{f["claim"]} {f.get("evidence", "")}' for f in _facts(listing)]


def claim_excerpt(text: str, listing: dict, per_claim: int = 2, limit: int = 4000) -> str:
    """Build the judges' evidence: the page opening, which says what the programme is, plus the top passages
    for each claim."""
    ps = chunk(text)
    if not ps:
        return ""
    index = BM25(ps)
    picked = [0]  # the opening passage identifies the programme
    for claim in _claims(listing):
        s = index.scores(claim)
        for i in sorted(range(len(ps)), key=lambda i: -s[i])[:per_claim]:
            if s[i] > 0 and i not in picked:
                picked.append(i)
    out, size = [], 0
    for i in picked:
        if size + len(ps[i]) > limit:
            break
        out.append(f"[passage {i + 1}] {ps[i]}")
        size += len(ps[i])
    return "\n".join(out)


# ---------------- hybrid retrieval for user questions

def _con():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CACHE, timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS vec (h TEXT PRIMARY KEY, v BLOB)")
    return con


def _vectors(passages: list[str]) -> np.ndarray:
    from .llm import embed
    hs = [hashlib.sha1(p.encode()).hexdigest() for p in passages]
    con = _con()
    have = {h: np.frombuffer(v, dtype=np.float32) for h, v in
            con.execute(f"SELECT h, v FROM vec WHERE h IN ({','.join('?' * len(hs))})", hs)}
    missing = [i for i, h in enumerate(hs) if h not in have]
    if missing:
        new = np.array(embed(ROLES["embedder"][0], [f"search_document: {passages[i]}" for i in missing]),
                       dtype=np.float32)
        new /= np.linalg.norm(new, axis=1, keepdims=True)
        con.executemany("INSERT OR REPLACE INTO vec VALUES (?,?)", [(hs[i], new[j].tobytes())
                                                                    for j, i in enumerate(missing)])
        con.commit()
        for j, i in enumerate(missing):
            have[hs[i]] = new[j]
    con.close()
    return np.stack([have[h] for h in hs])


def retrieve(text: str, query: str, k: int = 4) -> list[tuple[int, str]]:
    """Return the top k passages of one page for a question, as (passage number, text) pairs."""
    from .llm import embed
    ps = chunk(text)
    if not ps:
        return []
    lex = BM25(ps).scores(query)
    by_lex = sorted(range(len(ps)), key=lambda i: -lex[i])
    try:
        q = np.array(embed(ROLES["embedder"][0], [f"search_query: {query}"])[0], dtype=np.float32)
        dense = _vectors(ps) @ (q / np.linalg.norm(q))
        order = rrf([sorted(range(len(ps)), key=lambda i: -dense[i]), by_lex])
    except Exception:  # no embedding model, so we fall back to BM25 alone
        order = by_lex
    return [(i + 1, ps[i]) for i in order[:k]]
