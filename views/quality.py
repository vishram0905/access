"""Quality: how ACCESS tests itself - unit tests, consistency checks, judge agreement and the Auditor's
planted-error tests."""
import json

import altair as alt
import pandas as pd
import streamlit as st

from access.evaluation import critic_metrics, run_gate_unit_tests, run_invariants
from access.lookup import LOOKUP
from access.ui import html_block, esc, footer, nice, setup

setup()
html_block("""<div class='hero' style='padding-top:6px'><div class='eyebrow'>Quality</div>
<h1 style='font-size:2.3rem'>How ACCESS checks itself</h1>
<p class='lead'>Automatic tests of the eligibility logic, the judge panel and the data, with no human labelling
needed.</p></div>""")


@st.cache_data(ttl=300)
def metrics():
    return critic_metrics()


cal_file = LOOKUP / "calibration.json"
cal = json.loads(cal_file.read_text()) if cal_file.exists() else {}
m = metrics()

html_block("<div class='section-title'>1 · Planted-error test (Auditor)</div><div class='section-sub'>The Auditor "
            "secretly plants a mistake in a verified record, such as a fake rule or a shifted deadline, and checks "
            "whether the judge panel catches it. This measures how reliable the judges are.</div>")
rates = cal.get("catch_rate", {})
if rates:
    df = pd.DataFrame([{"Planted error": nice(k), "Caught": round(100 * v["caught"]), "Tests": v["tests"]}
                       for k, v in rates.items()])
    total = sum(v["tests"] for v in rates.values())
    caught = sum(v["caught"] * v["tests"] for v in rates.values())
    c1, c2 = st.columns([1, 2.2])
    c1.markdown(f"<div class='kpi'><b>{100 * caught / max(1, total):.0f}%</b><span>of {total:,} planted errors "
                f"caught overall</span></div>", unsafe_allow_html=True)
    c2.altair_chart(alt.Chart(df).mark_bar(cornerRadiusEnd=6, height=18).encode(
        x=alt.X("Caught:Q", scale=alt.Scale(domain=[0, 100]), title="% caught"),
        y=alt.Y("Planted error:N", sort="-x", title=None),
        color=alt.Color("Caught:Q", scale=alt.Scale(domain=[0, 50, 100], range=["#B23B3B", "#C8642B", "#2E7D4F"]),
                        legend=None),
        tooltip=["Planted error", "Caught", "Tests"]).properties(height=200), use_container_width=True)
    def listing(xs):
        names = {"fake_rule": "fake rules", "wrong_page": "wrong pages", "shifted_deadline": "shifted deadlines",
                 "inflated_funding": "inflated funding amounts", "flipped_nationality": "flipped nationality rules"}
        xs = [names.get(x, nice(x).lower()) for x in xs]
        return ", ".join(xs[:-1]) + " and " + xs[-1] if len(xs) > 1 else (xs[0] if xs else "")
    strong = listing([k for k, v in rates.items() if v["caught"] >= 0.8])
    weak = listing([k for k, v in rates.items() if v["caught"] < 0.5])
    finding = (f"Finding: the panel reliably catches {strong or 'no error type yet'}"
               + (f", but often misses {weak}. That's why eligibility decisions use only rules backed by "
                  f"a verbatim quote, and results link to the official page for the final check." if weak else "."))
    st.caption(finding + (f" Trust bands are provisional until 30 records are blind-audited "
                          f"({cal.get('audited', 0)} so far)." if cal.get("provisional") else ""))
else:
    st.info("The Auditor has not reported yet.")

html_block("<div class='section-title'>2 · Judge panel</div><div class='section-sub'>Judges from different "
            "companies should agree often, but not always. Constant agreement would suggest an echo chamber."
            "</div>")
if m:
    html_block(f"""<div class='kpis'>
<div class='kpi'><b>{m['listings_reviewed']:,}</b><span>records reviewed by the panel</span></div>
<div class='kpi'><b>{m['official_sources_pct']}%</b><span>from official sources</span></div>
<div class='kpi'><b>{m['rules_dropped_by_panel_pct']}%</b><span>of extracted rules removed as unsupported</span></div>
<div class='kpi'><b>{m['evidence_found_verbatim_pct']}%</b><span>of rules with the quote found word-for-word</span></div>
</div>""")
    pairs = sorted(m["judge_agreement_pct"].items(), key=lambda kv: -kv[1])
    if pairs:
        with st.expander("Agreement between each pair of judges"):
            st.dataframe([{"Judge pair": k, "Agreement": f"{v}%"} for k, v in pairs], hide_index=True,
                         use_container_width=True)

html_block("<div class='section-title'>3 · Logic tests</div><div class='section-sub'>Unit tests for the "
            "Eligibility Gate, and consistency checks that run example researchers against the real data.</div>")
if st.button("Run all tests", type="primary"):
    with st.spinner("Running tests…"):
        unit, inv = run_gate_unit_tests(), run_invariants()
    n_u, n_i = sum(x["passed"] for x in unit), sum(x["passed"] for x in inv)
    c1, c2 = st.columns(2)
    c1.markdown(f"<div class='kpi'><b>{n_u}/{len(unit)}</b><span>Eligibility Gate unit tests passed</span></div>",
                unsafe_allow_html=True)
    c2.markdown(f"<div class='kpi'><b>{n_i}/{len(inv)}</b><span>example researchers with no inconsistencies"
                f"</span></div>", unsafe_allow_html=True)
    with st.expander("Test details"):
        st.dataframe(unit, hide_index=True, use_container_width=True)
        st.dataframe([{k: (v if k != "faults" else len(v)) for k, v in x.items()} for x in inv], hide_index=True,
                     use_container_width=True)
    for x in inv:
        for f in x["faults"]:
            st.error(f"{esc(x['persona'])}: {f}")
footer()
