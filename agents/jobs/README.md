# Jobs agent

Maps people actively looking for work, sorted by **how reachable** they are. Writes to
`agency.job_seekers`. Reuses the shared pipeline template; its distinctive feature is
reachability tiering instead of a fit score.

## Pipeline

```
raw query
  → parse_query_to_fields (shared/llm)        # → target_role_or_skills, seniority, location
  → fetch_open_to_work (SerpAPI)              # 'open to work' across Wellfound/Contra/portfolios
  + fetch_reddit_forhire (Reddit)             # DISCOVERY ONLY — usernames, never emails
  → dedup_by profile_url (shared/utils)
  → classify_seeker per candidate (classifier)# 1 LLM call → skills, role, tier, draft
  → upsert to agency.job_seekers (shared/db)  # on_conflict=profile_url
  → insert one agency.search_runs row
```

`run.py` is the only module that touches the database. `sources.py` and
`classifier.py` are pure and unit-test offline.

## Reachability tiering (the gate)

Unlike lead/expert (gated by a 0–100 score), the jobs queue is gated by a tier:

| Tier | Meaning | In review queue? | status |
|---|---|---|---|
| 1 | A real public email was found in the source | ✅ yes | `new` |
| 2 | Contact form / DM path, no email | no | `archived` |
| 3 | Profile exists, no contact route | no | `archived` |
| 4 | Name / weak signal only | no | `archived` |

**Tier 1 is a fact, not an LLM opinion.** It's assigned in Python only when the source
text actually exposed an email (`_extract_email` reads, never guesses). The LLM is
told never to return tier 1; it only distinguishes 2 vs 3 vs 4. So the actionable gate
can't be hallucinated.

## Reddit guardrail

CLAUDE.md: Reddit r/forhire is a **discovery layer only** — usernames, never emails,
never outreach. Enforced structurally: every Reddit candidate carries
`reddit_discovery_only=True` and `contact_email=None`, and `classify_seeker` bars them
from tier 1 even if an email somehow appeared in the record (and nulls it). The test
`test_classify_reddit_never_tier1_even_with_email` locks this in.

## Files

| File | Role |
|---|---|
| `sources.py` | `fetch_open_to_work` (SerpAPI) + `fetch_reddit_forhire` (discovery); mock/live via `JOBS_SOURCE_MODE` |
| `classifier.py` | `classify_seeker` — one Groq call → skills, matched_role, tier (2–4), draft; tier 1 set in Python |
| `run.py` | `run_jobs_agent(raw_query, *, limit=20)` — orchestrates + writes; tier-1 → status `new`, else `archived` |
| `fixtures/serpapi_jobs_sample.json` | Mock open-to-work results (one exposes an email → tier 1) |
| `fixtures/reddit_forhire_sample.json` | Mock r/forhire posts (discovery only) |

## Running

Mock (default — zero credits):

```python
from agents.jobs.run import run_jobs_agent
summary = run_jobs_agent("open to work React engineers, mid-level, remote")
```

Live validation (⚠️ 1 SerpAPI search + free Reddit read):

```powershell
$env:JOBS_SOURCE_MODE = "live"
python scripts/validate_jobs_live.py
```

## Tests

`tests/test_jobs_agent.py` — offline, stubs the LLM and DB. Run with `pytest`.
