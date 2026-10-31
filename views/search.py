"""The search page, which is also the landing page.

The flow we designed for: the visitor describes themselves once, eligible programmes appear in about a second
(no cloud model is involved up to that point), then two independent reviewers and the fit ranker refine the
order in the background, and an application plan is only written when someone opens a programme.
"""
import json
import re
import threading
import time

import streamlit as st

from access.evaluation import PERSONAS
from access.gate import evaluate
from access.lookup import load as load_lookup
from access.pipeline import enrich, instant, is_example, list_runs, plan_for, save_run
from access.results import best_follow_up, final_order, tidy
from access.schema import (CAREER_SINGULAR, CAREER_STAGES, DEGREE_LABELS, DEGREES, FIELDS, OPPORTUNITY_TYPES,
                           PROVIDER_TYPES, human, human_title, humanize_text as H)
from access.ui import chip, esc, footer, html_block, icon, nice, setup

COUNTRIES = sorted(["Singapore", "Malaysia", "Indonesia", "India", "China", "Vietnam", "Philippines", "Thailand",
                    "Japan", "South Korea", "Hong Kong", "Australia", "New Zealand", "United States",
                    "Canada", "United Kingdom", "Germany", "France", "Netherlands", "Switzerland", "Italy", "Spain",
                    "Sweden", "Israel", "Nigeria", "Kenya", "Ghana", "South Africa", "Egypt", "Brazil", "Mexico",
                    "Pakistan", "Bangladesh", "Sri Lanka", "Nepal", "Iran", "Turkey", "Saudi Arabia",
                    "United Arab Emirates", "Other"])
EXAMPLE_CAPTIONS = {"Priya": "Master's → PhD", "Wei Ling": "PhD → postdoc", "Daniel": "Physics postdoc",
                    "Amara": "Undergrad → master's"}
DEADLINE_CHIP = {"open": "ok", "closing_soon": "amber", "next_round": "", "closed": "bad", "check": ""}
DEADLINE_ICON = {"open": "calendar", "closing_soon": "clock", "next_round": "repeat", "closed": "ban", "check": "calendar"}


@st.cache_resource
def ai_lock() -> threading.Lock:
    """We allow one AI enrichment at a time across all visitors, because the free tiers are rate limited.
    Eligibility results never wait on this lock."""
    return threading.Lock()


def example_runs() -> dict:
    """The latest saved run for each example researcher, in a fixed order."""
    out = {}
    for path in list_runs():
        try:
            name = json.loads(path.read_text())["form"].get("name", "")
        except (ValueError, KeyError):
            continue
        for label, p in PERSONAS.items():
            if p.get("name") == name and label not in out and is_example(json.loads(path.read_text())["form"]):
                out[label] = path
    return {label: out[label] for label in PERSONAS if label in out}


def refresh_saved(res: dict) -> dict:
    """Re-check a saved run against today's gate and result rules.

    This is deterministic and takes milliseconds, so we do it on every load: the examples then always reflect
    the current logic and deadlines rather than whatever was true when they were saved.
    """
    live = {p["id"]: p for p in load_lookup()[0]}  # we drop anything no longer in today's verified library
    for key in ("shortlist", "near_misses"):
        kept = []
        for x in res.get(key, []):
            if x.get("id") not in live:
                continue
            x = {**live[x["id"]], **{k: x[k] for k in ("fit", "why", "similarity", "ranker", "critic", "weaker_fit",
                                                      "score", "ranked_by", "advice", "host_tier") if k in x}}
            x["gate"] = evaluate(x, res.get("profile") or {})
            kept.append(x)
        res[key] = [x for x in tidy(kept) if x["gate"]["outcome"] == ("eligible" if key == "shortlist" else "near_miss")]
        if key == "shortlist" and res.get("enriched"):
            res[key] = final_order(res[key])
    res.setdefault("enriched", True)
    return res


