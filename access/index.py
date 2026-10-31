"""Vector index over the listings file (Layer 0) and a plain semantic search over it.

We embed each listing once with the local embedder and store unit vectors, so a search is one query embedding
and a dot product. The main app searches the lookup document through access/search.py instead.
"""
import json

import numpy as np

from .config import INDEX_FILE, LISTINGS_FILE, ROLES
from .llm import embed


def listing_text(l: dict) -> str:
    return (f'{l["name"]}. {l["type"].replace("_", " ")} in {l["host_country"]}. '
            f'Fields: {", ".join(l["fields"])}. {l["summary"]}')


def build_index(listings: list[dict]) -> None:
    spec = ROLES["embedder"][0]
    vecs = np.array(embed(spec, [f"search_document: {listing_text(l)}" for l in listings]), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    np.savez(INDEX_FILE, vecs=vecs, ids=np.array([l["id"] for l in listings]))


def load_listings() -> list[dict]:
    return json.loads(LISTINGS_FILE.read_text()) if LISTINGS_FILE.exists() else []


def search(query: str, k: int = 20) -> list[tuple[str, float]]:
    spec = ROLES["embedder"][0]
    data = np.load(INDEX_FILE)
    q = np.array(embed(spec, [f"search_query: {query}"])[0], dtype=np.float32)
    q /= np.linalg.norm(q)
    sims = data["vecs"] @ q
    order = np.argsort(-sims)[:k]
    return [(str(data["ids"][i]), float(sims[i])) for i in order]
