"""Harvester for the curated source catalogue (Layer 0, library building).

For each programme in sources.py we first try the seed URL. If that page does not match the programme well,
we crawl links on the official site whose text matches the programme name, and as a last resort we run a free
web search and keep only results on the official domain. Pages are saved under data/raw/ so the rest of the
pipeline can run offline. The shared page helpers (page_text, text_size, UA) also live here.
"""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import RAW_DIR
from .sources import SOURCES

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
MIN_TEXT = 600
GENERIC = {"the", "of", "for", "and", "in", "a", "an", "program", "programme", "official"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def _words(name: str) -> list[str]:
    name = re.sub(r"\(.*?\)", "", name)  # acronyms in brackets rarely appear on the page, so we drop them
    return [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in GENERIC and len(w) > 1]


def relevance(name: str, title: str, text: str) -> float:
    """Return the share of the programme name's words that appear in the page title and opening text."""
    words = _words(name)
    hay = (title + " " + text[:2500]).lower()
    return sum(w in hay for w in words) / len(words) if words else 1.0


CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def text_size(text: str) -> int:
    """Return a text length that is fair across scripts.

    A Chinese, Japanese or Korean character carries roughly as much meaning as three Latin letters, so we count
    it three times. Otherwise a dense CJK page would look almost empty to the size thresholds.
    """
    return len(text) + 2 * len(CJK.findall(text))


def _text(node) -> str:
    return re.sub(r"\n{2,}", "\n", node.get_text("\n", strip=True))


def page_text(html: str) -> tuple[str, str]:
    """Return (title, main text) of a page.

    We only strip clutter (scripts, menus, footers, site headers, form controls) and then pick the block that
    actually holds the text. Many sites, ASP.NET ones in particular, wrap the whole page in one <form>, and some
    have an empty or teaser <main> or <article>, so we do not trust either of them blindly.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:200]
    h1 = soup.find("h1")
    if h1:
        title = f"{h1.get_text(' ', strip=True)} | {title}"[:250]
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template", "nav", "footer",
                     "input", "select", "button", "textarea", "option"]):
        tag.decompose()
    for tag in soup.find_all("header"):  # drop site banners but keep headers inside the content itself
        if not tag.find_parent(["main", "article"]):
            tag.decompose()
    body = soup.body or soup
    full = _text(body)
    blocks = soup.find_all(["main", "article"]) + soup.find_all(attrs={"role": "main"})
    best = max((_text(b) for b in blocks), key=len, default="")
    # We use the content block only when it holds a good part of the page, not a teaser or an empty wrapper.
    text = best if len(best) >= 500 and len(best) >= 0.3 * len(full) else full
    return title, text


def get(url: str):
    """Fetch an HTML page, or return None. The one-second pause keeps us gentle on small sites."""
    try:
        r = requests.get(url, headers=UA, timeout=25)
        time.sleep(1.0)
        if r.status_code == 200 and "html" in r.headers.get("content-type", "html"):
            return r
    except requests.RequestException:
        pass
    return None


def is_official(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == domain or host.endswith("." + domain)


def _links(resp, domain: str, name: str) -> list[str]:
    """Return up to six official links whose anchor text or URL best matches the programme name."""
    soup = BeautifulSoup(resp.text, "html.parser")
    words = _words(name)
    scored = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(resp.url, a["href"]).split("#")[0]
        if not url.startswith("http") or not is_official(url, domain):
            continue
        hay = (a.get_text(" ", strip=True) + " " + url.replace("-", " ").replace("/", " ")).lower()
        s = sum(w in hay for w in words) / len(words) if words else 0
        if s >= 0.5:
            scored[url] = max(s, scored.get(url, 0))
    return [u for u, _ in sorted(scored.items(), key=lambda x: -x[1])][:6]


def _search(query: str) -> list[str]:
    """Run a last-resort free search on DuckDuckGo's HTML page. It rate-limits quickly, hence the long pause."""
    try:
        r = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=UA, timeout=20)
        time.sleep(5)
        soup = BeautifulSoup(r.text, "html.parser")
        from urllib.parse import parse_qs, unquote
        out = []
        for a in soup.select("a.result__a")[:8]:
            h = a.get("href", "")
            if "uddg=" in h:
                h = unquote(parse_qs(urlparse(h).query)["uddg"][0])
            out.append(h)
        return out
    except requests.RequestException:
        return []


def harvest_one(name: str, domain: str, seed: str) -> dict:
    """Find the best official page for one programme and return it as a raw record.

    A page counts only if it has enough text and at least 70% of the name's words. We stop crawling further links
    once a page reaches 90%.
    """
    record = {"id": slug(name), "name": name, "official_domain": domain,
              "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    tried, best = [], None

    def consider(resp, how):
        nonlocal best
        title, text = page_text(resp.text)
        rel = relevance(name, title, text)
        tried.append((resp.url, round(rel, 2)))
        if len(text) >= MIN_TEXT and rel >= 0.7 and (best is None or rel > best[0]):
            best = (rel, resp.url, title, text, how)

    seed_resp = get(seed)
    if seed_resp:
        consider(seed_resp, "seed URL")
    if not best or best[0] < 0.9:
        hubs = [seed_resp] if seed_resp else []
        root = get(f"https://www.{domain}/") or get(f"https://{domain}/")
        if root:
            hubs.append(root)
        for hub in hubs:
            for url in _links(hub, domain, name):
                if any(url == t[0] for t in tried):
                    continue
                r = get(url)
                if r:
                    consider(r, "crawled official site")
                if best and best[0] >= 0.9:
                    break
    if not best:
        for url in _search(f"{name} site:{domain}"):
            if is_official(url, domain):
                r = get(url)
                if r:
                    consider(r, "web search")
                if best:
                    break
    if best:
        rel, url, title, text, how = best
        return {**record, "status": "ok", "url": url, "title": title, "found_via": how,
                "relevance": round(rel, 2), "official_source": is_official(url, domain), "text": text[:30000]}
    return {**record, "status": "no_usable_page", "tried": tried[:10]}


def harvest_all(progress=None, only_missing: bool = True) -> list[dict]:
    """Harvest every catalogue entry, skipping those already saved with status ok unless only_missing is False."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for i, (name, domain, seed) in enumerate(SOURCES):
        path = RAW_DIR / f"{slug(name)}.json"
        rec = json.loads(path.read_text()) if path.exists() else None
        if not (only_missing and rec and rec.get("status") == "ok"):
            rec = harvest_one(name, domain, seed)
            path.write_text(json.dumps(rec, indent=1))
        out.append(rec)
        if progress:
            progress(i + 1, len(SOURCES), rec)
    return out
