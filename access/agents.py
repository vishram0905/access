"""The data agents that build the ACCESS library (Layer 0).

They run in parallel and talk to each other only through the SQLite database, so we can stop and restart any one
of them without the others noticing. The Scout finds funding sites (plain rules, no model calls), the Scraper
crawls them and the Annotator fills in the schema, and the Info Critic puts each record before a three-company
judge panel and rebuilds the lookup document. The Auditor and Sentinel entry points live here too.

Run one agent with `python -m access.agents scout|scraper|critic`, or all of them with `python agents.py start`.
"""
import json
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .config import RAW_DIR, check_role_diversity, is_excluded_place
from .critics import review_listing
from .db import connect, fingerprint, now, save_listing
from .discover import (FUNDING_WORDS, SKIP_URL, _base_domain, candidate_links, classify, is_challenge,
                       crawl_paginated, polite_get)
from .harvester import UA, page_text, text_size
from .hubs import HUBS, LEVELS, REGION_PRIORITY, SEEDS_BY_PROVIDER, site_priority, tier1_group, university_seeds
from .llm import LLMError, set_role
from .lookup import build as build_lookup
from .normalizer import normalize
from . import resources, runtime
from .verify import listing_id
from . import factcheck, scoring

# We cap the site database and the link depth from a seed directory to keep the crawl focused on funders.
MAX_SITES = 8000
MAX_DEPTH = 2
PAGES_PER_SITE = 120
CRAWL_WORKERS = 24
REBUILD_EVERY = 15
# Every row needs the full three-company panel. We never let two judges decide on their own.
MIN_JUDGE_FAMILIES = 3
# Errors on the provider's side (quota, rate limits, outages). These are never the page's fault.
QUOTA = re.compile(r"quota|rate|429|RESOURCE_EXHAUSTED|per ?day|daily|TPD|RPD|unavailable|benched", re.I)
NOT_FUNDERS = re.compile(r"(google\.com|facebook|twitter|x\.com|linkedin|youtube|instagram|wikipedia|"
                         r"medium\.com|github|apple\.com/app|play\.google|scholarship(s|portal|positions)\.|"
                         r"scholars4dev|opportunitydesk|afterschoolafrica|mastersportal|findaphd|"
                         r"topuniversities|timeshighereducation)", re.I)
INTERGOV = re.compile(r"(un\.org|unesco|worldbank|oas\.org|oecd|who\.int|europa\.eu|commonwealth|"
                      r"\.int$|asean|adb\.org|afdb)", re.I)


def log(agent, msg):
    print(f"{time.strftime('%H:%M:%S')} [{agent}] {msg}", flush=True)


def guess_provider_type(domain: str, publisher: str = "") -> str:
    d, p = domain.lower(), publisher.lower()
    if INTERGOV.search(d) or "erasmus" in p or "euraxess" in p:
        return "intergovernmental"
    if re.search(r"\.(edu|ac\.[a-z]{2})$|\.edu\.[a-z]{2}$|univ|uni-|ox\.ac|cam\.ac|ntu\.edu|nus\.edu|"
                 r"stanford|mit\.edu|eth|epfl|kaust|oist", d):
        return "university"
    if re.search(r"a-star|max-planck|mpg\.de|cnrs|riken|embo|institut|csiro|nih\.gov", d):
        return "research_institute"
    if re.search(r"\.gov|\.gc\.ca|gov\.|\.go\.jp|admin\.ch|bund|nrf|daad|dfg|nwo|snf|fwf|arc\.gov|anid|capes|"
                 r"cnpq|conicet|conahcyt|minciencias|ukri|jsps|mext|nserc|campusfrance|studyin", d):
        return "government"
    if re.search(r"research\.(google|nvidia)|microsoft|nvidia|qualcomm|ibm|meta|amazon|apple|\.com$", d):
        return "industry"
    return "foundation_charity"


# ---------------------------------------------------------------- 1. Scout

