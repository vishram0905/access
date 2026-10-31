"""Build the public demo for Streamlit Community Cloud in ~/access-space from this repository (tooling).

The public copy runs the search app only, over a fixed snapshot of the verified library. We ship the app code
(app.py, access/, views/) with excluded places removed, data/lookup, the latest unedited example searches and a
slim read-only database: page text for the searchable programmes plus the counts the Database and Quality pages
need, again without excluded places. Public mode is on by default in the published copy. API keys are never
copied; they live as app secrets on Streamlit Cloud.

Run: PYTHONPATH=. python scripts/build_public.py
"""
import json
import re
import shutil
import sqlite3
from datetime import date
from pathlib import Path

from access.config import DATA, EXCLUDED_PLACES, ROOT, RUNS_DIR, is_excluded_place
from access.evaluation import PERSONAS
from access.pipeline import is_example, list_runs

DEST = Path.home() / "access-space"
SNAPSHOT = date.today().strftime("%-d %B %Y")


def copy_code():
    """Copy the app code and Streamlit settings into the public copy."""
    for d in ("access", "views"):
        (DEST / d).mkdir(parents=True)
        for f in (ROOT / d).glob("*.py"):
            shutil.copy2(f, DEST / d / f.name)
    shutil.copy2(ROOT / "app.py", DEST / "app.py")
    shutil.copytree(ROOT / ".streamlit", DEST / ".streamlit")
    # We let the host choose the address: binding to localhost froze the hosted app.
    cfg = DEST / ".streamlit" / "config.toml"
    cfg.write_text(cfg.read_text().replace('address = "localhost"\n', ""))


def strip_places():
    """Remove excluded places from the published code.

    On the hosted app they come from the ACCESS_EXCLUDED_PLACES setting instead of being named in the source.
    We assert at the end that none is left.
    """
    for f in list((DEST / "access").glob("*.py")) + list((DEST / "views").glob("*.py")):
        s = f.read_text()
        for place in EXCLUDED_PLACES:
            s = re.sub(rf'"{place}":\s*"[^"]*",\s*', "", s)                      # dict entries
            s = re.sub(rf'"[a-z]{{2}}":\s*"{place}",\s*', "", s)                 # TLD -> country
            s = re.sub(rf'"{place}",\s*', "", s)                                   # list items
            s = re.sub(rf"\n\s*# Excluded through config\.EXCLUDED_PLACES[^\n]*\n\s*#[^\n]*{place}[^\n]*", "", s)
            s = re.sub(rf"\n\s*#[^\n]*{place}[^\n]*", "", s)                      # disabled seed lines
            s = re.sub(rf",\s*{place}\b", "", s)                                   # prose lists
        s = s.replace('EXCLUDED_PLACES = {' + ", ".join(f'"{p}"' for p in sorted(EXCLUDED_PLACES)) + '}',
                      'EXCLUDED_PLACES = {p.strip() for p in os.environ.get("ACCESS_EXCLUDED_PLACES", "").split(",") if p.strip()}')
        s = s.replace('EXCLUDED_TLDS = tuple(t.strip() for t in os.environ.get("ACCESS_EXCLUDED_TLDS", "").split(",") if t.strip())', 'EXCLUDED_TLDS = tuple(t.strip() for t in os.environ.get("ACCESS_EXCLUDED_TLDS", "").split(",") if t.strip())')
        if f.name == "config.py":  # the published copy runs as the public demo unless told otherwise
            s = s.replace('PUBLIC = os.environ.get("ACCESS_PUBLIC") == "1"', 'PUBLIC = os.environ.get("ACCESS_PUBLIC", "1") == "1"')
            s = s.replace('PUBLIC_SNAPSHOT = os.environ.get("ACCESS_SNAPSHOT_DATE", "")', f'PUBLIC_SNAPSHOT = os.environ.get("ACCESS_SNAPSHOT_DATE", "{SNAPSHOT}")')
        f.write_text(s)
    left = [f"{f.relative_to(DEST)}:{i}" for f in DEST.rglob("*.py") for i, l in enumerate(f.read_text().splitlines(), 1)
            if any(p.lower() in l.lower() for p in EXCLUDED_PLACES) or '".tw"' in l]
    assert not left, f"excluded place still named in published code: {left[:5]}"


def copy_data():
    """Copy the lookup document and one unedited example run per persona."""
    shutil.copytree(DATA / "lookup", DEST / "data" / "lookup")
    runs = DEST / "data" / "runs"
    runs.mkdir(parents=True)
    picked = {}
    for path in list_runs():
        form = json.loads(path.read_text())["form"]
        if is_example(form) and form["name"] not in picked:
            picked[form["name"]] = path
            shutil.copy2(path, runs / path.name)
    assert len(picked) == len(PERSONAS), picked


