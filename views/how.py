"""The "How it works" page.

We wrote it for two audiences at once: each step has a plain-language summary, and the engineering detail sits
in a collapsed "Technical detail" box underneath. The page goes from the big picture to the three phases, then
to the individual steps.
"""
import streamlit as st

from access.config import ROLES
from access.ui import html_block, esc, footer, icon, setup


def who(role: str) -> str:
    return ", ".join(f"{m.label} ({m.family})" for m in ROLES.get(role, []))


html_block("""<style>
.how-hero{text-align:center;padding:18px 0 4px}
.how-hero h1{font-family:'Source Serif 4',Georgia,serif;font-size:2.5rem;margin:0 0 10px}
.how-hero p{color:var(--muted);max-width:680px;margin:0 auto;font-size:1.04rem}
.guide{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin:16px 0 4px;font-size:.82rem;color:var(--muted)}
.phases{display:grid;grid-template-columns:1fr 34px 1fr 34px 1fr;align-items:stretch;margin:22px 0 8px}
.phase{border-radius:18px;padding:18px;border:1px solid var(--line);background:#fff;text-decoration:none!important}
.phase:hover{box-shadow:0 6px 24px rgba(15,23,42,.07)}
.phase .tag{font-size:.72rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.phase h3{margin:6px 0 6px;font-size:1.12rem;color:var(--ink)!important}
.phase p{color:#475569;font-size:.88rem;margin:0;line-height:1.5}
.phase .ico{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:#fff;
            border:1px solid var(--line);margin-bottom:10px}
.p1 .ico{color:#4338CA} .p2 .ico{color:#0E7490} .p3 .ico{color:#047857}
.guide span{display:inline-flex;align-items:center;gap:6px}
.arrow{display:grid;place-items:center;color:#94A3B8;font-size:1.4rem}
.p1{background:linear-gradient(180deg,#EEF2FF,#fff)} .p1 .tag{color:#4338CA}
.p2{background:linear-gradient(180deg,#ECFEFF,#fff)} .p2 .tag{color:#0E7490}
.p3{background:linear-gradient(180deg,#ECFDF5,#fff)} .p3 .tag{color:#047857}
.phase-head{display:flex;align-items:center;gap:12px;margin:38px 0 4px}
.phase-head .badge{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;color:#fff;font-weight:800}
.phase-head h2{margin:0;font-size:1.5rem}
.phase-intro{color:var(--muted);margin:2px 0 14px 50px;max-width:760px}
.stepper{position:relative;margin-left:18px;padding-left:32px;border-left:2px dashed #CBD5E1}
.step{position:relative;margin:0 0 16px;border:1px solid var(--line);border-radius:14px;padding:14px 16px;background:#fff}
.step .num{position:absolute;left:-49px;top:12px;width:32px;height:32px;border-radius:50%;background:#fff;
           border:2px solid currentColor;display:grid;place-items:center;font-weight:700;font-size:.82rem}
.step h4{margin:0 0 4px;font-size:1.02rem}
.step .plain{color:#334155;font-size:.92rem;line-height:1.55;margin:0}
.step .who{font-size:.75rem;color:var(--muted);margin-top:6px}
details.tech{margin-top:8px;font-size:.85rem;color:#475569}
details.tech summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:.8rem;list-style:none}
details.tech summary::before{content:"＋ "} details.tech[open] summary::before{content:"－ "}
details.tech div{margin-top:6px;padding:10px 12px;background:var(--soft);border-radius:10px;line-height:1.55}
.c1{color:#4338CA} .c2{color:#0E7490} .c3{color:#047857}
.fig{border:1px solid var(--line);border-radius:18px;padding:20px;margin:14px 0;background:#fff}
.fig h4{margin:0 0 4px} .fig .cap{color:var(--muted);font-size:.86rem;margin-bottom:14px}
.flow{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:center}
.box{border:1px solid var(--line);border-radius:12px;padding:10px 12px;text-align:center;font-size:.84rem;background:#fff;min-width:120px}
.box b{display:block;font-size:.9rem}
.box.g{background:#EEF2FF;border-color:#C7D2FE}
.judges{display:flex;flex-direction:column;gap:6px}
.vote{display:grid;grid-template-columns:1fr;gap:6px}
.out{border-radius:12px;padding:10px 12px;font-size:.84rem}
.three{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.lane{border-radius:14px;padding:14px}
.lane h5{margin:0 0 6px;font-size:.95rem}
.lane ul{margin:0;padding-left:18px;font-size:.85rem;color:#334155}
.bar{display:flex;height:36px;border-radius:10px;overflow:hidden;font-size:.72rem;color:#fff;font-weight:600}
.bar div{display:grid;place-items:center;text-align:center;line-height:1.1;padding:0 4px}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:6px 18px;margin-top:12px;font-size:.84rem;color:#334155}
.principles{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.pr{border:1px solid var(--line);border-radius:14px;padding:16px;background:#fff}
.pr h5{margin:4px 0 4px;font-size:1rem} .pr p{margin:0;color:#475569;font-size:.88rem;line-height:1.5}
.roles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
.role{border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff;font-size:.86rem}
.role b{display:block;margin-bottom:4px}
.co{display:inline-block;margin:2px 4px 0 0;padding:2px 8px;border-radius:999px;font-size:.72rem;font-weight:600;background:var(--soft)}
.gloss{display:grid;grid-template-columns:repeat(2,1fr);gap:8px 22px;font-size:.88rem}
.gloss b{color:var(--ink)}
@media (max-width:760px){.phases{grid-template-columns:1fr}.arrow{transform:rotate(90deg);height:30px}
 .three,.principles,.gloss,.vote{grid-template-columns:1fr}}
</style>""")