def seed_sites():
    with connect() as con:
        for region, country, publisher, url in HUBS:
            done = con.execute("SELECT COUNT(*) FROM sources WHERE hub_url=?", (url,)).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO sites (url, domain, publisher, region, country, provider_type, "
                        "found_via, depth, priority, status, first_seen, pages_found) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (url, urlparse(url).netloc, publisher, region, country,
                         guess_provider_type(urlparse(url).netloc, publisher), "seed", 0,
                         site_priority(region, country, 0, guess_provider_type(urlparse(url).netloc, publisher), url),
                         "done" if done else "new", now(), done))
        for region, country, publisher, url, ptype in SEEDS_BY_PROVIDER:
            con.execute("INSERT OR IGNORE INTO sites (url, domain, publisher, region, country, provider_type, "
                        "found_via, depth, priority, status, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (url, urlparse(url).netloc, publisher, region, country, ptype, "seed:provider", 0,
                         site_priority(region, country, 0, ptype, url), "new", now()))
        # Ranked universities get one site per study-level scholarship page (see docs/DECISIONS.md, D23).
        # The Annotator records the level from the seed.
        for u in university_seeds():
            for level in LEVELS:
                url = (u.get("pages") or {}).get(level)
                if not url or not url.startswith("http"):
                    continue
                con.execute("INSERT OR IGNORE INTO sites (url, domain, publisher, region, country, provider_type, "
                            "found_via, depth, priority, status, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (url, urlparse(url).netloc, f"{u['name']} ({level})"[:100], u["region"],
                             u.get("country") or u["group"], "university", f"seed:university:{level}", 0,
                             site_priority(u["region"], u.get("country") or u["group"], 0, "university", url),
                             "new", now()))
        for name, pattern, pages in (("EURAXESS", "https://euraxess.ec.europa.eu/funding/search?page={p}", 120),
                                     ("UKRI", "https://www.ukri.org/opportunity/page/{p}/", 30)):
            con.execute("INSERT OR IGNORE INTO sites (url, domain, publisher, region, country, provider_type, "
                        "found_via, depth, priority, status, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (pattern, urlparse(pattern).netloc, name, "Europe", "Europe (various)",
                         "intergovernmental" if name == "EURAXESS" else "government", "feed", 0, 2, "done", now()))
        # The 29 programme pages we picked by hand at the start of the project.
        for f in RAW_DIR.glob("*.json"):
            r = json.loads(f.read_text())
            if r.get("status") != "ok":
                continue
            tld = urlparse(r["url"]).netloc.rsplit(".", 1)[-1]
            region = {"sg": "Asia", "jp": "Asia", "uk": "Europe", "de": "Europe", "eu": "Europe", "ch": "Europe",
                      "ca": "North America", "au": "Asia-Pacific"}.get(tld, "Global")
            con.execute("INSERT OR IGNORE INTO sources (url, domain, name, found_via, official, status, priority, "
                        "title, text, content_hash, http_status, first_seen, last_checked, region, provider_type, score) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r["url"], urlparse(r["url"]).netloc, r["name"], "seed_list", 1, "candidate",
                         REGION_PRIORITY.get(region, 5) * 10 - 9, r["name"] + " | " + r.get("title", ""), r["text"],
                         fingerprint(r["text"]), 200, now(), now(), region,
                         guess_provider_type(urlparse(r["url"]).netloc), 9))


def scout(stop: threading.Event | None = None):
    """Grow the site database from the index pages and outbound links the Scraper finds."""
    seed_sites()
    log("scout", "site database seeded")
    while not (stop and stop.is_set()):
        try:
            _scout_cycle()
        except sqlite3.OperationalError as e:  # another agent holds the write lock, so we wait and retry
            log("scout", f"database busy ({e}); retrying in 30 s")
            time.sleep(30)


def _scout_cycle():
    """One round of the Scout: add sites from index pages and outlinks, then try to recover failed sites."""
    added = 0
    with connect() as con:
        total = con.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
        if total < MAX_SITES:
            # Index pages the Annotator found become sites to crawl, one hop deeper.
            for r in con.execute("SELECT s.url, s.region, s.country, s.publisher, s.provider_type, "
                                 "COALESCE(si.depth,0) d FROM sources s LEFT JOIN sites si ON si.url=s.site_url "
                                 "WHERE s.status='index_page' AND s.url NOT IN (SELECT url FROM sites) LIMIT 50"):
                if r["d"] + 1 <= MAX_DEPTH:
                    con.execute("INSERT OR IGNORE INTO sites (url, domain, publisher, region, country, provider_type,"
                                " found_via, depth, priority, status, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (r["url"], urlparse(r["url"]).netloc, r["publisher"], r["region"], r["country"],
                                 r["provider_type"], "index_page", r["d"] + 1,
                                 site_priority(r["region"], r["country"], r["d"] + 1, r["provider_type"], r["url"]),
                                 "new", now()))
                    added += 1
            # Links to other official funders that we saw while crawling.
            for r in con.execute("SELECT o.to_url, o.anchor, si.region, si.country, si.depth FROM outlinks o "
                                 "JOIN sites si ON si.url=o.site_url WHERE o.used=0 LIMIT 300").fetchall():
                con.execute("UPDATE outlinks SET used=1 WHERE to_url=?", (r["to_url"],))
                dom = urlparse(r["to_url"]).netloc.lower()
                if (r["depth"] or 0) + 1 > MAX_DEPTH or NOT_FUNDERS.search(dom) or is_excluded_place(domain=dom):
                    continue
                if con.execute("SELECT 1 FROM sites WHERE domain=?", (dom,)).fetchone():
                    continue
                if not re.search(r"\.(gov|edu|ac|org|int|eu|gc\.ca)|europa|\.go\.|admin\.ch|research", dom):
                    continue
                con.execute("INSERT OR IGNORE INTO sites (url, domain, publisher, region, country, provider_type,"
                            " found_via, depth, priority, status, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (r["to_url"], dom, r["anchor"][:80] or dom, r["region"], r["country"],
                             guess_provider_type(dom, r["anchor"]), "outlink", (r["depth"] or 0) + 1,
                             site_priority(r["region"], r["country"], (r["depth"] or 0) + 1,
                                           guess_provider_type(dom, r["anchor"]), r["to_url"]), "new", now()))
                added += 1
        stats = dict(con.execute("SELECT status, COUNT(*) FROM sites GROUP BY status").fetchall())
    if added:
        log("scout", f"added {added} new sites · site database: {stats}")
    try:  # we only use legitimate workarounds here (archive copies, sitemaps), never bypass a block
        from .recovery import cycle
        cycle(lambda m: log("scout", m))
    except Exception as e:
        log("scout", f"recovery error: {str(e)[:120]}")
    time.sleep(60)