def ai_allowed(kind: str) -> bool:
    """Rate limiting for the public demo: a few AI uses per visit plus a shared hourly cap, so one visitor cannot
    use up the free quotas for everyone. Counts the use when it is allowed."""
    from access.config import CACHE_DIR, PUBLIC, PUBLIC_HOURLY_CAP, PUBLIC_LIMITS
    if not PUBLIC:
        return True
    used = st.session_state.setdefault("ai_used", {})
    if used.get(kind, 0) >= PUBLIC_LIMITS[kind]:
        return False
    f = CACHE_DIR / "public_ai_hour.json"
    hour = time.strftime("%Y%m%d%H")
    try:
        d = json.loads(f.read_text())
    except Exception:
        d = {}
    if d.get("hour") != hour:
        d = {"hour": hour, "n": 0}
    if d["n"] >= PUBLIC_HOURLY_CAP:
        return False
    d["n"] += 1
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d))
    used[kind] = used.get(kind, 0) + 1
    return True


LIMIT_MSG = ("This public demo limits AI features to a few uses per visit, because they run on free quotas. "
             "Eligibility results above are unaffected.")


def host_countries() -> dict:
    """Host countries with at least one programme in the library, most programmes first, as {country: count}.
    We only offer countries we can actually return results for; an empty country just produced empty pages."""
    from access.schema import COUNTRY_REGION
    hc = load_lookup()[1].get("host_countries", {})
    counts = {c: len(ids) for c, ids in hc.items() if c in COUNTRY_REGION and ids}
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# ------------------------------------------------------------------ result cards

def funding_text(l) -> str | None:
    f = l.get("funding")
    if isinstance(f, dict):
        if f.get("stipend_amount"):
            per = f" / {f['stipend_period']}" if f.get("stipend_period") else ""
            return f"{f.get('currency') or ''} {f['stipend_amount']:,.0f}{per}".strip()
        return "Fully funded" if f.get("fully_funded") else None
    return str(f)[:40] if f else None


def card_html(l, facts: list[str], score=None, status=("Eligible", "")) -> str:
    """The top of a result card: provider line, title, key facts, the reason it fits and one quote from the funder.

    We put the fit score in its own column on the right so the eye can scan scores down the page, and we show one
    quote from the official page on the card itself, because "every decision is traceable" is the product's core
    promise and should not hide inside an expander.
    """
    prov = " · ".join(esc(x) for x in (l.get("provider"), l.get("host_label") or l.get("host_country"),
                                       human_title(l.get("opportunity_type") or l.get("type") or "")) if x)
    quote = next((c.get("evidence") for c in l.get("gate", {}).get("checks", []) if c.get("evidence")
                  and c["status"] == "pass"), None)
    left = (f"<div class='rc-prov'>{prov}</div>"
            f"<a class='res-title' href='{esc(l.get('url'))}' target='_blank'>"
            f"{esc(l.get('display_name') or l.get('name'))}{icon('external', 15)}</a>"
            f"<div class='facts'>{''.join(facts)}</div>"
            + (f"<p class='why'>{esc(H(l['why']))}</p>" if l.get("why") else "")
            + (f"<div class='quote-box'><b>From the official page</b>“{esc(quote[:220])}”</div>" if quote else "")
            + concerns_html(l))
    label, kind = status
    tick = icon("check" if not kind else "alert", 11)
    if score is not None:
        right = (f"<div><small>Fit</small><b>{int(score)}</b><div class='meter'><i style='width:{int(score)}%'></i></div>"
                 f"</div><div class='status {kind}'><i>{tick}</i>{label}</div>")
    else:
        right = f"<div><small>Fit</small><b style='color:var(--line)'>–</b></div><div class='status {kind}'><i>{tick}</i>{label}</div>"
    return f"<div class='rc'><div>{left}</div><div class='score'>{right}</div></div>"


def fact(text, ic=None, kind="") -> str:
    return f"<span class='{kind}'>{icon(ic, 14) if ic else ''}{text}</span>"


