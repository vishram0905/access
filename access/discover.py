"""Deep discovery (Layer 0, library building).

We crawl the official funding directories in hubs.py and a few paginated public feeds, and store every
candidate programme page in the database. Pages that are clearly not programmes are filtered out with cheap
heuristics and no model calls, so they cost nothing. The crawler honours robots.txt and paces requests per site.

Run:  python -m access.discover            # crawl hubs + feeds
"""
import re
import threading
import time
import urllib.robotparser as robotparser
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .db import connect, fingerprint, log_check, now, upsert_source
from .harvester import UA, page_text, text_size
from .hubs import HUBS, REGION_PRIORITY, site_priority

FUNDING_WORDS = re.compile(
    r"scholar|fellow|grant|award|bursar|studentship|funding|stipend|prize|beca|bolsa|stipendi|"
    r"phd position|doctoral|postdoc|programme|program", re.I)
SKIP_URL = re.compile(
    r"/(news|events?|press|media|blog|stories|story|magazine|podcast|video|contact|login|signin|register|"
    r"search|tag|tags|category|privacy|cookies?|terms|legal|sitemap|careers/jobs|vacanc|shop|donat)\b|"
    r"\.(pdf|docx?|xlsx?|pptx?|zip|jpg|jpeg|png|gif|svg|mp4)$|^mailto:|^tel:|facebook|twitter|linkedin|"
    r"instagram|youtube|x\.com", re.I)
APPLY_WORDS = re.compile(
    r"eligib|who can apply|applicant|requirement|deadline|how to apply|application|stipend|tuition|"
    r"funding|candidates? must|nationals|citizens|elegib|requisitos|postula|inscri", re.I)
MAX_PER_HUB = 80
# Bot-protection interstitials come back as 200 but carry no content. We respect them: the page is retried
# politely later and we never try to render around or bypass the check.
CHALLENGE = re.compile(r"_Incapsula_Resource|incapsula|cf-chl|challenge-platform|Just a moment\.\.\.|"
                       r"Attention Required! \| Cloudflare|Access Denied</title>|Request unsuccessful|"
                       r"Pardon Our Interruption|ak_bmsc|captcha", re.I)


def is_challenge(html: str) -> bool:
    return bool(html) and len(html) < 20000 and bool(CHALLENGE.search(html))
MAX_TEXT = 30000

_robots: dict = {}
_robots_lock = threading.Lock()
_last_hit: dict = {}
_hit_lock = threading.Lock()
_gap: dict = {}        # per-site delay, which we raise when a site rate-limits us
_backoff_until: dict = {}  # per-site pause after a 429/403, at least as long as Retry-After


