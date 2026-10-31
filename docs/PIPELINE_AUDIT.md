# Pipeline audit: does each step work, and why this method?

One section per component, in pipeline order (the layers of [ARCHITECTURE.md](ARCHITECTURE.md)). Each section
answers four questions: **what it does**, **the concept / algorithm**, **how we know it works** (a measurement,
reproducible from the repo) and **where it fails** (and what the system does about it). Verdicts: works as
designed · works with a known limitation · broken (fixed or open).

Audit started 7 Oct 2026. Library at start: 598 searchable programmes (117 verified by the claim check, D22).

---

## Layer 0 · Building the library

### 0.1 Harvester (scout, crawler, renderer, page filter)
**What it does.** Finds funding websites (hand-picked seeds, ranked universities, national agencies, links seen while
crawling, Wikidata, grants.gov), crawls them, renders JavaScript-only pages, and keeps pages that look like a single
funding programme.

**Concepts.** Breadth-first crawl with a depth limit and one site per domain at a time (politeness); robots.txt
respected; SHA-256 content fingerprints for exact de-duplication; a free keyword-scoring filter before any model
sees a page (cost control: the annotator's free quota is the scarcest resource); headless-browser rendering
(Playwright) and Internet Archive fallback for unreachable official pages; priority queue by country tier and
provider type (D23).

**How we know it works.** (crawl datalog `data/fetchlog.db`, one row per request)

| Measure | Value |
|---|---|
| Requests / distinct domains | 84,415 / 6,021 |
| Fetched successfully | 72% (60,535) |
| Skipped because robots.txt disallows | 501 |
| Filter precision: of pages it passed to the annotator, a real programme | 67% (1,762 / 2,612) |
| … an index page listing programmes (crawled for links) | 25% (666) |
| … irrelevant | 7% (184) |
| Filter recall: discarded pages that were in fact a programme | 10% (6/60, 95% CI 5-20%), random sample of the 18,508 discarded pages over 700 characters, labelled by an independent model (Nemotron, NVIDIA) |

**Verdict (limitation): precise, with a measured recall gap.** Of the 6 misses, 2 were current programmes the keyword score put
just under the threshold, 2 were non-English pages, 2 were old news items (arguably correct to drop).
**Tried and rejected:** adding tier-1-language keywords. On the same sample it rescued 0 of the 6 misses and let 3
irrelevant pages through, so it was reverted (a negative result: the misses fail on page structure, not vocabulary).
**Not done, and why:** lowering the threshold or adding a model check on borderline pages would raise recall, but
16,000 pages already wait for annotation, so recall is not the bottleneck today. Exact-hash de-duplication misses
near-duplicates (e.g. the same award page per year); the Critic catches same-name programmes on the same site
before spending judges (`_already_decided`).
Reproduce: `data/eval/filter_recall_sample.json` (labels and reasons per page).

---

### 0.2 Normalizer (annotator)
_pending_

### 0.3 Info Critic (three-company panel + claim check, D22)
**What it does.** Decides what a user may see. First a three-company panel judges the record as a whole (is this
page a funding programme, does the record match it). Then the claim check verifies every displayed claim
separately: each eligibility rule, the deadline, the amount, "fully funded" and the programme type.

**Concepts.** (1) Ensemble of heterogeneous judges: three different companies, majority vote, so one model family's
blind spots cannot pass a claim alone (D19). (2) Decomposition: a record is verified claim by claim, not as a whole,
because a whole-record verdict hides which part is wrong. (3) Retrieve-then-verify: step 1 LOCATES the claim on
the page deterministically (dates, amount digits, the rule's quote near its keywords), at zero model cost; step 2
asks each judge one narrow question per claim, showing only the located passage. A claim that cannot be located
is removed without asking a model. (4) Fail closed: Verified = every displayed claim confirmed, at least one
confirmed rule, no rule that is on the page but unconfirmed, type confirmed (or corrected by a majority naming
the same category). Anything else is withheld as "incomplete", never shown as fact.

**How we know it works.**

| Measure | Value | Source |
|---|---|---|
| Step 1 locates true claims | deadline 85%, amount 92%, rule quote 98% | §5c EVALUATION, all accepted records |
| Step 1 locates planted errors (= would let them through) | shifted deadline 0.5%, amount ×4 0% | same |
| Step 2 catches a flipped nationality rule (pilot) | 4/4; the whole-record panel caught 48% | pilot, 9 records |
| Records checked so far | 219: **142 verified (65%)**, 77 withheld | `listings.verification` |
| Located claims confirmed by the panel | rules 91% (282/310), type 86% (189/219, +7 corrected), deadline 88% (61/69), amount 69% (97/141), fully funded 65% (120/184) | same |
| Why records are withheld | a rule on the page but not confirmed 41, no confirmed rule 40, type not confirmed 23 | same |

**Findings.** (a) The type check asked the wrong question ("is it exactly this label?"), so reasonable labels were
rejected and never corrected. Rephrased as best-fit classification from the fixed list with majority correction
(7 corrected so far); 55 records re-queued. (b) Amount and "fully funded" are the least confirmed claims. A random
sample of removed amounts showed mostly TRUE amounts rejected: the page said "up to USD $5000", the claim said
"the award pays 5000 USD per total", and two of three judges correctly refused "pays" for "up to". The error was
in our claim wording, not the judges. Reworded on 7 Oct ("the page gives the award amount as 5000 USD in total,
stated exactly or as a maximum such as 'up to'; a range is not one value"); re-asking only the amount claim on the
44 removed amounts: **35 now confirmed** (full three-company panels); the 9 still rejected were read by hand and
8 are correct rejections (5 ranges such as "S$1,600 to S$2,000", 2 minimums "at least S$650", 1 stipend that rises
after the qualifying exam), 1 arguable (an amount with no period stated). **Negative control** (does the looser
wording accept anything?): in 28 confirmed records the amount was replaced by a different number that is also on
the page near funding words, so step 1 still locates it: 1/28 accepted, and that one is a real figure on the page
(S$4,800, the permanent-resident tier of a tiered stipend). The 35 confirmed amounts were restored from these
votes (same standard as the critic: a majority of three companies). Data: `data/eval/amount_recheck.json`,
`amount_negctl.json`. Schema limit exposed: one amount per programme cannot express tiered rates (by
citizenship or stage); the record keeps the headline figure. Planted ×4 amounts are stopped earlier, at the locate step (0/339 located), so
the looser wording does not let inflated amounts through. Removed "fully funded" claims are mixed: some correct
(subsidised tuition plus an allowance is not full funding), some arguable (tuition plus a monthly stipend). (c) **Open:** 83% of panels are OpenAI + NVIDIA + Microsoft (Phi-4-mini, a 3.8B
local model), because the other companies' free quota runs out first. If Phi is the weak vote, it drives the
withheld rate. The per-judge experiment (EVALUATION §5b) measures each judge's accuracy on planted errors and
clean records and answers this. (d) The Auditor's fault injection tested only the whole-record panel, not the
claim check that now decides "verified". Fixed on 7 Oct: planted errors go through the full gate, and a catch
counts only if the error is not shown (panel rejects, claim removed, or record withheld); see §0.5.

**Verdict (limitation): works, fail-closed by design; cost is yield.** 35% of checked records are withheld, the price of
showing only confirmed claims (the user's stated preference: 500 trusted rows over 2,000 unverified ones).

### 0.4 Vector index and rule register
_pending_

### 0.5 Auditor (blind re-read, fault injection, calibration)
**What it does.** Measures the gate rather than trusting it: (1) re-reads random pages blind and compares its
extraction with the stored record (agreement feeds calibration of the trust bands); (2) plants known errors in
verified records and checks whether they get through.

**Concept.** Fault injection / mutation testing: a detector's recall is measured with errors whose location is
known. Five error kinds: fake eligibility rule, flipped nationality rule, deadline shifted by months, amount ×4,
record paired with the wrong page.

**Findings (7 Oct).** (a) It tested the wrong gate: errors went through the whole-record panel only, while
"verified" is now decided by panel **plus** claim check (D22). Fixed: each planted error runs through the full
gate as deployed, with a fresh three-company panel from the judge pool, and counts as caught only if it would not
be shown, credited to the first layer that removes it (panel, claim check, or record withheld). Old rows stay in
the table but are excluded from the reported catch rate. (b) Our own test bug, found by its first "miss": the
panel nulls an unconfirmed amount in place, so the comparison saw the planted value as None on both sides and
reported an inflated amount as surviving. The test now compares against a snapshot taken before judging.

**Results so far** (corrected test): 5/5 kinds caught: wrong page and the three re-run kinds by the panel,
shifted deadline by the claim check. One test per kind proves the harness runs end to end, not a catch rate;
the Auditor now adds tests continuously, and calibration reports per-kind rates (`data/lookup/calibration.json`).
**Verdict (limitation): harness fixed and running; rates still to accumulate.**

## Layer 1 · User input
### 1.1 Input form · 1.2 Profile builder
_pending_

## Layer 2 · Matching
### 2.1 Research matcher (hybrid retrieval)
_pending_

### 2.2 Eligibility gate
**What it does.** Checks every rule of every candidate programme against the profile, one line at a time, and puts
the programme in one of three groups: eligible, within reach (near-miss), excluded.

**Concept.** Deterministic constraint satisfaction over a typed rule register (`nationality in [...]`,
`gpa >= 3.5`, `career_stage in [...]`), with five outcomes per rule: pass, fail, near, conditional (met once the
current degree is completed), unknown (the profile lacks the attribute: never a silent pass or fail). No model is
involved, so the decision is reproducible and explainable line by line, each line citing the page's own quote.

**How we know it works.** 32/32 unit tests (one per rule type and outcome, incl. 5 near and 3 conditional cases)
and 4/4 invariants (e.g. a programme is never both eligible and excluded) pass: `access.evaluation`.

**Verdict (works): logic correct.** It is only as good as the rules it is given, which is why D22 verifies each rule
against the page before the gate may use it.

### 2.3 Near-miss set
**What it does.** Programmes that fail only soft, closable gaps (one career step, a GPA or language score just below
the bar) are shown as "within reach", easiest gap first.

**Concept.** Soft-constraint relaxation ordered by an estimated gap cost (weeks of effort: e.g. +0.5 IELTS ≈ 4
weeks, one career step ≈ 26 weeks).

**How we know it works.** Unit tests above (5 near cases). On the whole library the gate finds near-misses
(Priya 19, Amara 15).

**Finding (7 Oct): the four example researchers show 0 near-misses.** Not a code regression (the gate is unchanged
since the first commit, and an older library gives the same picture): near-misses fall outside each example's
chosen countries and programme types, and they are rare by nature, because pages seldom state numeric thresholds
(GPA in 17 of 598 records, IELTS in 2). **Verdict (limitation): correct but rarely visible.**

### 2.4 Orchestrator · 2.5 Online critic
_pending_

## Layer 3 · Results
### 3.1 Fit ranker
**What it does.** Scores every eligible programme 0-100 for fit with the researcher's field, stage and goals, with a
one-sentence reason, then blends that with semantic similarity.

**Concept.** LLM-as-ranker (pointwise scoring in small listwise batches) plus late fusion:
`score = 0.7 x fit + 0.3 x similarity` (similarity rescaled to 0-100). The ranker only ORDERS; the gate decides
eligibility, so a ranker failure can never hide or admit a programme. Without a score the item falls back to
similarity alone and is labelled so (never an invented score).

**Finding (7 Oct): incomplete and slow, fixed.**

| Problem (measured on the 4 example researchers) | Cause | Fix |
|---|---|---|
| 3-4 of 30 programmes left unranked; 0 ranked whenever Qwen was out | one prompt with all 30 items: the model drops items; one model, no fallback | batches of 10, a second pass for skipped ids, fallback chain Qwen → Nemotron → GLM (three companies); one model per researcher where possible, since scores from different models are not on one scale; each item records which model scored it |
| 215-531 s per researcher, even after batching | one batch costs ~2 s of model time; the rest was waiting for Groq's per-minute token window, which the background critic kept full; the ranker also counted against the critic's budget | per-minute priority: background roles may fill only 60% of each minute (`BACKGROUND_TPM`), so a live request never queues behind them |

After the fix (critic running at the same time, no cache): Daniel 29/29 ranked in 55 s, Priya 17/17 in 15 s, both
by the fallback model because Qwen had reached Groq's daily limit, which is the case the fallback exists for.
**Verdict (works): complete; latency now bounded by the model, not by the queue.**
**Trade-off:** the critic loses up to 40% of its per-minute throughput when no one uses the app (the
reserve is not lent out); accepted because the app answers in seconds and the critic works around the clock.

### 3.2 Shortlist, plans and Q&A · 3.3 Evaluation harness
_pending_