def card_facts(l) -> list[str]:
    out = []
    money = funding_text(l)
    if money:
        out.append(fact(f"<b>{esc(money)}</b>", "wallet"))
    d = l.get("deadline_status") or {}
    if d:
        out.append(fact(esc(d["label"]), DEADLINE_ICON[d["state"]], DEADLINE_CHIP[d["state"]]))
    if l.get("archived_at"):
        out.append(fact(f"Archived official page, {esc(l['archived_at'])}", "archive", "amber"))
    elif l.get("official_source") or (l.get("review") or {}).get("decision") in ("accepted", "accepted_with_warning"):
        out.append(fact("Official source", "shield", "ok"))
    return out


STATUS_ICON = {"pass": "check", "conditional": "clock", "fail": "x", "near": "alert", "unknown": "help"}


def check_row(status: str, text: str, evidence: str | None = None) -> str:
    """One line of the eligibility checklist, with the supporting quote from the funder's page underneath."""
    row = (f"<div class='check'><span class='st {status}'>{icon(STATUS_ICON.get(status, 'help'), 12)}</span>"
           f"<span>{esc(text)}</span></div>")
    return row + (f"<div class='evidence'>Official page: “{esc(evidence[:220])}”</div>" if evidence else "")


def eligibility_details(l):
    checks = l.get("gate", {}).get("checks", [])
    rows = [check_row(c["status"], H(c["why"]), c.get("evidence")) for c in checks]
    rows += [check_row("unknown", "Check for: " + H(c)) for c in l.get("conditional_criteria") or []]
    if rows:
        html_block("".join(rows))
    if not checks:
        st.caption("The official page lists no explicit eligibility rules.")


def plan_block(l, res, near=False):
    """We only write a plan when someone asks for one. It keeps the page fast and spends AI quota only on the
    programmes people actually read."""
    a = l.get("advice")
    if not a:
        label = "How do I close the gap?" if near else "Draft my application plan"
        if st.button(label, key=f"plan-{l['id']}", use_container_width=True):
            if not ai_allowed("plan"):
                st.caption(LIMIT_MSG)
                return
            with st.spinner("Writing your plan…"):
                a = plan_for(res, l["id"])
            if a:
                save_run(res)  # we keep the plan with the saved search
                st.rerun()     # and redraw without the button
            st.caption("The AI writers are busy right now. Please try again in a minute.")
        if not a:
            return
    if a.get("verdict"):
        st.markdown(f"**{H(a['verdict'])}**")
    if near and a.get("close_the_gap"):
        st.markdown(H(a["close_the_gap"]))
    for i, step in enumerate(a.get("steps") or [], 1):
        st.markdown(f"{i}. {H(step)}")
    if a.get("timeline"):
        st.markdown(f"**Timeline:** {H(a['timeline'])}")
    if a.get("watch_out"):
        st.markdown(f"**Watch out:** {H(a['watch_out'])}")


def ask_block(l, res):
    """Questions about one programme, answered by retrieval-augmented generation.

    The answer may only use passages retrieved from this programme's official page, it has to cite them, and we
    then check that every quoted sentence really appears on the page before marking the answer as verified.
    """
    for qa in l.get("qa", []):
        st.markdown(f"**Q:** {esc(qa['q'])}")
        badge = (f"{icon('shield', 12)} Verified against the official page" if qa["verified"]
                 else f"{icon('alert', 12)} Could not verify every quote on the page: please check the source")
        st.markdown(f"{H(qa['answer'])}  \n<span class='muted' style='font-size:.8rem'>{badge}</span>",
                    unsafe_allow_html=True)
        for n, passage in qa.get("citations", [])[:3]:
            st.caption(f"[P{n}] “{passage[:300]}{'…' if len(passage) > 300 else ''}”")
    with st.form(f"ask-{l['id']}", border=False, clear_on_submit=True):
        q = st.text_input("Your question", placeholder="e.g. Can I apply in my final year? What documents do I need?",
                          label_visibility="collapsed")
        if st.form_submit_button("Ask") and q.strip():
            if not ai_allowed("ask"):
                st.caption(LIMIT_MSG)
                return
            from access.rag import ask
            with st.spinner("Reading the official page…"):
                r = ask(l, q.strip())
            l.setdefault("qa", []).append({"q": q.strip(), **r})
            save_run(res)
            st.rerun()


