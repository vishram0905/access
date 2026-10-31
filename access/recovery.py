"""Recovery for sites the crawler could not read (Layer 0, library building).

We only use legitimate workarounds. A page that moved (404) is looked up again in the site's own sitemap.
Timeouts and connection errors are retried after 1, 3 and 7 days before we give up. JavaScript-only pages are
rendered in a local headless browser (Playwright). On a certificate error we retry without the check, but only
on government and university domains, and those rows carry a "certificate warning" so they are trusted less.
Bot challenge pages get the same 1, 3 and 7 day retries, because some protection only challenges some requests.

Bot protection, robots.txt refusals and 401-405 or 429 answers are respected and never worked around. Such a
site is kept as a "known programme" stub with only its name and official link; stubs are shown separately and
never used for matching.
"""
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from .db import connect, now
from .discover import allowed, is_challenge
from .harvester import UA, page_text

RETRY_DAYS = [1, 3, 7]
TRUSTED_TLD = re.compile(r"\.(gov|edu|ac|go|gob|gouv|govt|mil)(\.[a-z]{2})?$|\.gc\.ca$|europa\.eu$|admin\.ch$|"
                         r"\.edu\.[a-z]{2}$|\.ac\.[a-z]{2}$", re.I)
SCHEMA = """
CREATE TABLE IF NOT EXISTS stubs (url TEXT PRIMARY KEY, name TEXT, region TEXT, country TEXT,
    provider_type TEXT, reason TEXT, found_via TEXT, at TEXT);
"""
SITE_COLUMNS = (("fail_reason", "TEXT"), ("retries", "INTEGER DEFAULT 0"), ("retry_at", "TEXT"),
                ("render", "INTEGER DEFAULT 0"), ("insecure", "INTEGER DEFAULT 0"))


def migrate():
    """Create the stubs table and add the recovery columns to older sites and sources tables."""
    with connect() as con:
        con.executescript(SCHEMA)
        cols = {r[1] for r in con.execute("PRAGMA table_info(sites)")}
        for c, t in SITE_COLUMNS:
            if c not in cols:
                con.execute(f"ALTER TABLE sites ADD COLUMN {c} {t}")
        scols = {r[1] for r in con.execute("PRAGMA table_info(sources)")}
        if "cert_warning" not in scols:
            con.execute("ALTER TABLE sources ADD COLUMN cert_warning INTEGER DEFAULT 0")
        if "archived_at" not in scols:
            con.execute("ALTER TABLE sources ADD COLUMN archived_at TEXT")


def classify(url: str) -> str:
    """Fetch the page once and name the reason it failed, or "ok" if it now reads fine."""
    try:
        if not allowed(url):
            return "robots"
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code in (401, 403, 405, 429, 451):
            return "protected"
        if r.status_code == 404 or r.status_code == 410:
            return "moved"
        if r.status_code >= 500 or r.status_code >= 400:
            return "transient"
        if is_challenge(r.text):
            return "challenge"  # bot protection: we retry politely, never render or bypass it
        title, text = page_text(r.text)
        return "js_only" if len(text) < 600 else "ok"
    except requests.exceptions.SSLError:
        return "ssl"
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        return "transient"
    except Exception:
        return "transient"


# ---------------- workarounds ----------------

def render(url: str, timeout_ms: int = 30000) -> str | None:
    """Render a JavaScript page in a local headless browser and return its HTML."""
    from playwright.sync_api import sync_playwright
    if not allowed(url):
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(user_agent=UA["User-Agent"])
            pg.goto(url, timeout=timeout_ms, wait_until="networkidle")
            html = pg.content()
            b.close()
            return html
    except Exception:
        return None


ARCHIVE_MAX_AGE_DAYS = 240


