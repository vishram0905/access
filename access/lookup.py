"""The lookup document: a precomputed local copy of the labelled matrix (end of Layer 0).

Search queries it in milliseconds, which means the rate-limited free-tier model agents only ever see a short
list instead of the whole library. The build writes these files:

data/lookup/
  programs.jsonl      one fully annotated programme per line (the source of truth for search)
  programs.csv        the flat labelled matrix (MATRIX_COLUMNS) for review / Excel
  facets.json         inverted indexes: value -> programme ids, per filterable column
  embeddings.npy      one search vector per programme (same row order as ids.json)
  ids.json            programme ids in embedding order
  data_dictionary.md  every column and its allowed values
  meta.json           build time, schema version, counts by region / provider type
"""
import csv
import json
from collections import defaultdict
from datetime import datetime
from functools import lru_cache

import numpy as np

from .config import DATA, ROLES
from .db import all_listings, connect
from .llm import embed
from .schema import DATA_DICTIONARY, MATRIX_COLUMNS, SCHEMA_VERSION

LOOKUP = DATA / "lookup"
FACET_COLUMNS = ["region", "provider_type", "host_country", "host_countries", "host_regions", "host_scope",
                 "opportunity_type", "career_levels", "fields",
                 "status", "nationality_allowed", "nationality_excluded", "targeted_groups", "fully_funded"]


def _rule_values(rules, attr, op=None):
    vals = []
    for r in rules:
        if r["attribute"] == attr and (op is None or r["operator"] == op):
            vals += r["value"] if isinstance(r["value"], list) else [r["value"]]
    return vals


def to_matrix_row(l: dict) -> dict:
    """Flatten one annotated listing into a row of the labelled matrix (one value per MATRIX_COLUMNS column)."""
    f, p, o, rules = l.get("funding") or {}, l.get("process") or {}, l.get("obligations") or {}, l.get("rules", [])
    first = lambda a, op=None: (_rule_values(rules, a, op) or [None])[0]
    review = l.get("review", {})
    return {
        "program_id": l["id"], "name": l["name"], "provider": l.get("provider"),
        "provider_type": l.get("provider_type"), "host_country": l.get("host_country"),
        # Where the programme is held, as lists rather than the catch-all "Multiple"
        # (see scripts/resolve_host_countries.py).
        "host_countries": l.get("host_countries") if "host_countries" in l else
        ([l["host_country"]] if l.get("host_country") not in (None, "", "Multiple") else []),
        "host_regions": l.get("host_regions") or [],
        "host_scope": "anywhere" if l.get("host_anywhere") else "not_stated" if l.get("host_resolved") is False
        else "unresolved" if l.get("host_country") == "Multiple" else "named",
        "region": l.get("region"), "official_url": l.get("url"), "official_source": l.get("official_source"),
        "language_of_page": l.get("language_of_page"),
        "opportunity_type": l.get("opportunity_type") or l.get("type"),
        "career_levels": l.get("career_levels", []), "fields": l.get("fields", []),
        "duration_months": l.get("duration_months"), "number_of_awards": l.get("number_of_awards"),
        "summary": l.get("summary"),
        "fully_funded": f.get("fully_funded"), "stipend_amount": f.get("stipend_amount"),
        "currency": f.get("currency"), "stipend_period": f.get("stipend_period"),
        "covers_tuition": f.get("covers_tuition"), "covers_travel": f.get("covers_travel"),
        "covers_research_costs": f.get("covers_research_costs"), "covers_insurance": f.get("covers_insurance"),
        "nationality_allowed": _rule_values(rules, "nationality", "in"),
        "nationality_excluded": _rule_values(rules, "nationality", "not_in"),
        "residency_required": _rule_values(rules, "residency", "in"),
        "degree_required": first("highest_degree"), "career_stage_required": _rule_values(rules, "career_stage"),
        "max_years_since_phd": first("years_since_phd", "lte"), "max_age": first("age", "lte"),
        "min_ielts": first("ielts"), "min_toefl": first("toefl"), "min_gpa": first("gpa"),
        "min_publications": first("publications"), "min_work_experience_years": first("work_experience_years"),
        "gender": _rule_values(rules, "gender"), "targeted_groups": l.get("targeted_groups", []),
        "conditional_criteria": l.get("conditional_criteria", []),
        "application_cycle": p.get("application_cycle"), "next_deadline": p.get("next_deadline"),
        "deadline_text": p.get("deadline_text"), "status": p.get("status") or l.get("status"),
        "needs_supervisor_or_host": p.get("needs_supervisor_or_host"),
        "proposal_required": p.get("proposal_required"), "references_required": p.get("references_required"),
        "documents_required": p.get("documents_required", []), "application_url": p.get("application_url"),
        "service_bond": o.get("service_bond"), "return_requirement": o.get("return_requirement"),
        "trust": l.get("trust"), "band": l.get("band"), "completeness": l.get("completeness"),
        "rules_count": len(rules), "rules_dropped": len(l.get("rules_dropped", [])),
        "judges": review.get("judges", []), "decision": review.get("decision"),
        "confidence": l.get("confidence"), "annotated_by": l.get("normalized_by"),
        "last_verified": l.get("verified_at") or l.get("fetched_at"), "content_hash": l.get("content_hash"),
        "schema_version": l.get("schema_version", "1.0"),
    }