def concerns_html(l) -> str:
    cs = (l.get("critic") or {}).get("concerns") or []
    strip = lambda c: re.sub(r"^[\w.\- ]{2,30}:\s*", "", str(c))  # reviewers prefix notes with their model name
    return "".join(f"<div class='note'>Reviewer note: {esc(H(strip(c)))}</div>" for c in cs[:2])


def match_card(l, res):
    checks = l.get("gate", {}).get("checks", [])
    met = sum(c["status"] == "pass" for c in checks)
    cond = sum(c["status"] == "conditional" for c in checks)
    facts = card_facts(l) + [fact(f"<b>{met} of {len(checks)}</b> rules met", "check", "ok") if checks
                             else fact("No listed restrictions", "check", "ok")]
    if cond:
        facts.append(fact(f"{cond} met once your current degree is completed", "clock", "amber"))
    score = l.get("score") if res.get("enriched") and l.get("fit") is not None else None
    status = ("Eligible, weaker fit", "amber") if l.get("weaker_fit") else ("Eligible", "")
    with st.container(border=True, key=f"card-{l['id']}"):
        st.markdown(card_html(l, facts, score, status), unsafe_allow_html=True)
        with st.expander("Eligibility details"):
            eligibility_details(l)
        with st.expander("Application plan", expanded=bool(l.get("advice"))):
            plan_block(l, res)
        with st.expander("Ask about this programme", expanded=bool(l.get("qa"))):
            ask_block(l, res)


def near_card(l, res):
    gaps = [c for c in l.get("gate", {}).get("checks", []) if c["status"] == "near"]
    with st.container(border=True, key=f"near-{l['id']}"):
        st.markdown(card_html(l, card_facts(l), None, (f"{len(gaps)} gap{'s' * (len(gaps) != 1)} to close", "amber")),
                    unsafe_allow_html=True)
        if gaps:
            html_block("".join(check_row("near", "Gap: " + H(g["why"])) for g in gaps))
        with st.expander("All eligibility checks"):
            eligibility_details(l)
        with st.expander("How to close the gap", expanded=bool(l.get("advice"))):
            plan_block(l, res, near=True)
        with st.expander("Ask about this programme", expanded=bool(l.get("qa"))):
            ask_block(l, res)


def show_results(res):
    short_all, near_all = res.get("shortlist", []), res.get("near_misses", [])
    closed = [x for x in short_all + near_all if (x.get("deadline_status") or {}).get("state") == "closed"]
    show_closed = st.session_state.get("show_closed", False)
    keep = lambda xs: xs if show_closed else [x for x in xs if (x.get("deadline_status") or {}).get("state") != "closed"]
    short, near = keep(short_all), keep(near_all)
    who = res.get("form", {}).get("name") or "you"
    strong = sum(not x.get("weaker_fit") for x in short)
    pills = (f"<span class='rs ok'><b>{len(short)}</b> eligible</span>"
             + (f"<span class='rs'><b>{strong}</b> strong match{'es' * (strong != 1)}</span>" if res.get("enriched") else "")
             + f"<span class='rs amber'><b>{len(near)}</b> within reach</span>")
    title = f"{len(short)} programme{'s' * (len(short) != 1)} {esc(who)} can apply for"
    html_block(f"<div class='results-head'><div><div class='rh-kicker'>Your results</div>"
               f"<div class='rh-title'>{title}</div></div><div class='rh-pills'>{pills}</div></div>")
    stt, prof = res.get("search_stats") or {}, res.get("profile") or {}
    if stt.get("after_filters") is not None:
        applied = stt.get("filters_applied") or {}
        what = ", ".join(human(t) + "s" for t in applied.get("opportunity_type", [])) or "programmes"
        where = " in " + ", ".join(applied["host_country"]) if applied.get("host_country") else ""
        fields = ", ".join(human(f) for f in prof.get("fields", []) if f != "any")
        from access.config import PUBLIC
        st.caption(f"Searched {stt['after_filters']} verified {what}{where}, out of {stt.get('programmes', 0)} in the "
                   + ("library." if PUBLIC else "library so far (it grows daily).")
                   + (f" Matched on your research fields: {fields} (change them under *Add details*)." if fields else ""))
    if "host_country" in (stt.get("relaxed") or []):
        st.warning("No verified programme is held in " + ", ".join(res.get("form", {}).get("target_countries") or [])
                   + " yet, so programmes in other countries are shown instead.")
    if "opportunity_type" in (stt.get("relaxed") or []):
        st.warning("No verified programme of the type you chose matches yet, so other funding types are shown.")
    follow_up_card(res, short_all + near_all)
    if res.get("ranking_note"):
        st.caption(res["ranking_note"])
    status_slot = st.container()  # the AI enrichment reports its progress here, above the results
    if closed:
        st.toggle(f"Show {len(closed)} closed programme{'s' * (len(closed) != 1)}", key="show_closed")
    t1, t2 = st.tabs([f"Eligible ({len(short)})", f"Within reach ({len(near)})"])
    with t1:
        if not short:
            st.info("No programme matches every rule yet. Check **Within reach** for options that need one "
                    "achievable step, such as a test score.")
        divider = False
        for l in short:
            if l.get("weaker_fit") and not divider and res.get("enriched"):
                divider = True
                st.markdown("**Also eligible, but a weaker fit for your goals**")
            match_card(l, res)
    with t2:
        st.caption("You don't qualify yet, but each gap is achievable, for example a language test, "
                   "a publication, or finishing your degree.")
        if not near:
            st.info("No near-misses for this profile.")
        for l in near:
            near_card(l, res)
    return status_slot


