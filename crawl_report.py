"""Crawl report from the fetch log (tooling).

We use this to see how many sites answered us, how many refused and why, and what happened to each stored page
further down the pipeline, from the keyword filter through annotation and judging to the published search.

  python crawl_report.py           # print the report (also saved to data/lookup/crawl_report.json)
  python crawl_report.py --csv     # also export every logged request to data/lookup/fetch_log.csv
"""
import csv
import json
import sqlite3
import sys
from collections import Counter

from access import fetchlog
from access.db import connect
from access.lookup import LOOKUP


def build() -> dict:
    """Collect the request counts and the page funnel into one dict and save it as crawl_report.json."""
    fetchlog.flush()
    lc = fetchlog._con()
    rows = lc.execute("SELECT outcome, domain FROM fetches").fetchall()
    first = lc.execute("SELECT MIN(at) FROM fetches").fetchone()[0]
    with connect() as con:
        dom_meta = {r["domain"]: (r["region"], r["provider_type"]) for r in con.execute(
            "SELECT domain, region, provider_type FROM sites")}
        pages = dict(con.execute("SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall())
        sites = dict(con.execute("SELECT status, COUNT(*) FROM sites GROUP BY status").fetchall())
        fail = dict(con.execute("SELECT fail_reason, COUNT(*) FROM sites WHERE fail_reason IS NOT NULL "
                                "GROUP BY fail_reason").fetchall()) if "fail_reason" in {
            r[1] for r in con.execute("PRAGMA table_info(sites)")} else {}
        reasons = Counter()
        for r in con.execute("SELECT data FROM listings WHERE decision IN ('rejected')"):
            reasons[json.loads(r[0]).get("review", {}).get("reason", "unspecified")] += 1
        decisions = dict(con.execute("SELECT decision, COUNT(*) FROM listings WHERE data LIKE "
                                     "'%\"schema_version\": \"2.0\"%' GROUP BY decision").fetchall())
        try:
            stubs = con.execute("SELECT COUNT(*) FROM stubs").fetchone()[0]
        except sqlite3.OperationalError:
            stubs = 0

    by_outcome = Counter(o for o, _ in rows)
    hs = sum(by_outcome[o] for o in fetchlog.HANDSHAKE)
    by_region, by_ptype = {}, {}
    for o, d in rows:
        reg, pt = dom_meta.get(d, ("unknown", "unknown"))
        by_region.setdefault(reg or "unknown", Counter())[o] += 1
        by_ptype.setdefault(pt or "unknown", Counter())[o] += 1
    top_refusers = Counter(d for o, d in rows if o in ("refused", "robots")).most_common(10)

    meta = json.loads((LOOKUP / "meta.json").read_text()) if (LOOKUP / "meta.json").exists() else {}
    report = {
        "datalog_since": first,
        "requests": len(rows),
        "handshakes": hs,
        "no_handshake": len(rows) - hs,
        "by_outcome": {fetchlog.LABELS.get(k, k): v for k, v in by_outcome.most_common()},
        "by_region": {k: dict(v) for k, v in by_region.items()},
        "by_provider_type": {k: dict(v) for k, v in by_ptype.items()},
        "top_refusing_domains": top_refusers,
        "sites": sites, "site_failure_reasons": fail,
        "funnel": {
            "pages_stored": sum(pages.values()),
            "dropped_free_filter": pages.get("not_programme", 0) + pages.get("duplicate", 0),
            "index_pages_turned_into_sites": pages.get("index_page", 0),
            "waiting_for_annotator": pages.get("candidate", 0) + pages.get("annotating", 0),
            "waiting_for_judges": pages.get("annotated", 0) + pages.get("judging", 0),
            "judge_decisions": decisions,
            "judge_rejection_reasons": dict(reasons.most_common()),
            "published_in_search": meta.get("programmes"),
            "known_programme_stubs": stubs,
        },
    }
    (LOOKUP / "crawl_report.json").write_text(json.dumps(report, indent=1, default=str))
    return report


def show(r):
    """Print the report from build() in a readable form."""
    import datetime as dt
    since = dt.datetime.fromtimestamp(r["datalog_since"]).strftime("%d %b %H:%M") if r["datalog_since"] else "-"
    print(f"CRAWL DATALOG (requests logged since {since})")
    print(f"  Requests: {r['requests']:,}   Handshakes: {r['handshakes']:,}   No handshake: {r['no_handshake']:,}")
    for k, v in r["by_outcome"].items():
        print(f"    {v:>7,}  {k}")
    print("\n  By region (ok / refused / other):")
    for reg, c in sorted(r["by_region"].items(), key=lambda x: -sum(x[1].values())):
        print(f"    {reg:<15} {c.get('ok', 0):>6} ok · {c.get('refused', 0) + c.get('robots', 0):>5} refused/robots · "
              f"{sum(c.values()) - c.get('ok', 0) - c.get('refused', 0) - c.get('robots', 0):>5} other")
    print("\n  Most refusing domains:", ", ".join(f"{d} ({n})" for d, n in r["top_refusing_domains"][:6]) or "-")
    f = r["funnel"]
    print(f"\nPIPELINE FUNNEL (all time)\n  Pages stored ............. {f['pages_stored']:,}")
    print(f"  Dropped by free filter ... {f['dropped_free_filter']:,} (not programmes / duplicates)")
    print(f"  Index pages -> new sites . {f['index_pages_turned_into_sites']:,}")
    print(f"  Waiting: annotator {f['waiting_for_annotator']:,} · judges {f['waiting_for_judges']:,}")
    print(f"  Judge decisions .......... {f['judge_decisions']}")
    for k, v in list(f["judge_rejection_reasons"].items())[:5]:
        print(f"      {v:>5}  rejected: {k}")
    print(f"  Published in search ...... {f['published_in_search']}")
    print(f"  Known-programme stubs .... {f['known_programme_stubs']} (protected sites, link only)")
    print(f"\nSite recovery reasons: {r['site_failure_reasons']}")


if __name__ == "__main__":
    rep = build()
    show(rep)
    if "--csv" in sys.argv:
        lc = fetchlog._con()
        with open(LOOKUP / "fetch_log.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["at", "agent", "url", "domain", "outcome", "http_status", "content_type", "bytes", "ms",
                        "detail", "insecure", "rendered"])
            w.writerows(lc.execute("SELECT * FROM fetches"))
        print(f"\nExported every logged request to {LOOKUP / 'fetch_log.csv'}")
