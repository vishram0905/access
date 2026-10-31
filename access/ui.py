"""Shared look and feel for the ACCESS web app.

Every page calls setup() first, which injects the stylesheet below and draws the top navigation. We keep the
design tokens (colours, radii, type scale) in one place so the four pages stay consistent, and we draw icons as
small inline SVGs instead of emoji, which render differently on every operating system.
"""
import html
from datetime import datetime

import streamlit as st

PAGES = [("views/search.py", "Search"), ("views/how.py", "How it works"),
         ("views/database.py", "Database"), ("views/quality.py", "Quality")]

# Icon paths in the style of the Lucide icon set (24x24 viewBox, 2px stroke). We inline them because Streamlit
# cannot load an icon font for raw HTML blocks, and emoji looked out of place next to the rest of the type.
ICONS = {
    "check": "<path d='M20 6 9 17l-5-5'/>",
    "x": "<path d='M18 6 6 18M6 6l12 12'/>",
    "help": "<circle cx='12' cy='12' r='10'/><path d='M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3'/><path d='M12 17h.01'/>",
    "clock": "<circle cx='12' cy='12' r='10'/><path d='M12 6v6l4 2'/>",
    "calendar": "<rect x='3' y='4' width='18' height='18' rx='2'/><path d='M16 2v4M8 2v4M3 10h18'/>",
    "repeat": "<path d='m17 2 4 4-4 4'/><path d='M3 11v-1a4 4 0 0 1 4-4h14'/><path d='m7 22-4-4 4-4'/>"
              "<path d='M21 13v1a4 4 0 0 1-4 4H3'/>",
    "ban": "<circle cx='12' cy='12' r='10'/><path d='m4.9 4.9 14.2 14.2'/>",
    "wallet": "<path d='M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2"
              "a1 1 0 0 0-1-1'/><path d='M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4'/>",
    "shield": "<path d='M20 13c0 5-3.5 7.5-7.7 9a1 1 0 0 1-.7 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.2-2.7"
              "a1.2 1.2 0 0 1 1.6 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z'/><path d='m9 12 2 2 4-4'/>",
    "archive": "<rect x='2' y='3' width='20' height='5' rx='1'/><path d='M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"
               "M10 12h4'/>",
    "alert": "<path d='m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3'/><path d='M12 9v4"
             "M12 17h.01'/>",
    "external": "<path d='M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'/>",
    "library": "<path d='m16 6 4 14M12 6v14M8 8v12M4 4v16'/>",
    "user": "<circle cx='12' cy='8' r='5'/><path d='M20 21a8 8 0 0 0-16 0'/>",
    "target": "<circle cx='12' cy='12' r='10'/><circle cx='12' cy='12' r='6'/><circle cx='12' cy='12' r='2'/>",
    "file": "<path d='M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z'/><path d='M14 2v4a2 2 0 0 0 2 2h4'/>",
    "book": "<path d='M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z'/>",
    "wrench": "<path d='M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1"
              "-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z'/>",
}


def icon(name: str, size: int = 14) -> str:
    """An inline SVG icon that takes the text colour of whatever it sits in."""
    return (f"<svg class='ic' width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' stroke='currentColor' "
            f"stroke-width='2' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>{ICONS[name]}</svg>")