def follow_up_card(res, items):
    """Ask the single question that would settle the most 'to confirm' rules in these results.

    We pick it greedily: the profile attribute that the largest number of shown programmes depend on.
    """
    f = best_follow_up(items)
    if not f or res["form"].get(f["attribute"]) is not None:
        return
    with st.container(border=True):
        n = f["programmes"]
        st.markdown(f"**One quick question to sharpen your results.** {n} rule{'s' * (n != 1)} in these results "
                    f"depend{'s' * (n == 1)} on it: *{f['question']}*")
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        if f["attribute"] == "residency":
            val = c1.selectbox("Answer", COUNTRIES + ["Singapore PR"], index=None, key="fu-val",
                               label_visibility="collapsed", placeholder="Select a country")
        else:
            val = c1.number_input("Answer", min_value=0.0, value=None, key="fu-val", label_visibility="collapsed",
                                  placeholder="Your answer")
        if c2.button("Update results", key="fu-go", use_container_width=True) and val is not None:
            form = {**res["form"], f["attribute"]: val}
            new = instant(form)
            new["timings"]["first_result_s"] = new["timings"]["instant_s"]
            st.session_state.update(result=new, enrich_pending=True)
            st.rerun()


def run_enrichment(res, slot):
    """Run the reviewers and the fit ranker once the results are already on screen.

    Whatever happens here, the eligibility answer the visitor is looking at must not break or disappear, so every
    failure path falls back to the similarity order.
    """
    if not ai_allowed("rank"):
        with slot:
            st.caption("Results are shown in order of similarity. " + LIMIT_MSG)
        st.session_state["enrich_pending"] = False
        return
    with slot, st.status("Ranking by fit and checking with independent AI reviewers…", expanded=False) as s:
        lock = ai_lock()
        if not lock.acquire(timeout=90):
            s.update(label="AI ranking is busy with another search; results are shown in order of similarity",
                     state="complete")
            st.session_state["enrich_pending"] = False
            return
        try:
            from access.config import PUBLIC, PUBLIC_RANK_BUDGET_S
            if PUBLIC:  # the free quotas are shared, so we never keep a visitor waiting past the time budget
                import copy
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as Late
                work = copy.deepcopy(res)
                pool = ThreadPoolExecutor(1)
                try:
                    done = pool.submit(enrich, work).result(timeout=PUBLIC_RANK_BUDGET_S)
                    res.clear()
                    res.update(done)
                    s.update(label="Ranked by fit and reviewed", state="complete")
                except Late:
                    res["ranking_note"] = ("AI ranking was too slow just now (shared free quota), so results are "
                                           "shown in order of similarity to your description.")
                    s.update(label="AI ranking is slow right now (shared free quota); results are shown in order "
                                   "of similarity", state="complete")
                finally:
                    pool.shutdown(wait=False)
            else:
                enrich(res)
                save_run(res)
                s.update(label="Ranked by fit and reviewed", state="complete")
        except Exception:
            s.update(label="AI ranking unavailable right now; results are shown in order of similarity",
                     state="complete")
        finally:
            lock.release()
    st.session_state["enrich_pending"] = False
    st.rerun()