# ---------------------------------------------------------------- 2. Scraper

def _store(con, url, resp, site, rendered: bool = False) -> tuple[str, list]:
    title, text = page_text(resp.text)
    if text_size(text) < 700 and not rendered and FUNDING_WORDS.search(title + " " + url):
        # Nearly empty but it looks like a funding page, so it is probably built by JavaScript. We queue it for
        # the renderer instead of storing an empty page.
        con.execute("INSERT OR IGNORE INTO render_queue (url, site_url, at) VALUES (?,?,?)",
                    (url, site["url"], now()))
        return "render_queued", []
    status, score = classify(title, text[:30000], url)
    h = fingerprint(text)
    if con.execute("SELECT 1 FROM sources WHERE content_hash=? AND url!=?", (h, url)).fetchone():
        status = "duplicate"
    con.execute("INSERT OR IGNORE INTO sources (url, domain, name, found_via, hub_url, site_url, official, status, "
                "priority, title, text, content_hash, http_status, first_seen, last_checked, region, country, "
                "publisher, provider_type, score) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (url, urlparse(url).netloc, title[:200], f"site:{site['publisher']}", site["url"], site["url"], 1,
                 status, REGION_PRIORITY.get(site["region"], 5) * 10 + site["depth"] * 5 - score, title[:250],
                 text[:30000], h, 200, now(), now(), site["region"], site["country"], site["publisher"],
                 site["provider_type"], score))
    # Outbound links to other domains with funding words in the anchor. The Scout reviews these later.
    soup = BeautifulSoup(resp.text, "html.parser")
    base = _base_domain(urlparse(resp.url).netloc)
    outs = []
    for a in soup.find_all("a", href=True):
        to = urljoin(resp.url, a["href"]).split("#")[0]
        anchor = a.get_text(" ", strip=True)
        if to.startswith("http") and not urlparse(to).netloc.lower().endswith(base) and \
                not SKIP_URL.search(to) and FUNDING_WORDS.search(anchor):
            outs.append((to, anchor[:120]))
    return status, outs


def _crawl_archived(site, base) -> dict | None:
    """Read a site that challenges automated visitors from the Internet Archive instead.

    We never contact the protected site itself. Pages are stored with their snapshot date and score lower on trust.
    """
    from .recovery import archived, migrate
    migrate()
    got = archived(site["url"])
    if not got:
        return None
    landing, _ = got
    pages = cands = 0
    for link, _a in candidate_links(landing, base)[:PAGES_PER_SITE]:
        with connect() as con:
            if con.execute("SELECT 1 FROM sources WHERE url=?", (link,)).fetchone():
                continue
        hit = archived(link)
        if not hit:
            continue
        r, when = hit
        pages += 1
        with connect() as con:
            status, _outs = _store(con, link, r, site, rendered=True)
            con.execute("UPDATE sources SET archived_at=? WHERE url=?", (when, link))
        cands += status == "candidate"
    return {"pages": pages, "candidates": cands, "reason": "archived_copy"}


