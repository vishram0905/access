"""Connectors to open funding databases (Layer 0, library building).

We use these only as a discovery index. From them we take facts, the programme names and official links, and
then annotate and verify every programme from its own official page rather than copying the database's text.
We use Wikidata (CC0) for scholarships with an official website and grants.gov (public domain) for US federal
opportunities open to individuals. We chose not to use commercial aggregators.
"""
import json
import time
from urllib.parse import urlparse

import requests

from .db import connect, fingerprint, now
from .harvester import UA
from .hubs import REGION_PRIORITY, site_priority

REGION = {
    "United States of America": "North America", "Canada": "North America", "Mexico": "North America",
    "United Kingdom": "Europe", "Germany": "Europe", "France": "Europe", "Netherlands": "Europe",
    "Switzerland": "Europe", "Sweden": "Europe", "Norway": "Europe", "Denmark": "Europe", "Finland": "Europe",
    "Ireland": "Europe", "Italy": "Europe", "Spain": "Europe", "Portugal": "Europe", "Belgium": "Europe",
    "Austria": "Europe", "Poland": "Europe", "Czech Republic": "Europe", "Hungary": "Europe", "Greece": "Europe",
    "Singapore": "Asia", "Japan": "Asia", "People's Republic of China": "Asia", "South Korea": "Asia",
    "India": "Asia", "Hong Kong": "Asia", "Malaysia": "Asia", "Indonesia": "Asia",
    "Thailand": "Asia", "Vietnam": "Asia", "Philippines": "Asia", "Pakistan": "Asia", "Bangladesh": "Asia",
    "Israel": "Asia", "Saudi Arabia": "Asia", "United Arab Emirates": "Asia", "Qatar": "Asia", "Turkey": "Asia",
    "Australia": "Asia-Pacific", "New Zealand": "Asia-Pacific",
    "Brazil": "South America", "Chile": "South America", "Argentina": "South America",
    "Colombia": "South America", "Peru": "South America", "Ecuador": "South America", "Uruguay": "South America",
}

WIKIDATA_QUERY = """SELECT ?item ?itemLabel ?site ?countryLabel WHERE {
  ?item wdt:P31 wd:Q618779 ; wdt:P856 ?site .
  OPTIONAL { ?item wdt:P17 ?country }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} LIMIT %d OFFSET %d"""


def wikidata_sites(progress=print, page: int = 1000) -> int:
    """Add Wikidata scholarships with official websites to the Scout's site database."""
    from .agents import guess_provider_type
    added, offset = 0, 0
    while True:
        try:
            r = requests.get("https://query.wikidata.org/sparql", timeout=90,
                             params={"query": WIKIDATA_QUERY % (page, offset)},
                             headers={**UA, "Accept": "application/sparql-results+json"})
            rows = r.json()["results"]["bindings"]
        except Exception as e:
            progress(f"  wikidata page at offset {offset} failed: {str(e)[:80]}")
            break
        if not rows:
            break
        with connect() as con:
            for b in rows:
                url = b["site"]["value"]
                country = b.get("countryLabel", {}).get("value", "")
                region = REGION.get(country, "Global")
                dom = urlparse(url).netloc
                if not dom:
                    continue
                cur = con.execute(
                    "INSERT OR IGNORE INTO sites (url, domain, publisher, region, country, provider_type, found_via, "
                    "depth, priority, status, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (url, dom, b["itemLabel"]["value"][:100], region, country, guess_provider_type(dom),
                     "wikidata", 1, site_priority(region, country, 1, guess_provider_type(dom), url), "new", now()))
                added += cur.rowcount
        progress(f"  wikidata: {offset + len(rows)} scholarships read, {added} new sites")
        offset += page
        time.sleep(2)
    return added


def grants_gov(progress=print, rows: int = 250) -> int:
    """Add US federal opportunities that individuals can apply for (fellowships, scholarships, training).

    The API gives structured text, so these go straight into sources as candidates with a fixed score of 6.
    """
    added = 0
    for kw in ("fellowship", "scholarship", "graduate", "postdoctoral", "training grant"):
        try:
            hits = requests.post("https://api.grants.gov/v1/api/search2", timeout=60,
                                 json={"keyword": kw, "rows": rows, "oppStatuses": "forecasted|posted"}
                                 ).json()["data"]["oppHits"]
        except Exception as e:
            progress(f"  grants.gov '{kw}' failed: {str(e)[:80]}")
            continue
        for h in hits:
            url = f"https://www.grants.gov/search-results-detail/{h['id']}"
            with connect() as con:
                if con.execute("SELECT 1 FROM sources WHERE url=?", (url,)).fetchone():
                    continue
            try:
                d = requests.post("https://api.grants.gov/v1/api/fetchOpportunity", timeout=60,
                                  json={"opportunityId": int(h["id"])}).json().get("data", {})
            except Exception:
                continue
            syn = d.get("synopsis") or d.get("forecast") or {}
            text = "\n".join(str(x) for x in (
                d.get("opportunityTitle"), f"Agency: {h.get('agency')}", f"Close date: {h.get('closeDate')}",
                syn.get("synopsisDesc") or syn.get("forecastDesc"), syn.get("applicantEligibilityDesc"),
                f"Award ceiling: {syn.get('awardCeiling')}", f"Award floor: {syn.get('awardFloor')}",
                f"Eligible applicants: {[a.get('description') for a in syn.get('applicantTypes', [])]}",
                syn.get("fundingDescLinkUrl")) if x)
            if len(text) < 400:
                continue
            with connect() as con:
                cur = con.execute(
                    "INSERT OR IGNORE INTO sources (url, domain, name, found_via, official, status, priority, title, "
                    "text, content_hash, http_status, first_seen, last_checked, region, country, publisher, "
                    "provider_type, score) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (url, "grants.gov", d.get("opportunityTitle", "")[:200], "api:grants.gov", 1, "candidate",
                     site_priority("North America", "United States", 0, "government") * 10 - 6,
                     d.get("opportunityTitle", "")[:250], text[:30000], fingerprint(text), 200, now(), now(),
                     "North America", "United States", h.get("agency"), "government", 6))
                added += cur.rowcount
            time.sleep(0.5)
        progress(f"  grants.gov '{kw}': {added} opportunities added so far")
    return added


if __name__ == "__main__":
    print("Wikidata:", wikidata_sites())
    print("grants.gov:", grants_gov())