CSS = """
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet">
<style>
:root{--ink:#0F172A;--body:#334155;--muted:#64748B;--line:#E5E7EB;--soft:#F6F7F9;--accent:#4338CA;--accent-soft:#EEF2FF;
      --ok:#047857;--ok-soft:#ECFDF5;--amber:#B45309;--amber-soft:#FFFBEB;--bad:#B91C1C;--bad-soft:#FEF2F2;
      --radius:14px;--shadow:0 1px 2px rgba(15,23,42,.04),0 4px 14px rgba(15,23,42,.04)}
html, body, [class*="st-"], .stMarkdown, button, input, textarea, select{font-family:'Inter',system-ui,sans-serif}
/* Streamlit draws its own icons with an icon font looked up by name ("check", "expand_more"), so our font rule
   above must never reach them. */
[data-testid="stIconMaterial"], [data-testid^="stExpanderIcon"], .material-symbols-rounded, .material-icons{font-family:'Material Symbols Rounded'!important}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stSidebarCollapsedControl"]{display:none!important}
header[data-testid="stHeader"]{height:0;background:transparent}
.block-container{padding-top:1.2rem;max-width:1080px}
h1,h2,h3{letter-spacing:-.02em;color:var(--ink)}
.ic{display:inline-block;vertical-align:-2px;flex:none}

/* Top navigation. The links live in Streamlit columns, which stack vertically on phones; inside our keyed
   container we keep them on one scrollable row instead. */
.st-key-topnav [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:4px!important;align-items:center}
.st-key-topnav [data-testid="stColumn"]{min-width:0!important;width:auto!important;flex:0 0 auto!important}
.st-key-topnav [data-testid="stColumn"]:first-child{flex:1 0 auto!important}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:1.12rem;color:var(--ink);letter-spacing:-.02em}
.brand .mark{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,#4338CA,#0EA5E9);
             display:grid;place-items:center;color:#fff;font-size:.95rem}
.brand small{font-weight:500;color:var(--muted);font-size:.78rem;letter-spacing:0}
[data-testid="stPageLink"] a{border-radius:999px;padding:5px 12px;justify-content:center;transition:background .15s}
[data-testid="stPageLink"] a:hover{background:var(--soft)}
[data-testid="stPageLink"] a[aria-current="page"], [data-testid="stPageLink-NavLink"][aria-current="page"]{background:var(--accent-soft)}
[data-testid="stPageLink"] p{font-size:.92rem;color:var(--body)}
[data-testid="stPageLink"] a[aria-current="page"] p{color:var(--accent)!important;font-weight:600}
.st-key-topnav [data-testid="stCheckbox"] p{font-size:.85rem;color:var(--muted)}
.navline{border-bottom:1px solid var(--line);margin:6px 0 22px}
[data-testid="stPageLink"] p, .brand{white-space:nowrap}
[data-testid="stCheckbox"] p{white-space:normal}
@media (max-width:1180px){.brand small{display:none}}
@media (max-width:700px){
  .st-key-topnav [data-testid="stHorizontalBlock"]{overflow-x:auto;overflow-y:hidden;padding:4px 0;scrollbar-width:none}
  .st-key-topnav [data-testid="stHorizontalBlock"]::-webkit-scrollbar{display:none}
  .brand{font-size:1rem}.brand .mark{width:26px;height:26px;font-size:.85rem}
  [data-testid="stPageLink"] a{padding:4px 8px}[data-testid="stPageLink"] p{font-size:.85rem}
  /* The live system panel is for the research machine; on a phone we drop its switch to save the row. */
  .st-key-topnav [data-testid="stColumn"]:last-child{display:none}
  .block-container{padding-left:1rem;padding-right:1rem}
}

/* hero */
.eyebrow{display:inline-block;font-size:.76rem;font-weight:600;color:var(--accent);background:var(--accent-soft);
         padding:4px 12px;border-radius:999px;margin-bottom:14px;letter-spacing:.01em}
.hero{text-align:center;padding:26px 0 8px}
.hero h1{font-family:'Source Serif 4',Georgia,serif;font-size:2.9rem;line-height:1.08;margin:0 auto 12px;max-width:760px;font-weight:700}
.hero p.lead{color:var(--muted);font-size:1.06rem;line-height:1.6;max-width:640px;margin:0 auto}
.trust{display:flex;justify-content:center;gap:26px;flex-wrap:wrap;margin:18px 0 28px;color:var(--muted);font-size:.86rem}
.trust span{display:flex;align-items:center;gap:7px}
.trust i{font-style:normal;width:20px;height:20px;border-radius:50%;background:var(--ok-soft);color:var(--ok);
         display:grid;place-items:center}

/* Example researchers: one compact pill per person instead of two-line buttons. */
.st-key-examples [data-testid="stButton"] button{border-radius:999px;min-height:38px;padding:4px 8px;max-width:100%;
         border:1px solid var(--line);background:#fff;box-shadow:none}
.st-key-examples [data-testid="stButton"] button:hover{border-color:#C7D2FE;background:var(--accent-soft);color:var(--accent)}
.st-key-examples [data-testid="stButton"] p{font-size:.83rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hint{font-size:.85rem;color:var(--muted);margin-bottom:8px}

/* Form and buttons */
[data-testid="stForm"]{border-radius:var(--radius)!important;border-color:var(--line)!important;box-shadow:var(--shadow);
         background:#fff}
[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"], button[kind="primary"]{border-radius:10px;
         min-height:44px;font-weight:600;background:var(--accent);border-color:var(--accent)}
[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"]:hover{background:#3730A3;border-color:#3730A3}

/* cards + chips */
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:var(--radius)!important}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;font-size:.76rem;font-weight:500;
      background:var(--soft);color:var(--body);border:1px solid var(--line);line-height:1.5}
.chip.ok{background:var(--ok-soft);color:var(--ok);border-color:#A7F3D0}
.chip.amber{background:var(--amber-soft);color:var(--amber);border-color:#FDE68A}
.chip.bad{background:var(--bad-soft);color:var(--bad);border-color:#FECACA}
.chip.acc{background:var(--accent-soft);color:var(--accent);border-color:#C7D2FE}
.res-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
.res-title{font-size:1.1rem;font-weight:650;color:var(--ink)!important;text-decoration:none!important;line-height:1.3}
.res-title .ic{color:var(--muted);margin-left:6px;vertical-align:0}
.res-title:hover{color:var(--accent)!important}
.res-title:hover .ic{color:var(--accent)}
.res-sub{color:var(--muted);font-size:.86rem;margin-top:3px}
.why, .stMarkdown p.why{color:var(--body);font-size:.92rem!important;line-height:1.6;margin:10px 0 4px}
/* Expanders inside result cards: quieter than the card itself, so the card reads as one unit. */
[data-testid="stExpander"] details{border-radius:10px!important;border-color:var(--line)!important}
[data-testid="stExpander"] summary{padding-top:.55rem;padding-bottom:.55rem}
[data-testid="stExpander"] summary p{font-size:.88rem;font-weight:500;color:var(--body)}
/* Eligibility checks list */
.check{display:flex;gap:10px;align-items:flex-start;margin:8px 0 2px;font-size:.9rem;color:var(--ink);line-height:1.5}
.check .st{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;flex:none;margin-top:1px}
.check .st.pass{background:var(--ok-soft);color:var(--ok)}
.check .st.fail{background:var(--bad-soft);color:var(--bad)}
.check .st.near, .check .st.conditional{background:var(--amber-soft);color:var(--amber)}
.check .st.unknown{background:var(--soft);color:var(--muted)}
.evidence{margin:2px 0 8px 30px;font-size:.8rem;color:var(--muted);border-left:2px solid var(--line);padding-left:10px;
          line-height:1.55}
.fit{min-width:62px;height:62px;border-radius:50%;display:grid;place-items:center;text-align:center;line-height:1;
     background:conic-gradient(var(--accent) calc(var(--p)*1%),#E0E7FF 0);position:relative}
.fit::before{content:"";position:absolute;inset:6px;border-radius:50%;background:#fff}
.fit b{position:relative;font-size:1.05rem;color:var(--ink)}
.fit small{position:relative;display:block;font-size:.6rem;color:var(--muted);margin-top:2px;font-weight:500}
.note{font-size:.84rem;color:var(--amber);background:var(--amber-soft);border-radius:10px;padding:7px 11px;margin-top:8px}
.muted{color:var(--muted)}
.section-title{font-size:1.35rem;font-weight:700;margin:26px 0 4px;letter-spacing:-.02em}
.section-sub{color:var(--muted);margin-bottom:14px}

/* stats */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:8px 0 6px}
.kpi{border:1px solid var(--line);border-radius:14px;padding:14px 16px;background:#fff}
.kpi b{display:block;font-size:1.7rem;letter-spacing:-.02em;color:var(--ink)}
.kpi span{color:var(--muted);font-size:.82rem}
.funnel-row{display:grid;grid-template-columns:230px 1fr 90px;gap:12px;align-items:center;margin:7px 0;font-size:.9rem}
.funnel-bar{height:14px;border-radius:999px;background:var(--soft);overflow:hidden}
.funnel-bar div{height:100%;border-radius:999px;background:linear-gradient(90deg,#4338CA,#0EA5E9)}
.funnel-row .n{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.foot{color:var(--muted);font-size:.78rem;text-align:center;margin:40px 0 10px}
@media (max-width:640px){.hero h1{font-size:2.1rem}.funnel-row{grid-template-columns:1fr 70px}.funnel-row .funnel-bar{display:none}}
</style>
"""