def step(n, color, title, plain, tech, by=""):
    by_html = f"<div class='who'>Done by: {esc(by)}</div>" if by else ""
    return (f"<div class='step'><div class='num {color}'>{n}</div><h4>{title}</h4><p class='plain'>{plain}</p>"
            f"{by_html}<details class='tech'><summary>Technical detail</summary><div>{tech}</div></details></div>")


def phase(n, color, bg, title, intro, steps):
    html_block(f"<div class='phase-head' id='phase-{n}'><div class='badge' style='background:{bg}'>{n}</div>"
                f"<h2>{title}</h2></div><div class='phase-intro'>{intro}</div>"
                f"<div class='stepper {color}'>{''.join(steps)}</div>")


setup()
html_block("""<div class='how-hero'><div class='eyebrow'>How it works</div>
<h1>From the open web to a personal shortlist</h1>
<p>ACCESS works in three phases. First, AI agents build and verify a library of funding programmes. Next, the
researcher's situation is turned into a precise profile. Finally, the two are matched under strict rules and
explained in plain language.</p></div>
<div class='guide'><span>ICON_BOOK Each step has a plain-language summary.</span>
<span>ICON_WRENCH Open <b>Technical detail</b> for the engineering.</span></div>

<div class='phases'>
 <a class='phase p1' href='#phase-1'><div class='ico'>ICON_LIB</div><div class='tag'>Phase 1 · runs continuously</div>
  <h3>Build a verified library</h3><p>Agents find official funding pages, extract every rule, and check each
  one with independent AI judges.</p></a>
 <div class='arrow'>→</div>
 <a class='phase p2' href='#phase-2'><div class='ico'>ICON_USER</div><div class='tag'>Phase 2 · milliseconds</div>
  <h3>Understand the researcher</h3><p>A short form and a few sentences become a structured profile: career
  stage, field, nationality, scores. No waiting on online AI.</p></a>
 <div class='arrow'>→</div>
 <a class='phase p3' href='#phase-3'><div class='ico'>ICON_TARGET</div><div class='tag'>Phase 3 · answer in ~1 second</div>
  <h3>Match, check and advise</h3><p>Rules are applied exactly, results are reviewed and ranked, and each comes
  with an application plan.</p></a>
</div>""".replace("ICON_BOOK", icon("book")).replace("ICON_WRENCH", icon("wrench"))
           .replace("ICON_LIB", icon("library", 18)).replace("ICON_USER", icon("user", 18))
           .replace("ICON_TARGET", icon("target", 18)))

