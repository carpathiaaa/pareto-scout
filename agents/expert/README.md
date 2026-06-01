# Expert agent

Finds and scores subject-matter experts in a given field, then writes scored, drafted
rows to `agency.experts` for human review. Clones the lead agent's shape; differs in
source (SerpAPI), table (`experts`), and conflict key (`url`).

## Pipeline

```
raw query
  → parse_query_to_fields (shared/llm)       # → field_or_domain, topic_or_specialty,
                                             #   credibility_signals, exclusions
  → fetch_from_serpapi (sources)             # one Google search; mock fixture by default
  → dedup_by url (shared/utils)
  → score_expert per candidate (scorer)      # 1 LLM call → score + draft + refined name
  → upsert to agency.experts (shared/db)     # on_conflict=url
  → insert one agency.search_runs row
```

`run.py` is the only module that touches the database. `sources.py` and `scorer.py`
are pure (data in, data out) so they unit-test offline with no network.

## Source: SerpAPI, the universal layer

CLAUDE.md names SerpAPI (~100 searches/mo free) as the cross-domain source: one Google
search for a field/topic surfaces experts wherever they publish — academia, GitHub,
blogs, conference pages. `_platform_from_url` derives a coarse platform label
(github / academia / blog / ...) from each result's host. Domain sources (PubMed,
Justia, SSRN, Dev.to) can be added later as extra source functions feeding the same
normalized shape.

SerpAPI returns non-experts too (listicles, ads). We don't filter those at the source
— the LLM score does it: a roundup article scores near 0 and drops below threshold.

## Files

| File | Role |
|---|---|
| `sources.py` | `fetch_from_serpapi`; mock/live via `EXPERT_SOURCE_MODE`; `_platform_from_url` |
| `scorer.py` | `score_expert` — one Groq call returns `score` (0–100) + `draft_message` + refined name |
| `run.py` | `run_expert_agent(raw_query, *, score_threshold=0, limit=20)` — orchestrates + writes |
| `fixtures/serpapi_sample.json` | Mock SerpAPI response (dup link + a non-expert listicle) |

## Schema dependency

Run `db/migrations/002_experts_unique_url.sql` once in Supabase before using this
agent. It adds `unique(url)` to `agency.experts` so `upsert(on_conflict="url")` is
idempotent across re-runs. Without it, re-running a search duplicates rows.

## Running

Mock (default — zero credits):

```python
from agents.expert.run import run_expert_agent
summary = run_expert_agent("experts in reinforcement learning for robotics")
```

Live validation (⚠️ spends one SerpAPI search, ~100/month free tier):

```powershell
$env:EXPERT_SOURCE_MODE = "live"
python scripts/validate_expert_live.py
```

Each run = 1 SerpAPI search + 1 Groq call per result.

## Scoring contract

`score` is credibility/authority on **this run's parsed topic only**, and non-persons
score near 0. A malformed LLM response degrades to score 0 (won't pass a threshold)
rather than crashing the run.

## Tests

`tests/test_expert_agent.py` — offline, stubs the LLM and DB. Run with `pytest`.
