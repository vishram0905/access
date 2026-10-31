"""Verification queue for Layer 0: candidate pages go through the Normalizer and the Info Critic panel and
come out as listings.

It runs for hours in the background, highest-priority pages first (Asia, then North America and Europe, and so
on), and stays inside the free-tier limits. Every EXPORT_EVERY pages we export the verified listings and rebuild
the search index, so the app picks up new programmes while the queue is still running.

Run:  python -m access.verify            # process the whole queue
      python -m access.verify --limit 50 # process at most 50 pages
"""
import hashlib
import json
import re
import sys
import time

from .config import LISTINGS_FILE, check_role_diversity
from .critics import review_listing
from .db import all_listings, connect, now, save_listing
from .index import build_index
from .llm import LLMError
from .normalizer import normalize

EXPORT_EVERY = 15
MAX_ATTEMPTS = 3
DAILY_LIMIT = re.compile(r"per day|daily|RPD|TPD|tokens per day|requests per day", re.I)


def listing_id(title: str, url: str) -> str:
    """A readable slug of the title plus a short URL hash, so two pages with the same title stay distinct."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    return f"{slug}-{hashlib.sha1(url.encode()).hexdigest()[:6]}"


def export(progress=print):
    """Write all verified listings to listings.json and rebuild the search index from them."""
    with connect() as con:
        listings = all_listings(con)
    LISTINGS_FILE.write_text(json.dumps(listings, indent=1))
    if listings:
        build_index(listings)
    progress(f"  ↻ exported {len(listings)} verified listings and rebuilt the search index")


def next_batch(n=20):
    """Candidate pages that are new or changed since we last verified them, best priority first."""
    with connect() as con:
        return con.execute(
            "SELECT url, title, text, official, region, country, publisher, content_hash, last_checked "
            "FROM sources WHERE status='candidate' AND (verified_hash IS NULL OR verified_hash != content_hash) "
            "AND COALESCE(attempts,0) < ? ORDER BY priority ASC, score DESC LIMIT ?", (MAX_ATTEMPTS, n)).fetchall()


def mark(url, **fields):
    with connect() as con:
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE sources SET {sets} WHERE url=?", (*fields.values(), url))


def process(row, progress=print) -> str:
    """Normalise and review one page and save the result; returns a one-line summary for the log.

    Index pages and pages that are not about a programme are marked and skipped. We refuse to save a review that
    fewer than two judges took part in.
    """
    title = re.split(r"\s+\|\s+", row["title"] or "")[0] or row["url"]
    raw = {"id": listing_id(title, row["url"]), "name": title, "url": row["url"], "title": row["title"],
           "text": row["text"], "official_source": bool(row["official"]), "fetched_at": row["last_checked"]}
    listing = normalize(raw)
    listing.update(region=row["region"], country_of_publisher=row["country"], publisher=row["publisher"])
    if listing.get("page_kind") != "single_opportunity" or not listing.get("about_programme", True):
        mark(row["url"], status="not_programme" if listing.get("page_kind") == "other" else "index_page",
             verified_hash=row["content_hash"])
        return f"skipped ({listing.get('page_kind')})"
    listing = review_listing(listing, row["text"])
    valid = [v for v in listing["review"]["verdicts"] if "error" not in v]
    if len(valid) < 2:
        raise LLMError("fewer than two judges available: " +
                       "; ".join(v.get("error", "")[:80] for v in listing["review"]["verdicts"] if "error" in v))
    with connect() as con:
        save_listing(con, listing)
    mark(row["url"], verified_hash=row["content_hash"], status="active" if listing["review"]["decision"] != "rejected"
         else "rejected")
    return f"{listing['review']['decision']} · rules kept {len(listing['rules'])}, dropped {len(listing['rules_dropped'])}"


def import_existing(progress=print):
    """Load the original 29 hand-verified listings into the database the first time it is empty."""
    if not LISTINGS_FILE.exists():
        return
    with connect() as con:
        if con.execute("SELECT COUNT(*) FROM listings").fetchone()[0]:
            return
        for l in json.loads(LISTINGS_FILE.read_text()):
            l.setdefault("page_kind", "single_opportunity")
            save_listing(con, l)
    progress("Imported the existing verified listings into the database.")


def run(limit: int | None = None, progress=print):
    """Work through the queue until it is empty or limit pages are done, pausing when a daily quota runs out."""
    problems = check_role_diversity()
    if problems:
        raise SystemExit("Model roles violate the no-self-checking rule: " + "; ".join(problems))
    import_existing(progress)
    done = since_export = 0
    while limit is None or done < limit:
        batch = next_batch()
        if not batch:
            progress("Queue empty.")
            break
        for row in batch:
            if limit is not None and done >= limit:
                break
            t = time.time()
            try:
                result = process(row, progress)
            except Exception as e:
                msg = str(e)
                with connect() as con:
                    con.execute("UPDATE sources SET attempts=COALESCE(attempts,0)+1 WHERE url=?", (row["url"],))
                progress(f"  ! {row['title'][:60]}: {msg[:140]}")
                if DAILY_LIMIT.search(msg) or "429" in msg:
                    progress("  ⏸ free-tier limit reached; pausing 30 minutes")
                    if since_export:
                        export(progress)
                        since_export = 0
                    time.sleep(1800)
                continue
            done += 1
            since_export += 1
            progress(f"  [{done}] {row['region'] or '-':<13} {(row['title'] or '')[:55]:<55} {result} "
                     f"({time.time() - t:.0f}s)")
            if since_export >= EXPORT_EVERY:
                export(progress)
                since_export = 0
    if since_export:
        export(progress)
    with connect() as con:
        n = con.execute("SELECT decision, COUNT(*) FROM listings GROUP BY decision").fetchall()
    progress(f"Finished at {now()}: " + ", ".join(f"{d} {c}" for d, c in n))


if __name__ == "__main__":
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    run(lim)
