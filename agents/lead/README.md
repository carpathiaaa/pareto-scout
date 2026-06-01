# Lead agent

Finds and scores potential customers/clients for outreach, then writes scored,
drafted rows to `agency.leads` for human review.

## Pipeline

```
raw query
  → parse_query_to_fields (shared/llm)      # natural language → 6 lead fields
  → fetch_from_apollo (sources)             # mock fixture by default
  → dedup_by email (shared/utils)
  → enrich_lead per candidate (enricher)    # 1 LLM call → fit_score + draft_message
  → upsert to agency.leads (shared/db)      # on_conflict=email
  → insert one agency.search_runs row
```

`run.py` is the only module that touches the database. `sources.py` and
`enricher.py` are pure (data in, data out) so they unit-test offline with no network.

## Files

| File | Role |
|---|---|
| `sources.py` | Fetch candidates; `fetch_from_apollo` switches mock/live on `LEAD_SOURCE_MODE` |
| `enricher.py` | `enrich_lead` — one Groq call returns `fit_score` (0–100) + `draft_message` |
| `run.py` | `run_lead_agent(raw_query, score_threshold=0)` — orchestrates + writes |
| `fixtures/apollo_sample.json` | Mock Apollo response (includes a dup + null-email row) |

## Running

Mock (default — zero credits):

```python
from agents.lead.run import run_lead_agent
summary = run_lead_agent("VP Eng at Series-A dev-tool startups in the EU")
```

Live validation (⚠️ spends Apollo email credits, ~50/month free tier):

```powershell
$env:LEAD_SOURCE_MODE = "live"   # then run as above
```

Every `enrich_lead` is one Groq request (free tier: 30/min, 14,400/day). A run over
the 4-candidate fixture costs ~4 LLM calls.

## Scoring contract

`fit_score` is fit to **this run's parsed criteria only** — there is no hardcoded
ideal customer. A bad/malformed LLM response degrades to score 0 (won't pass a
threshold) rather than crashing the run.

## Tests

`tests/test_lead_agent.py` — offline, stubs the LLM and DB. Run with `pytest`.
