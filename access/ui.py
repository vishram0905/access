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
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* Design tokens. The palette is shared with the project slides and the documentation site: navy ink on warm
   paper, with one orange accent reserved for the primary action and for evidence. */
:root{--ink:#1B2A3A;--body:#3D4A57;--muted:#7A8592;--line:#E4DDD1;--soft:#F3EEE5;--paper:#FBF8F3;--card:#FFFFFF;
      --accent:#C8642B;--accent-dark:#A9521F;--accent-soft:#F7E6DA;--blue:#2F6690;--blue-soft:#E3ECF4;
      --ok:#2E7D4F;--ok-soft:#E3F1E8;--amber:#A86A12;--amber-soft:#FBF0D9;--bad:#B23B3B;--bad-soft:#F6DEDE;
      --radius:18px;--shadow:0 1px 2px rgba(27,42,58,.04),0 10px 30px -18px rgba(27,42,58,.22);
      --serif:'Fraunces',Georgia,serif}
html, body, [class*="st-"], .stMarkdown, button, input, textarea, select{font-family:'Inter',system-ui,sans-serif}
/* Streamlit draws its own icons with an icon font looked up by name ("check", "expand_more"), so our font rule
   above must never reach them. */
[data-testid="stIconMaterial"], [data-testid^="stExpanderIcon"], .material-symbols-rounded, .material-icons{font-family:'Material Symbols Rounded'!important}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stSidebarCollapsedControl"]{display:none!important}
header[data-testid="stHeader"]{height:0;background:transparent}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"]{background:var(--paper)}
.block-container{padding-top:0;padding-bottom:2rem!important;max-width:1200px}
h1,h2,h3{letter-spacing:-.02em;color:var(--ink)}
.ic{display:inline-block;vertical-align:-2px;flex:none}

/* Top navigation. The links live in Streamlit columns, which stack vertically on phones; inside our keyed
   container we keep them on one scrollable row instead. */
.st-key-topnav{border-bottom:1px solid var(--line);margin:0 0 6px;padding:10px 0 2px}
.st-key-topnav [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:6px!important;align-items:center}
.st-key-topnav [data-testid="stColumn"]{min-width:0!important;width:auto!important;flex:0 0 auto!important}
.st-key-topnav [data-testid="stColumn"]:first-child{flex:1 0 auto!important}
.brand{display:flex;align-items:center;gap:12px;font-family:var(--serif);font-weight:700;font-size:1.45rem;color:var(--ink);
       letter-spacing:-.01em}
.brand .mark{width:32px;height:32px;border-radius:50%;border:2px solid var(--ink);display:grid;place-items:center;
             font-size:.95rem;font-weight:700}
.brand small{font-family:'Inter',sans-serif;font-weight:600;color:var(--muted);font-size:.7rem;letter-spacing:.1em;
             text-transform:uppercase}
[data-testid="stPageLink"] a{border-radius:0;padding:14px 10px 15px;justify-content:center;background:transparent!important;
       border-bottom:2px solid transparent;transition:border-color .15s}
[data-testid="stPageLink"] a:hover{border-bottom-color:var(--line)}
[data-testid="stPageLink"] a[aria-current="page"], [data-testid="stPageLink-NavLink"][aria-current="page"]{border-bottom-color:var(--accent)}
[data-testid="stPageLink"] p{font-size:.93rem;color:var(--body);font-weight:500}
[data-testid="stPageLink"] a[aria-current="page"] p{color:var(--ink)!important;font-weight:600}
.navline{display:none}
[data-testid="stPageLink"] p, .brand{white-space:nowrap}
[data-testid="stCheckbox"] p{white-space:normal}
@media (max-width:1180px){.brand small{display:none}}
@media (max-width:700px){
  .st-key-topnav [data-testid="stHorizontalBlock"]{overflow-x:auto;overflow-y:hidden;padding:2px 0;scrollbar-width:none}
  .st-key-topnav [data-testid="stHorizontalBlock"]::-webkit-scrollbar{display:none}
  .brand{font-size:1.2rem}.brand .mark{width:28px;height:28px;font-size:.85rem}
  [data-testid="stPageLink"] a{padding:12px 7px 13px}[data-testid="stPageLink"] p{font-size:.86rem}
  .block-container{padding-left:1rem;padding-right:1rem}
}

