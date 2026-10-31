"""Replace the catch-all host_country "Multiple" with the actual list of countries (tooling, Layer 0).

"Multiple" mixed three different cases: programmes held in one country (an annotator shortcut), bilateral
programmes (two named countries) and programmes that really are open to any destination. Search had to treat it as
a wildcard, so every such programme matched every country filter. Each record gets:
  host_countries: [..]   countries where the funded activity takes place
  host_regions:   [..]   a named region instead (e.g. "EU member states" -> Europe), from the fixed region list
  host_anywhere:  bool   the page says recipients may go to any country / worldwide
  host_evidence:  quote  sentence from the page that supports it (must be found on the page, else unresolved)
We run the extraction with the annotator's model family (Google), never one of the judges, so the judges stay
independent when check_host_claims.py verifies the result.

Run: PYTHONPATH=. python scripts/resolve_host_countries.py
"""
import json
import re

from access.config import ROLES
from access.db import connect
from access.llm import LLMError, call_json, set_role
from access.schema import COUNTRY_ALIASES, COUNTRY_REGION, region_of

REGIONS = ["Europe", "Asia", "Asia-Pacific", "North America", "South America", "Middle East", "Africa"]
REGION_SYNONYMS = {"East Asia": "Asia", "South Asia": "Asia", "Southeast Asia": "Asia", "Latin America": "South America",
                   "European Union": "Europe", "EU": "Europe", "Oceania": "Asia-Pacific", "MENA": "Middle East", "ASEAN": "Asia"}

SYSTEM = "You read official funding programme pages and report facts exactly as the page states them. Reply in JSON."
PROMPT = """Programme: {name}
Provider: {provider}

PAGE:
<<<
{text}
>>>

Where does the funded activity take place, i.e. in which country or countries do recipients study, do research
or work? A named host university or institute implies its country. If the page names a region or group of
countries instead (e.g. "EU member states and associated countries"), give the region from this list:
{regions}. "anywhere" is true ONLY if the page says recipients may choose any country / go worldwide; moving to
"another country" or "abroad" within a named region is that region, not anywhere. Answer from the page only.
JSON: {{"countries": ["full English country names"], "regions": [], "anywhere": false,
"quote": "the supporting words copied EXACTLY, character for character, from the page (one sentence or less)"}}
If the page does not say, return {{"countries": [], "regions": [], "anywhere": false, "quote": ""}}."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def resolve(listing: dict, text: str) -> dict:
    """Ask the model where the programme is held and accept the answer only if its quote is found on the page."""
    d = call_json(ROLES["normalizer"][0], SYSTEM, PROMPT.format(
        name=listing.get("name", ""), provider=listing.get("provider", ""), text=text[:9000],
        regions=", ".join(REGIONS)))
    quote = (d.get("quote") or "").strip()
    # A paraphrased quote fails this test, but a quote whose tail was cut off still passes.
    grounded = len(quote) >= 12 and _norm(quote)[:120] in _norm(text)
    countries = sorted({COUNTRY_ALIASES.get(c.strip(), c.strip()) for c in d.get("countries") or [] if c.strip()})
    named = [REGION_SYNONYMS.get(x, x) for x in (d.get("regions") or []) + countries]
    countries = [c for c in countries if REGION_SYNONYMS.get(c, c) not in REGIONS]  # region names are not countries
    # We keep a named region even next to countries in it: "ASEAN, China, India" is wider than China plus India.
    # Too wide is the safer mistake, because too narrow would hide a programme from someone it fits.
    regions = sorted({x for x in named if x in REGIONS})
    if not grounded or not (countries or regions or d.get("anywhere")):
        return {"host_countries": [], "host_regions": [], "host_anywhere": False, "host_evidence": None,
                "host_resolved": False}
    return {"host_countries": countries, "host_regions": regions, "host_anywhere": bool(d.get("anywhere")),
            "host_evidence": quote, "host_resolved": True}


def label(r: dict) -> str:
    if r["host_anywhere"]:
        return "Any country"
    if not r["host_resolved"]:
        return "Not stated"
    return ", ".join(r["host_countries"] + r["host_regions"])


def main():
    """Resolve every "Multiple" record not yet processed and write the new host fields back to the database."""
    set_role("critic")
    with connect() as con:
        rows = con.execute("SELECT l.id, l.data, s.text FROM listings l JOIN sources s ON s.url = l.source_url "
                           "WHERE json_extract(l.data, '$.host_country') = 'Multiple' "
                           "AND json_extract(l.data, '$.host_resolved') IS NULL").fetchall()
    print(len(rows), "records to resolve", flush=True)
    tally = {"one": 0, "several": 0, "anywhere": 0, "unresolved": 0}
    for row in rows:
        listing = json.loads(row["data"])
        try:
            r = resolve(listing, row["text"] or "")
        except LLMError as e:
            print("! stopped:", str(e)[:150], flush=True)
            break
        listing.update(r, host_country_was="Multiple", host_country=label(r))
        listing["region"] = region_of(listing)
        key = ("anywhere" if r["host_anywhere"] else "unresolved" if not r["host_resolved"]
               else "region" if r["host_regions"] else "one" if len(r["host_countries"]) == 1 else "several")
        tally[key] = tally.get(key, 0) + 1
        with connect() as con:
            con.execute("UPDATE listings SET data = ? WHERE id = ?", (json.dumps(listing), row["id"]))
        print(f'{key:<10} {listing["host_country"][:40]:<40} {listing["name"][:50]}', flush=True)
    print("TALLY", tally, flush=True)


if __name__ == "__main__":
    main()
