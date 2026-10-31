"""Lexical retrieval (BM25) and rank fusion (RRF) for Layer 2 matching.

We implement both straight from the formulas so the project needs no extra search dependency.

BM25 (Robertson & Zaragoza, 2009) scores a document d for a query q as

    score(d, q) = sum over query terms t of  IDF(t) * f(t,d) * (k1 + 1) / (f(t,d) + k1 * (1 - b + b * |d| / avgdl))
    IDF(t)      = ln(1 + (N - n(t) + 0.5) / (n(t) + 0.5))

f(t,d) = term frequency, |d| = document length, avgdl = average length, N = documents, n(t) = documents containing
t. k1 controls term-frequency saturation, b controls length normalisation (standard values 1.2-2.0 and 0.75).

Reciprocal Rank Fusion (Cormack, Clarke & Buettcher, 2009) merges ranked lists without needing comparable scores:

    RRF(d) = sum over rankers r of 1 / (k + rank_r(d)),   k = 60

Dense retrieval matches meaning ("plastic-eating enzymes" ~ "biodegradation"); BM25 matches exact terms ("SINGA",
"Chevening", "cryo-EM"). We fuse the two so that each covers the other's blind spot.
"""
import math
import re
from collections import Counter

STOP = set("a an the and or of for to in on at by with from as is are be this that it its into your you we our their "
           "i my me am will can who what which how all any not no".split())


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower().replace("_", " ")) if t not in STOP and len(t) > 1]


class BM25:
    """Okapi BM25 over a fixed list of documents. We compute the IDF table once, when the index is built."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokens(d)) for d in docs]
        self.lens = [sum(c.values()) for c in self.docs]
        self.avgdl = sum(self.lens) / max(1, len(self.lens))
        df = Counter(t for c in self.docs for t in c)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - m + 0.5) / (m + 0.5)) for t, m in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for c, dl in zip(self.docs, self.lens):
            s = 0.0
            for t in q:
                f = c.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append(s)
        return out


def rrf(rankings: list[list], k: int = 60, weights: list[float] | None = None) -> list:
    """Fuse several rankings (lists of ids, best first) into one. weights scale each ranker's contribution."""
    score = Counter()
    for ranking, w in zip(rankings, weights or [1.0] * len(rankings)):
        for r, doc in enumerate(ranking, 1):
            score[doc] += w / (k + r)
    return [d for d, _ in score.most_common()]


# We picked these weights with the known-item benchmark (access/bench.py, 100 queries, results in
# data/eval/results.json). BM25 weighted 2:1 over dense is statistically tied with BM25 alone at rank 1
# (MRR 0.786 vs 0.794) and finds more programmes in the top 5 (recall@5 0.930 vs 0.880). Equal weights lost
# precision at rank 1.
FUSION_WEIGHTS = {"dense": 1.0, "bm25": 2.0}