/* Shared page header for the inner pages */
.eyebrow{display:inline-flex;align-items:center;gap:10px;font-size:.74rem;font-weight:600;color:var(--accent);
         letter-spacing:.14em;text-transform:uppercase;margin-bottom:16px}
.eyebrow::before{content:"";width:26px;height:1px;background:var(--accent)}
.hero{text-align:center;padding:40px 0 12px}
.hero h1, .how-hero h1{font-family:var(--serif)!important;font-size:3.1rem;line-height:1.05;margin:0 auto 14px;max-width:820px;
         font-weight:600!important;letter-spacing:-.025em}
.hero p.lead{color:var(--body);font-size:1.08rem;line-height:1.65;max-width:660px;margin:0 auto}
.section-title{font-family:var(--serif);font-size:1.7rem;font-weight:600;margin:34px 0 4px;letter-spacing:-.02em;color:var(--ink)}
.section-sub{color:var(--muted);margin-bottom:16px}

/* Search page: pitch on the left, form card on the right */
.hero-l{padding:56px 0 8px}
.hero-l h1{font-family:var(--serif)!important;font-size:4rem;line-height:1.02;margin:0 0 24px;font-weight:600!important;
           letter-spacing:-.03em}
.hero-l h1 em{font-style:italic;color:var(--accent);font-weight:500}
.hero-l .lead{color:var(--body);font-size:1.12rem;line-height:1.7;margin:0 0 34px;max-width:520px}
.proof{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.proof div{padding:18px 0}
.proof div+div{border-left:1px solid var(--line);padding-left:22px}
.proof b{display:block;font-family:var(--serif);font-size:2.1rem;font-weight:600;letter-spacing:-.02em;color:var(--ink)}
.proof span{font-size:.82rem;color:var(--muted)}
.pull{display:flex;gap:14px;margin-top:28px;color:var(--body);font-size:.92rem;line-height:1.6;max-width:520px}
.pull i{font-family:var(--serif);font-style:normal;font-size:2.6rem;line-height:.8;color:var(--accent)}
.st-key-formcard{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:30px 30px 22px;
       box-shadow:0 30px 60px -30px rgba(27,42,58,.28);margin-top:40px}
.form-title{font-family:var(--serif);font-size:1.6rem;font-weight:600;color:var(--ink);letter-spacing:-.01em}
.form-sub{font-size:.9rem;color:var(--muted);margin:2px 0 16px}
.st-key-formcard [data-testid="stForm"]{border:none!important;padding:0!important;box-shadow:none!important;background:transparent}
@media (max-width:640px){.hero-l{padding-top:28px}.hero-l h1{font-size:2.5rem}.proof b{font-size:1.6rem}.pull{display:none}
  .st-key-formcard{padding:22px 18px 14px;margin-top:16px}}

/* Homepage: centred hero, then one search bar. Sections below share a single vertical rhythm (96px). */
.hero-c{text-align:center;padding:72px 0 30px;max-width:860px;margin:0 auto}
.hero-c .eyebrow::after{content:"";width:26px;height:1px;background:var(--accent)}
.hero-c h1{font-family:var(--serif)!important;font-size:4.2rem;line-height:1.02;font-weight:600!important;
           letter-spacing:-.03em;margin:0 0 22px}
.hero-c h1 em{font-style:italic;color:var(--accent);font-weight:500}
.hero-c .lead{color:var(--body);font-size:1.15rem;line-height:1.65;max-width:620px;margin:0 auto}
.st-key-searchbar{max-width:1000px;margin:8px auto 0;background:#fff;border:1px solid var(--line);border-radius:24px;
       padding:20px 22px 6px;box-shadow:0 40px 80px -40px rgba(27,42,58,.35),0 2px 6px rgba(27,42,58,.04)}
.st-key-searchbar [data-testid="stForm"]{border:none!important;padding:0!important;background:transparent;box-shadow:none}
.st-key-searchbar textarea{font-size:1.02rem!important;line-height:1.55!important}
.st-key-searchbar [data-testid="stFormSubmitButton"] button{min-height:44px;font-size:.98rem}
.st-key-searchbar [data-testid="stExpander"] details{border-top:1px dashed var(--line)!important}
.st-key-searchbar [data-testid="stExpander"] summary p{font-size:.85rem;font-weight:500;color:var(--muted)}
.st-key-examples{max-width:1000px;margin:6px auto 0}
.try{font-size:.82rem;color:var(--muted);text-align:right;white-space:nowrap}
.fineprint{max-width:1000px;margin:6px auto 0;text-align:center;font-size:.76rem;color:var(--muted)}
/* Trust strip */
.logos{margin:84px 0 0;text-align:center}
.logos-k{font-size:.74rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:600;margin-bottom:20px}
.logos-row{display:flex;flex-wrap:wrap;justify-content:center;gap:14px 38px}
.logos-row span{font-family:var(--serif);font-size:1.12rem;font-weight:600;color:#9AA2AB;letter-spacing:-.005em;white-space:nowrap}
/* Landing sections */
.lp{margin:96px 0 0}
.lp-k{font-size:.74rem;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:600;margin-bottom:10px}
.lp-h{font-family:var(--serif)!important;font-size:2.6rem!important;font-weight:600!important;letter-spacing:-.025em;
      line-height:1.08;margin:0 0 34px!important;padding:0!important}
.lp-p{font-size:1.05rem;line-height:1.7;color:var(--body);margin:0 0 28px}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border-top:1px solid var(--ink)}
.step3{padding:26px 28px 0 0}
.step3+.step3{padding-left:28px;border-left:1px solid var(--line)}
.step3 span{font-family:var(--serif);font-size:1rem;color:var(--accent);font-weight:600}
.step3 h3{font-family:var(--serif)!important;font-size:1.45rem!important;font-weight:600!important;margin:10px 0 10px!important;padding:0!important}
.step3 p{font-size:.95rem;line-height:1.65;color:var(--body);margin:0}
.lp-split{display:grid;grid-template-columns:.85fr 1.15fr;gap:56px;align-items:center}
.proof-sm b{font-size:1.75rem!important}
.sample{position:relative;background:#fff;border:1px solid var(--line);border-radius:22px;padding:26px 26px 22px;
        box-shadow:0 40px 80px -40px rgba(27,42,58,.35)}
.sample-tag{position:absolute;top:-12px;left:22px;background:var(--ink);color:#fff;font-size:.7rem;font-weight:600;
            letter-spacing:.08em;text-transform:uppercase;border-radius:999px;padding:4px 11px}
.faq{border-top:1px solid var(--ink)}
.lp-faq{display:grid;grid-template-columns:.8fr 1.2fr;gap:56px;align-items:start}
.faq details{border-bottom:1px solid var(--line);padding:4px 0}
.faq summary{cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center;
             font-size:1.08rem;font-weight:600;color:var(--ink);padding:18px 0}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";font-family:var(--serif);font-size:1.6rem;font-weight:400;color:var(--accent);transition:transform .2s}
.faq details[open] summary::after{transform:rotate(45deg)}
.faq details p{margin:0 0 20px;color:var(--body);line-height:1.7;max-width:720px}
.cta-band{margin:110px 0 0;background:var(--ink);color:#fff;border-radius:28px;padding:64px 40px;text-align:center}
.cta-band h2{font-family:var(--serif)!important;color:#fff!important;font-size:2.6rem!important;font-weight:600!important;
             letter-spacing:-.02em;margin:0 0 12px!important;padding:0!important}
.cta-band p{color:#C9D3DD;margin:0 auto 28px;font-size:1.05rem}
.cta-band a{display:inline-block;background:var(--accent);color:#fff!important;text-decoration:none!important;font-weight:600;
            border-radius:12px;padding:14px 28px}
.cta-band a:hover{background:var(--accent-dark)}
@media (max-width:760px){.lp-faq{grid-template-columns:1fr;gap:0}.hero-c{padding-top:40px}.hero-c h1{font-size:2.6rem}.st-key-searchbar{padding:16px 14px 4px;border-radius:18px}
  .try{text-align:left;margin:4px 0 2px}.steps,.lp-split{grid-template-columns:1fr}.step3,.step3+.step3{padding:22px 0 0;border-left:none}
  .lp{margin-top:64px}.lp-h,.cta-band h2{font-size:1.9rem!important}.logos{margin-top:56px}.cta-band{padding:44px 22px}}

/* Example researchers: compact pills inside the form card */
.st-key-examples [data-testid="stButton"] button{border-radius:999px;min-height:34px;padding:3px 10px;max-width:100%;
         border:1px solid var(--line);background:var(--paper);box-shadow:none;color:var(--body)}
.st-key-examples [data-testid="stButton"] button:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
.st-key-examples [data-testid="stButton"] p{font-size:.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.st-key-examples [data-testid="stHorizontalBlock"]{gap:8px!important}
.hint{font-size:.85rem;color:var(--muted);margin-bottom:8px}

/* Form controls: uppercase micro-labels, white fields with a warm border, one orange primary button */
[data-testid="stWidgetLabel"] p{font-size:.72rem!important;font-weight:600!important;letter-spacing:.06em;text-transform:uppercase;
       color:var(--muted)!important}
[data-testid="stCheckbox"] [data-testid="stWidgetLabel"] p, [data-testid="stCheckbox"] label p{text-transform:none;letter-spacing:0;
       font-size:.82rem!important;font-weight:400!important}
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="textarea"], .stTextArea textarea, .stNumberInput input{
       background:#fff!important;border-color:var(--line)!important;border-radius:12px!important}
[data-baseweb="select"] > div:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="input"]:focus-within{
       border-color:var(--accent)!important;box-shadow:0 0 0 3px var(--accent-soft)!important}
[data-baseweb="tag"]{background:var(--ink)!important;border-radius:999px!important}
[data-testid="stFormSubmitButton"] button, button[kind="primary"], button[kind="primaryFormSubmit"]{border-radius:12px!important;
       min-height:50px;font-weight:600;font-size:1rem;background:var(--accent)!important;border-color:var(--accent)!important;color:#fff!important}
[data-testid="stFormSubmitButton"] button:hover, button[kind="primary"]:hover{background:var(--accent-dark)!important;border-color:var(--accent-dark)!important}
button[kind="secondary"]{border-radius:10px;border-color:var(--line)}
button[kind="secondary"]:hover{border-color:var(--accent);color:var(--accent)}
[data-testid="stForm"]{border-radius:var(--radius)!important;border-color:var(--line)!important;background:#fff}

/* Results */
.results-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;
              margin:56px 0 4px;padding-top:44px;border-top:1px solid var(--line)}
.rh-kicker{font-size:.72rem;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:6px}
.rh-title{font-family:var(--serif);font-size:2.3rem;font-weight:600;letter-spacing:-.02em;color:var(--ink);line-height:1.1}
.rh-pills{display:flex;gap:8px;flex-wrap:wrap}
.rs{font-size:.84rem;color:var(--body);background:#fff;border:1px solid var(--line);border-radius:999px;padding:6px 13px}
.rs b{color:var(--ink)}
.rs.ok b{color:var(--ok)} .rs.amber b{color:var(--amber)}
[data-baseweb="tab-list"], [data-testid="stTabs"] [role="tablist"]{gap:26px;border-bottom:1px solid var(--line)}
[data-testid="stTabs"] [role="tab"]{padding-left:2px;padding-right:2px}
[data-baseweb="tab"] p{font-size:.95rem;font-weight:600}
[data-baseweb="tab-highlight"]{background:var(--accent)!important}

/* Result cards */
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:var(--radius)!important;border-color:var(--line)!important}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-card-"]),
[data-testid="stVerticalBlockBorderWrapper"]:has(> [class*="st-key-card-"]),
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-near-"]),
[data-testid="stVerticalBlockBorderWrapper"]:has(> [class*="st-key-near-"]){background:#fff;box-shadow:var(--shadow);
       padding:18px 22px 6px;transition:box-shadow .2s,transform .2s}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-card-"]):hover{transform:translateY(-1px);
       box-shadow:0 2px 4px rgba(27,42,58,.05),0 18px 40px -20px rgba(27,42,58,.3)}
.rc{display:grid;grid-template-columns:1fr 132px;gap:24px}
.rc-prov{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600;margin-bottom:6px}
.res-title{font-family:var(--serif);font-size:1.55rem;font-weight:600;color:var(--ink)!important;text-decoration:none!important;
       line-height:1.2;letter-spacing:-.01em}
.res-title .ic{color:var(--muted);margin-left:8px;vertical-align:2px}
.res-title:hover{color:var(--accent)!important}
.res-title:hover .ic{color:var(--accent)}
.facts{display:flex;flex-wrap:wrap;gap:6px 22px;font-size:.88rem;color:var(--body);margin:12px 0 4px}
.facts span{display:inline-flex;align-items:center;gap:6px}
.facts b{color:var(--ink);font-weight:600}
.facts .ok{color:var(--ok)} .facts .amber{color:var(--amber)} .facts .bad{color:var(--bad)}
.why, .stMarkdown p.why{color:var(--body);font-size:.96rem!important;line-height:1.65;margin:12px 0 6px}
.quote-box{border-left:3px solid var(--accent);background:var(--paper);border-radius:0 10px 10px 0;padding:11px 15px;margin:12px 0 4px;
       font-size:.86rem;font-style:italic;color:var(--body);line-height:1.55}
.quote-box b{display:block;font-style:normal;font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--ink);margin-bottom:3px}
.score{border-left:1px solid var(--line);padding-left:22px;display:flex;flex-direction:column;justify-content:space-between;min-height:120px}
.score small{font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:600}
.score b{display:block;font-family:var(--serif);font-size:3.2rem;font-weight:600;line-height:1;letter-spacing:-.03em;color:var(--ink);margin-top:4px}
.meter{height:5px;border-radius:9px;background:var(--soft);margin:10px 0 0;overflow:hidden}
.meter i{display:block;height:100%;background:var(--accent);border-radius:9px}
.status{display:inline-flex;align-items:center;gap:7px;font-size:.82rem;font-weight:600;color:var(--ok);margin-top:14px}
.status i{width:20px;height:20px;border-radius:50%;background:var(--ok-soft);display:grid;place-items:center}
.status.amber{color:var(--amber)} .status.amber i{background:var(--amber-soft)}
@media (max-width:640px){.rc{grid-template-columns:1fr}.score{border-left:none;padding-left:0;border-top:1px solid var(--line);
       padding-top:12px;min-height:0;flex-direction:row;align-items:center;justify-content:space-between}.score b{font-size:2.2rem}}
/* Card details: quiet expanders separated by hairlines, so the card reads as one object */
[data-testid="stExpander"] details{border:none!important;border-top:1px solid var(--line)!important;border-radius:0!important;background:transparent}
[data-testid="stExpander"] summary{padding:.7rem .2rem}
[data-testid="stExpander"] summary p{font-size:.9rem;font-weight:600;color:var(--ink)}
[data-testid="stExpander"] summary:hover p{color:var(--accent)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;font-size:.76rem;font-weight:500;
      background:var(--soft);color:var(--body);border:1px solid var(--line);line-height:1.5}
.chip.ok{background:var(--ok-soft);color:var(--ok);border-color:#BFE0CB}
.chip.amber{background:var(--amber-soft);color:var(--amber);border-color:#F0D9A8}
.chip.bad{background:var(--bad-soft);color:var(--bad);border-color:#EBC0C0}
.chip.acc{background:var(--accent-soft);color:var(--accent-dark);border-color:#EFCDB6}
/* Eligibility checks list */
.check{display:flex;gap:10px;align-items:flex-start;margin:8px 0 2px;font-size:.9rem;color:var(--ink);line-height:1.5}
.check .st{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;flex:none;margin-top:1px}
.check .st.pass{background:var(--ok-soft);color:var(--ok)}
.check .st.fail{background:var(--bad-soft);color:var(--bad)}
.check .st.near, .check .st.conditional{background:var(--amber-soft);color:var(--amber)}
.check .st.unknown{background:var(--soft);color:var(--muted)}
.evidence{margin:2px 0 8px 30px;font-size:.8rem;color:var(--muted);border-left:2px solid var(--line);padding-left:10px;
          line-height:1.55;font-style:italic}
.note{font-size:.84rem;color:var(--amber);background:var(--amber-soft);border-radius:10px;padding:8px 12px;margin-top:8px}
.muted{color:var(--muted)}

/* stats */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:12px 0 6px}
.kpi{border:1px solid var(--line);border-radius:16px;padding:18px 20px;background:#fff;box-shadow:var(--shadow)}
.kpi b{display:block;font-family:var(--serif);font-size:2.2rem;font-weight:600;letter-spacing:-.02em;color:var(--ink)}
.kpi span{color:var(--muted);font-size:.84rem}
.funnel-row{display:grid;grid-template-columns:230px 1fr 90px;gap:12px;align-items:center;margin:8px 0;font-size:.9rem}
.funnel-bar{height:12px;border-radius:999px;background:var(--soft);overflow:hidden}
.funnel-bar div{height:100%;border-radius:999px;background:var(--blue)}
.funnel-row:last-child .funnel-bar div{background:var(--accent)}
.funnel-row .n{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.foot{color:var(--muted);font-size:.78rem;text-align:center;margin:56px 0 16px;padding-top:22px;border-top:1px solid var(--line);
      line-height:1.7}
@media (max-width:640px){.hero h1{font-size:2.2rem}.funnel-row{grid-template-columns:1fr 70px}.funnel-row .funnel-bar{display:none}
  .results-head{margin-top:30px;padding-top:28px}.rh-title{font-size:1.7rem}.res-title{font-size:1.3rem}}
</style>
"""


def html_block(markup: str):
    """Render raw HTML through st.markdown.

    Markdown treats indented lines as code and ends an HTML block at the first blank line, so we strip every line
    and drop the blank ones before handing the markup over.
    """
    st.markdown("\n".join(line.strip() for line in markup.splitlines() if line.strip()), unsafe_allow_html=True)


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
        left, *links = st.columns([3.2, 0.75, 1.05, 0.8, 0.75], vertical_alignment="center")
        left.markdown("<div class='brand'><div class='mark'>A</div>ACCESS <small>Funding finder</small></div>",
                      unsafe_allow_html=True)
        for col, (path, label) in zip(links, PAGES):
            col.page_link(path, label=label)
    # Streamlit does not mark the current page link in the HTML, so we underline it by position.
    current = [label for _, label in PAGES].index(st.session_state.get("current_page", "Search")) \
        if st.session_state.get("current_page") in [label for _, label in PAGES] else 0
    html_block(f"<style>.st-key-topnav [data-testid='stColumn']:nth-child({current + 2}) a{{border-bottom-color:var(--accent)}}"
               f".st-key-topnav [data-testid='stColumn']:nth-child({current + 2}) a p{{color:var(--ink)!important;"
               "font-weight:600!important}</style>")
    # The live system panel is a research tool, so it now lives on the Database page rather than in the menu.


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