def search_text(l: dict) -> str:
    return (f'{l["name"]}. {(l.get("opportunity_type") or l.get("type", "")).replace("_", " ")} in '
            f'{l.get("host_country", "")}. For: {", ".join(l.get("career_levels", []))}. '
            f'Fields: {", ".join(l.get("fields", []))}. {l.get("summary", "")}')


def build(progress=print) -> dict:
    """Rebuild every file in data/lookup/ from the searchable records in the database and return the meta block."""
    LOOKUP.mkdir(parents=True, exist_ok=True)
    from .scoring import band_of, bands
    from .config import is_excluded_place
    b = bands()
    with connect() as con:
        listings = [l for l in all_listings(con) if l.get("schema_version") == SCHEMA_VERSION]
    for l in listings:
        l["band"] = band_of(l.get("trust"), b) if l.get("trust") is not None else "medium"
    withheld = [l for l in listings if l["band"] == "low"]
    listings = [l for l in listings if l["band"] != "low"]  # low-trust rows stay in the DB, not in search
    # Only verified records are searchable, meaning every claim we show was confirmed on the official page
    # (see docs/DECISIONS.md, D22). Records not yet claim-checked wait in the database until the critic gets to them.
    status = lambda l: (l.get("verification") or {}).get("status", "unchecked")
    incomplete = [l for l in listings if status(l) == "incomplete"]
    listings = [l for l in listings if status(l) == "verified"]
    listings = [l for l in listings if not is_excluded_place(l)]  # config.EXCLUDED_PLACES: kept in DB, not searchable
    rows = [to_matrix_row(l) for l in listings]
    with open(LOOKUP / "programs.jsonl", "w") as fh:
        for l in listings:
            fh.write(json.dumps(l) + "\n")
    with open(LOOKUP / "programs.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MATRIX_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("; ".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()})
    facets = {c: defaultdict(list) for c in FACET_COLUMNS}
    for r in rows:
        for c in FACET_COLUMNS:
            vals = r.get(c)
            for v in (vals if isinstance(vals, list) else [vals]):
                if v not in (None, ""):
                    facets[c][str(v)].append(r["program_id"])
    (LOOKUP / "facets.json").write_text(json.dumps(facets, indent=1))
    # Stubs are known programmes whose pages we could not read (protected sites). We show them as links only and
    # never match on them.
    with connect() as con:
        try:
            stubs = [dict(r) for r in con.execute("SELECT * FROM stubs")]
        except Exception:
            stubs = []
    with open(LOOKUP / "stubs.jsonl", "w") as fh:
        for st in stubs:
            fh.write(json.dumps(st) + "\n")
    if listings:
        vecs = np.array(embed(ROLES["embedder"][0], [f"search_document: {search_text(l)}" for l in listings]),
                        dtype=np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        np.save(LOOKUP / "embeddings.npy", vecs)
    (LOOKUP / "ids.json").write_text(json.dumps([l["id"] for l in listings]))
    dd = ["# ACCESS data dictionary", f"Schema version {SCHEMA_VERSION}. One row per funding programme.", "",
          "| Column | Meaning |", "|---|---|"]
    dd += [f"| `{c}` | {DATA_DICTIONARY.get(c, '')} |" for c in MATRIX_COLUMNS]
    (LOOKUP / "data_dictionary.md").write_text("\n".join(dd))
    count = lambda c: {k: len(v) for k, v in sorted(facets[c].items(), key=lambda x: -len(x[1]))}
    meta = {"built": datetime.now().isoformat(timespec="seconds"), "schema_version": SCHEMA_VERSION,
            "programmes": len(listings), "withheld_low_trust": len(withheld), "bands": b,
            "verified": sum(status(l) == "verified" for l in listings),
            "awaiting_claim_check": sum(status(l) == "unchecked" for l in listings),
            "withheld_incomplete": len(incomplete),
            "by_band": {k: sum(l["band"] == k for l in listings) for k in ("high", "medium")}, "by_region": count("region"), "by_provider_type": count("provider_type"),
            "by_opportunity_type": count("opportunity_type")}
    (LOOKUP / "meta.json").write_text(json.dumps(meta, indent=1))
    _load.cache_clear()
    progress(f"  ↻ lookup document rebuilt: {len(listings)} programmes")
    return meta


@lru_cache(maxsize=1)
def _load(stamp):
    if not (LOOKUP / "programs.jsonl").exists():
        return [], {}, np.zeros((0, 768), dtype=np.float32), {}
    programs = [json.loads(line) for line in open(LOOKUP / "programs.jsonl")]
    vecs = np.load(LOOKUP / "embeddings.npy") if (LOOKUP / "embeddings.npy").exists() else \
        np.zeros((0, 768), dtype=np.float32)
    facets = json.loads((LOOKUP / "facets.json").read_text())
    meta = json.loads((LOOKUP / "meta.json").read_text())
    if len(vecs) != len(programs):
        raise ValueError("lookup document is mid-rebuild")
    return programs, facets, vecs, meta


_last_good = [None]


def load():
    """Load the lookup document, the fast path for every query.

    We cache it in memory and re-read it when the files' timestamps change, so a long-running process such as
    the web app picks up new programmes after the agents rebuild the document.
    """
    stamp = tuple(round(f.stat().st_mtime, 3) if f.exists() else 0
                  for f in (LOOKUP / "programs.jsonl", LOOKUP / "embeddings.npy", LOOKUP / "meta.json"))
    try:
        _last_good[0] = _load(stamp)
    except (ValueError, OSError):  # caught mid-rebuild, so we keep serving the previous version
        if _last_good[0] is None:
            raise
    return _last_good[0]