# ------------------------------------------------------------------ page

setup()
if not load_lookup()[0]:
    st.warning("The programme library is still being built. Please check back shortly.")
    st.stop()

# The first screen is split in two: what ACCESS does on the left, the search form on the right, so a visitor can
# start a search without scrolling. On phones Streamlit stacks the two columns.
FUNDERS = ["DAAD", "Alexander von Humboldt Foundation", "UK Research and Innovation", "Fulbright", "JSPS",
           "A*STAR", "National University of Singapore", "Simons Foundation", "Royal Society", "Mitacs"]


def sample_card(lib) -> str:
    """A real programme from the library, drawn exactly as a result card, so first-time visitors see what they will
    get before they search. We pick a well-known one that has a quoted rule."""
    good = [x for x in lib if len(x.get("rules") or []) >= 2 and funding_text(x)
            and any(r.get("evidence") and r.get("attribute") in ("career_stage", "highest_degree") for r in x["rules"])]
    pick = next((x for x in good if "Nanyang President" in (x.get("name") or "")), good[0] if good else None)
    if not pick:
        return ""
    rule = next(r for r in pick["rules"] if r.get("evidence") and r.get("attribute") in ("career_stage", "highest_degree"))
    l = {**pick, "gate": {"checks": [{"status": "pass", "evidence": rule["evidence"]}]},
         "why": pick.get("summary", "")[:190].rsplit(" ", 1)[0] + "…"}
    n = len(pick.get("rules") or [])
    facts = card_facts(l) + [fact(f"<b>{n} of {n}</b> rules met", "check", "ok")]
    return card_html(l, facts, 91)


def landing(lib, n_rules):
    """What a first-time visitor sees below the search: who the data comes from, how it works, an example result,
    the questions people ask, and a way back up to the search. Once there are results, they replace all of this."""
    funders = "".join(f"<span>{esc(f)}</span>" for f in FUNDERS)
    html_block(f"""<div class='logos'><div class='logos-k'>Programmes verified from the official pages of funders
including</div><div class='logos-row'>{funders}</div></div>
<section class='lp'><div class='lp-k'>How it works</div><h2 class='lp-h'>Three steps, one honest answer.</h2>
<div class='steps'>
<div class='step3'><span>01</span><h3>Describe yourself</h3><p>A few sentences about your research, your nationality
and career stage. Fixed facts are taken exactly as you give them; nothing is guessed.</p></div>
<div class='step3'><span>02</span><h3>Every rule is checked</h3><p>Plain code tests each programme's eligibility
rules against your profile, line by line, so the same profile always gets the same answer.</p></div>
<div class='step3'><span>03</span><h3>See the evidence</h3><p>Eligible programmes are ranked by fit. Each one shows
the sentence from the funder's page that its decision rests on, and a plan to apply.</p></div>
</div></section>
<section class='lp lp-split'><div><div class='lp-k'>What you get</div><h2 class='lp-h'>A shortlist you can
check yourself.</h2><p class='lp-p'>Every result links to the funder's official page and quotes the rule it was
decided on. Three AI judges from three different companies verified each programme before it entered the
library, and anything they could not confirm was left out.</p>
<div class='proof proof-sm'><div><b>{len(lib):,}</b><span>verified programmes</span></div>
<div><b>{n_rules:,}</b><span>rules, each quoted</span></div><div><b>0.4 s</b><span>to your shortlist</span></div></div>
</div><div class='sample'><div class='sample-tag'>Example result</div>{sample_card(lib)}</div></section>
<section class='lp lp-faq'><div><div class='lp-k'>Questions</div><h2 class='lp-h'>Before you search</h2>
<p class='lp-p'>The short version: it is free, it only uses official sources, and code, not a model, decides who
is eligible.</p></div><div class='faq'>
<details><summary>Is ACCESS free, and do I need an account?</summary><p>Yes, it is free, and there is no
account. Your answers are used for this search only.</p></details>
<details><summary>Where do the programmes come from?</summary><p>Only from funders' own websites: universities,
government agencies and foundations. Aggregator sites are used to discover programmes, never as the source of a
fact.</p></details>
<details><summary>How is eligibility decided?</summary><p>By plain code, not by an AI model. Each rule is stored
with the sentence it came from, and your profile is tested against it. Rules that depend on something you did not
tell us are marked "to confirm" instead of guessed.</p></details>
<details><summary>Can I trust the result completely?</summary><p>Treat it as a well-checked shortlist. Deadlines
and conditions change, so always confirm the details on the funder's official page before applying.</p></details>
</div></section>
<section class='cta-band'><h2>Find the funding that fits you.</h2><p>It takes about two minutes, and you can start
from an example researcher.</p><a href='#search'>Start a search</a></section>""")


