"""The Database page: how far the library has been built, read straight from the database, plus an explorer
for the verified programmes themselves."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from access.config import DATA
from access.db import connect
from access.logtail import tail_lines
from access.lookup import LOOKUP, load as load_lookup
from access.schema import human, human_title
from access.ui import html_block, esc, footer, nice, setup, stats_panel

AGENTS = DATA / "agents"
AGENT_NAMES = {"scout": "Scout", "scraper": "Scraper + Annotator", "critic": "Judge panel", "auditor": "Auditor",
               "sentinel": "Sentinel"}


@st.cache_data(ttl=60)
def progress() -> dict:
    with connect() as con:
        sites = dict(con.execute("SELECT status, COUNT(*) FROM sites GROUP BY status").fetchall())
        pages = dict(con.execute("SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall())
        dec = dict(con.execute("SELECT decision, COUNT(*) FROM listings GROUP BY decision").fetchall())
        daily = con.execute("SELECT substr(verified_at,1,10) d, COUNT(*) FROM listings WHERE decision IN "
                            "('accepted','accepted_with_warning') AND verified_at IS NOT NULL GROUP BY d ORDER BY d"
                            ).fetchall()
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        last24 = con.execute("SELECT COUNT(*) FROM listings WHERE decision IN ('accepted','accepted_with_warning') "
                             "AND verified_at >= ?", (since,)).fetchone()[0]
        try:
            stubs = con.execute("SELECT COUNT(*) FROM stubs").fetchone()[0]
            mut = con.execute("SELECT COUNT(*), SUM(detected) FROM mutation_tests").fetchone()
        except Exception:
            stubs, mut = 0, (0, 0)
    return {"sites": sites, "pages": pages, "decisions": dec, "daily": [tuple(r) for r in daily], "last24": last24,
            "stubs": stubs, "mutations": tuple(mut), "at": datetime.now().strftime("%H:%M")}


def agent_status() -> list[tuple[str, str, str]]:
    """(name, state, colour) for each data agent, from its pid file and latest log line."""
    from access.config import PUBLIC
    if PUBLIC:
        return [(name, "Runs on the research machine", "#94A3B8") for name in AGENT_NAMES.values()]
    out = []
    for key, name in AGENT_NAMES.items():
        alive = False
        try:
            os.kill(int((AGENTS / f"{key}.pid").read_text()), 0)
            alive = True
        except Exception:
            pass
        state, colour = ("Running", "#10B981") if alive else ("Stopped", "#EF4444")
        log = AGENTS / f"{key}.log"
        if alive and log.exists():
            tail = [l for l in tail_lines(log, 60) if "AFC" not in l]
            last = tail[-1] if tail else ""
            m = re.search(r"⏸.*?re-checking at (\d\d:\d\d)", "\n".join(tail[-8:]))
            if m and m.group(1) >= datetime.now().strftime("%H:%M"):
                state, colour = f"Waiting for free AI quota (re-checks {m.group(1)})", "#F59E0B"
            elif "paused" in last.lower():
                state, colour = "Paused (waiting for AI quota)", "#F59E0B"
        out.append((name, state, colour))
    return out


def bar_chart(counts: dict, label: str):
    df = pd.DataFrame({"name": [human_title(k) for k in counts], "n": list(counts.values())})
    return (alt.Chart(df).mark_bar(cornerRadiusEnd=6, color="#2F6690", height=18)
            .encode(x=alt.X("n:Q", title=None, axis=alt.Axis(grid=False, labels=False, ticks=False, domain=False)),
                    y=alt.Y("name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=180, ticks=False, domain=False)),
                    tooltip=[alt.Tooltip("name:N", title=label), alt.Tooltip("n:Q", title="Programmes")])
            .properties(height=max(120, 32 * len(df))).configure_view(stroke=None))


setup()
programs, facets, vecs, meta = load_lookup()
p = progress()
pages, sites, dec = p["pages"], p["sites"], p["decisions"]
published = len(programs)
quoted_rules = sum(len(x.get("rules") or []) for x in programs)  # every kept rule carries a quote from the page


def real_countries(xs) -> int:
    """Distinct host countries. We split multi-country labels and skip placeholders such as 'Not stated' or
    'Any country', which an earlier version of this page counted as countries."""
    skip = {"", "Multiple", "Not stated", "Any country", "Asia", "Europe", "North America", "Global"}
    out = set()
    for x in xs:
        for part in re.split(r",| or ", x.get("host_country") or ""):
            if part.strip() and part.strip() not in skip:
                out.add(part.strip())
    return len(out)


countries = real_countries(programs)

html_block("""<div class='hero'><div class='eyebrow'>The library</div>
<h1>A verified library of research funding</h1>
<p class='lead'>Built and checked continuously by AI agents. Every programme below was verified against its
official page by three independent AI judges.</p></div>""")

from access.config import PUBLIC, PUBLIC_SNAPSHOT
stamp = (f"Last updated {PUBLIC_SNAPSHOT}" if PUBLIC else f"Live from the database · updated {p['at']}")
html_block(f"""<div class='kpis'>
<div class='kpi'><b>{published:,}</b><span>verified programmes, searchable now</span></div>
<div class='kpi'><b>{quoted_rules:,}</b><span>eligibility rules, each backed by a quote</span></div>
<div class='kpi'><b>{countries}</b><span>host countries</span></div>
<div class='kpi'><b>{sum(sites.values()):,}</b><span>funding websites discovered</span></div>
</div><div class='muted' style='font-size:.8rem;text-align:right'>{stamp}</div>""")

# The live system panel (crawler rate, queues, model quotas) is for whoever runs the agents, so we keep it behind
# a switch here instead of in the main menu.
if st.toggle("Show live system stats", key="stats_toggle"):
    stats_panel()

tab1, tab2, tab3 = st.tabs(["Build progress", "Explore the data", "Crawl log & limits"])

# ------------------------------------------------------------------ build progress
with tab1:
    total_pages = sum(pages.values())
    filtered_out = pages.get("not_programme", 0) + pages.get("duplicate", 0) + pages.get("index_page", 0)
    relevant = total_pages - filtered_out
    annotated = sum(pages.get(s, 0) for s in ("annotated", "judging", "active", "rejected"))
    judged = dec.get("accepted", 0) + dec.get("accepted_with_warning", 0) + dec.get("rejected", 0)
    funnel = [("Funding websites discovered", sum(sites.values())), ("Pages collected", total_pages),
              ("Passed the relevance filter", relevant), ("Annotated by AI", annotated),
              ("Decided by the judge panel", judged), ("Verified and published", published)]
    top = max(v for _, v in funnel) or 1
    rows = "".join(f"<div class='funnel-row'><span>{esc(k)}</span><div class='funnel-bar'><div style='width:"
                   f"{max(1.5, 100 * v / top):.1f}%'></div></div><span class='n'>{v:,}</span></div>"
                   for k, v in funnel)
    html_block(f"<div class='section-title'>Pipeline funnel</div><div class='section-sub'>From the open web to "
                f"verified records. Most pages are dropped early by free filters, before any AI is used."
                f"</div>{rows}")

    q_annot = pages.get("candidate", 0) + pages.get("annotating", 0)
    q_judge = pages.get("annotated", 0) + pages.get("judging", 0)
    html_block(f"""<div class='section-title'>Work in progress</div>
