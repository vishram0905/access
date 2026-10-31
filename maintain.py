"""Keeps the library current after it is built (Layer 0 maintenance).

We re-check each provider type on its own schedule. A page whose content fingerprint has not changed costs nothing.
A changed page goes back through the Annotator, condensed to its templated sections when we have a template, and
then through the Info Critic panel. Pages that no longer answer are retired from search.

  python maintain.py            # check everything that is due
  python maintain.py --report   # coverage report by provider type and region
"""
import json
import sys
from datetime import datetime, timedelta, timezone

from access import templates
from access.db import connect, fingerprint, log_check, now
from access.discover import polite_get
from access.harvester import page_text
from access.lookup import build as build_lookup

# Days between checks for each provider type: weekly for universities and industry, monthly for intergovernmental.
SCHEDULE = {"university": 7, "industry": 7, "foundation_charity": 14, "government": 14,
            "research_institute": 14, "intergovernmental": 30}


def due(provider_type: str, last_checked: str | None) -> bool:
    if not last_checked:
        return True
    last = datetime.fromisoformat(last_checked)
    return datetime.now(timezone.utc) - last > timedelta(days=SCHEDULE.get(provider_type or "", 14))


def check(progress=print):
    """Re-fetch every verified page that is due and queue the changed ones for annotation and judging again."""
    templates.build()
    counts = {"unchanged": 0, "changed": 0, "moved": 0, "gone": 0}
    with connect() as con:
        rows = con.execute("SELECT url, provider_type, last_checked, content_hash FROM sources "
                           "WHERE status IN ('active','rejected')").fetchall()
    rows = [r for r in rows if due(r["provider_type"], r["last_checked"])]
    progress(f"{len(rows)} verified pages are due for a check")
    for r in rows:
        resp = polite_get(r["url"])
        with connect() as con:
            if not resp:
                con.execute("UPDATE sources SET status='gone', last_checked=? WHERE url=?", (now(), r["url"]))
                con.execute("UPDATE listings SET decision='gone' WHERE source_url=?", (r["url"],))
                log_check(con, r["url"], "gone")
                counts["gone"] += 1
                continue
            title, text = page_text(resp.text)
            h = fingerprint(text)
            moved = resp.url.rstrip("/") != r["url"].rstrip("/")
            if h == r["content_hash"]:
                con.execute("UPDATE sources SET last_checked=? WHERE url=?", (now(), r["url"]))
                log_check(con, r["url"], "moved" if moved else "unchanged", resp.url if moved else "")
                counts["moved" if moved else "unchanged"] += 1
                continue
            condensed, matched = templates.extract_sections(text, r["url"])
            con.execute("UPDATE sources SET status='candidate', text=?, title=?, content_hash=?, last_checked=?, "
                        "last_changed=?, attempts=0, annotation=NULL WHERE url=?",
                        (condensed if matched else text[:30000], title[:250], h, now(), now(), r["url"]))
            log_check(con, r["url"], "changed", "template matched" if matched else "template did not match")
            counts["changed"] += 1
    progress(f"Done: {counts}. Changed pages are queued for the Annotator and Info Critic agents.")
    build_lookup(progress)


def report():
    with connect() as con:
        rows = con.execute("SELECT json_extract(data,'$.provider_type') pt, json_extract(data,'$.region') rg, "
                           "COUNT(*) n, AVG(json_extract(data,'$.confidence')) conf, "
                           "SUM(json_array_length(json_extract(data,'$.rules'))>0) with_rules, "
                           "SUM(json_extract(data,'$.process.next_deadline') IS NOT NULL) with_deadline "
                           "FROM listings WHERE decision NOT IN ('rejected','gone') AND data LIKE '%\"schema_version\": \"2.0\"%' "
                           "GROUP BY pt, rg ORDER BY pt, n DESC").fetchall()
    print(f"{'provider type':<20}{'region':<15}{'programmes':>11}{'with rules':>12}{'with deadline':>15}{'confidence':>12}")
    for r in rows:
        print(f"{r['pt'] or '-':<20}{r['rg'] or '-':<15}{r['n']:>11}{r['with_rules']:>12}{r['with_deadline']:>15}"
              f"{(r['conf'] or 0):>12.2f}")
    t = templates.build()
    print(f"\nScrape templates: {len(t)} sites; sections learnt for "
          f"{sum(bool(x['sections']) for x in t.values())} of them.")


if __name__ == "__main__":
    report() if "--report" in sys.argv else check()