def crawl_site(site) -> dict:
    site = dict(site)
    if site["found_via"] == "feed":
        crawl_paginated(site["region"], site["country"], site["publisher"], site["url"],
                        r"/jobs/funding/[a-z0-9-]+$" if "euraxess" in site["url"] else r"ukri\.org/opportunity/[a-z0-9-]+/?$",
                        15, progress=lambda m: log("scraper", m))
        return {"pages": 0}
    opts = {"render": bool(site.get("render")), "insecure": bool(site.get("insecure"))}
    resp = polite_get(site["url"], **opts)
    if not resp:
        return {"pages": 0, "failed": True}
    base = _base_domain(urlparse(resp.url).netloc)
    queue = candidate_links(resp, base)
    if not queue:  # we never mark a site "done" without knowing why it gave us nothing
        if is_challenge(resp.text):
            return _crawl_archived(site, base) or {"pages": 0, "failed": True, "reason": "bot_challenge"}
        if len(page_text(resp.text)[1]) < 600 and not opts["render"]:
            return {"pages": 0, "failed": True, "reason": "js_only"}
        from .recovery import sitemap_urls  # funding pages can sit deeper than anything the landing page links to
        queue = [(u, "") for u in sitemap_urls(urlparse(resp.url).netloc, cap=3000)
                 if FUNDING_WORDS.search(urlparse(u).path.replace("-", " ")) and not SKIP_URL.search(u)][:PAGES_PER_SITE]
        if not queue:
            return {"pages": 0, "reason": "no_funding_links"}
    seen, pages, cands, budget = {site["url"]}, 0, 0, PAGES_PER_SITE
    while queue and pages < PAGES_PER_SITE:
        link, _ = queue.pop(0)
        if link in seen:
            continue
        seen.add(link)
        with connect() as con:
            if con.execute("SELECT 1 FROM sources WHERE url=?", (link,)).fetchone():
                continue
        r = polite_get(link, **opts)
        if not r:
            continue
        pages += 1
        with connect() as con:
            status, outs = _store(con, link, r, site)
            if opts["insecure"]:
                con.execute("UPDATE sources SET cert_warning=1 WHERE url=?", (link,))
            con.executemany("INSERT OR IGNORE INTO outlinks (to_url, anchor, site_url, used) VALUES (?,?,?,0)",
                            [(o, a, site["url"]) for o, a in outs])
        cands += status == "candidate"
        more = candidate_links(r, base)
        if len(more) >= 5 and budget > 0:
            for m in more:
                if m[0] not in seen:
                    queue.append(m)
                    budget -= 1
    return {"pages": pages, "candidates": cands}


def _crawl_loop(stop):
    while not (stop and stop.is_set()):
        with connect() as con:
            workers = resources.crawl_workers()  # sized to the memory that is free at this moment
            batch = con.execute("SELECT * FROM sites WHERE status='new' ORDER BY priority, depth LIMIT ?",
                                (workers * 3,)).fetchall()
            # At most one site per domain at a time. The 116 EURAXESS feeds, for example, all share one server.
            busy = {r[0] for r in con.execute("SELECT DISTINCT domain FROM sites WHERE status='crawling'")}
            picked, doms = [], set(busy)
            for s_ in batch:
                if s_["domain"] not in doms:
                    picked.append(s_)
                    doms.add(s_["domain"])
                if len(picked) >= workers:
                    break
            batch = picked
            for s in batch:
                con.execute("UPDATE sites SET status='crawling' WHERE url=?", (s["url"],))
        if not batch:
            time.sleep(30)
            continue

        def one(s):
            try:
                res = crawl_site(s)
            except Exception as e:
                res = {"pages": 0, "failed": True, "error": str(e)[:100]}
            with connect() as con:
                con.execute("UPDATE sites SET status=?, pages_found=?, candidates=?, last_crawled=?, "
                            "fail_reason=COALESCE(?, fail_reason) WHERE url=?",
                            ("failed" if res.get("failed") else "done", res.get("pages", 0),
                             res.get("candidates", 0), now(), res.get("reason"), s["url"]))
            log("scraper", f"crawled {s['publisher'][:30]:<30} {s['country'] or '':<14} "
                           f"pages {res.get('pages', 0):>3}, candidates {res.get('candidates', 0):>3}"
                           f"{' (' + res['reason'].replace('_', ' ') + ')' if res.get('reason') else ''}"
                           f"{' (unreachable)' if res.get('failed') and not res.get('reason') else ''}")
        log("scraper", f"crawling {len(batch)} sites in parallel · {resources.snapshot()}")
        with ThreadPoolExecutor(max(1, len(batch))) as ex:
            list(ex.map(one, batch))


ANNOTATE_WORKERS = 4  # upper bound; the Sentinel decides how many are active
_claim_lock = threading.Lock()


def _next_group(con, waiting_status: str) -> list[tuple[str, str]] | None:
    """Return the (country, region) pairs to take the next page from (see docs/DECISIONS.md, D23).

    Tier 1 comes first. Of the 8 tier-1 groups with work waiting we pick the one with the fewest programmes done or
    in progress, a max-min fairness rule so that the large US queue cannot starve China or Australia. Tier 2 is only
    served when tier 1 has nothing waiting, and there we group by region.
    """
    # "done" must not include the queue being served. For the judging queue, annotated pages are waiting, not
    # done. Counting them once hid Australia's 78 waiting pages behind a "well served" score and none were judged
    # for four days.
    done = "status IN ('active','judging')" if waiting_status == "annotated" else \
        "status IN ('active','annotated','judging')"
    groups = {}
    for x in con.execute(f"SELECT COALESCE(country,'') c, COALESCE(region,'') r, SUM({done}) done, "
                         "SUM(status=? AND COALESCE(attempts,0) < 3) waiting FROM sources GROUP BY c, r",
                         (waiting_status,)):
        g = tier1_group(x["c"], x["r"])
        key = (1, g) if g else (2, x["r"])
        a = groups.setdefault(key, [0, 0, []])
        a[0] += x["done"] or 0
        a[1] += x["waiting"] or 0
        a[2].append((x["c"], x["r"]))
    live = {k: v for k, v in groups.items() if v[1] > 0}
    if not live:
        return None
    tier = min(k[0] for k in live)
    return min(((k, v) for k, v in live.items() if k[0] == tier), key=lambda kv: kv[1][0])[1][2]


