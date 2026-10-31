"""The local SQLite database that holds the library (Layer 0).

It keeps every source page we know about with its content fingerprint and check history, the sites we crawl,
and the verified listings. The app only ever searches this database, never the live web.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DATA

DB_FILE = DATA / "access.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    url            TEXT PRIMARY KEY,
    domain         TEXT,
    name           TEXT,           -- programme name if known (seed list) or page title
    found_via      TEXT,           -- seed | hub:<url> | api:<name>
    hub_url        TEXT,           -- index page it was discovered on (used to re-find moved pages)
    official       INTEGER,
    status         TEXT,           -- discovered | active | changed | moved | gone | not_programme | error
    priority       INTEGER DEFAULT 5,  -- lower = verified sooner (Singapore = 1)
    title          TEXT,
    text           TEXT,
    content_hash   TEXT,
    etag           TEXT,
    last_modified  TEXT,
    http_status    INTEGER,
    moved_to       TEXT,
    first_seen     TEXT,
    last_checked   TEXT,
    last_changed   TEXT,
    verified_hash  TEXT            -- content_hash at the time the listing was last verified
);
CREATE TABLE IF NOT EXISTS listings (
    id           TEXT PRIMARY KEY,
    source_url   TEXT,
    decision     TEXT,             -- accepted | accepted_with_warning | rejected
    data         TEXT,             -- full listing JSON (rules, review, ...)
    verified_at  TEXT
);
CREATE TABLE IF NOT EXISTS checks (
    run_at   TEXT,
    url      TEXT,
    result   TEXT,                 -- unchanged | changed | moved | gone | error | new
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status, priority);
CREATE TABLE IF NOT EXISTS sites (
    url            TEXT PRIMARY KEY,   -- directory / index page to crawl
    domain         TEXT,
    publisher      TEXT,
    region         TEXT,
    country        TEXT,
    provider_type  TEXT,
    found_via      TEXT,               -- seed | outlink:<parent> | index_page:<url> | feed
    depth          INTEGER DEFAULT 0,  -- hops from a seed directory
    priority       INTEGER DEFAULT 5,
    status         TEXT DEFAULT 'new', -- new | crawling | done | failed
    pages_found    INTEGER DEFAULT 0,
    candidates     INTEGER DEFAULT 0,
    first_seen     TEXT,
    last_crawled   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sites_status ON sites(status, priority);
CREATE TABLE IF NOT EXISTS render_queue (
    url TEXT PRIMARY KEY, site_url TEXT, at TEXT, done INTEGER DEFAULT 0, result TEXT
);
CREATE TABLE IF NOT EXISTS outlinks (
    to_url TEXT PRIMARY KEY, anchor TEXT, site_url TEXT, used INTEGER DEFAULT 0
);
"""

SOURCE_COLUMNS = (("region", "TEXT"), ("country", "TEXT"), ("publisher", "TEXT"), ("score", "INTEGER"),
                  ("attempts", "INTEGER DEFAULT 0"), ("provider_type", "TEXT"), ("annotation", "TEXT"),
                  ("site_url", "TEXT"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(text: str) -> str:
    """Hash the page text with whitespace normalised and digit-only lines dropped.

    We do this so cosmetic changes, such as a date in the footer or different spacing, do not count as updates.
    """
    lines = [" ".join(l.split()) for l in text.splitlines()]
    lines = [l for l in lines if l and not l.replace(" ", "").isdigit()]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:20]


_ready = False


@contextmanager
def connect():
    """Open a connection that several agent processes can use at once (WAL mode, long busy timeout).

    The first call in a process also creates the tables and adds any columns missing from older databases.
    """
    global _ready
    con = sqlite3.connect(DB_FILE, timeout=60)
    con.row_factory = sqlite3.Row
    if not _ready:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        cols = {r[1] for r in con.execute("PRAGMA table_info(sources)")}
        for col, typ in SOURCE_COLUMNS:
            if col not in cols:
                con.execute(f"ALTER TABLE sources ADD COLUMN {col} {typ}")
        _ready = True
    con.execute("PRAGMA busy_timeout=60000")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def upsert_source(con, url: str, **fields):
    """Insert a source page or update its fields. Returns True only when the page was new."""
    row = con.execute("SELECT url FROM sources WHERE url=?", (url,)).fetchone()
    if row:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            con.execute(f"UPDATE sources SET {sets} WHERE url=?", (*fields.values(), url))
        return False
    fields.setdefault("first_seen", now())
    cols = ["url", *fields]
    con.execute(f"INSERT INTO sources ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                (url, *fields.values()))
    return True


def save_listing(con, listing: dict):
    con.execute("INSERT OR REPLACE INTO listings (id, source_url, decision, data, verified_at) VALUES (?,?,?,?,?)",
                (listing["id"], listing["url"], listing["review"]["decision"], json.dumps(listing), now()))


def all_listings(con, include_rejected=False) -> list[dict]:
    q = "SELECT data FROM listings" + ("" if include_rejected else
                                       " WHERE decision IN ('accepted', 'accepted_with_warning')")
    from .schema import region_for, region_of
    out = []
    for r in con.execute(q):
        l = json.loads(r["data"])
        if "host_countries" in l:  # a programme with a host list can have a label naming several countries
            l["region"] = region_of(l)
        else:
            l["host_country"], l["region"] = region_for(l.get("host_country"), l.get("url"))
        out.append(l)
    return out


def log_check(con, url, result, detail=""):
    con.execute("INSERT INTO checks VALUES (?,?,?,?)", (now(), url, result, detail[:500]))


def stats(con) -> dict:
    by_status = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM sources GROUP BY status")}
    by_decision = {r[0]: r[1] for r in con.execute("SELECT decision, COUNT(*) FROM listings GROUP BY decision")}
    last = con.execute("SELECT MAX(run_at) FROM checks").fetchone()[0]
    return {"sources": sum(by_status.values()), "by_status": by_status,
            "listings": by_decision, "last_check": last}
