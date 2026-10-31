"""Crawl log for Layer 0: one row for every request the crawlers make or deliberately skip.

We keep it in its own SQLite file (data/fetchlog.db) so that logging never slows down the main database.
The outcome of each row is one of these:

  the site answered (any HTTP status)
    ok            200 and HTML with usable text
    refused       401, 403, 405, 429 or 451 (bot protection, rate limiting)
    not_found     404 or 410
    server_error  5xx
    other_status  any other 4xx or 3xx
    not_html      PDF, image and so on
    too_short     the page answered but had almost no text, often because it is built by JavaScript
  no answer
    robots        skipped because robots.txt asks crawlers not to fetch it; never requested
    timeout       no answer in time
    ssl           certificate or TLS failure
    connection    DNS failure, connection refused or reset
"""
import sqlite3
import threading
import time
from urllib.parse import urlparse

from .config import DATA

LOG_DB = DATA / "fetchlog.db"
_lock = threading.Lock()
_buffer: list = []
FLUSH_EVERY = 25
_last_flush = [time.time()]

SCHEMA = """CREATE TABLE IF NOT EXISTS fetches (
    at REAL, agent TEXT, url TEXT, domain TEXT, outcome TEXT, http_status INTEGER,
    content_type TEXT, bytes INTEGER, ms INTEGER, detail TEXT, insecure INTEGER, rendered INTEGER);
CREATE INDEX IF NOT EXISTS idx_fetch_outcome ON fetches(outcome);
CREATE INDEX IF NOT EXISTS idx_fetch_domain ON fetches(domain);"""


import atexit
atexit.register(lambda: flush())


def _con():
    con = sqlite3.connect(LOG_DB, timeout=30)
    con.executescript(SCHEMA)
    return con


def flush():
    """Write the buffered rows to the log database."""
    global _buffer
    with _lock:
        rows, _buffer = _buffer, []
    if rows:
        con = _con()
        con.executemany("INSERT INTO fetches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()


def record(url, outcome, status=None, ctype=None, size=None, ms=None, detail="", agent="crawler",
           insecure=False, rendered=False):
    """Buffer one fetch row. We write in batches of FLUSH_EVERY, or every 30 s, to keep crawling fast."""
    with _lock:
        _buffer.append((time.time(), agent, url, urlparse(url).netloc, outcome, status, (ctype or "")[:40],
                        size, ms, (detail or "")[:200], int(insecure), int(rendered)))
        full = len(_buffer) >= FLUSH_EVERY or time.time() - _last_flush[0] > 30
    if full:
        _last_flush[0] = time.time()
        flush()


def outcome_of_response(r, text_len: int | None = None) -> str:
    s = r.status_code
    if s in (401, 403, 405, 429, 451):
        return "refused"
    if s in (404, 410):
        return "not_found"
    if s >= 500:
        return "server_error"
    if s != 200:
        return "other_status"
    if "html" not in r.headers.get("content-type", "html"):
        return "not_html"
    if text_len is not None and text_len < 600:
        return "too_short"
    return "ok"


def outcome_of_exception(e) -> str:
    import requests
    if isinstance(e, requests.exceptions.SSLError):
        return "ssl"
    if isinstance(e, requests.exceptions.Timeout):
        return "timeout"
    return "connection"


HANDSHAKE = ("ok", "refused", "not_found", "server_error", "other_status", "not_html", "too_short")
LABELS = {
    "ok": "Answered with a usable page", "refused": "Refused (bot protection / rate limit: 401, 403, 429…)",
    "not_found": "Page not found (404 / 410)", "server_error": "Server error (5xx)",
    "other_status": "Other HTTP status", "not_html": "Not a web page (PDF, image…)",
    "too_short": "Answered but almost no text (often JavaScript-only)",
    "robots": "Skipped: robots.txt asks crawlers not to read it", "timeout": "No answer in time (timeout)",
    "ssl": "Certificate / TLS failure", "connection": "Could not connect (DNS, refused, reset)",
}