def _pairs_sql(pairs) -> tuple[str, list]:
    return "(" + " OR ".join(["(COALESCE(country,'') = ? AND COALESCE(region,'') = ?)"] * len(pairs)) + ")", \
        [v for p in pairs for v in p]


def _neediest_region(con, waiting_status: str) -> str | None:
    """Return the region with the fewest verified or in-progress programmes that still has work waiting.

    We use this so the library grows evenly across regions instead of finishing one queue before starting the next.
    """
    done = "status IN ('active','judging')" if waiting_status == "annotated" else \
        "status IN ('active','annotated','judging')"  # see _next_group: the served queue is not "done"
    r = con.execute(f"SELECT COALESCE(region,'') AS reg, SUM({done}) AS done "
                    "FROM sources GROUP BY reg HAVING SUM(status=? AND COALESCE(attempts,0) < 3) > 0 "
                    "ORDER BY done ASC LIMIT 1", (waiting_status,)).fetchone()
    return r["reg"] if r else None


def _claim_candidate():
    """Take the next candidate page under a lock, so two annotator workers never get the same one."""
    with _claim_lock, connect() as con:
        row = con.execute("SELECT * FROM sources WHERE status='candidate' AND COALESCE(attempts,0) < 3 "
                          "AND priority < 0 ORDER BY priority LIMIT 1").fetchone()  # fast-tracked pages first
        if not row:
            pairs = _next_group(con, "candidate")
            if pairs:
                where, args = _pairs_sql(pairs)
                row = con.execute("SELECT * FROM sources WHERE status='candidate' AND COALESCE(attempts,0) < 3 "
                                  f"AND {where} ORDER BY (COALESCE(provider_type,'') = 'university'), priority, score DESC LIMIT 1",
                                  args).fetchone()
        if row:
            con.execute("UPDATE sources SET status='annotating' WHERE url=?", (row["url"],))
        return row


# Shared by all annotator workers. When the quota runs out, nobody claims a page before this time.
_annotate_pause = [0.0]
_annotate_pause_lock = threading.Lock()


def _annotate_loop(stop, worker=0):
    while not (stop and stop.is_set()):
        if worker >= runtime.get()["workers"]["annotator"]:  # the Sentinel has turned this worker off for now
            time.sleep(60)
            continue
        if time.time() < _annotate_pause[0]:
            time.sleep(min(30, _annotate_pause[0] - time.time()))
            continue
        row = _claim_candidate()
        if not row:
            time.sleep(20)
            continue
        title = re.split(r"\s+\|\s+", row["title"] or "")[0] or row["url"]
        raw = {"id": listing_id(title, row["url"]), "name": title, "url": row["url"], "text": row["text"],
               "official_source": bool(row["official"]), "fetched_at": row["last_checked"]}
        try:
            a = normalize(raw)
        except Exception as e:
            quota = bool(QUOTA.search(str(e)))
            with connect() as con:  # a quota failure is not the page's fault, so it does not cost an attempt
                con.execute("UPDATE sources SET status='candidate'" + ("" if quota else
                            ", attempts=COALESCE(attempts,0)+1") + " WHERE url=?", (row["url"],))
            if quota:  # we pause every worker, not just this one, so they do not take turns failing on the queue
                with _annotate_pause_lock:
                    if time.time() >= _annotate_pause[0]:
                        _annotate_pause[0] = time.time() + 600
                        log("annotator", f"⏸ Google free-tier limit reached; all annotator workers re-checking at "
                                         f"{time.strftime('%H:%M', time.localtime(_annotate_pause[0]))}")
            else:
                log("annotator", f"! {title[:50]}: {str(e)[:120]}")
            continue
        a.update(region=row["region"], country_of_publisher=row["country"], publisher=row["publisher"],
                 content_hash=row["content_hash"])
        a["provider_type"] = a.get("provider_type") or row["provider_type"]
        if a["page_kind"] == "single_opportunity" and a["about_programme"]:
            status = "annotated"
        else:
            status = "index_page" if a["page_kind"] == "list_of_opportunities" else "not_programme"
        with connect() as con:
            con.execute("UPDATE sources SET status=?, annotation=?, provider_type=? WHERE url=?",
                        (status, json.dumps(a) if status == "annotated" else None, a["provider_type"], row["url"]))
        log("annotator", f"{status:<14} {row['region'] or '-':<13} {a['provider_type']:<18} {title[:55]}")


RENDER_MIN_FREE_GB = 1.5


