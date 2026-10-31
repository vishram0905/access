# Evaluation

All numbers below are reproducible with the commands in §8. Library size at the time of measurement: 408 verified
programmes (it grows daily). Confidence intervals are 95% percentile-bootstrap intervals over queries (2,000 resamples).

## 1. Eligibility Gate (correctness of the decision logic)
- **32 hand-checked unit tests** (`access/evaluation.py: GATE_CASES, IMPLIED_CASES`): every rule type and outcome,
  including the cases that were once wrong (degree-entry scholarships, "open to all" nationality, postdoc ≈ early
  career, final-year students): **32 / 32 pass**.
- **4 consistency checks** run four example researchers against the real library and check invariants
  (e.g. nothing excluded for a rule the profile satisfies): **4 / 4 pass**.

## 2. Retrieval: known-item benchmark (`python -m access.bench`)
**Protocol.** 100 programmes sampled at random (fixed seed). For each, an LLM from a different model family than
the embedder (NVIDIA Nemotron; Nomic embedder) writes the query a qualifying researcher would type, *in its own
words and without the programme's or funder's name*; leaky queries are rejected automatically. The programme is
the single relevant item. Ranking is over the whole library (no filters, no eligibility gate).

| Method | recall@1 | recall@5 | recall@10 | MRR | ms/query |
|---|---|---|---|---|---|
| Dense (nomic-embed-text) | 0.49 [0.39–0.59] | 0.73 [0.64–0.82] | 0.83 [0.75–0.90] | 0.60 [0.52–0.68] | 11 |
| BM25 | 0.72 [0.63–0.81] | 0.88 [0.81–0.94] | 0.93 [0.88–0.97] | 0.79 [0.72–0.86] | 0.5 |
| Hybrid RRF 1:1 | 0.66 [0.56–0.75] | 0.89 [0.83–0.95] | 0.94 [0.89–0.98] | 0.76 [0.69–0.83] | 12 |
| **Hybrid RRF, BM25 2:1 (live)** | 0.69 [0.60–0.78] | **0.93** [0.88–0.97] | **0.94** [0.89–0.98] | 0.79 [0.72–0.85] | 14 |

**Ablation.** Embedding plain-English labels instead of internal codes did not help dense retrieval
(MRR 0.59 vs 0.60): the limitation is the embedding model, not the text.

**Decision.** Weighted fusion: statistically tied with BM25 at rank 1, better at placing the programme in the top 5,
and robust to paraphrased queries where BM25 alone fails.

## 3. Judge agreement (chance-corrected)
Over 1,888 rule judgements by complete three-judge panels: **Fleiss' κ = 0.51** (moderate agreement on the
Landis & Koch scale), against 67% raw unanimity. Moderate rather than near-perfect agreement is the expected
signature of independent judges; near-perfect agreement would suggest an echo chamber.

## 4. Judge reliability: fault injection (the Auditor)
The Auditor plants a known error in a verified record and re-runs the panel; detection = the panel removes the
planted rule or flags the planted fact. 768 tests to date:

| Planted error | Caught |
|---|---|
| Fake eligibility rule | 100% |
| Wrong page (record judged against another programme's page) | 98% |
| Flipped nationality rule (in ↔ not in) | 51% |
| Shifted deadline | 27% |
| Inflated funding amount (×4) | 21% |

**Reading.** The panel reliably rejects invented content but often misses subtle numeric changes. Consequences built
into the system: eligibility uses only quote-backed rules; every result links to the official page; the
retrieve-then-verify excerpt (§5) targets exactly this weakness.

## 5. Retrieve-then-verify vs quote-anchored excerpts (paired experiment)
`python -m access.bench excerpt`. Each planted error is judged twice by the **same** three judges, once with each
excerpt; discordant pairs show which excerpt made the difference.

Panel: Nemotron 3 Super (NVIDIA), Phi-4-mini (Microsoft), Muse Glimmer 30B (Meta); 8 paired tests per error type.

| Planted error | Caught, quote-anchored | Caught, retrieved | Only retrieved caught | Only anchored caught |
|---|---|---|---|---|
| Shifted deadline | 100% | 88% | 0 | 1 |
| Inflated funding | 75% | 88% | 1 | 0 |
| Fake rule | 100% | 100% | 0 | 0 |
| Flipped nationality | 88% | 100% | 1 | 0 |

Mean excerpt size: 2,292 characters (anchored) vs 3,293 (retrieved), i.e. +44% prompt text.

**Reading.** Only 3 of 32 pairs were discordant (2 favour retrieval, 1 the anchored excerpt): no significant
difference (McNemar exact test, p = 1.0). **The hypothesis that retrieval improves detection is not supported at this
sample size.** Retrieval is kept because it guarantees the judges see the passage relevant to each claim even when the
annotator's quote is wrong (a documented failure mode, e.g. a deadline absent from the anchored excerpt), at the cost
of +44% prompt text. A notable side finding: this panel caught 75-100% of numeric errors, versus the Auditor's long-run
21-27% with other panels, which suggests **panel composition matters more than excerpt construction**. Testing
judges individually is the most valuable next experiment.

## 5b. Per-judge reliability (fully crossed; protocol fixed before results)
`python -m access.bench judges [HH:MM]`, scheduled overnight by `scripts/judge_experiment_nightly.sh`.
Motivated by §5's side finding. All six judges in the pool (GPT-OSS-120B, Qwen 27B, Nemotron 3 Super, GLM-5.3 Flash,
Phi-4-mini, Muse Glimmer 30B; six different companies) vote on the **same** fixed test set
(`data/eval/judge_items.jsonl`, seed 23): 24 planted errors (6 per type: shifted deadline, inflated funding, fake
rule, flipped nationality) and 12 clean copies of the same records. Fallback models are disabled so each vote comes
from the named model; temperature 0.