def archived(url: str, max_age_days: int = ARCHIVE_MAX_AGE_DAYS):
    """Fetch the latest Internet Archive copy of a page that blocks automated visitors.

    We never contact the protected site itself here, and copies older than max_age_days are ignored.
    Returns (response, 'YYYY-MM-DD') or None.
    """
    from .discover import polite_get
    rows = None
    for wait in (0, 15, 45):  # the archive is often briefly overloaded (503s, timeouts), so we back off and retry
        time.sleep(wait)
        # We ask the CDX index because it lists snapshots reliably; the quicker "available" lookup often comes
        # back empty.
        try:
            r = requests.get("https://web.archive.org/cdx/search/cdx", headers=UA, timeout=45,
                             params={"url": re.sub(r"^https?://", "", url), "output": "json", "limit": "-1",
                                     "filter": "statuscode:200", "fl": "timestamp,original"})
            if r.status_code == 200:
                rows = r.json() if r.text.strip() else []
                break
        except (requests.RequestException, ValueError):
            continue
    if rows is None:
        return None
    ts = rows[-1][0] if len(rows) > 1 else None  # row 0 is the header
    if not ts:
        return None
    when = datetime.strptime(ts[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - when).days > max_age_days:
        return None
    # The id_ suffix asks for the original page without the archive's toolbar.
    r = polite_get(f"https://web.archive.org/web/{ts}id_/{url}", min_gap=3.0)
    if not r or is_challenge(r.text):
        return None
    r.url = url  # so that relative links resolve against the original site, not the archive
    return r, when.date().isoformat()


def sitemap_urls(domain: str, cap: int = 5000) -> list[str]:
    """Return the page URLs a site lists in its sitemaps, following sitemap indexes up to 2 levels deep."""
    base = f"https://{domain}"
    maps = []
    try:
        rb = requests.get(base + "/robots.txt", headers=UA, timeout=15).text
        maps = re.findall(r"(?im)^sitemap:\s*(\S+)", rb)
    except requests.RequestException:
        pass
    maps = maps or [base + "/sitemap.xml", base + "/sitemap_index.xml"]
    out, seen = [], set()

    def read(u, depth=0):
        if u in seen or len(out) >= cap or depth > 2:
            return
        seen.add(u)
        try:
            root = ET.fromstring(requests.get(u, headers=UA, timeout=20).content)
        except Exception:
            return
        for loc in root.iter():
            if loc.tag.endswith("loc") and loc.text:
                t = loc.text.strip()
                (read(t, depth + 1) if t.endswith(".xml") else out.append(t))
    for m in maps[:3]:
        read(m)
    return out[:cap]


def refind(old_url: str, name: str) -> str | None:
    """Find a moved programme page in the site's sitemap by matching words of its name against URL slugs.

    We only accept a URL whose slug contains at least 60% of the words; below that the guesses were unreliable.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower())
             if len(w) > 2 and w not in {"the", "and", "for", "programme", "program", "official"}]
    if not words:
        words = [w for w in re.findall(r"[a-z0-9]+", urlparse(old_url).path.lower()) if len(w) > 3]
    best, score = None, 0.0
    for u in sitemap_urls(urlparse(old_url).netloc):
        slug = u.lower().replace("-", " ").replace("_", " ")
        s = sum(w in slug for w in words) / len(words) if words else 0
        if s > score:
            best, score = u, s
    return best if score >= 0.6 else None


def make_stub(con, site, reason):
    con.execute("INSERT OR IGNORE INTO stubs VALUES (?,?,?,?,?,?,?,?)",
                (site["url"], site["publisher"], site["region"], site["country"], site["provider_type"],
                 reason, site["found_via"], now()))


def cycle(progress=print, batch: int = 25) -> dict:
    """Work through the failed sites whose retry is due. The Scout agent calls this periodically."""
    migrate()
    stats = {}
    with connect() as con:
        rows = con.execute("SELECT * FROM sites WHERE status='failed' AND (retry_at IS NULL OR retry_at <= ?) "
                           "LIMIT ?", (now(), batch)).fetchall()
    for s in rows:
        reason = classify(s["url"])
        dom = urlparse(s["url"]).netloc
        action, update = reason, {}
        if reason == "ok":
            update = {"status": "new"}
        elif reason == "js_only":
            html = render(s["url"])
            ok = html and len(page_text(html)[1]) >= 600
            update = {"status": "new", "render": 1} if ok else {"status": "given_up"}
            action = "rendered in headless browser" if ok else "js_only: render failed"
        elif reason == "ssl" and TRUSTED_TLD.search(dom):
            try:
                r = requests.get(s["url"], headers=UA, timeout=20, verify=False)
                ok = r.status_code == 200 and len(page_text(r.text)[1]) >= 600
            except requests.RequestException:
                ok = False
            update = {"status": "new", "insecure": 1} if ok else {"status": "given_up"}
            action = "certificate warning (official domain)" if ok else "ssl: unreadable"
        elif reason == "moved":
            new = refind(s["url"], s["publisher"])
            if new:
                with connect() as con:
                    con.execute("INSERT OR IGNORE INTO sites (url, domain, publisher, region, country, provider_type, "
                                "found_via, depth, priority, status, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (new, dom, s["publisher"], s["region"], s["country"], s["provider_type"],
                                 "sitemap_refind", s["depth"], s["priority"], "new", now()))
                update, action = {"status": "moved"}, "re-found via sitemap"
            else:
                update, action = {"status": "gone"}, "moved: not found in sitemap"
        elif reason in ("transient", "challenge"):
            n = (s["retries"] or 0)
            if n < len(RETRY_DAYS):
                when = (datetime.now(timezone.utc) + timedelta(days=RETRY_DAYS[n])).isoformat(timespec="seconds")
                update, action = {"retries": n + 1, "retry_at": when}, f"retry in {RETRY_DAYS[n]} day(s)"
            else:
                # Still behind bot protection after a week of retries, so we keep a link-only stub.
                if reason == "challenge":
                    with connect() as con:
                        make_stub(con, s, "bot protection")
                    update, action = {"status": "protected"}, "challenge: respected, kept as stub"
                else:
                    update, action = {"status": "given_up"}, "transient: gave up after 3 retries"
        else:  # protected, robots or ssl on an untrusted domain: we respect it and never work around it
            with connect() as con:
                make_stub(con, s, reason)
            update, action = {"status": "protected"}, f"{reason}: respected, kept as stub"
        update["fail_reason"] = reason
        with connect() as con:
            sets = ", ".join(f"{k}=?" for k in update)
            con.execute(f"UPDATE sites SET {sets} WHERE url=?", (*update.values(), s["url"]))
        stats[action] = stats.get(action, 0) + 1
        time.sleep(1)
    if stats:
        progress(f"recovery: {stats}")
    return stats