def _render_loop(stop):
    """Re-read JavaScript-built pages, falling back to one local headless browser that we keep open and reuse."""
    from playwright.sync_api import sync_playwright
    from .discover import allowed, polite_get
    with connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS render_queue (url TEXT PRIMARY KEY, site_url TEXT, at TEXT, "
                    "done INTEGER DEFAULT 0, result TEXT)")
    with sync_playwright() as p:
        browser = ctx = None
        while not (stop and stop.is_set()):
            if resources.available_gb() < RENDER_MIN_FREE_GB or runtime.get()["renderer_paused"]:
                if browser:
                    browser.close()
                    browser = ctx = None
                time.sleep(120)
                continue
            with connect() as con:
                job = con.execute("SELECT q.url, q.site_url FROM render_queue q WHERE q.done=0 LIMIT 1").fetchone()
                site = con.execute("SELECT * FROM sites WHERE url=?", (job["site_url"],)).fetchone() if job else None
            if not job:
                time.sleep(60)
                continue
            site = dict(site) if site else {"url": job["site_url"] or job["url"], "publisher": "", "region": None,
                                            "country": None, "provider_type": None, "depth": 1}
            result = "skipped (robots.txt)"
            if allowed(job["url"]):
                from . import fetchlog
                t0 = time.time()
                try:
                    # We try a plain fetch first. It is enough for most pages, and the browser is only started
                    # for pages that really need JavaScript.
                    r0 = polite_get(job["url"])
                    html = r0.text if r0 is not None and not is_challenge(r0.text) else ""
                    text = page_text(html)[1] if html else ""
                    if text_size(text) < 600:
                        if browser is None:
                            browser = p.chromium.launch()
                            ctx = browser.new_context(user_agent=UA["User-Agent"])
                            # We only need the text, so we skip images, fonts and video. Faster, and far less memory.
                            ctx.route("**/*", lambda route: route.abort()
                                      if route.request.resource_type in ("image", "media", "font")
                                      else route.continue_())
                        page = ctx.new_page()
                        page.goto(job["url"], timeout=45000, wait_until="domcontentloaded")
                        page.wait_for_timeout(3500)  # let client-side scripts fill in the content
                        html = page.content()
                        page.close()
                        _, text = page_text(html)
                    fetchlog.record(job["url"], "ok" if text_size(text) >= 600 else "too_short", 200, "text/html",
                                    len(html), int(1000 * (time.time() - t0)), "headless browser", rendered=True)
                    if text_size(text) >= 600:
                        resp = type("R", (), {"text": html, "url": job["url"]})()
                        with connect() as con:
                            con.execute("DELETE FROM sources WHERE url=?", (job["url"],))
                            status, _ = _store(con, job["url"], resp, site, rendered=True)
                        result = f"rendered -> {status}"
                    else:
                        result = "still empty after rendering"
                    # Short pages are often index pages, so we also queue their funding links on the same site.
                    resp = type("R", (), {"text": html, "url": job["url"]})()
                    links = candidate_links(resp, _base_domain(urlparse(job["url"]).netloc))[:15] if html else []
                    with connect() as con:
                        added = sum(con.execute(
                            "INSERT OR IGNORE INTO render_queue (url, site_url, at, done) SELECT ?, ?, ?, 0 "
                            "WHERE NOT EXISTS (SELECT 1 FROM sources WHERE url=?)",
                            (u, job["site_url"], now(), u)).rowcount for u, _ in links)
                    if added:
                        result += f" · followed {added} funding link{'s' * (added != 1)}"
                except Exception as e:
                    fetchlog.record(job["url"], "connection", None, None, None, int(1000 * (time.time() - t0)),
                                    f"render: {type(e).__name__}", rendered=True)
                    result = f"render failed ({type(e).__name__})"
                time.sleep(3)  # polite pacing
            with connect() as con:
                con.execute("UPDATE render_queue SET done=1, result=? WHERE url=?", (result, job["url"]))
            log("renderer", f"{result:<32} {job['url'][:90]}")


def scraper(stop: threading.Event | None = None):
    with connect() as con:  # put back any work a previous stop interrupted
        con.execute("UPDATE sites SET status='new' WHERE status='crawling'")
        con.execute("UPDATE sources SET status='candidate' WHERE status='annotating'")
    threading.Thread(target=_crawl_loop, args=(stop,), daemon=True).start()
    threading.Thread(target=_render_loop, args=(stop,), daemon=True).start()
    for w in range(1, ANNOTATE_WORKERS):
        threading.Thread(target=_annotate_loop, args=(stop, w), daemon=True).start()
    _annotate_loop(stop, 0)


# ---------------------------------------------------------------- 3. Info Critic

CRITIC_WORKERS = 4  # upper bound; the Sentinel decides how many are active
_critic_lock = threading.Lock()


