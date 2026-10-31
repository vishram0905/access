# ACCESS app: test report

**Run:** 12 October 2026, 06:26 SGT · **Suite:** `scripts/test_suite.py` (results in `data/eval/test_suite.json`)
**Library under test:** 373 claim-verified programmes · **Status of the app:** work in progress (demo build)

## 1. Summary

| | |
|---|---|
| Tests run | 49, in 12 areas |
| Passed | **48** |
| Failed | **1** (D2: three of fourteen test profiles receive fewer than five results; a coverage gap, not a logic error) |
| Defects found and fixed while preparing and running the suite | **10** in the app, **3** in the test suite itself (Section 5) |
| Wall-clock time | 31 s with warm caches; about 2 min when the AI services are called afresh |

The core promise of the app holds in every test: **every programme shown matches the researcher's chosen country,
funding type and career stage, every displayed eligibility rule is quoted from the funder's official page, and the
same input always gives the same answer.** The remaining weakness is coverage: some combinations (for example a
master's degree in Japan, or mid-career research grants) return only one to four programmes because few verified
programmes exist for them yet.

## 2. Scope and method

The suite tests the app as a user meets it (the four pages and the search form) and the components behind it
(eligibility gate, search library, retrieval, AI ranking, question answering, application plans). Three kinds of test
are used:

- **Example-based tests** compare an output with a known correct answer (for example, 37 hand-checked eligibility
  cases).
- **Property and integrity tests** check a statement that must hold for every item (for example, "every rule's quote
  appears on the official page", checked for all 633 rules).
- **Metamorphic tests** compare related searches when the correct answer for one search is unknown. If a
  researcher adds a country, no result for the countries already chosen may disappear. Such relations expose
  logic errors without a labelled ground truth.

Fourteen realistic researcher profiles are used across the suite: the four example researchers on the home page and
ten new ones that vary nationality, career stage, field, destination and funding type (Appendix A).

The AI tests (H to J) use the free-tier models deployed in the app. Their outputs are cached, so repeated runs are
fast and reproducible, and latencies reported for them come from the first, uncached run.

## 3. Results by area

### A. Unit tests: eligibility logic

| ID | Test | Result |
|---|---|---|
| A1 | Hand-checked eligibility cases: every rule type and outcome (pass, fail, near, conditional, unknown), including cases that were once wrong | **37/37 pass** |
| A2 | Library-wide invariants for the four example researchers (for example, a programme is never both eligible and excluded) | **4/4 pass** |

### B. Library integrity

| ID | Test | Result |
|---|---|---|
| B1 | Every searchable programme is claim-verified | 373/373 |
| B2 | No programme from an excluded place | 0 found |
| B3 | Programme identifiers are unique | 373 unique |
| B4 | One embedding vector per programme | 373 vectors |
| B5 | Every eligibility rule's quote is found on the stored official page | **633/633 (100%)**, no rule without a quote |
| B6 | Programme types and career levels come from the controlled vocabulary | 0 violations |
| B7 | Every programme links to an official web page | 0 invalid links |
| B8 | Names and funders contain no internal codes (such as `biology_life_sciences`) | 0 found |
| B9 | The displayed host country agrees with the stored host-country list | 0 disagreements |
| B10 | Programmes whose several host countries are not yet resolved ("Multiple") | 32 of 373, kept out of country searches until resolved |
| B11 | Search filters point only to programmes in the library | 0 dangling references |

### C. Retrieval quality

Known-item benchmark: for each programme, an independent model wrote the query a qualifying researcher would type,
without the programme's or funder's name. The test uses the 54 benchmark programmes that are in today's verified
library and searches the whole library with the hybrid method used by the app.

| Measure | Result |
|---|---|
| Recall@1 | 0.74 |
| **Recall@5** | **0.93** |
| Recall@10 | 0.96 |
| Mean reciprocal rank | 0.82 |

These figures match the earlier benchmark on the larger, partly unverified library (recall@5 0.93), so restricting
search to verified programmes did not reduce retrieval quality.

### D. Consistency across 14 researcher profiles

Each result of each profile is checked against the request: host country (or its region, "any country" or "not
stated"), funding type, career stage, closed calls, duplicates, readable labels, excluded places and verification.

| ID | Test | Result |
|---|---|---|
| D1 | Results match the chosen country, type and career stage | **0 mismatches in 14 profiles** |
| D2 | Every profile receives at least five eligible programmes | **Fail:** Sofia (4), Hiroshi (1), Minh (1) |

Eligible programmes per profile (instant results, before AI ranking):

| Profile | Eligible | Profile | Eligible |
|---|---|---|---|
| Priya (PhD, Singapore) | 11 | Sofia (master's, Australia or UK) | 4 |
| Wei Ling (postdoc, UK, Germany, Singapore) | 11 | Hiroshi (mid-career grants, Japan or US) | 1 |
| Daniel (postdoc, Germany, Japan, Singapore) | 17 | Fatima (postdoc, Canada or US) | 8 |
| Amara (master's, UK, Germany, France) | 6 | Lucas (master's, Germany, Netherlands, UK) | 5 |
| Chen (PhD, Singapore, Japan, Australia) | 12 | Minh (master's, Japan) | 1 |
| Aisha (undergraduate, Singapore) | 23 | Siti (undergraduate, Singapore) | 27 |
| Tom (research or travel grants, US) | 6 | Arjun (any country, any type) | 29 |

The thin profiles reflect the verified library, not the logic: their results are correct, there are simply few
verified programmes for those combinations yet. Two further observations, not failures:

- Aisha sees two different programmes with the same title ("ASEAN Undergraduate Scholarship", offered by two
  universities). The app now shows the funder after such titles.
- Arjun, who chose no country, sees five programmes whose host countries are still being resolved; they are labelled
  "Several countries (see official page)".

### E. Metamorphic tests

| ID | Relation that must hold | Result |
|---|---|---|
| E1 | The same search twice gives the same results in the same order | Holds |
| E2 | Adding a country never removes results for the countries already chosen (10 profiles) | Holds, 0 violations |
| E3 | Removing the funding-type filter never removes a result (10 profiles) | Holds, 0 violations |
| E4 | A nationality rule admits the nationals it lists and excludes others (every such rule in the library) | **147/147 rules** |
| E5 | A missing attribute is reported as "unknown", never silently passed or failed (every programme) | 0 silent decisions |
| E6 | Giving more information never adds a programme that was not already eligible | Holds (13 eligible with nationality blank, 11 with it given, 0 added) |

### F. Robustness to unusual inputs

All twelve inputs return a sensible answer without an error, in under 60 ms.

| ID | Input | Result |
|---|---|---|
| F1 | Empty research description | 12 eligible |
| F2 | 20,000-character description | 11 eligible, 56 ms |
| F3 | Description in Chinese | 12 eligible |
| F4 | HTML and a script tag in the description | 11 eligible, nothing executed |
| F5 | Emoji only | 12 eligible |
| F6 | No nationality given | 13 eligible (nationality rules reported as "unknown") |
| F7 | No countries and no types chosen | 30 eligible (list limit) |
| F8 | Every funding type chosen | 12 eligible |
| F9 | Working professional with a master's degree seeking a PhD scholarship | 11 eligible (was 0 before a fix, see D-6 in Section 5) |
| F10 | Senior researcher, 30 years after the PhD, seeking a PhD scholarship | Correctly 0 |
| F11 | Implausible numbers (age −5, GPA 9.9, IELTS 12) | 11 eligible, no crash |
| F12 | A country with no programmes (Nepal) | 3 programmes, all open to any country or not tied to one |

### G. Performance

| Measure (30 searches, instant path, no cloud AI) | Result | Target |
|---|---|---|
| Median | **24 ms** | |
| 95th percentile | 28 ms | under 2 s |
| Maximum | 28 ms | |

The browser adds rendering time (about 0.4 s measured earlier from click to results).

### H. AI ranking (background enrichment)

| ID | Profile | Programmes scored | Order consistent* | Time (uncached) |
|---|---|---|---|---|
| H1 | Priya | 11/11 | Yes | 13 s |
| H2 | Daniel | 17/17 | Yes | 26 s |
| H3 | Siti | 27/27 | Yes | 23 s |

\*Strong matches by score, then weaker fits by score, then closed programmes. All runs used the main ranking model
(Qwen 27B); both independent reviewers answered (no reviewer errors after fix D-9).

### I. Question answering about a programme

| ID | Test | Result |
|---|---|---|
| I2 | Questions the official page does answer (funding of LKY-STEP and NTU Research Scholarship, eligibility for A*STAR Graduate Scholarship and Chevening) | **4/4 answered, every quote found on the page** |
| I1 | Six random programme and question pairs | 6/6 faithful; all six answered "The official page does not say" |

I1 shows that the safeguard works (no invented answers), but it also shows a limitation: for programmes whose stored
page is short or is a third-party summary, the honest answer is often "the page does not say". Answering from the
funder's linked documents would be the next improvement.

### J. Application plans

| ID | Test | Result |
|---|---|---|
| J1 | A plan is written for the top eligible programme | 1,515 characters (cached; 2 to 12 s when written afresh) |

### K. Privacy

| ID | Test | Result |
|---|---|---|
| K1 | A searcher's name is never stored | Stored as "you" |
| K2 | An edited example search is not stored or shown as the example | Holds |

### L. User interface (run through the real multipage app)

| ID | Test | Result |
|---|---|---|
| L1 | Search page renders | 0 exceptions |
| L2 | How it works page renders | 0 exceptions |
| L3 | Database page renders | 0 exceptions |
| L4 | Quality page renders | 0 exceptions |
| L5 | Each example opens and shows eligible programmes | Priya 11, Wei Ling 11, Daniel 17, Amara 6 |
| L6 | A search typed into the form returns results | Results shown, 0 exceptions |

## 4. Known limitations

1. **Coverage** (D2): a few combinations return one to four programmes. The library holds 373 verified programmes and
   grows as the critic verifies the backlog.
2. **Unresolved host countries** (B10): 32 verified programmes list several host countries that are not yet
   resolved. They are excluded from country searches, so a researcher choosing a country may miss some of them.
   Resolution needs the Gemini extractor, whose free quota resets daily at about 15:00 SGT.
3. **Near misses are rare**: the gate finds near misses correctly (unit tests), but funder pages seldom state numeric
   thresholds, so most profiles see none.
4. **Q&A depends on the stored page** (I1): short or third-party pages often lead to "the official page does not say".
5. **Data errors the checks cannot catch**: an eligibility rule that the extractor missed cannot be enforced. The
   independent reviewers flag some of these as "weaker fit" (for example, a postdoc programme restricted to US and
   Canadian scholars), but the programme is still listed as eligible.
6. **Free-tier dependence**: AI ranking takes about 10 s to 2 min depending on quota. Results always appear first and
   remain usable if the AI services are unavailable.

## 5. Defects found and fixed

### In the app

| # | Defect | How it was found | Fix | Evidence after the fix |
|---|---|---|---|---|
| D-1 | An edited example search ("Wei Ling" changed to a master's student in cancer research) replaced the real example, so the form and the results did not match | Manual check of the examples in the browser | A saved search counts as an example only if its form is unedited; examples regenerated | K2, L5 |
| D-2 | 187 programmes that had not passed the claim check were searchable | Consistency harness (97 unverified results across profiles) | Search library holds verified programmes only | B1 |
| D-3 | With fewer than 8 matches, the country filter was silently dropped and programmes from other countries appeared | Consistency harness (9 wrong-country results for one profile) | A filter is relaxed only when nothing matches, and the page says so | D1, F12 |
| D-4 | Programmes labelled "Multiple" matched every country search | Consistency harness | Excluded from country searches until resolved | D1, B10 |
| D-5 | A PhD candidate was told a grant requiring at least 7 years since the PhD would be "met once your PhD is awarded" | Consistency harness (stage check) | Such rules now fail for PhD candidates | A1 (2 new cases) |
| D-6 | A working professional with a master's degree was excluded from every PhD scholarship | Robustness test F9 | Holding the preceding degree qualifies as an applicant | F9, A1 (3 new cases) |
| D-7 | One-off calls that had closed, and calls named for a past year ("2020-21"), were shown as current | Consistency harness | Dropped or marked closed and listed last | D1 |
| D-8 | Match scores were not in order on screen (for example 82, 77, 71, then 89) | Manual check in the browser | Strong matches by score, then weaker fits by score under a heading | H1 to H3 |
| D-9 | The local reviewer model was benched after timeouts caused by the background critic, so live searches reported reviewer errors | Trace of test H | On demo days the local model serves live searches only | H1 to H3 (no reviewer errors) |
| D-10 | Generic or identical titles ("Research Fellowships", two "ASEAN Undergraduate Scholarship") were ambiguous | Consistency harness | The funder is added to such titles | Section 3D |

### In the test suite

Errors in the tests themselves were found by their first results and corrected, so that a pass means what it says:
E6 originally could not fail, F12 expected the wrong behaviour (a country with no programmes correctly shows
programmes open to any country), and the interface tests first loaded pages outside the app's navigation.

## 6. How to reproduce

```bash
cd access-prototype
PYTHONPATH=. python scripts/test_suite.py           # full suite, about 2 min uncached
PYTHONPATH=. python scripts/test_suite.py --no-ai   # without the AI tests (H to J), under 30 s
PYTHONPATH=. python scripts/demo_check.py --verbose # the 14-profile consistency check with the top results
```

## Appendix A. Test profiles

| Profile | Nationality | Stage | Seeking | Where |
|---|---|---|---|---|
| Priya | India | Master's student | PhD scholarship | Singapore |
| Wei Ling | Singapore | PhD candidate | Postdoctoral fellowship | UK, Germany, Singapore |
| Daniel | United States | Postdoc, 2 years after PhD | Postdoctoral fellowship or research grant | Germany, Japan, Singapore |
| Amara | Nigeria | Undergraduate | Master's scholarship | UK, Germany, France |
| Chen | China | Master's student | PhD scholarship | Singapore, Japan, Australia |
| Aisha | Malaysia | School leaver | Undergraduate scholarship | Singapore |
| Tom | United Kingdom | PhD candidate (history) | Research or travel grant | United States |
| Sofia | Indonesia | Graduate | Master's scholarship | Australia, UK |
| Hiroshi | Japan | Mid-career (12 years after PhD) | Research grant | Japan, United States |
| Fatima | Pakistan | PhD candidate (public health) | Postdoctoral or research fellowship | Canada, United States |
| Lucas | Brazil | Graduate (engineering) | Master's scholarship | Germany, Netherlands, UK |
| Minh | Vietnam | Graduate (economics) | Master's scholarship | Japan |
| Siti | Singapore | Undergraduate | Undergraduate scholarship | Singapore |
| Arjun | India | Postdoc (AI) | Any funding | Anywhere |