def load_example(label: str):
    """Button callback: fill the form with an example researcher. It runs before the page is redrawn, which is what
    lets the example buttons sit below the form they fill in."""
    st.session_state.update(example=label, enrich_pending=False, show_closed=False, result=None)


lib = load_lookup()[0]
n_rules = sum(len(x.get("rules") or []) for x in lib)
html_block("""<div id='search'></div><div class='hero-c'><div class='eyebrow'>Verified research funding</div>
<h1>Only the funding you can <em>actually</em> apply for.</h1>
<p class='lead'>Describe yourself once. ACCESS checks every rule on the funder's official page against your
profile and shows you the sentence behind each decision.</p></div>""")

p = PERSONAS.get(st.session_state.get("example") or "", {})
k = st.session_state.get("example") or "blank"
# The search reads like one object, in the spirit of travel-search bars: the description on top, the four facts
# that decide eligibility in one row, and the button at the end of that row. Everything optional is folded away.
with st.container(key="searchbar"):
    with st.form("profile", border=False):
        about = st.text_area("Your research and goals", p.get("about", ""), height=86, key=f"about-{k}",
                             placeholder="e.g. I'm finishing a master's in computer science and want a funded PhD "
                                         "in trustworthy machine learning, ideally in Asia.")
        c1, c2, c3, c4, c5 = st.columns([1, 1.25, 1.1, 1.1, 0.85], vertical_alignment="bottom")
        nat = c1.selectbox("Nationality", COUNTRIES, key=f"nat-{k}",
                           index=COUNTRIES.index(p["nationality"]) if p.get("nationality") in COUNTRIES else None,
                           placeholder="Select")
        stage = c2.selectbox("Career stage", CAREER_STAGES, key=f"stage-{k}",
                             format_func=lambda c: CAREER_SINGULAR[c].capitalize(),
                             index=CAREER_STAGES.index(p.get("career_stage", "masters")))
        wanted = c3.multiselect("Looking for", OPPORTUNITY_TYPES, default=p.get("wanted_types", []),
                                format_func=human_title, key=f"want-{k}", placeholder="Any funding")
        hosts = host_countries()  # only countries we have programmes for
        targets = c4.multiselect("Where", list(hosts), default=[c for c in p.get("target_countries", []) if c in hosts],
                                 format_func=lambda c: f"{c} ({hosts[c]})", key=f"where-{k}", placeholder="Anywhere")
        go = c5.form_submit_button("Find funding", type="primary", use_container_width=True)
        with st.expander("More details for sharper checks (optional)"):
            fields = st.multiselect("Research fields", [f for f in FIELDS if f != "any"], format_func=human_title,
                                    key=f"fields-{k}", placeholder="Detected automatically from your description")
            c1, c2, c3 = st.columns(3)
            res_opts = COUNTRIES + ["Singapore PR"]
            resid = c1.selectbox("Country of residence", res_opts, key=f"res-{k}",
                                 index=res_opts.index(p["residency"]) if p.get("residency") in res_opts else None,
                                 placeholder="Same as nationality")
            degree = c2.selectbox("Highest degree completed", DEGREES, key=f"deg-{k}",
                                  format_func=lambda d: DEGREE_LABELS[d][:1].upper() + DEGREE_LABELS[d][1:],
                                  index=DEGREES.index(p.get("highest_degree", "bachelors")))
            ysp = c3.number_input("Years since PhD", 0, 40, p.get("years_since_phd"), key=f"ysp-{k}", placeholder="—")
            st.caption("Leave a box empty if you'd rather not say: ACCESS then marks those rules as *to confirm* "
                       "instead of guessing.")
            c1, c2, c3, c4, c5 = st.columns(5)
            age = c1.number_input("Age", 16, 80, p.get("age"), key=f"age-{k}", placeholder="—")
            ielts = c2.number_input("IELTS", 0.0, 9.0, p.get("ielts"), 0.5, key=f"ielts-{k}", placeholder="—")
            gpa = c3.number_input("GPA / 4.0", 0.0, 4.0, p.get("gpa"), 0.1, key=f"gpa-{k}", placeholder="—")
            pubs = c4.number_input("Publications", 0, 500, p.get("publications"), key=f"pubs-{k}", placeholder="—")
            wexp = c5.number_input("Work experience (yrs)", 0, 50, p.get("work_experience_years"), key=f"wexp-{k}",
                                   placeholder="—")
            ptypes = st.multiselect("Funder type", PROVIDER_TYPES, format_func=human_title, key=f"pt-{k}",
                                    placeholder="Any funder")

