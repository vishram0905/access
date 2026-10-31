# Design decisions

One record per component of the ACCESS architecture (see the flowchart in [ARCHITECTURE.md](ARCHITECTURE.md)).
Guiding principle: **use the method that is efficient, quick and of most value at this scale**. State of the art
where it pays off; a simpler, defended choice elsewhere. Every claim of performance points to a measurement in
[EVALUATION.md](EVALUATION.md).

Each record: **Decision** · **Alternatives considered** (including the state of the art) · **Why / trade-offs** ·
**Evidence**.

---

## Layer 0 · Data ingestion (offline, scheduled)

### D1 · Harvester: breadth-first crawl, free relevance filter, sitemaps, feeds, archive fallback
- **Decision.** Crawl outward from curated official seeds (government, university, foundation, intergovernmental,
  research institute) and structured feeds (EURAXESS, UKRI, grants.gov, Wikidata) with a page budget per site.
  A keyword/heuristic classifier discards non-funding pages before any AI is used. Content fingerprints (SHA-256 of
  normalised text) detect duplicates and changes. JavaScript-only pages go to a headless browser (Playwright).
  Sites that answer every request with a bot challenge are read from the Internet Archive (the site itself is never
  contacted), labelled with the snapshot date, and get half the official-source trust credit.
- **Alternatives.** *Focused crawling* with a learned link classifier (best-first by predicted relevance, Chakrabarti
  et al. 1999); commercial search APIs.
- **Why.** The bottleneck is annotation quota, not crawling: a learned crawler would need labelled links and would
  not increase verified rows per day. Politeness is non-negotiable (robots.txt, per-site delays, exponential
  back-off, no circumvention of protection).
- **Evidence.** 45,787 pages collected from 6,835 sites; 23,069 (50%) discarded by the free filter and 5,610 as
  duplicates, before any AI call. Fixing the text extractor (D2) raised the useful-page yield of re-reads from ~3% to ~14%.

### D2 · Text extraction: content-block selection
- **Decision.** Strip only clutter (scripts, menus, footers, site banners, form controls); choose the `main`/`article`
  block only if it holds ≥ 30% of the page text, else the whole body. Length thresholds count CJK characters ×3.
- **Why.** Two real bugs found by measurement: ASP.NET sites wrap the whole page in one `<form>` (deleting forms
  deleted the content) and teaser `<article>` boxes were picked over the real content.
- **Evidence.** e.g. ASPET award page 0 → 5,241 characters; RNG Foundation 59 → 8,492.

### D3 · Normalizer: zero-shot LLM information extraction with evidence spans
- **Decision.** Gemini Flash fills a fixed schema (~50 typed fields, controlled vocabularies). Every eligibility rule
  is a typed triple *(attribute, operator, value)* marked hard/soft and must carry a **verbatim quote** from the page.
- **Alternatives.** Fine-tuned extractor (no labelled data); hand-written parsers (brittle across thousands of
  site layouts).
- **Why.** Zero-shot extraction generalises across layouts with no training data. The evidence quote is what makes
  verification (D4) possible.
- **Trade-off.** Google's free tier caps annotation at ~500 pages/day, which is the main throughput limit. Rules
  the page states but the model misses cannot be enforced by the gate (e.g. a Chevening work-experience rule was
  missed; RAG Q&A, D15, still surfaces it).