# ------------------------------------------------------------------ phase 1
phase(1, "c1", "#4338CA", "Build a verified library",
      "This happens in the background, before anyone searches. Six cooperating agents keep the library growing "
      "and up to date, so searches are fast and every fact can be traced back to an official page.", [
          step(1, "c1", "Scout: find where funding is published",
               "The Scout starts from official sources, such as government agencies, universities, foundations and "
               "existing public funding databases. It follows their links to discover more funding pages, "
               "organised by region and by type of funder.",
               "Seeds: curated official directories by provider type (government, university, foundation, "
               "intergovernmental, research institute), plus structured feeds (EURAXESS, UKRI, grants.gov) and "
               "Wikidata. Index pages with many funding links become new crawl targets. One site per domain at a "
               "time; a site cap keeps the crawl focused.", "Python crawler (no AI)"),
          step(2, "c1", "Scraper: read each page, politely",
               "The Scraper downloads the pages and keeps only the text. It follows each website's rules for "
               "automated visitors and slows down if a site asks it to. Sites that block automated access are "
               "never forced. They're listed as \"known programmes\" with a link only.",
               "robots.txt is respected; per-site delays; exponential back-off on 403/429/503 that honours "
               "Retry-After. JavaScript-only pages are rendered in a local headless browser (Playwright). Moved "
               "pages are re-found through the site's sitemap; timeouts are retried after 1, 3 and 7 days. A free "
               "keyword filter and content fingerprints discard non-funding pages and duplicates before any AI "
               "is used. Every request is written to a crawl datalog.", "Python crawler + headless browser"),
          step(3, "c1", "Annotator: turn a web page into a structured record",
               "An AI model reads each page and fills in a standard form of about 50 fields: who can apply, what "
               "it pays, deadlines, required documents. Every eligibility rule must come with the exact sentence "
               "from the page that supports it.",
               f"Schema v2 with controlled vocabularies (opportunity type, provider type, career stage, 25-field "
               f"taxonomy). Rules are typed (attribute, operator, value) and marked hard (nationality, age) or "
               f"achievable (test scores, publications). A deterministic validator checks consistency (e.g. "
               f"a past deadline cannot be 'open').", who("normalizer")),
          step(4, "c1", "Three independent judges verify every record",
               "Three AI models from three different companies check the record against the original page. Is "
               "this really a funding opportunity? Does each rule actually appear on the page? Are the amounts "
               "and deadlines right? Rules the judges don't support are removed. If three judges aren't "
               "available, the record waits. It's never decided by fewer.",
               "Panel drawn per record from a pool of six models, three distinct vendors required (never the "
               "annotator's vendor). Retrieve-then-verify: for each claim, the most relevant passages of the page "
               "are retrieved (BM25) and shown to the judges. Majority vote per rule and per fact; verbatim evidence "
               "is located in the page text (grounding). Judges that time out are benched and substituted. "
               f"Pool: {esc(who('judge_pool'))}.", "Three of six models, from different companies"),
          step(5, "c1", "Trust score: publish only what holds up",
               "Each verified record gets a trust score that combines several signals, such as whether it comes "
               "from an official site and how strongly the judges agreed. Only records with a high enough score "
               "are published to the search library.",
               "See the trust score diagram below. Bands: high ≥ 0.75, medium ≥ 0.5; lower scores are withheld. A "
               "certificate warning on the source halves the official-source credit. A separate completeness "
               "score shows how many fields are filled.", "Deterministic scoring (no AI)"),
          step(6, "c1", "Auditor: test the testers",
               "A separate AI, which is never one of the judges, re-reads a sample of pages without seeing earlier "
               "answers. It also plants deliberate mistakes, such as a fake rule or a shifted deadline, to check "
               "that the judges catch them. No human labelling is needed.",
               f"Blind re-extraction with leave-one-out agreement; code-generated mutations (fake_rule, "
               f"shifted_deadline, inflated_funding, wrong_page, flipped_nationality) measure the panel's detection "
               f"rate. After 30 audits the trust bands are recalibrated automatically. Auditor: {esc(who('auditor'))}.",
               who("auditor")),
          step(7, "c1", "Lookup document: a library built for speed",
               "Verified records are compiled into a compact, searchable file with a precomputed \"meaning\" "
               "index. That's why a search takes milliseconds instead of minutes, even on free, rate-limited AI "
               "services.",
               "programs.jsonl and csv (labelled matrix), facets.json (filter indexes), embeddings.npy "
               "(nomic-embed-text vectors), data dictionary and scrape templates. It is rebuilt automatically as "
               "rows are verified, and re-checked on a schedule by provider type.", who("embedder")),
          step(8, "c1", "Sentinel: keep it all running",
               "A monitoring agent checks the others every five minutes. It restarts stalled agents, works around "
               "failing AI services, and adjusts the workload to the computer's memory. It sends a phone alert "
               "only when something needs a person.",
               "Detect → diagnose → fix → verify → escalate. Whitelisted actions only: restart, bench or disable a "
               "model, change worker counts, re-queue stuck rows, pause rendering, relaunch the local model "
               "server. Expected pauses (daily free-tier quotas) are recognised and not escalated.",
               "Python monitor + push notifications"),
      ])