def _claim_annotated():
    with _critic_lock, connect() as con:
        row = con.execute("SELECT url, text, annotation, content_hash FROM sources WHERE status='annotated' "
                          "AND COALESCE(attempts,0) < 3 AND priority < 0 ORDER BY priority LIMIT 1").fetchone()
        if not row:
            pairs = _next_group(con, "annotated")
            if pairs:
                where, args = _pairs_sql(pairs)
                row = con.execute("SELECT url, text, annotation, content_hash FROM sources WHERE status='annotated' "
                                  f"AND COALESCE(attempts,0) < 3 AND {where} "
                                  "ORDER BY (COALESCE(provider_type,'') = 'university'), priority LIMIT 1", args).fetchone()
        if row:
            con.execute("UPDATE sources SET status='judging' WHERE url=?", (row["url"],))
        return row


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _already_decided(listing: dict, url: str) -> str | None:
    """Return an earlier decision for the same programme name on the same website, if there is one.

    One award is often listed once per year, and we do not want each copy to cost a new three-judge panel.
    """
    name, dom = _norm_name(listing.get("name")), urlparse(url).netloc
    if len(name) < 6:
        return None
    with connect() as con:
        for r in con.execute("SELECT source_url, decision, data FROM listings WHERE source_url LIKE ? "
                             "AND decision IN ('accepted','accepted_with_warning','rejected')",
                             (f"%://{dom}/%",)):
            if r["source_url"] != url and _norm_name(json.loads(r["data"]).get("name")) == name:
                return r["decision"]
    return None


_repair_lock, _repairing = threading.Lock(), set()


def _with_original_claims(listing: dict, annotation: str | None) -> dict:
    """Return a copy of the record with the Annotator's original process, funding and deadline claims put back.

    The panel review clears the claims it cannot confirm. We restore them so the claim check
    (see docs/DECISIONS.md, D22) can test each one on its own.
    """
    rec = json.loads(json.dumps(listing))
    ann = json.loads(annotation) if annotation else {}
    for k in ("process", "funding", "deadline"):
        if k in ann:
            rec[k] = ann[k]
    return rec


def _claim_repair():
    """Claim an accepted record that has not been through the claim check yet, or return None."""
    with _repair_lock, connect() as con:
        for r in con.execute(
                "SELECT l.id, l.data, s.annotation, s.text FROM listings l JOIN sources s ON s.url = l.source_url "
                "WHERE l.decision IN ('accepted','accepted_with_warning') AND l.data LIKE '%\"schema_version\": \"2.0\"%' "
                "AND l.data NOT LIKE ? ORDER BY s.priority LIMIT 40", (f'%"{factcheck.METHOD}"%',)):
            if r["id"] not in _repairing:
                _repairing.add(r["id"])
                return dict(r)
    return None


def _repair(rep: dict, panel: list, counter) -> None:
    t = time.time()
    listing = json.loads(rep["data"])
    rec = _with_original_claims(listing, rep["annotation"])
    try:
        outcome = factcheck.check(rec, rep["text"], panel)
    except LLMError as e:
        failed = getattr(e, "failed", {})
        for spec in panel:
            if spec.label in failed:
                resources.bench(spec.model, failed[spec.label])
        log("critic", f"! repair {listing.get('name', '')[:40]}: " + "; ".join(
            f"{k} rested {resources.cooldown_left(next(j.model for j in panel if j.label == k)) / 60:.0f} min "
            f"({v[-70:]})" for k, v in failed.items()) + "; will retry")
        time.sleep(60)
        with _repair_lock:
            _repairing.discard(rep["id"])
        return
    listing = factcheck.apply(rec, outcome)
    scoring.score(listing, rep["text"])
    with connect() as con:
        save_listing(con, listing)
    v = listing["verification"]
    log("critic", f"{'repaired ✓ verified' if v['status'] == 'verified' else 'repaired · incomplete':<22} "
                  f"{listing['name'][:46]:<46} removed {len(v['removed'])}"
                  f"{' · ' + '; '.join(v['problems'])[:70] if v['problems'] else ''} ({time.time() - t:.0f}s)")
    with counter["lock"]:
        counter["n"] += 1
        if counter["n"] >= REBUILD_EVERY:
            build_lookup(lambda m: log("critic", m))
            counter["n"] = 0