def _site(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def allowed(url: str) -> bool:
    site = _site(url)
    with _robots_lock:
        if site not in _robots:
            r = robotparser.RobotFileParser(site + "/robots.txt")
            try:
                resp = requests.get(site + "/robots.txt", headers=UA, timeout=10)
                r.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except requests.RequestException:
                r.parse([])
            _robots[site] = r
    return _robots[site].can_fetch(UA["User-Agent"], url)


def polite_get(url: str, min_gap: float = 1.5, insecure: bool = False, render: bool = False):
    """Fetch a page after checking robots.txt and waiting out the per-site delay.

    Args:
        render: fetch through the local headless browser, for sites that only work with JavaScript.
        insecure: skip the certificate check. We only use this for official gov/edu domains.

    Returns the response for an HTML page with status 200, otherwise None.
    """
    from . import fetchlog
    if not allowed(url):
        fetchlog.record(url, "robots")
        return None
    site = _site(url)
    with _hit_lock:
        gap = max(min_gap, _gap.get(site, min_gap))
        start = max(time.time(), _backoff_until.get(site, 0))
        wait = max(start - time.time(), gap - (time.time() - _last_hit.get(site, 0)))
        _last_hit[site] = time.time() + max(0, wait)
    if wait > 0:
        time.sleep(wait)
    t0 = time.time()
    if render:
        from .recovery import render as _render
        html = _render(url)
        fetchlog.record(url, "ok" if html else "connection", 200 if html else None, "text/html",
                        len(html or ""), int(1000 * (time.time() - t0)), "headless browser", rendered=True)
        if not html:
            return None
        resp = requests.models.Response()
        resp._content, resp.status_code, resp.url = html.encode(), 200, url
        resp.headers["content-type"] = "text/html"
        resp.encoding = "utf-8"
        return resp
    try:
        r = requests.get(url, headers=UA, timeout=25, verify=not insecure)
        ms = int(1000 * (time.time() - t0))
        outcome = fetchlog.outcome_of_response(r)
        if outcome == "ok":
            outcome = fetchlog.outcome_of_response(r, len(page_text(r.text)[1]))
        fetchlog.record(url, outcome, r.status_code, r.headers.get("content-type"), len(r.content), ms,
                        insecure=insecure)
        # The site is refusing us or rate-limiting, so we double its delay and pause it for at least 5 minutes.
        if r.status_code in (403, 429, 503):
            try:
                retry = float(r.headers.get("Retry-After", "0"))
            except ValueError:
                retry = 0
            with _hit_lock:
                _gap[site] = min(30.0, _gap.get(site, min_gap) * 2)
                _backoff_until[site] = time.time() + max(retry, 300)
        elif r.status_code == 200 and _gap.get(site, min_gap) > min_gap:
            with _hit_lock:
                _gap[site] = max(min_gap, _gap[site] * 0.9)  # once it answers again we speed up slowly
        if r.status_code == 200 and "html" in r.headers.get("content-type", "html"):
            return r
    except requests.RequestException as e:
        fetchlog.record(url, fetchlog.outcome_of_exception(e), None, None, None,
                        int(1000 * (time.time() - t0)), type(e).__name__, insecure=insecure)
    return None


def _base_domain(host: str) -> str:
    parts = host.lower().split(".")
    keep = 3 if len(parts) >= 3 and parts[-2] in ("co", "ac", "edu", "gov", "org", "com", "go") else 2
    return ".".join(parts[-keep:])


def candidate_links(resp, base_domain: str) -> list[tuple[str, str]]:
    """Return (url, anchor text) for same-site links whose text or slug mentions funding."""
    soup = BeautifulSoup(resp.text, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(resp.url, a["href"]).split("#")[0].rstrip("/")
        text = a.get_text(" ", strip=True)
        if not url.startswith("http") or SKIP_URL.search(url):
            continue
        if not urlparse(url).netloc.lower().endswith(base_domain):
            continue
        if FUNDING_WORDS.search(text + " " + url.rsplit("/", 1)[-1].replace("-", " ")):
            out.setdefault(url, text[:150])
    return list(out.items())


def classify(title: str, text: str, url: str) -> tuple[str, int]:
    """Score a page with keyword heuristics and return (status, score).

    This runs on every crawled page, so it has to be cheap. Pages scoring 4 or more stay as candidates.
    """
    if text_size(text) < 700:
        return "not_programme", 0
    head = (title + " " + url).lower()
    score = 3 * bool(FUNDING_WORDS.search(head)) + min(5, len(APPLY_WORDS.findall(text[:12000])) // 2)
    if re.search(r"/(news|event|press|blog|story)", url, re.I):
        score -= 4
    # Degree and course pages ("Master of Science in ...") are not funding unless they actually talk about it.
    if re.search(r"^(bachelor|master|doctor|diploma|graduate certificate|phd in|msc|ma |mba|bsc|beng|meng)\b|"
                 r"\b(degree programme|course outline|curriculum|modules|admission requirements)\b", title, re.I) and \
            not re.search(r"scholar|fellow|stipend|bursar|funding|grant|award|tuition waiver", text[:6000], re.I):
        score -= 6
    if re.search(r"polic|process|dates|system|faq|guidance|terms and|report|book prize|annual review|"
                 r"how to enter|assessment|panel|committee|our people|history|governance", title, re.I):
        score -= 4
    return ("candidate" if score >= 4 else "not_programme"), score


def store_page(con, url, resp, region, country, publisher, found_via, hub_url):
    title, text = page_text(resp.text)
    text = text[:MAX_TEXT]
    status, score = classify(title, text, url)
    h = fingerprint(text)
    dup = con.execute("SELECT url FROM sources WHERE content_hash=? AND url!=?", (h, url)).fetchone()
    if dup:
        status = "duplicate"
    # Tier 1 first, national sources before ranked universities (D23). Within a band, higher-scoring pages go first.
    prio = site_priority(region, country, 0, None, url) * 10 - score
    new = upsert_source(con, url, domain=urlparse(url).netloc, name=title[:200], found_via=found_via,
                        hub_url=hub_url, official=1, status=status, priority=prio, title=title[:250],
                        text=text, content_hash=h, http_status=200, last_checked=now(),
                        region=region, country=country, publisher=publisher, score=score)
    log_check(con, url, "new" if new else "seen", status)
    return status


def crawl_hub(hub, progress=print) -> dict:
    """Crawl one hub and the funding links on it, storing up to MAX_PER_HUB new pages."""
    region, country, publisher, url = hub
    counts = {"pages": 0, "candidate": 0}
    resp = polite_get(url)
    if not resp:
        progress(f"  ✗ {publisher}: hub unreachable")
        return counts
    base = _base_domain(urlparse(resp.url).netloc)
    queue = candidate_links(resp, base)
    seen = {resp.url.rstrip("/"), url.rstrip("/")}
    depth2_budget = MAX_PER_HUB
    while queue and counts["pages"] < MAX_PER_HUB:
        link, anchor = queue.pop(0)
        if link in seen:
            continue
        seen.add(link)
        with connect() as con:
            if con.execute("SELECT 1 FROM sources WHERE url=?", (link,)).fetchone():
                continue
        r = polite_get(link)
        if not r:
            continue
        counts["pages"] += 1
        with connect() as con:
            status = store_page(con, r.url.rstrip("/"), r, region, country, publisher, f"hub:{publisher}", url)
        counts[status] = counts.get(status, 0) + 1
        # A page with many funding links is probably an index, so we follow its links one level further.
        more = candidate_links(r, base)
        if len(more) >= 5 and depth2_budget > 0:
            for m in more:
                if m[0] not in seen:
                    queue.append(m)
                    depth2_budget -= 1
    progress(f"  ✓ {publisher:<32} {country:<15} pages {counts['pages']:>3}, candidates {counts.get('candidate', 0):>3}")
    return counts


def crawl_paginated(region, country, publisher, page_url, item_pattern, max_pages, progress=print):
    """Crawl a feed that lists funding offers page by page, such as EURAXESS or UKRI."""
    found = 0
    for p in range(max_pages):
        resp = polite_get(page_url.format(p=p), min_gap=4.0)
        if not resp:
            break
        soup = BeautifulSoup(resp.text, "html.parser")
        links = {urljoin(resp.url, a["href"]).split("#")[0] for a in soup.find_all("a", href=True)
                 if re.search(item_pattern, a["href"])}
        new_links = []
        with connect() as con:
            new_links = [l for l in links if not con.execute("SELECT 1 FROM sources WHERE url=?", (l,)).fetchone()]
        if not links:
            break
        for link in new_links:
            r = polite_get(link, min_gap=4.0)
            if r:
                with connect() as con:
                    store_page(con, link, r, region, country, publisher, f"feed:{publisher}", page_url)
                found += 1
        if p % 10 == 0:
            progress(f"  … {publisher} page {p}: {found} offers stored")
    progress(f"  ✓ {publisher:<32} {country:<15} offers {found}")
    return found


FEEDS = [
    ("Europe", "Europe (various)", "EURAXESS", "https://euraxess.ec.europa.eu/funding/search?page={p}",
     r"/jobs/funding/[a-z0-9-]+$", 120),
    ("Europe", "United Kingdom", "UKRI", "https://www.ukri.org/opportunity/page/{p}/",
     r"ukri\.org/opportunity/[a-z0-9-]+/?$", 30),
]


def migrate():
    """Add the discovery columns to the sources table if an older database lacks them."""
    with connect() as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(sources)")}
        for col, typ in (("region", "TEXT"), ("country", "TEXT"), ("publisher", "TEXT"),
                         ("score", "INTEGER"), ("attempts", "INTEGER DEFAULT 0")):
            if col not in cols:
                con.execute(f"ALTER TABLE sources ADD COLUMN {col} {typ}")


def run(progress=print, workers: int = 8):
    migrate()
    progress(f"Crawling {len(HUBS)} official directories ({workers} sites in parallel)...")
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda h: crawl_hub(h, progress), HUBS))
    progress("Crawling structured feeds...")
    with ThreadPoolExecutor(len(FEEDS)) as ex:
        list(ex.map(lambda f: crawl_paginated(*f, progress=progress), FEEDS))
    with connect() as con:
        rows = con.execute("SELECT region, status, COUNT(*) FROM sources GROUP BY region, status").fetchall()
    progress("Summary (region, status, pages):")
    for r in rows:
        progress(f"  {r[0] or '-':<15} {r[1]:<15} {r[2]}")


if __name__ == "__main__":
    run()