# ------------------------------------------------------------------ figures for phase 1
html_block(f"""
<div class='fig'><h4>Figure 1 · How a single record is verified</h4>
<div class='cap'>One AI writes the record, three AIs from different companies check it, and plain code makes the
final call. No model ever checks its own work.</div>
<div class='flow'>
 <div class='box'><b>Official page</b>original text</div><div class='arrow'>→</div>
 <div class='box g'><b>Annotator</b>{esc(who('normalizer'))}<br><span class='muted'>extracts rules + quotes</span></div>
 <div class='arrow'>→</div>
 <div class='judges'><div class='box'><b>Judge A</b>company 1</div><div class='box'><b>Judge B</b>company 2</div>
  <div class='box'><b>Judge C</b>company 3</div></div>
 <div class='arrow'>→</div>
 <div class='box'><b>🗳️ Majority vote</b>per rule, per fact</div><div class='arrow'>→</div>
 <div class='vote'><div class='out' style='background:var(--ok-soft);color:var(--ok)'><b>Kept</b><br>supported by the page</div>
  <div class='out' style='background:var(--bad-soft);color:var(--bad)'><b>Removed</b><br>not supported</div></div>
</div></div>

<div class='fig'><h4>Figure 2 · What goes into the trust score</h4>
<div class='cap'>Six signals, weighted. A record must score high enough before it can appear in search results.</div>
<div class='bar'>
 <div style='width:25%;background:#4338CA'>Official<br>source 25%</div>
 <div style='width:20%;background:#6366F1'>Funding<br>confirmed 20%</div>
 <div style='width:20%;background:#0EA5E9'>Rules<br>supported 20%</div>
 <div style='width:20%;background:#14B8A6'>Quotes<br>found 20%</div>
 <div style='width:10%;background:#10B981'>Agree<br>10%</div>
 <div style='width:5%;background:#84CC16'>✓</div></div>
<div class='legend'>
 <span><b>Official source</b>: published by the funder itself</span>
 <span><b>Funding confirmed</b>: judges agree it is real funding</span>
 <span><b>Rules supported</b>: share of rules the judges upheld</span>
 <span><b>Quotes found</b>: evidence appears word-for-word on the page</span>
 <span><b>Agreement</b>: how closely the three judges agreed</span>
 <span><b>Validation</b>: passes automatic consistency checks</span></div></div>
""")

# ------------------------------------------------------------------ phase 2
phase(2, "c2", "#0E7490", "Understand the researcher",
      "A search starts with a short form. Fixed facts, such as nationality, are taken exactly as entered. "
      "The free-text description is turned into fields and keywords the system can work with.", [
          step(1, "c2", "Profile form",
               "The researcher gives their nationality, career stage and the kind of funding they want, plus a "
               "few sentences about their research. Optional details, such as test scores and years since their "
               "PhD, make the eligibility checks sharper.",
               "Structured inputs map directly onto rule attributes (nationality, residency, career_stage, "
               "highest_degree, years_since_phd, age, ielts, gpa, publications). Unknown values are never "
               "guessed. Rules that depend on them are reported as 'to confirm'.", "The researcher"),
          step(2, "c2", "Profile Builder",
               "The research fields are worked out from the description, for example 'data science & AI', and "
               "shown so the researcher can correct them. This runs on the computer itself in a few "
               "milliseconds, so results never wait for an online AI service.",
               "Local embedding model: the description is compared with the 25-field taxonomy used for "
               "programmes, so both sides of the match speak one vocabulary; every field within a small margin of "
               "the best score is kept. Fields the user picks override the inference.", who("embedder")),
      ])

