# Lead agent

Finds and scores potential customers/clients for outreach, then writes scored,
drafted rows to `agency.leads` for human review.

## Pipeline

```
raw query + target domains
  → parse_query_to_fields (shared/llm)      # natural language → 6 lead fields (rubric)
  → fetch_from_hunter per domain (sources)  # mock fixture by default
  → dedup_by email (shared/utils)
  → enrich_lead per candidate (enricher)    # 1 LLM call → fit_score + draft_message
  → upsert to agency.leads (shared/db)      # on_conflict=email
  → insert one agency.search_runs row
```

`run.py` is the only module that touches the database. `sources.py` and
`enricher.py` are pure (data in, data out) so they unit-test offline with no network.

## Source: Hunter, domain-centric

Apollo's people-search API is paywalled on the free plan (`API_INACCESSIBLE`), so the
live source is **Hunter.io** `/v2/domain-search`. Hunter is domain-centric: you give
it a company domain and it returns the people it knows there — it does not filter by
role. So the agent takes a list of **target domains**, and the LLM does the role
filtering by scoring each person against the query criteria. Set a `score_threshold`
to drop low-fit people before review.

`fetch_from_apollo` is kept as the upgrade path for when the org funds a paid Apollo
plan; it shares the same normalized candidate shape, so swapping sources touches only
the source edge, not the pipeline.

## Files

| File | Role |
|---|---|
| `sources.py` | `fetch_from_hunter` (live source) + `fetch_from_apollo` (paid upgrade path); mock/live via `LEAD_SOURCE_MODE` |
| `enricher.py` | `enrich_lead` — one Groq call returns `fit_score` (0–100) + `draft_message` |
| `run.py` | `run_lead_agent(raw_query, *, domains, score_threshold=0, limit=25)` — orchestrates + writes |
| `fixtures/hunter_sample.json` | Mock Hunter response (includes a dup + null-email row) |
| `fixtures/apollo_sample.json` | Mock Apollo response (for the upgrade path) |

## Running

Mock (default — zero credits):

```python
from agents.lead.run import run_lead_agent
summary = run_lead_agent(
    "Heads of L&D at mid-size tech companies",
    domains=["northwind-labs.com"],
)
```

Live validation (⚠️ spends Hunter searches, ~25/month free tier — one per domain):

```powershell
$env:LEAD_SOURCE_MODE = "live"
python scripts/validate_lead_live.py     # PYTHONPATH=. on the import if needed
```

Each domain = 1 Hunter search credit. Each returned person = 1 Groq call (free tier:
30/min, 14,400/day).

## Scoring contract

`fit_score` is fit to **this run's parsed criteria only** — there is no hardcoded
ideal customer. A bad/malformed LLM response degrades to score 0 (won't pass a
threshold) rather than crashing the run. Validated live against `zapier.com`: people
roles scored 80, unrelated roles scored 20, same run.

## Tests

`tests/test_lead_agent.py` — offline, stubs the LLM and DB. Run with `pytest`.