- **Catch rate** = planted claim voted unsupported (no vote counts as a miss); Wilson 95% interval.
- **False-alarm rate** = true claims of clean records voted unsupported. A judge that rejects everything would
  catch 100%, so the two are reported together, with balanced accuracy = (catch + 1 − false alarm) / 2.
- **Do judges differ?** Cochran's Q over the planted items every judge has voted on.
- **Panels:** all 20 three-company panels are scored post hoc with the production majority rule from the same votes
  (no extra model calls), and the current default panel is marked.

Threats: n = 24 planted items per judge gives wide intervals (pilot scale, chosen to fit free-tier quota); clean
records were accepted by the production panel, which favours its members on the false-alarm measure.

_Results: pending (run scheduled for the night of 6 Oct 2026)._

## 5c. Claim-level verification (D22)
`python -m access.bench locate`. Step 1 (locate) on all accepted records, zero model cost:

| Claim | True claims located | Planted errors located (= missed) |
|---|---|---|
| Deadline | 85% (370/436) | shifted deadline: 0.5% (2/436) |
| Amount | 92% (312/339) | amount ×4: 0% (0/339) |
| Rule quote | 98% (915/938) | |

Step 2 (narrow check) pilot, 9 records: flipped nationality caught 4/4 (panel-level fault injection: 48%); true rules
confirmed 18/22, deadlines 8/9, programme type 6/9 (several rejections were real annotation errors, e.g. a prize
labelled "research grant"). Pilot scale; the Auditor's ongoing fault injection will measure it at scale.

## 6. RAG faithfulness ("Ask about this programme")
`python -m access.bench rag`. A fixed set of applicant questions across random programmes; an answer is
**faithful** if every quote it gives appears in the official page text and its citations point at retrieved passages,
or if it correctly answers "The official page does not say".

12 random programmes × 2 questions = 24 answers (writer: Nemotron 3 Super; median 2.7 s per answer).

| Measure | Result |
|---|---|
| Faithful answers (all quotes on the page, citations valid, or correctly "the page does not say") | **24 / 24** (exact 95% Clopper-Pearson lower bound 0.86) |
| Answers that said "The official page does not say." | 42% |

**Bug found by this evaluation.** The first run scored 79%: the verifier rejected citations written as "P5" instead of
5. Every rejected quote was in fact on the page; after fixing the parser, the same answers score 24 / 24.

**Limits.** The check proves the quotes are real, not that the answer *follows* from them (entailment is not tested).
Some "does not say" answers may be retrieval misses rather than genuinely absent information; this was not measured.

## 7. Latency (user-experience targets)
| Tier | Target | Measured |
|---|---|---|
| First results (instant path, no cloud AI) | < 2 s | 0.02–0.3 s in code; 0.43 s click-to-render in the browser |
| Enrichment (reviewers + ranker, background) | < 30 s | 15.8 s for 30 results |
| Application plan (on demand) | ~10–15 s | 2–12 s |
| RAG answer (on demand) | ~10–15 s | median 2.7 s (range 2–16 s) |

## 8. Threats to validity
- **Synthetic queries.** Known-item queries are generated from the same programme text that is indexed, which can
  favour lexical matching even with the "own words" instruction; results are relative comparisons, not absolute
  search quality.
- **Sample sizes.** 100 retrieval queries and ~8 paired tests per error type: intervals are wide; differences inside
  overlapping intervals are not claimed as significant.
- **Model overlap.** The benchmark's query writer (Nemotron) is also one of the judges; it plays no part in retrieval.
- **Coverage bias.** The library reflects which sites were reachable and annotated first (Asia-first until the queues
  were rebalanced by region).
- **Hand-set parameters.** Trust weights, gap-effort units and the 0.7/0.3 fusion are expert choices, not learned.

## 9. Reproduce
```bash
python -m access.bench            # retrieval benchmark + judge agreement -> data/eval/results.json
python -m access.bench excerpt    # paired retrieve-then-verify experiment -> data/eval/excerpt_experiment.json
python -m access.bench rag        # RAG faithfulness -> data/eval/rag_eval.json
python -c "from access.evaluation import run_gate_unit_tests as t; print(sum(x['passed'] for x in t()), len(t()))"
```