def slim_db():
    """Write a cut-down copy of the database with the same schema and no excluded places.

    Page text is kept only for the searchable programmes, which the Q&A box and application plans read.
    """
    src = sqlite3.connect(DATA / "access.db")
    out = DEST / "data" / "access.db"
    dst = sqlite3.connect(out)
    for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE type IN ('table','index') AND sql IS NOT NULL "
                              "AND name NOT LIKE 'sqlite_%'"):
        dst.execute(sql)
    library = {json.loads(l)["url"] for l in (DATA / "lookup" / "programs.jsonl").read_text().splitlines() if l.strip()}
    cols = lambda t: [r[1] for r in src.execute(f"PRAGMA table_info({t})")]
    out_place = lambda d, c: is_excluded_place(domain=d or "", country=c)
    n = {}
    # We keep every site and page row for the funnel counts, but blank the text of pages outside the library.
    for table in ("sites", "sources"):
        c = cols(table)
        rows = []
        for r in src.execute(f"SELECT * FROM {table}"):
            r = dict(zip(c, r))
            if out_place(r.get("domain"), r.get("country")):
                continue
            if table == "sources":
                r["annotation"] = None
                if r["url"] not in library:
                    r["text"] = None
            rows.append(tuple(r[k] for k in c))
        dst.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(c))})", rows)
        n[table] = len(rows)
    c = cols("listings")
    dropped = set()
    rows = []
    for r in src.execute("SELECT * FROM listings"):
        r = dict(zip(c, r))
        if is_excluded_place(json.loads(r["data"])):
            dropped.add(r["id"])
            continue
        rows.append(tuple(r[k] for k in c))
    dst.executemany(f"INSERT INTO listings VALUES ({','.join('?' * len(c))})", rows)
    n["listings"] = len(rows)
    for table, key in (("mutation_tests", "program_id"), ("audits", "program_id")):
        c = cols(table)
        rows = [r for r in src.execute(f"SELECT * FROM {table}") if dict(zip(c, r))[key] not in dropped]
        dst.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(c))})", rows)
        n[table] = len(rows)
    c = cols("stubs")
    rows = [r for r in src.execute("SELECT * FROM stubs")
            if not out_place(re.sub(r"^https?://([^/]+).*", r"\1", dict(zip(c, r))["url"] or ""), dict(zip(c, r)).get("country"))]
    dst.executemany(f"INSERT INTO stubs VALUES ({','.join('?' * len(c))})", rows)
    n["stubs"] = len(rows)
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    print("slim database:", n, f"{out.stat().st_size / 1e6:.1f} MB")


def stats_snapshot():
    """Save the Stats panel's crawler, pipeline and system figures at build time.

    The public app has no crawl log of its own, so it shows this snapshot.
    """
    from access import stats
    snap = {"crawler": stats.crawler(), "pipeline": stats.pipeline(), "system": stats.system(), "at": SNAPSHOT}
    (DEST / "data" / "lookup" / "stats_snapshot.json").write_text(json.dumps(snap, default=str))


REQUIREMENTS = """streamlit==1.52.2
pyarrow<25
numpy>=2.0
pandas>=2.0
altair>=5.0
python-dotenv>=1.0
requests>=2.31
beautifulsoup4>=4.12
psutil>=5.9
google-genai>=2.0
groq>=1.0
ollama>=0.6
fastembed==0.9.0
"""  # tested on Python 3.14 (the Streamlit Cloud default); we pin 1.52 because it keeps the classic Tornado server

README = """# ACCESS: AI-Curated Constraint-Aware Eligibility & Scholarly Search

GP8000 / GP8001 AI Literacy · Cohort C · Group 5

A multi-agent system that identifies the research funding for which a researcher is eligible and traces every
stated condition to the funder's own page. **This is a public demo of a work-in-progress prototype**: it searches a
fixed snapshot of the verified library ({snapshot}). Searches are not stored. AI features run on free quotas and
are limited per visit.

Documentation, results, glossary and test report: https://vishram0905.github.io/access-docs/

Run locally: `pip install -r requirements.txt && streamlit run app.py` (API keys as environment variables
GEMINI_API_KEY, GROQ_API_KEY and NVIDIA_API_KEY; search and eligibility work without them).
"""


def main():
    """Rebuild the public copy from scratch, keeping only its .git folder."""
    if DEST.exists():
        keep = DEST / ".git"
        for p in DEST.iterdir():
            if p != keep:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    DEST.mkdir(exist_ok=True)
    copy_code()
    strip_places()
    copy_data()
    slim_db()
    stats_snapshot()
    (DEST / "requirements.txt").write_text(REQUIREMENTS)
    (DEST / "README.md").write_text(README.format(snapshot=SNAPSHOT))
    (DEST / ".gitignore").write_text("__pycache__/\n*.pyc\n.env\n.streamlit/secrets.toml\ndata/cache/\n")
    size = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file() and ".git" not in f.parts)
    print(f"built {DEST} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
