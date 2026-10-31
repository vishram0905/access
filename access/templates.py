"""Per-site scrape templates (Layer 0, library building).

A template records which page headings hold each field on a given site, for example that eligibility sits
under "Who can apply". We build them from the Annotator's sections output. When a page changes we send only
those sections to the Annotator, which is faster on the free model tiers, and a template that no longer
matches tells us the site's layout has changed.
"""
import json
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

from .db import all_listings, connect
from .lookup import LOOKUP

TEMPLATE_FILE = LOOKUP / "scrape_templates.json"
FIELDS = ("eligibility", "funding", "deadline", "how_to_apply")


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (h or "").lower().replace("​", "")).strip()


def build() -> dict:
    """Rebuild the templates from all v2 listings, keeping the four most common headings per field and site."""
    with connect() as con:
        rows = [l for l in all_listings(con) if l.get("schema_version") == "2.0"]
    by_site = defaultdict(list)
    for l in rows:
        by_site[urlparse(l["url"]).netloc].append(l)
    templates = {}
    for domain, ls in by_site.items():
        sections = {f: Counter(_norm(l.get("sections", {}).get(f)) for l in ls if l.get("sections", {}).get(f))
                    for f in FIELDS}
        templates[domain] = {
            "provider_type": Counter(l.get("provider_type") for l in ls).most_common(1)[0][0],
            "region": Counter(l.get("region") for l in ls).most_common(1)[0][0],
            "pages": len(ls),
            "sections": {f: [h for h, _ in c.most_common(4)] for f, c in sections.items() if c},
            "coverage": {
                "rules": round(sum(bool(l.get("rules")) for l in ls) / len(ls), 2),
                "deadline": round(sum(bool((l.get("process") or {}).get("next_deadline")) for l in ls) / len(ls), 2),
                "funding_amount": round(sum((l.get("funding") or {}).get("stipend_amount") is not None
                                            for l in ls) / len(ls), 2),
                "documents": round(sum(bool((l.get("process") or {}).get("documents_required")) for l in ls) / len(ls), 2),
            },
        }
    LOOKUP.mkdir(parents=True, exist_ok=True)
    TEMPLATE_FILE.write_text(json.dumps(templates, indent=1))
    return templates


def load() -> dict:
    return json.loads(TEMPLATE_FILE.read_text()) if TEMPLATE_FILE.exists() else {}


def extract_sections(text: str, url: str, keep_intro: int = 2500) -> tuple[str, bool]:
    """Cut a page down to its intro and templated sections. Returns (text, template_matched)."""
    t = load().get(urlparse(url).netloc)
    if not t or not t.get("sections"):
        return text, False
    lines = text.splitlines()
    heads = {h for hs in t["sections"].values() for h in hs}
    starts = [i for i, ln in enumerate(lines) if _norm(ln) in heads]
    if not starts:
        return text, False  # none of the known headings are there, so the layout has probably changed
    blocks = [text[:keep_intro]]
    for i in starts:
        blocks.append("\n".join(lines[i:i + 40]))
    return "\n...\n".join(blocks)[:12000], True
