"""Profile builder (Layer 1): turns the form answers and free-text description into a structured profile.

local_profile() is the instant path. We take the form fields as they are and infer research fields from the
description with the local embedding model (no cloud model, no quota, about 10 ms), so eligibility never waits
on a remote service. The user can confirm or correct the inferred fields in the form.
build_profile() asks a cloud model for fields, keywords and a summary. The CLI still uses it.
"""
from functools import lru_cache

import numpy as np

from .config import ROLES
from .llm import call_json, embed
from .schema import FIELDS, LABELS

# We keep every field that scores within this margin of the best one. Descriptions often span two areas
# (say, graph ML for fraud detection) and the single top pick turned out to be noisy.
FIELD_MARGIN = 0.035
MAX_FIELDS = 4

SYSTEM = ("You turn a researcher's self-description into a structured profile for matching them "
          "to funding opportunities. Reply in JSON.")

PROMPT = """Researcher's description of their work and goals:
<<<
{text}
>>>
Known facts: career stage = {stage}; highest degree = {degree}; wants to work in: {targets}.

Return JSON:
{{"fields": list of 1-3 from {fields},
  "keywords": 5-8 specific research keywords,
  "research_summary": 2 sentences in third person describing the research focus,
  "goals": one sentence on what kind of opportunity they want next}}"""


def build_profile(form: dict) -> dict:
    """Ask the profile-builder model for fields, keywords, a summary and goals, on top of the form answers."""
    spec = ROLES["profile_builder"][0]
    data = call_json(spec, SYSTEM, PROMPT.format(
        text=form.get("about", "")[:3000], stage=form.get("career_stage"),
        degree=form.get("highest_degree"), targets=", ".join(form.get("target_countries", [])) or "anywhere",
        fields=FIELDS))
    fields = [f for f in data.get("fields", []) if f in FIELDS and f != "any"] or ["any"]
    profile = {
        "name": form.get("name") or "Researcher",
        "nationality": form.get("nationality"),
        "residency": form.get("residency") or form.get("nationality"),
        "career_stage": form.get("career_stage"),
        "highest_degree": form.get("highest_degree"),
        "years_since_phd": form.get("years_since_phd"),
        "age": form.get("age"),
        "ielts": form.get("ielts"),
        "publications": form.get("publications"),
        "gpa": form.get("gpa"),
        "target_countries": form.get("target_countries", []),
        "wanted_types": form.get("wanted_types", []),
        "fields": fields,
        "keywords": data.get("keywords", [])[:8],
        "research_summary": data.get("research_summary") or form.get("about", "")[:300],
        "goals": data.get("goals", ""),
        "built_by": spec.label,
    }
    return profile


def search_query(profile: dict) -> str:
    """Turn a profile into the query text we embed and match against programme descriptions."""
    types = ", ".join(t.replace("_", " ") for t in profile.get("wanted_types", []))
    where = ", ".join(profile.get("target_countries", []))
    return (f'{profile["research_summary"]} Keywords: {", ".join(profile["keywords"])}. '
            f'Looking for: {types or "funding"} {("in " + where) if where else ""}. {profile["goals"]}')


@lru_cache(maxsize=1)
def _field_vectors():
    # We cache the field label vectors: they never change, and embedding them on every search is wasted work.
    labels = [f for f in FIELDS if f != "any"]
    v = np.array(embed(ROLES["embedder"][0], [f"Research field: {LABELS[f]}" for f in labels]), dtype=np.float32)
    return labels, v / np.linalg.norm(v, axis=1, keepdims=True)


def infer_fields(text: str) -> list[str]:
    """Suggest research fields for a description using local embeddings. Returns ['any'] if there is no text."""
    if not (text or "").strip():
        return ["any"]
    try:
        labels, vecs = _field_vectors()
        q = np.array(embed(ROLES["embedder"][0], [text[:3000]])[0], dtype=np.float32)
    except Exception:  # local model unavailable, and we would rather not guess
        return ["any"]
    sims = vecs @ (q / np.linalg.norm(q))
    top = float(sims.max())
    order = [int(i) for i in np.argsort(-sims) if sims[i] >= top - FIELD_MARGIN]
    return [labels[i] for i in order[:MAX_FIELDS]]


def local_profile(form: dict) -> dict:
    """Build the profile for the instant path. Nothing here calls a cloud model, so the result is deterministic."""
    about = (form.get("about") or "").strip()
    return {
        "name": form.get("name") or "Researcher",
        "nationality": form.get("nationality"),
        "residency": form.get("residency") or form.get("nationality"),
        "career_stage": form.get("career_stage"),
        "highest_degree": form.get("highest_degree"),
        "years_since_phd": form.get("years_since_phd"),
        "age": form.get("age"), "ielts": form.get("ielts"), "publications": form.get("publications"),
        "gpa": form.get("gpa"), "work_experience_years": form.get("work_experience_years"),
        "target_countries": form.get("target_countries", []), "wanted_types": form.get("wanted_types", []),
        "fields": form.get("fields") or infer_fields(about),
        "keywords": [], "research_summary": about[:600], "goals": "",
        "built_by": "form + local field inference",
    }