def html_block(markup: str):
    """Render raw HTML through st.markdown.

    Markdown treats indented lines as code and ends an HTML block at the first blank line, so we strip every line
    and drop the blank ones before handing the markup over.
    """
    st.markdown("\n".join(line.strip() for line in markup.splitlines() if line.strip()), unsafe_allow_html=True)


def _remember_stats():
    st.session_state["show_stats"] = st.session_state["stats_toggle"]


def setup():
    """Inject the stylesheet and draw the top navigation. Every page calls this first."""
    html_block(CSS)
    from .config import PUBLIC
    if PUBLIC:  # Streamlit Cloud lays its own toolbar strip over the top of the page; we keep the menu below it
        html_block("<style>.block-container{padding-top:4.75rem!important}"
                   "header[data-testid='stHeader']{pointer-events:none}</style>")
    # The key gives the container a CSS class (st-key-topnav), which is how the stylesheet keeps the links on one
    # row on small screens.
    with st.container(key="topnav"):
        left, *links, tog = st.columns([2.1, 0.9, 1.2, 1, 0.9, 0.8], vertical_alignment="center")
        left.markdown("<div class='brand'><div class='mark'>A</div>ACCESS <small>research funding finder</small>"
                      "</div>", unsafe_allow_html=True)
        for col, (path, label) in zip(links, PAGES):
            col.page_link(path, label=label)
        # Widget state is per page in Streamlit, so we mirror the toggle into session state to keep it on when the
        # visitor moves to another page.
        tog.toggle("Stats", key="stats_toggle", value=st.session_state.get("show_stats", False),
                   on_change=_remember_stats)
    st.markdown("<div class='navline'></div>", unsafe_allow_html=True)
    if st.session_state.get("show_stats"):
        stats_panel()