### D4 · Info Critic (ingestion): three-vendor LLM jury, majority vote, retrieve-then-verify
- **Decision.** Three judges from **three different companies** (pool: OpenAI GPT-OSS, Alibaba Qwen, NVIDIA
  Nemotron, Zhipu GLM, Microsoft Phi-4-mini, Meta Muse; never the annotator's company) vote per rule and per key fact;
  a claim is kept only with a strict majority. A record is never decided by fewer than three judges (it waits).
  Judges see **passages retrieved for each claim** (BM25 over the page's passages) plus the page opening.
- **Alternatives.** A single strong judge; a natural-language-inference (NLI) classifier; human review.
- **Why.** Condorcet's jury theorem: a majority beats its members when each is better than chance **and errors are
  independent**; vendor diversity reduces error correlation ("no echo chamber"). Verga et al. (2024) report that a
  panel of diverse smaller judges outperforms a single large judge with less bias. Retrieval replaced an excerpt
  that only showed text around the annotator's own quotes, which hides the true value whenever the annotator was wrong.
- **Evidence.** Fleiss' κ = 0.51 (moderate agreement: diverse, not an echo chamber). Planted-error catch rates
  (768 tests): fake rule 100%, wrong page 98%, flipped nationality 51%, shifted deadline 27%, inflated funding 21%.
  Paired excerpt experiment (EVALUATION §5): no significant difference between retrieved and quote-anchored
  excerpts (3 discordant pairs of 32), +44% prompt text. Kept for its guarantee, not for a measured gain; panel
  composition appears to matter more (75-100% numeric catch rate with a different panel).

### D5 · Trust score: transparent weighted scorecard, calibrated bands
- **Decision.** Trust = 0.25 authenticity + 0.20 funding vote + 0.20 rule support + 0.20 grounding + 0.10
  agreement + 0.05 validation. Rows below the medium band are withheld from search. Band cut-offs are recalibrated
  by the Auditor after 30 blind audits.
- **Alternatives.** Learned weights (e.g. logistic regression on labelled correct/incorrect rows).
- **Why.** Explainable to users and examiners; no labelled outcomes existed at design time.
- **Future work.** The Auditor's mutation tests are labelled data, so the weights can be learned from them.

### D6 · Vector index: programme-level embeddings, exact nearest-neighbour search
- **Decision.** `nomic-embed-text` (768-d, local via Ollama), L2-normalised, cosine similarity by exhaustive dot
  product. Passage vectors are computed per document on demand and cached (D15).
- **Alternatives.** Approximate indexes (HNSW / FAISS); larger embedding models.
- **Why.** At ~400–5,000 programmes an exhaustive search is milliseconds; approximate indexes pay off around 10⁵+
  vectors. Local embeddings cost nothing and never hit a quota.
- **Evidence.** Dense retrieval alone is the weakest signal (MRR 0.60); see D7.

### D7 · Rule Register
- **Decision.** Rules are stored as a typed constraint knowledge base (attribute, operator, value, hard/soft,
  evidence quote, judge votes). Codes are always shown through a plain-English label table.

---

## Layer 1 · Profile acquisition

### D8 · User input: consent and data minimisation
- **Decision.** An explicit consent box is required before a search. Saved searches never store a personal name;
  they are kept locally only to evaluate the system. Unanswered numeric fields stay **blank (unknown)**; the form never
  invents defaults.
- **Why.** "Consent-based capture" is in the architecture; PDPA (Singapore) data-minimisation principles. A default
  age of 25 was found to silently decide age rules for users who never gave an age.

### D9 · Profile Builder: local zero-shot field inference + user confirmation
- **Decision.** Facts come from the form unchanged. Research fields are inferred by embedding the description and the
  25 field labels and keeping every field within a margin (0.035) of the best cosine score; the user can override.
- **Alternatives.** LLM slot filling (used in v1); a conversational interviewer.
- **Why.** The answer must never wait on a cloud AI service: the v1 Gemini profile builder made every search depend
  on quota. The top-1 embedding label is noisy (physics scored just below chemistry for a physicist), so a margin plus
  user confirmation is used.
- **Evidence.** Instant path 0.02–0.3 s with no cloud AI.

### D10 · One follow-up question by greedy information gain
- **Decision.** After a search, ask only the missing fact that appears in the most "unknown" eligibility checks
  across the results (e.g. "How many years since your PhD?" settles 5 results for a postdoc).
- **Alternatives.** A full conversational interviewer; asking everything up front.
- **Why.** An unknown check is an uncertain outcome; the attribute that occurs in the most unknown checks removes the
  most uncertainty per question (a greedy information-gain proxy). Deterministic, free, one question at a time.

---

## Layer 2 · Orchestration and filtering

### D11 · Research Matcher: hybrid retrieval (BM25 + dense, weighted Reciprocal Rank Fusion)
- **Decision.** BM25 (implemented from the formula) and dense similarity, fused by RRF (k = 60) with BM25 weighted 2:1.
- **Alternatives.** Dense only; BM25 only; equal-weight RRF; a cross-encoder reranker (not evaluated: CPU latency
  for marginal gains at this scale, a candidate for future work).
- **Why.** Exact names and acronyms ("SINGA", "Chevening") favour lexical matching; paraphrases favour dense. Fusion
  without score calibration is what RRF is for.
- **Evidence (100 known-item queries, 95% bootstrap CIs).** Dense MRR 0.60 · BM25 0.79 · RRF 1:1 0.76 · **RRF 2:1
  0.79** with recall@5 0.93 vs 0.88 for BM25. Ablation: plain-English document text did *not* improve dense
  (MRR 0.59): a negative result.

### D12 · Eligibility Gate: deterministic constraint satisfaction
- **Decision.** Each rule is checked by code. Five outcomes: pass, conditional (met once the current degree is
  completed), near (soft constraint missed within a margin), fail, unknown. **Unknown is never treated as pass.**
  Degree scholarships treat the stage before the funded degree as the applicant stage; postdoc ≈ early career.
- **Alternatives.** Letting an LLM decide eligibility.
- **Why.** Same input → same answer, every decision traceable to a quoted rule, testable. LLM decisions are
  non-deterministic and unauditable.
- **Evidence.** 32 hand-checked unit tests and 4 consistency checks pass; runs in under a millisecond per programme.

### D13 · Near-Miss Set: soft-constraint relaxation with a gap cost
- **Decision.** Hard rules (nationality, age, years since PhD) exclude; soft rules missed within a margin create a
  near-miss, ordered by estimated effort to close (e.g. 0.5 IELTS points ≈ 4 weeks, one publication ≈ 12 weeks).
- **Trade-off.** Effort units are hand-set and approximate.

### D14 · Orchestrator: three-tier workflow with availability-based model routing
- **Decision.** `instant()` (no cloud AI, the answer) → `enrich()` (reviewers + ranker, in the background) →
  `plan_for()` / `ask()` (on demand). Each AI role has an ordered fallback chain across providers; the first with
  free quota is used. A busy or failing AI step never removes or blocks the answer.
- **Alternatives.** A single blocking pipeline (v1); an autonomous LLM agent choosing its own steps.
- **Why.** In Anthropic's terminology ACCESS is a *workflow* (fixed paths), not an *agent*: predictability matters
  more than autonomy for eligibility. Routing by availability is what keeps a free-tier system usable.
- **Evidence.** First results 0.27 s (was 2–3 min); enrichment 15.8 s for 30 results; plans 2–12 s (was ~90 s each,
  all written up front).

### D15 · Info Critic (online): two-vendor relevance jury that orders, never removes
- **Decision.** Two reviewers (different companies) rate relevance 1–5 for the top 15 eligible results and 5
  near-misses; a mean below 2 marks a "weaker fit", shown last with the reason.
- **Why.** In testing a reviewer wrongly dropped a valid scholarship (A*STAR Graduate Scholarship for a CS student);
  eligible results must never disappear because of one model's opinion.

---

## Layer 3 · Ranking and evaluation

### D16 · Fit Ranker: one joint LLM call + late fusion
- **Decision.** Qwen sees all eligible candidates in one prompt and scores each 0–100 with a reason; final score =
  0.7 × fit + 0.3 × rescaled similarity.
- **Alternatives.** Sliding-window listwise reranking (RankGPT, Sun et al. 2023); cross-encoders.
- **Why.** Joint scoring of ≤ 30 candidates in one call gives listwise context at one call's cost; sliding windows
  need several calls per search on a rate-limited tier.

### D17 · RAG: document-scoped retrieval, cited generation, faithfulness check
- **Decision.** "Ask about this programme" and application plans retrieve passages (110-word windows, 30-word
  overlap) from **that programme's official page** with hybrid BM25 + dense; the model answers only from numbered
  passages, cites them and copies verbatim quotes; every quote is verified against the page (the same lexical
  grounding test as D4). If the passages do not answer, it must say "The official page does not say."
- **Alternatives.** A global passage vector database; LLM-judged faithfulness.
- **Why.** Every question is about one programme, so a global index is unnecessary; a page is 10–40 passages. The
  lexical faithfulness test is deterministic and free.
- **Evidence.** e.g. "Do I need work experience?" (Chevening) → "Yes, at least two years… [P3]" (a rule the
  extractor missed); an off-page question → "The official page does not say."; an answer whose quote was paraphrased
  was flagged as unverified. Faithfulness: 24/24 answers (exact 95% lower bound 0.86), median 2.7 s; 42% correctly or
  conservatively answered "the page does not say" (EVALUATION §6).

### D18 · Evaluation Harness: tests, fault injection, retrieval and agreement metrics
- See [EVALUATION.md](EVALUATION.md). Known-item retrieval needs no human labels; mutation testing creates its own
  ground truth; Fleiss' κ corrects agreement for chance; bootstrap CIs on every retrieval metric.

---

## Cross-cutting

### D19 · No echo chamber: model roles by company
Annotator (Google) ≠ judges (three other companies per record) ≠ auditor's self-grading (leave-one-out: the auditor's
own votes are removed when it re-checks rows it judged) ≠ query writer for the benchmark (NVIDIA) vs embedder (Nomic).

### D20 · Free-tier resource governance and self-healing
Per-role token budgets over a rolling 24 h window, provider cooldowns, region-fair work queues (the region with the
fewest verified programmes is served first: max-min fairness) and a Sentinel monitor that diagnoses with rules first
and lets an LLM choose only from a whitelist of safe actions (restart, bench a model, change worker counts).

### D21 · Failure semantics: provider failures are never the record's fault
Found in a health audit (5 Oct): quota and provider errors counted as failed attempts, and three attempts retire a
page, so 15,729 of 15,731 queued pages had been silently retired and annotation had all but stopped. Now: only
failures caused by the record itself count; provider failures (quota, rate limit, outage, timeout) trigger a pause
shared by all workers; every cloud client has a 90 s request timeout (a stalled Google server had left workers
waiting indefinitely); quota cooldown files are written atomically; the scout waits out a locked database; the
Sentinel's log window handles midnight. The auditor re-checks with the first model that did not judge the record,
so calibration is no longer blocked by one model's quota.

### D22 · Claim-level verification: locate deterministically, then interpret narrowly (precision over volume)
**Problem (measured 6 Oct, 575 accepted records).** The panel read all of a record's claims in one long prompt and was
wrong in both directions: 93% of the deadlines it marked "unconfirmed" (151/162) and 91% of the amounts (135/148) are
on the official page, while it caught only 27% of planted shifted deadlines, 21% of inflated amounts and 48% of
flipped nationality rules. 117 of 118 eligibility rules it dropped quote text that IS on the page, so real
restrictions were silently removed (the app then over-states eligibility). Only 114 records had every claim confirmed.
**Choice.** Each claim is checked on its own, in two steps ([factcheck.py](../access/factcheck.py)):
1. *Locate* (deterministic, free): the claim's day+month, amount digits or rule quote must occur on the page, near a
   keyword of its kind. Not located = not confirmed, whatever a model says.
2. *Interpret* (narrow LLM check): three judges from three companies see only the located passage per claim, with the
   known traps listed (opening/intake dates as deadlines, ranges as one value, per-year vs per-month, inverted rules,
   category labels judged by meaning). Majority decides.
Recurring deadlines without a year are rolled forward to the next occurrence. Unconfirmed claims are removed (shown as
"not stated, see official page"). A record is **verified** only if every claim it shows is confirmed, it has at least
one confirmed eligibility rule, and no rule quoted from the page is left unconfirmed. Only verified records are
searchable; existing records are repaired before new pages are judged.
**State of the art considered.** Claim decomposition + per-claim verification (FActScore, Min et al. 2023; SAFE, Wei et
al. 2024) and attribution checking (RARR; AIS). We adopt the decomposition and per-claim evidence, but replace the
retrieval step for numbers with exact matching, because exact matching is free and, for dates and amounts, strictly
more reliable than a model's reading.
**Trade-offs.** Fewer searchable records at first (the library shrinks while repairs run, then grows with verified
records only); +3 short judge calls per record (about 40% fewer records per day on free quota). Exact matching can
miss a true value written in an unusual format (deadline located 85%, amount 92%); the cost is a removed claim, never
a wrong one shown.
**Evidence.** `python -m access.bench locate` (all records, no model cost): true claims located: deadline 85%, amount
92%, rule quote 98%; planted shifted deadlines located 0.5% (2/436) and inflated amounts 0% (0/339), i.e. caught
before any judge reads them. Pilot of the narrow check (n = 9 records): flipped nationality rules caught 4/4; true
rules confirmed 18/22, deadlines 8/9. Two defects found by the pilot and fixed: judges renamed claim ids (votes lost)
and rejected category labels taken literally ("sedimentary geology" vs "earth climate sciences").

### D23 · Coverage order: country tiers, national programmes first, universities by ranking
**Choice (6 Oct, from the product owner).** Tier 1 = the destinations with the most student traffic: Singapore,
United States, United Kingdom, Japan, China, Australia, Canada and the rest of Europe (8 groups). New work (site
discovery, crawling, annotation, judging) serves tier 1 first; tier 2 only when tier 1 has nothing waiting. Within
tier 1 the next group is the one with the fewest programmes done (max-min fairness), so the US queue (6,000 pages)
cannot starve China (5 programmes) or Australia (0). Within a country: government and national programmes first,
then universities in ranking order (QS 2026 order, approximate; [hubs.py](../access/hubs.py) `UNIVERSITY_RANKING`),
starting from each university's central scholarships / graduate-funding page. Records already in the database are
not re-ordered; the claim-check repair queue (D22) keeps its order.
**Why.** Value to users is concentrated where students go; national schemes are few, high-value and open to many
applicants, and a university's central funding page lists most of its awards in one place, so both give the most
verified programmes per crawl.
**Trade-offs.** Tier-2 countries (e.g. Hong Kong, South Korea, India, Latin America) wait; global programmes
("Multiple"/"Global" host) are tier 2 unless their host is a tier-1 country. Rankings are a proxy for student demand,
not a measure of funding quality.

**D23 addendum (6 Oct): ranked university seeds.** Top 50 universities per tier-1 group (all universities for
Singapore and Australia; Canada filled to 50 with unranked U15 / Universities Canada members; Europe = top 50
excluding the UK; China includes Hong Kong), in QS World University Rankings 2026 order, each with its official
scholarship pages for bachelor's, master's, PhD and postdoc plus a central page where one exists:
[data/seeds/](../data/seeds/) — 355 universities, 1,059 page URLs, 790 confirmed loading at collection time. No URL is
invented (each came from a search result or a link on a fetched official page; one guessed URL was removed). These
files replace the hand-written ranking. Study level is recorded per programme by the Annotator (career_levels), and
the library can be filtered by it. Known gaps: sites behind bot walls (e.g. NUS, Oxford, several mainland Chinese
universities) are unverified or missing; Japanese universities mostly list all levels on one central page; few
universities run central postdoc schemes.

**D19 addendum (6 Oct): stand-in judge.** With Groq's daily quota spent and two NVIDIA-hosted judges (GLM, Muse)
timing out all day, only two companies were available and the critic (three companies required) stalled for ~4 h.
Probing NVIDIA's free catalogue found most listed models not served (404) or timing out; GPT-OSS-20B (OpenAI) is
served with its own quota and caught a planted flipped-nationality rule in its first test, so it joins the pool last
as an OpenAI stand-in (separate cooldown record from Groq's same-named model). The three-company rule is unchanged.
The per-judge experiment keeps its original six judges (`EXPERIMENT_JUDGES`) so its protocol stays fixed.