<div class='kpis'>
<div class='kpi'><b>{q_annot:,}</b><span>pages waiting for the Annotator</span></div>
<div class='kpi'><b>{q_judge:,}</b><span>records waiting for the judge panel</span></div>
<div class='kpi'><b>{dec.get('pending_full_panel', 0):,}</b><span>held until all three judges are available</span></div>
<div class='kpi'><b>{dec.get('rejected', 0):,}</b><span>rejected by the judges (not real or not supported)</span></div>
<div class='kpi'><b>{sites.get('new', 0):,}</b><span>websites still to crawl</span></div>
</div>""")

    html_block("<div class='section-title'>Agents</div>")
    html_block("".join(f"<div style='margin:4px 0;font-size:.92rem'><span class='dot' style='background:{c}'>"
                        f"</span><b>{esc(n)}</b> <span class='muted'>· {esc(s)}</span></div>"
                        for n, s, c in agent_status()))
    st.caption("The agents run on free AI tiers with daily limits. When a limit is reached they pause and "
               "resume automatically when it resets.")

    days = pd.Series([(x.get("verified_at") or "")[:10] for x in programs if x.get("verified_at")])
    if len(days):
        df = days.value_counts().sort_index().rename_axis("day").reset_index(name="verified")
        df["day"] = pd.to_datetime(df["day"])
        df["total"] = df["verified"].cumsum()
        html_block("<div class='section-title'>Growth</div><div class='section-sub'>Verified programmes published to the "
                    "library, cumulative (UTC dates).</div>")
        st.altair_chart(alt.Chart(df).mark_area(line={"color": "#C8642B"}, color=alt.Gradient(
            gradient="linear", stops=[alt.GradientStop(color="#F7E6DA", offset=0),
                                      alt.GradientStop(color="#FBF8F3", offset=1)], x1=1, x2=1, y1=1, y2=0),
            point=True).encode(x=alt.X("day:T", title=None, axis=alt.Axis(format="%d %b", tickCount="day")),
                               y=alt.Y("total:Q", title=None), tooltip=["day:T", "verified:Q", "total:Q"])
            .properties(height=220), use_container_width=True)

    if programs:
        def count(key):
            out = {}
            for x in programs:
                out[x.get(key) or "unknown"] = out.get(x.get(key) or "unknown", 0) + 1
            return out
        html_block("<div class='section-title'>What's in the library</div>")
        c1, c2, c3 = st.columns(3)
        for col, key, label in ((c1, "region", "By region"), (c2, "provider_type", "By funder type"),
                                (c3, "opportunity_type", "By funding type")):
            col.markdown(f"**{label}**")
            col.altair_chart(bar_chart(count(key), label), use_container_width=True)

# ------------------------------------------------------------------ explorer
with tab2:
    csv = LOOKUP / "programs.csv"
    if not csv.exists():
        st.info("The labelled matrix will appear here once the first programmes are verified.")
    else:
        df = pd.read_csv(csv, keep_default_na=False)
        q = st.text_input("Search", placeholder="Search by name, funder or country…", label_visibility="collapsed")
        f1, f2, f3 = st.columns(3)
        reg = f1.multiselect("Region", sorted(x for x in df["region"].unique() if x), placeholder="All regions")
        pt = f2.multiselect("Funder type", sorted(x for x in df["provider_type"].unique() if x), format_func=human_title,
                            placeholder="All funders")
        ot = f3.multiselect("Funding type", sorted(x for x in df["opportunity_type"].unique() if x),
                            format_func=human_title, placeholder="All types")
        mask = pd.Series(True, index=df.index)
        if reg:
            mask &= df["region"].isin(reg)
        if pt:
            mask &= df["provider_type"].isin(pt)
        if ot:
            mask &= df["opportunity_type"].isin(ot)
        if q:
            hay = (df["name"] + " " + df["provider"] + " " + df["host_country"]).str.lower()
            mask &= hay.str.contains(re.escape(q.lower()))
        view = df[mask]
        show_all = st.toggle("Show all labelled columns", value=False)
        main_cols = [c for c in ("name", "provider", "host_country", "region", "opportunity_type", "provider_type",
                                 "fully_funded", "next_deadline", "band", "official_url") if c in df.columns]
        st.caption(f"{len(view):,} of {len(df):,} programmes")
        shown = (view if show_all else view[main_cols]).copy()
        for col in ("opportunity_type", "provider_type"):
            if col in shown:
                shown[col] = shown[col].map(human_title)
        for col in ("fields", "career_levels"):  # stored as lists of codes
            if col in shown:
                shown[col] = shown[col].map(lambda v: ", ".join(human(x) for x in re.findall(r"[a-z_]+", str(v))))
        st.dataframe(shown, hide_index=True, use_container_width=True, height=440,
                     column_config={"official_url": st.column_config.LinkColumn("Official page", display_text="Open"),
                                    "name": st.column_config.TextColumn("Programme", width="large"),
                                    "provider": st.column_config.TextColumn("Funder", width="medium"), "host_country": "Host country", "region": "Region",
                                    "opportunity_type": "Type", "provider_type": "Funder type",
                                    "fully_funded": "Fully funded", "next_deadline": "Next deadline",
                                    "band": "Confidence"})
        st.download_button("Download the labelled matrix (CSV)", csv.read_bytes(), "access_programmes.csv",
                           "text/csv")
        dd = LOOKUP / "data_dictionary.md"
        if dd.exists():
            with st.expander("Data dictionary: what every column means"):
                st.markdown(dd.read_text())

# ------------------------------------------------------------------ crawl log
with tab3:
    @st.cache_data(ttl=600)
    def crawl_report():
        try:
            from crawl_report import build
            return build()
        except Exception:
            f = LOOKUP / "crawl_report.json"
            return json.loads(f.read_text()) if f.exists() else None

    rep = crawl_report()
    if rep:
        html_block(f"""<div class='kpis'>