# ------------------------------------------------------------------ phase 3
phase(3, "c3", "#047857", "Match, check and advise",
      "The answer appears in about a second, because everything up to the eligibility decision runs without "
      "online AI. The AI then refines the order in the background, and writes an application plan only when a "
      "programme is opened. Eligibility itself is decided by plain code, so the same profile always gets the "
      "same answer and every 'yes' or 'no' can be traced to a sentence on the funder's site.", [
          step(1, "c3", "Search",
               "A fast search script narrows the library using the researcher's filters, then ranks programmes by "
               "two signals at once: exact words (names, acronyms, terms) and meaning. This takes milliseconds.",
               "Hybrid retrieval: facet filters → BM25 (lexical) and cosine similarity over embeddings (dense), fused "
               "by Reciprocal Rank Fusion with BM25 weighted 2:1. Chosen by a 100-query benchmark: MRR 0.79 vs 0.60 "
               "for dense alone.", "Python search script + " + who("embedder")),
          step(2, "c3", "Eligibility Gate",
               "Every rule of every candidate programme is checked against the profile, one line at a time. Each "
               "programme ends up in one of three groups: <b>eligible</b>, <b>within reach</b> (only achievable "
               "gaps, such as a test score) or <b>not eligible</b> (a fixed rule fails, such as nationality).",
               "Deterministic evaluator. Hard rules (nationality, residency, age, years since PhD) exclude. Soft "
               "or achievable rules within a margin create a near-miss. Missing profile values give 'unknown', "
               "which is never treated as a pass. 23 unit tests cover the gate.", "Deterministic rules (no AI)"),
          step(3, "c3", "Shortlist review (in the background)",
               "Two AI reviewers from different companies read the shortlist with the researcher's goals in mind. "
               "They flag programmes that are eligible but a weaker match, and add cautions where details need "
               "checking. They never remove an eligible programme; weaker fits are shown last, with the reason.",
               "Runs after the results are on screen, on the 15 most relevant eligible programmes and 5 "
               "near-misses (two batches). Mean relevance below 2/5 marks a weaker fit. Reviewers here "
               f"are separate from the library's judge panel. Reviewers: {esc(who('critic_shortlist'))}.",
               who("critic_shortlist")),
          step(4, "c3", "Fit Ranker",
               "A different AI scores how well each remaining programme fits the researcher, from 0 to 100, and "
               "explains why in one or two sentences.",
               "Combined score blends the ranker's fit with semantic similarity; results under 40 are set aside as "
               "weak fits.", who("fit_ranker")),
          step(5, "c3", "Ask about this programme (RAG, on demand)",
               "Any question about a programme, such as \"Can I apply in my final year?\", is answered only from "
               "passages of its official page, with the passages cited. If the page doesn't say, ACCESS says so "
               "instead of guessing.",
               "Retrieval-augmented generation: the page is split into overlapping 110-word passages; the best ones "
               "for the question are retrieved (BM25 + dense, fused); the model must cite them and copy verbatim "
               "quotes, and every quote is checked against the page (faithfulness check).", who("advisor")),
          step(6, "c3", "Application Advisor (on demand)",
               "When a programme is opened, an advisor writes a short, practical application plan: what to "
               "prepare, in what order, and what to watch out for. For near-misses it writes a gap plan, such as "
               "which test to take and by when.",
               "Written only when asked for, so AI quota is spent on programmes people actually read. Grounded in "
               "the programme's stored record (documents, referees, deadlines). The first writer with free quota "
               "is used, in a fixed order.", who("advisor")),
      ])

