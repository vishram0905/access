# Product framework

A lean blend of industry practice, sized for an academic project: one idea from each framework, a one-page spec,
and a fixed appetite.

| Borrowed from | What we kept |
|---|---|
| Amazon: *Working Backwards* | A one-paragraph promise as the north star (below) |
| Christensen: *Jobs To Be Done* | Three user jobs |
| Google: *HEART* | Three measurable targets |
| Apple: *Human Interface Guidelines* | Five UX principles and explicit non-goals |
| Basecamp: *Shape Up* | A fixed appetite: three build cycles, each ending in a working demo |

## The promise
> **ACCESS finds the research funding you actually qualify for, in seconds, and shows you why.** Describe yourself;
> see every programme you are eligible for, each "yes" backed by a quote from the funder's own page, with a plan to
> apply. If you are one step away, ACCESS tells you exactly what to do.

## Jobs to be done
1. *When I plan my next degree or position, I want to know which funding I can realistically win, so I don't waste weeks on ones that rule me out.*
2. *When I find a promising programme, I want to know exactly what to prepare and by when.*
3. *When I am slightly short of a requirement, I want the fastest way to close the gap.*

**Non-goals (demo):** accounts, notifications, payments, social features, a mobile app.

## Targets (HEART-lite)
| Dimension | Target | Status |
|---|---|---|
| Task success | First result in under 2 s | 0.43 s in the browser |
| Task success | No failed searches, even when AI services are down | Instant path uses no cloud AI |
| Happiness | "Was this useful?" above 80% | Cycle 3 |

## UX principles
1. **Answer first, explain on demand.** Results appear immediately; evidence, plans and Q&A open in place.
2. **Never block the user.** AI extras run in the background or on request.
3. **Every claim is traceable.** Rules and answers quote the official page.
4. **Honest about limits.** Coverage line, deadline status, archive labels, unverified-answer warnings.
5. **Plain language only.** No codes or jargon.

## Build cycles
1. **Core flow** (done): instant results, background enrichment, on-demand plans, deadline status, de-duplication.
2. **Decision support**: RAG Q&A (done), follow-up question (done), sorting/filtering, shortlist + export, shareable links.
3. **Evaluation**: benchmarks (done: retrieval, agreement, fault injection), usefulness feedback, a short usability test.