<div class='kpi'><b>{rep['requests']:,}</b><span>requests made by the crawlers</span></div>
<div class='kpi'><b>{rep['handshakes']:,}</b><span>websites answered</span></div>
<div class='kpi'><b>{rep['no_handshake']:,}</b><span>no answer (timeout, DNS, certificate)</span></div>
<div class='kpi'><b>{p['stubs']:,}</b><span>protected sites kept as links only</span></div></div>""")
        st.markdown("**Outcome of every request**")
        st.dataframe([{"Outcome": k, "Requests": v} for k, v in rep["by_outcome"].items()], hide_index=True,
                      use_container_width=True)
        if rep.get("top_refusing_domains"):
            st.markdown("**Sites that most often refused automated access** (respected, never bypassed)")
            st.dataframe([{"Website": d, "Refusals": n} for d, n in rep["top_refusing_domains"]], hide_index=True,
                         use_container_width=True)
    stubs = LOOKUP / "stubs.jsonl"
    if stubs.exists():
        rows = [json.loads(x) for x in stubs.read_text().splitlines() if x.strip()]
        with st.expander(f"Known programmes we could not read ({len(rows):,})"):
            st.caption("These sites block automated access or ask crawlers not to read them. We respect that, so "
                       "they are listed with a link only and are never used for eligibility matching.")
            st.dataframe([{"Programme / site": x.get("name"), "Region": x.get("region"),
                           "Funder type": human_title(x.get("provider_type")), "Official link": x.get("url")} for x in rows],
                         hide_index=True, use_container_width=True,
                         column_config={"Official link": st.column_config.LinkColumn(display_text="Open")})
footer()