html_block("""
<div class='fig'><h4>Figure 3 · The three outcomes of the Eligibility Gate</h4>
<div class='cap'>Rules are labelled as fixed (they can't change) or achievable (they can be met with effort).</div>
<div class='three'>
 <div class='lane' style='background:var(--ok-soft)'><h5 style='color:var(--ok)'>Eligible</h5>
  <ul><li>Every rule is met</li><li>Ranked by fit and reviewed</li><li>Comes with an application plan</li></ul></div>
 <div class='lane' style='background:var(--amber-soft)'><h5 style='color:var(--amber)'>Within reach</h5>
  <ul><li>Only achievable gaps, e.g. IELTS 6.5 vs 7.0 required</li><li>Fixed rules all met</li>
  <li>Comes with a gap plan</li></ul></div>
 <div class='lane' style='background:var(--bad-soft)'><h5 style='color:var(--bad)'>Not eligible</h5>
  <ul><li>A fixed rule fails, e.g. nationality or age</li><li>Shown with the reason</li><li>Never ranked</li></ul></div>
</div></div>""")

# ------------------------------------------------------------------ principles + roles + glossary
html_block("""<div class='phase-head'><div class='badge' style='background:#0F172A'>★</div><h2>Design principles</h2></div>
<div class='principles' style='margin-top:12px'>
 <div class='pr'>🪞<h5>No echo chamber</h5><p>Different stages use AI models from different companies, and no model
 ever checks its own work. A mistake one model makes is unlikely to be repeated by the others.</p></div>
 <div class='pr'>🔎<h5>Evidence or it doesn't count</h5><p>Every eligibility rule must quote the official page.
 Rules without a matching quote are removed before anyone sees them.</p></div>
 <div class='pr'>⚖️<h5>Code decides, AI explains</h5><p>AI reads messy web pages and writes explanations; plain,
 tested code makes the eligible / not eligible decision, so it's consistent and auditable.</p></div>
 <div class='pr'>🤝<h5>Respectful and free</h5><p>Crawling follows each site's rules and never bypasses protection.
 Everything runs on free tiers and open models, with no paid services.</p></div>
</div>""")

COLORS = {"Google": "#DBEAFE", "OpenAI": "#E0E7FF", "Alibaba": "#FFEDD5", "Microsoft": "#DCFCE7",
          "NVIDIA": "#ECFCCB", "Meta": "#E0F2FE", "Zhipu AI": "#FCE7F3", "Nomic": "#F1F5F9"}
ROLE_NAMES = [("normalizer", "Annotator"), ("judge_pool", "Judge pool (three per record)"),
              ("auditor", "Auditor"), ("embedder", "Meaning index"), ("profile_builder", "Profile Builder"),
              ("critic_shortlist", "Shortlist reviewers"), ("fit_ranker", "Fit Ranker"),
              ("advisor", "Application Advisor")]
cards = "".join(
    f"<div class='role'><b>{name}</b>" + "".join(
        f"<span class='co' style='background:{COLORS.get(m.family, '#F1F5F9')}'>{esc(m.family)} · {esc(m.label)}</span>"
        for m in ROLES[key]) + "</div>" for key, name in ROLE_NAMES if key in ROLES)
html_block(f"""<div class='fig' style='margin-top:22px'><h4>Who does what</h4>
<div class='cap'>The AI model behind each role, and the company that made it. All run on free tiers or locally
on the laptop.</div><div class='roles'>{cards}</div></div>""")

html_block("""<div class='fig'><h4>Glossary</h4><div class='gloss'>
<span><b>Agent</b>: a program that does one job on its own, such as finding or checking pages.</span>
<span><b>Annotation</b>: turning free text into labelled fields.</span>
<span><b>Embedding</b>: a list of numbers that captures what a text means, so similar ideas can be found.</span>
<span><b>Free tier</b>: a no-cost usage allowance from an AI provider, with daily limits.</span>
<span><b>Grounding</b>: checking that a claim appears word-for-word in the source.</span>
<span><b>Near-miss</b>: a programme you'd qualify for after one achievable step.</span>
<span><b>robots.txt</b>: a website's instructions for automated visitors.</span>
<span><b>Trust score</b>: a 0–1 score of how reliable a record is.</span>
</div></div>""")
footer()
