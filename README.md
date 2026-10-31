# ACCESS

**AI-Curated Constraint-Aware Eligibility and Scholarly Search**

ACCESS finds the research funding a researcher is actually eligible for, and shows why. You describe yourself once;
within about a second you see the scholarships, fellowships and grants whose rules you meet, and every "yes" is
backed by a quote from the funder's own page.

We built it as our group project for GP8000/GP8001 AI Literacy at NTU (Cohort C, Group 5). It runs entirely on free
model tiers and local models.

- Live app: <https://access-funding.streamlit.app/>
- Project site (method, results, test report): <https://vishram0905.github.io/access-docs/>

## Why we built it

Funding calls are scattered across thousands of university, government and foundation websites. Existing scholarly
recommenders rank opportunities by topic, but topic is rarely what stops someone applying: nationality, career stage,
host country and deadline are. And a wrong deadline or a misread nationality rule costs an applicant weeks.

So we split the work in two. Language models do what they are good at, reading messy web pages and judging whether a
sentence supports a claim. Plain code makes the decisions that must be reproducible, such as whether a researcher
meets a nationality rule.

## How it works

| Layer | What happens | Main methods |
|---|---|---|
| 0 · Build the library (offline) | Agents crawl official funder sites, extract each programme into a fixed schema with a quote for every rule, and verify each claim | Breadth-first crawl with robots.txt, SHA-256 de-duplication, keyword pre-filter, schema-constrained extraction, three judges from three different companies with a majority vote, trust score, fault injection |
| 1 · Understand the user | A short form becomes a structured profile | Form fields taken as given, zero-shot field classification with local embeddings |
| 2 · Match and filter | Relevant programmes are retrieved, then every rule is tested | BM25 plus dense retrieval fused by reciprocal rank fusion, a deterministic eligibility gate, near-misses ordered by gap cost |
| 3 · Rank and explain | Eligible programmes are ordered by fit and explained | LLM fit score fused with similarity, retrieval-augmented Q&A with citation checks, on-demand application plans |

The component map and the agents are described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Why we picked each
method over the alternatives, with the measurements behind each choice, is in [docs/DECISIONS.md](docs/DECISIONS.md).

## Results

All figures are measured on the repository's own benchmarks; the details are in [docs/EVALUATION.md](docs/EVALUATION.md)
and [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

- **Retrieval:** on 100 known-item queries, hybrid search reaches MRR 0.79 and recall@5 0.93, against 0.60 and 0.73
  for dense retrieval alone.
- **Verification:** the judge panel agrees at Fleiss' κ = 0.51. It catches 100% of invented rules and 98% of wrong
  pages, but only 21 to 27% of subtle numeric changes, which is why we added a deterministic claim check on top.
- **Questions and answers:** 24 of 24 answers quote only what is on the official page.
- **Eligibility gate:** 32 of 32 unit tests pass. First results appear in about 0.4 s; the AI ranking adds about 15 s
  in the background.

## Running it locally

```bash
pip install -r requirements.txt
ollama pull nomic-embed-text           # local embeddings, needed for search
cp .env.example .env                   # add free API keys for Gemini, Groq and NVIDIA

streamlit run app.py                   # http://localhost:8501
```

The repository ships a snapshot of the verified library in `data/lookup/`, so the app works without running the
agents. Search itself only needs the local embedding model; the AI ranking, plans and Q&A use the API keys.
The Database page reads the agents' working database, so on a fresh clone it shows zeros until the agents have
run for a while.

To build and grow the library yourself:

```bash
playwright install chromium            # renders JavaScript-only pages
ollama pull phi4-mini                  # local judge
python agents.py start                 # Scout, Scraper, Critic, Auditor and Sentinel in the background
python agents.py watch                 # live status
PYTHONPATH=. python scripts/test_suite.py --no-ai   # the automated test suite
```

## Repository layout

```
app.py              Streamlit entry point; the pages live in views/
views/              Search, How it works, Database, Quality
agents.py           start, stop, status and watch for the background agents
access/             the system itself (see docs/ARCHITECTURE.md for the component map)
scripts/            test suite, demo checks and the public build
data/lookup/        the published search library (snapshot)
data/eval/          benchmark query sets and results
docs/               architecture, design decisions, evaluation, test report, product framework
```

## Responsible design

- The crawler respects robots.txt and rate limits. We never get around bot protection: protected sites are listed as
  links only, or read from a public archive copy that is labelled as such.
- A search needs the visitor's consent, and saved searches contain no names.
- Eligibility is decided by tested code, not by a model, and every decision traces back to a sentence on the
  funder's page.
- ACCESS is a research prototype. Always confirm the details on the funder's official website before applying.

## Team

GP8000/GP8001 AI Literacy, Nanyang Technological University, Cohort C, Group 5.