STATS_CSS = """<style>
.term{background:#0B1020;color:#C9D1E9;border-radius:16px;padding:16px 18px;margin:-8px 0 22px;
      font-family:'JetBrains Mono','SF Mono',Menlo,monospace;font-size:.76rem;line-height:1.55;
      box-shadow:0 10px 30px rgba(11,16,32,.25)}
.term-head{display:flex;justify-content:space-between;align-items:center;color:#7C8AB8;margin-bottom:10px}
.term-head b{color:#E2E8FF;letter-spacing:.04em}
.live{display:inline-block;width:7px;height:7px;border-radius:50%;background:#22C55E;margin-right:6px;
      box-shadow:0 0 0 0 rgba(34,197,94,.7);animation:pulse 1.6s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(34,197,94,.6)}70%{box-shadow:0 0 0 7px rgba(34,197,94,0)}
                 100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
.tgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.tbox{border:1px solid #1E2745;border-radius:12px;padding:10px 12px;background:#0E1428}
.tbox h6{margin:0 0 6px;color:#8EA2FF;font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;font-family:inherit}
.kv{display:flex;justify-content:space-between;gap:10px}
.kv span:last-child{color:#F1F5FF;font-variant-numeric:tabular-nums;text-align:right}
.spark{display:flex;align-items:flex-end;gap:1px;height:34px;margin:6px 0 2px}
.spark i{flex:1;background:linear-gradient(180deg,#38BDF8,#6366F1);border-radius:1px;min-height:1px}
.m-ok{color:#4ADE80}.m-warn{color:#FBBF24}.m-bad{color:#F87171}
.mrow{display:grid;grid-template-columns:1fr auto;gap:8px;border-bottom:1px dashed #1E2745;padding:2px 0}
.mrow small{color:#64748B}
</style>"""