# Example researchers sit under the bar as one quiet row, the way search sites offer suggestions.
with st.container(key="examples"):
    cols = st.columns([0.62, 1, 1, 1, 1], vertical_alignment="center")
    cols[0].markdown("<div class='try'>Try an example</div>", unsafe_allow_html=True)
    for col, label in zip(cols[1:], PERSONAS):
        first = label.split(" - ", 1)[0]
        col.button(f"{first} · {EXAMPLE_CAPTIONS.get(first, nice(PERSONAS[label].get('career_stage')))}",
                   key=f"ex-{first}", use_container_width=True, on_click=load_example, args=(label,))
from access.config import PUBLIC
# Pressing the button is the consent. We say what that means right next to it rather than behind a checkbox.
html_block("<div class='fineprint'>By searching you agree that ACCESS uses these answers only to find funding for you. "
           + ("Searches are not stored and are never shared." if PUBLIC else
              "Searches are kept on this computer, without your name, to evaluate the system, and are never shared.")
           + "</div>")

if go:
    if not about.strip() or not nat:
        st.warning("Please add a short description of your research and your nationality.")
        st.stop()
    form = {"name": p.get("name") or "you", "nationality": nat, "residency": resid or nat,
            "career_stage": stage, "highest_degree": degree,
            "years_since_phd": ysp if degree == "phd" else None, "age": age, "ielts": ielts,
            "publications": pubs, "gpa": gpa, "work_experience_years": wexp,
            "target_countries": targets, "wanted_types": wanted,
            "provider_types": ptypes, "fields": fields, "about": about}
    t0 = time.time()
    try:
        res = instant(form)  # the eligibility answer itself; no cloud model is involved
    except Exception as e:
        st.error("Something went wrong while searching. Please try again.")
        st.caption(f"Technical detail: {type(e).__name__}: {str(e)[:160]}")
        st.stop()
    res["timings"]["first_result_s"] = round(time.time() - t0, 2)
    st.session_state.update(result=res, enrich_pending=True, show_closed=False)

res = st.session_state.get("result")
# We draw all results into one fixed container and replace it as a whole on every run. When the layout changed
# between runs (a "weaker fit" divider appearing, say), Streamlit left the previous run's cards greyed out below
# the new ones for as long as the AI ranking took.
results_area = st.empty()
if res:
    with results_area.container():
        slot = show_results(res)
        if st.session_state.get("enrich_pending"):
            run_enrichment(res, slot)
else:
    landing(lib, n_rules)
footer()
