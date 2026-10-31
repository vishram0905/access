"""The Annotator, also called the Normalizer (Layer 0, library building).

It turns one programme page into one fully annotated row of the labelled matrix (schema v2). Each row keeps
verbatim evidence and the page sections each field came from; templates.py uses those sections to build the
per-site scrape template. The model output is cleaned against the closed vocabularies in schema.py, so a value
outside them is dropped or replaced by a default rather than stored.
"""
import re
from datetime import date

from .config import ROLES
from .llm import call_json
from .schema import (ANNOTATION_SPEC, APPLICATION_CYCLES, ATTRIBUTES, CAREER_STAGES, FIELDS,
                     OPPORTUNITY_TYPES, PROVIDER_TYPES, REGIONS, SCHEMA_VERSION, STATUSES, TARGETED_GROUPS)

SYSTEM = ("You annotate research funding programmes for a database. Be literal: record only what the page "
          "states, use null when the page does not say, and never invent eligibility rules. Reply with one JSON object.")

PROMPT = """Programme (from the page title): {name}
Page URL: {url}

Page text:
<<<
{text}
>>>

{spec}"""


def _pick(v, allowed, default):
    return v if v in allowed else default


def _list(v, allowed=None):
    v = v if isinstance(v, list) else ([] if v in (None, "") else [v])
    return [x for x in v if allowed is None or x in allowed]


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _date(v):
    return v if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None


def _clean_rules(rules) -> list[dict]:
    """Keep only rules whose attribute, operator and value fit the schema, and number them r1, r2, ..."""
    out = []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        attr, op = r.get("attribute"), r.get("operator")
        if attr not in ATTRIBUTES or op not in ATTRIBUTES[attr][0]:
            continue
        val = r.get("value")
        if op in ("in", "not_in"):
            val = val if isinstance(val, list) else [val]
            if attr == "field":
                val = [v for v in val if v in FIELDS] or None
            elif attr == "career_stage":
                val = [v for v in val if v in CAREER_STAGES] or None
        elif attr == "highest_degree" and op == "gte":
            val = val if val in ("bachelors", "masters", "phd") else None
        else:
            val = _num(val)
        if val is None:
            continue
        out.append({"attribute": attr, "operator": op, "value": val, "hard": ATTRIBUTES[attr][1],
                    "evidence": str(r.get("evidence", ""))[:300]})
    for i, r in enumerate(out):
        r["id"] = f"r{i + 1}"
    return out


def validate(row: dict) -> list[str]:
    """Run consistency checks on an annotation and return the problems found. An empty list means it passed."""
    issues = []
    p = row["process"]
    if p.get("next_deadline") and p["next_deadline"] < date.today().isoformat() and p.get("status") == "open":
        issues.append("deadline in the past but status is open")
    f = row["funding"]
    if f.get("stipend_amount") is not None and not f.get("currency"):
        issues.append("stipend amount without currency")
    if row["opportunity_type"] == "postdoc_fellowship" and "undergraduate" in row["career_levels"]:
        issues.append("postdoc fellowship listed for undergraduates")
    return issues