@st.fragment(run_every=10)
def stats_panel():
    from . import stats
    from .config import PUBLIC, PUBLIC_SNAPSHOT
    try:
        if PUBLIC:  # the crawl log and the agents stay on the research machine: show the build-time snapshot
            import json
            from .lookup import LOOKUP
            snap = json.loads((LOOKUP / "stats_snapshot.json").read_text())
            c, p, sy, ms = snap["crawler"], snap["pipeline"], snap["system"], stats.models()
        else:
            c, p, ms, sy = stats.crawler(), stats.pipeline(), stats.models(), stats.system()
    except Exception as e:  # never let the stats panel break a page
        st.caption(f"Stats unavailable right now ({type(e).__name__}).")
        return

    def kv(k, v):
        return f"<div class='kv'><span>{esc(k)}</span><span>{v}</span></div>"

    top = max(c["per_min"]) or 1
    spark = "".join(f"<i style='height:{max(3, 100 * v / top):.0f}%' title='{v} requests'></i>" for v in c["per_min"])
    pg, d = p["pages"], p["decisions_1h"]
    lat = f"{c['p50_ms']:,} / {c['p95_ms']:,} ms" if c["p50_ms"] else "-"
    crawl = (f"<div class='tbox'><h6>Crawler · last 60 min</h6><div class='spark'>{spark}</div>"
             + kv("requests", f"{c['requests']:,} ({c['requests'] / 60:.1f}/min)")
             + kv("handshake rate", f"{c['handshake_pct']}%") + kv("usable pages", f"{c['ok']:,}")
             + kv("refused · robots.txt", f"{c['refused']:,} · {c['robots']:,}")
             + kv("timeouts / conn / TLS", f"{c['timeouts']:,}") + kv("latency p50 / p95", lat)
             + kv("sites done · queued", f"{p['sites'].get('done', 0):,} · {p['sites'].get('new', 0):,}")
             + kv("protected (stubs)", f"{p['sites'].get('protected', 0):,}") + "</div>")
    scrape = (f"<div class='tbox'><h6>Scraper + annotator</h6>"
              + kv("pages stored (1 h)", f"{p['new_pages_1h']:,}") + kv("pages annotated (1 h)", f"{p['annotated_1h']:,}")
              + kv("annotation queue", f"{pg.get('candidate', 0) + pg.get('annotating', 0):,}")
              + kv("in progress", f"{pg.get('annotating', 0):,}")
              + kv("dropped by free filter", f"{pg.get('not_programme', 0):,}")
              + kv("duplicates", f"{pg.get('duplicate', 0):,}")
              + kv("JS render queue", f"{p['render_queue']:,}" + (" (paused)" if sy["renderer_paused"] else ""))
              + kv("annotator workers", sy["workers"].get("annotator")) + "</div>")
    judged = d.get("accepted", 0) + d.get("accepted_with_warning", 0) + d.get("rejected", 0)
    judge = (f"<div class='tbox'><h6>Judge panel</h6>"
             + kv("decisions (1 h)", f"{judged:,}")
             + kv("accepted · rejected", f"{d.get('accepted', 0) + d.get('accepted_with_warning', 0):,} · "
                                         f"{d.get('rejected', 0):,}")
             + kv("duplicates skipped (1 h)", f"{p['dup_skips_1h']:,}")
             + kv("failed panels (1 h)", f"{p['judge_failures_1h']:,}")
             + kv("waiting for judges", f"{pg.get('annotated', 0) + pg.get('judging', 0):,}")
             + kv("published (active)", f"{pg.get('active', 0):,}")
             + kv("critic workers", sy["workers"].get("critic"))
             + kv("search index rebuilt", sy["lookup_built"]) + "</div>")
    rows = "".join(f"<div class='mrow'><span>{esc(m['model'].split('/')[-1])} <small>{esc(m['family'])} · "
                   f"{esc(m['role'])}</small>{'<br><small>' + esc(m['used']) + '</small>' if m['used'] else ''}"
                   f"</span><span class='m-{m['kind']}'>{esc(m['state'])}</span></div>" for m in ms)
    models = f"<div class='tbox' style='grid-column:span 2'><h6>Models · quota state</h6>{rows}</div>"
    load = " ".join(f"{x:.2f}" for x in sy["load"])
    system = (f"<div class='tbox'><h6>System</h6>"
              + kv("RAM free", f"{sy['ram_free_gb']:.1f} / {sy['ram_total_gb']:.0f} GB")
              + kv("swap used", f"<span class='m-{'bad' if sy['swap_gb'] > 12 else 'ok'}'>{sy['swap_gb']:.1f} GB</span>")
              + kv(f"load avg ({sy['cpus']} cores)", load)
              + kv("agents up", f"{sy['agents_up']} / {sy['agents_total']}")
              + kv("crawl workers cap", sy["workers"].get("crawl_cap"))
              + kv("main DB", f"{sy['db_mb']:,.0f} MB") + kv("crawl datalog", f"{sy['fetchlog_mb']:,.0f} MB") + "</div>")
    trace = ""
    res = st.session_state.get("result")
    if res and res.get("trace"):
        trace = ("<div class='tbox'><h6>Last search · stage timings</h6>" + "".join(
            kv(ev["key"].replace("_", " "), f"{ev.get('seconds', 0):.1f}s") for ev in res["trace"])
                 + kv("total", f"{sum(ev.get('seconds', 0) for ev in res['trace']):.1f}s") + "</div>")
    html_block(STATS_CSS + f"<div class='term'><div class='term-head'><b>&gt;_ SYSTEM STATS</b>"
               + (f"<span>as of {esc(PUBLIC_SNAPSHOT)} · model quotas live</span></div>" if PUBLIC else
                  f"<span><span class='live'></span>live · refreshes every 10 s · {datetime.now():%H:%M:%S}</span></div>")
               + f"<div class='tgrid'>{crawl}{scrape}{judge}{system}{models}{trace}</div></div>")


def footer():
    st.markdown("<div class='foot'>ACCESS · AI-Curated Constraint-Aware Eligibility and Scholarly Search · "
                "research prototype by NTU GP8001 Group 5.<br>Always confirm details on the funder's official website "
                "before applying.</div>", unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def chip(text, kind="", ic: str | None = None) -> str:
    """A small rounded label. kind picks the colour (ok, amber, bad, acc); ic adds an icon from ICONS."""
    return f"<span class='chip {kind}'>{icon(ic, 12) if ic else ''}{esc(text)}</span>"


def nice(s) -> str:
    return str(s or "").replace("_", " ").strip().capitalize()