def _critic_loop(stop, worker, counter):
    from .config import ROLES
    set_role("critic")
    while not (stop and stop.is_set()):
        if worker >= runtime.get()["workers"]["critic"]:
            time.sleep(60)
            continue
        panel, wait = resources.pick_panel(ROLES["judge_pool"], "critic", MIN_JUDGE_FAMILIES)
        if len({j.family for j in panel}) < MIN_JUDGE_FAMILIES:  # we only judge with the full panel
            wait = min(max(wait, 120), 3600)
            if worker == 0:
                log("critic", f"⏸ paused: {len(panel)} of {MIN_JUDGE_FAMILIES} judge companies have quota "
                              f"({', '.join(j.label for j in panel) or 'none'}); re-checking at "
                              f"{time.strftime('%H:%M', time.localtime(time.time() + wait))}")
            time.sleep(wait)
            continue
        # Even workers repair existing records first and odd workers judge new ones first, each falling back to the
        # other queue. A strict repairs-first order held new countries back for days. The runtime flag
        # "repairs_first" overrides this so every worker verifies existing records before judging new ones.
        rep = _claim_repair() if worker % 2 == 0 or runtime.get().get("repairs_first") else None
        if rep:
            _repair(rep, panel, counter)
            continue
        row = _claim_annotated()
        if not row and worker % 2 == 1:
            rep = _claim_repair()
            if rep:
                _repair(rep, panel, counter)
                continue
        if not row:
            time.sleep(20)
            continue
        listing = json.loads(row["annotation"])
        dup = _already_decided(listing, row["url"])
        if dup:
            with connect() as con:
                con.execute("UPDATE sources SET status='duplicate' WHERE url=?", (row["url"],))
            log("critic", f"= {listing.get('name', '')[:46]}: same programme already decided ({dup}); "
                          f"skipped, no judges used")
            continue
        t = time.time()
        try:
            listing = review_listing(listing, row["text"], judges=panel)
            valid = [v for v in listing["review"]["verdicts"] if "error" not in v]
            if len({v["family"] for v in valid}) < MIN_JUDGE_FAMILIES:
                raise LLMError("daily budget: full panel not available, row deferred: " + "; ".join(
                    f'{v["judge"]}: {v.get("error", "")[:60]}' for v in listing["review"]["verdicts"] if "error" in v))
            if listing["review"]["decision"] != "rejected":  # then every claim, one by one (D22)
                rec = _with_original_claims(listing, row["annotation"])
                listing = factcheck.apply(rec, factcheck.check(rec, row["text"], panel))
        except Exception as e:
            budget = "daily budget" in str(e)
            # We bench any judge that failed (timeout, outage, quota) so the next panel picks a substitute.
            failed = {v["judge"]: v["error"] for v in (listing.get("review") or {}).get("verdicts", []) if "error" in v}
            failed.update(getattr(e, "failed", {}))  # judges that failed in the claim check
            for spec in ROLES["judge_pool"]:
                if spec.label in failed:
                    resources.bench(spec.model, failed[spec.label])
            with connect() as con:  # a judge timing out or running out of quota is not the record's fault
                con.execute("UPDATE sources SET status='annotated'" + ("" if budget or failed else
                            ", attempts=COALESCE(attempts,0)+1") + " WHERE url=?", (row["url"],))
            log("critic", f"! {listing.get('name', '')[:46]}: rested " + (", ".join(
                f"{k} {resources.cooldown_left(next(j.model for j in ROLES['judge_pool'] if j.label == k)) / 60:.0f} min"
                f" ({v[-60:]})" for k, v in failed.items()) or "-") + "; retrying with a substitute judge")
            time.sleep(300 if not failed and (budget or QUOTA.search(str(e))) else 30)  # back off, never spin
            continue
        listing["verified_at"] = now()
        with connect() as con:
            cw = con.execute("SELECT cert_warning, archived_at FROM sources WHERE url=?", (row["url"],)).fetchone()
        listing["cert_warning"] = bool(cw and cw[0])
        listing["archived_at"] = cw[1] if cw else None
        scoring.score(listing, row["text"])
        decision = listing["review"]["decision"]
        with connect() as con:
            save_listing(con, listing)
            con.execute("UPDATE sources SET status=?, verified_hash=? WHERE url=?",
                        ("active" if decision != "rejected" else "rejected", row["content_hash"], row["url"]))
        log("critic", f"{decision:<22} {listing.get('provider_type', ''):<18} {listing['name'][:46]:<46} "
                      f"trust {listing.get('trust')} [{listing.get('band')}] · panel "
                      f"{'/'.join(j.family for j in panel)} ({time.time() - t:.0f}s)")
        with counter["lock"]:
            counter["n"] += 1
            if counter["n"] >= REBUILD_EVERY:
                build_lookup(lambda m: log("critic", m))
                counter["n"] = 0


def critic(stop: threading.Event | None = None):
    problems = check_role_diversity()
    if problems:
        raise SystemExit("; ".join(problems))
    with connect() as con:  # release rows a previous run claimed but never finished
        con.execute("UPDATE sources SET status='annotated' WHERE status='judging'")
    counter = {"n": 0, "lock": threading.Lock()}
    for w in range(1, CRITIC_WORKERS):
        threading.Thread(target=_critic_loop, args=(stop, w, counter), daemon=True).start()
    _critic_loop(stop, 0, counter)


def auditor(stop: threading.Event | None = None):
    from .auditor import run
    set_role("auditor")
    run(stop)


def sentinel(stop: threading.Event | None = None):
    from .sentinel import run
    run(stop)


AGENTS = {"scout": scout, "scraper": scraper, "critic": critic, "auditor": auditor, "sentinel": sentinel}

if __name__ == "__main__":
    AGENTS[sys.argv[1]]()