def normalize(raw: dict, spec=None, system: str | None = None) -> dict:
    """Annotate one raw page and return the cleaned row.

    By default the Annotator's model and system prompt are used. The Auditor passes its own model (spec) and a
    different system prompt (system), so its annotation is made independently of the first one.
    """
    spec = spec or ROLES["normalizer"][0]
    d = call_json(spec, system or SYSTEM, PROMPT.format(name=raw["name"], url=raw["url"],
                                              text=raw["text"][:20000], spec=ANNOTATION_SPEC))
    funding, process, oblig = d.get("funding") or {}, d.get("process") or {}, d.get("obligations") or {}
    fields = _list(d.get("fields"), FIELDS) or ["any"]
    otype = _pick(d.get("opportunity_type"), OPPORTUNITY_TYPES, "research_grant")
    row = {
        "id": raw["id"],
        "schema_version": SCHEMA_VERSION,
        "page_kind": _pick(d.get("page_kind"), ["single_opportunity", "list_of_opportunities", "other"],
                           "single_opportunity"),
        "about_programme": bool(d.get("about_programme", True)),
        "name": d.get("name") or raw["name"],
        "provider": d.get("provider") or "",
        "provider_type": _pick(d.get("provider_type"), PROVIDER_TYPES, "government"),
        # Where the programme is held. We store explicit lists rather than a catch-all "Multiple", because
        # matching needs the actual countries; host_country is only the label we display.
        "host_countries": _list(d.get("host_countries")),
        "host_regions": [r for r in _list(d.get("host_regions")) if r in REGIONS],
        "host_anywhere": bool(d.get("host_anywhere")),
        "host_country": ("Any country" if d.get("host_anywhere") else
                         ", ".join(_list(d.get("host_countries")) + _list(d.get("host_regions")))
                         or d.get("host_country") or "Not stated"),
        "host_institutions": _list(d.get("host_institutions"))[:8],
        "language_of_page": d.get("language_of_page") or "",
        "opportunity_type": otype,
        "type": otype,  # alias used by the gate, ranker and UI
        "career_levels": _list(d.get("career_levels"), CAREER_STAGES),
        "fields": fields,
        "summary": d.get("summary") or "",
        "duration_months": _num(d.get("duration_months")),
        "number_of_awards": _num(d.get("number_of_awards")),
        "funding": {
            "fully_funded": funding.get("fully_funded"),
            "stipend_amount": _num(funding.get("stipend_amount")),
            "currency": (funding.get("currency") or None),
            "stipend_period": _pick(funding.get("stipend_period"), ["month", "year", "total"], None),
            "covers_tuition": funding.get("covers_tuition"), "covers_travel": funding.get("covers_travel"),
            "covers_research_costs": funding.get("covers_research_costs"),
            "covers_insurance": funding.get("covers_insurance"),
            "other_benefits": funding.get("other_benefits"), "evidence": funding.get("evidence"),
        },
        "rules": _clean_rules(d.get("rules")),
        "conditional_criteria": [str(c)[:250] for c in _list(d.get("conditional_criteria"))][:6],
        "targeted_groups": [g for g in _list(d.get("targeted_groups"), TARGETED_GROUPS) if g != "none"],
        "process": {
            "application_cycle": _pick(process.get("application_cycle"), APPLICATION_CYCLES, "unclear"),
            "next_deadline": _date(process.get("next_deadline")),
            "deadline_text": process.get("deadline_text"),
            "opens": _date(process.get("opens")),
            "status": _pick(process.get("status"), STATUSES, "unclear"),
            "needs_supervisor_or_host": process.get("needs_supervisor_or_host"),
            "proposal_required": process.get("proposal_required"),
            "references_required": _num(process.get("references_required")),
            "documents_required": [str(x)[:120] for x in _list(process.get("documents_required"))][:10],
            "application_url": process.get("application_url"),
            "evidence": process.get("evidence"),
        },
        "obligations": {"service_bond": oblig.get("service_bond"),
                        "return_requirement": oblig.get("return_requirement"), "text": oblig.get("text")},
        "sections": {k: v for k, v in (d.get("sections") or {}).items()
                     if k in ("eligibility", "funding", "deadline", "how_to_apply") and v},
        "url": raw["url"],
        "official_source": raw.get("official_source", False),
        "fetched_at": raw.get("fetched_at"),
        "normalized_by": spec.label,
    }
    # Flat convenience fields that the UI reads directly.
    row["deadline"] = row["process"]["deadline_text"] or row["process"]["next_deadline"]
    row["funding_text"] = row["funding"]["other_benefits"]
    row["status"] = row["process"]["status"]
    row["validation_issues"] = validate(row)
    return row
