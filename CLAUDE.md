# CLAUDE.md — Pareto Labs Agent System

This file is read by Claude Code at the start of every session.
Follow every instruction here unless the developer explicitly overrides it in the session.

---

## How to work with me on this project (read this first)

The developer is using this project to learn the stack and to test Claude Code's
capabilities. The developer is comfortable letting you build autonomously, but the
goal is not just working code. The goal is that the developer understands why each
choice was made. Optimize for that.

Concretely, on every meaningful piece of work:

1. **State the approach before building it.** Before implementing a non-trivial
   component, write 2 to 4 sentences on what you are about to do and why you chose
   this approach over the obvious alternatives. Name the alternatives.
2. **Explain the why in comments, not the what.** Code comments should explain the
   reasoning behind a non-obvious decision, not narrate what a line does. Skip
   comments that restate the code.
3. **Keep a decision log.** Maintain `DECISIONS.md` at the repo root. Append a short
   dated entry whenever you make an architectural choice, pick a library, or hit a
   tradeoff. One entry = the decision, the alternatives, and why this one won.
4. **Flag every limit and irreversible action.** Whenever code spends a free-tier
   credit (Apollo, Hunter, SerpAPI), approaches a rate limit, or does something hard
   to undo, say so explicitly and explain the implication.
5. **Summarize after each component.** When a component is done, give a short
   "what I built and why it's shaped this way" recap before moving on.
6. **Teach, do not just tell.** Assume the developer wants to learn the pattern, not
   only the result. Err toward the clearer explanation.

When in doubt about scope or a design fork, stop and ask rather than guessing.

---

## Project overview

This repo contains three independent agents for Pareto Labs. The datasets do not
connect to each other. Each agent is its own pipeline with its own table.

| Agent | Purpose |
|---|---|
| `lead` | Find and score potential customers or clients for outreach |
| `expert` | Find and score subject matter experts in a given field |
| `jobs` | Map people actively looking for work, sorted by how reachable they are |

Each agent does the same five things: take criteria, fetch candidates from free
public sources, enrich and score with the LLM, draft a personalized message, and
write rows to Supabase. A human reviews and approves before anything sends.

This is a zero-budget proof of concept. Everything must run on free tiers. The
design must let the org pay for scale later without a rewrite.

---

## Core decisions (and why)

These are settled. Do not relitigate them, but understanding the reasoning helps
you extend the system correctly.

- **Datasets stay separate.** Three parallel pipelines, not a matching engine. A
  matching system is a possible v2, not part of this build.
- **Groq for the LLM, behind a provider-agnostic wrapper.** Groq's free tier needs
  no credit card and is enough for scoring, extraction, classification, and short
  drafting. The wrapper (`shared/llm.py`) is written to the OpenAI-compatible
  interface so a paid Gemini or Claude key swaps in later via one config value.
- **Existing Pareto Supabase project, isolated schema.** Reuses infra the org
  already pays for, but all tables live in a dedicated `agency` schema so a bad
  migration cannot touch Pareto production data.
- **Next.js + Supabase for the UI.** Streamlit reruns the whole script on every
  interaction, which fights the stateful review queue. Next.js handles state
  properly, Supabase realtime makes the queue update live, and it graduates into a
  real product if the org funds scale.
- **FastAPI as a thin trigger.** The agents are Python. The UI is JavaScript. A
  small FastAPI service exposes each agent run as an endpoint so the UI can start a
  search and get a live result.
- **Human-in-the-loop activation.** The system never auto-sends. It finds, scores,
  and drafts, then a person approves. This keeps it compliant and protects sending
  reputation.
- **Criteria come from a chat query at run time.** There is no hardcoded ideal
  customer. "Good" means fit to the parsed criteria of the current run.

---

## Architecture

Three layers that communicate only through the database, which keeps them decoupled.

**Agents (Python).** `agents/lead/`, `agents/expert/`, `agents/jobs/`. Each takes
criteria, fetches candidates, enriches and scores via the LLM, drafts a message, and
writes rows to Supabase.

**API trigger (FastAPI, Python).** `api/`. Thin endpoints that run an agent and
return its result, so the Next.js UI can kick off a search live. Endpoints call the
agent modules directly. No business logic lives here.

**UI (Next.js + Supabase).** `web/`. The search input, the review queue, the approve
action, and the email send. Sending uses the Resend JS SDK from a Next.js API route,
so email lives here, not in Python. Reads and writes Supabase directly and uses
Supabase realtime for live queue updates.

Supporting services: Groq (LLM), Supabase (store, `agency` schema), Resend (email,
approved rows only), Slack (notifications via the existing Pareto webhook).

### Repo structure

```
pareto-agents/
├── CLAUDE.md
├── DECISIONS.md            ← append-only decision log (you maintain this)
├── .env.example
├── requirements.txt        ← Python deps
├── agents/
│   ├── lead/    run.py  sources.py  enricher.py  README.md
│   ├── expert/  run.py  sources.py  scorer.py    README.md
│   └── jobs/    run.py  sources.py  classifier.py README.md
├── api/
│   └── main.py             ← FastAPI app exposing agent runs
├── shared/
│   ├── llm.py              ← provider-agnostic LLM wrapper (Groq now)
│   ├── db.py               ← Supabase client (agency schema)
│   └── utils.py            ← logging, env loading, rate limiting, dedup
└── web/                    ← Next.js app (input, queue, approve, Resend send)
```

---

## Tech stack

### Python (agents + api)
- Python 3.11+, formatted with `black`, type hints on all signatures.
- `httpx` for HTTP, not `requests`.
- `supabase-py` for the database, configured to target the `agency` schema.
- `python-dotenv` for env loading.
- Python's `logging` module, never `print()`.

### LLM (Groq)
- Model: `llama-3.3-70b-versatile`.
- Access via the OpenAI-compatible endpoint at `https://api.groq.com/openai/v1`.
- All calls go through `shared/llm.py`. Never call Groq directly from an agent file.
- The wrapper exposes a generic chat function and a `parse_query_to_fields` helper
  that returns structured JSON.
- Respect the free tier: 30 requests/minute, 6,000 tokens/minute, 14,400/day at the
  org level. Keep drafting prompts tight and do not fire bursts.

### Database (Supabase)
- Existing Pareto project. All tables in the `agency` schema, never `public`.
- Tables: `leads`, `experts`, `job_seekers`, `outreach_log`, `search_runs`.
- Always upsert, never plain insert, since agents may re-run on the same data.
- Never hard delete. Use a soft-delete pattern if removal is needed.

### UI (Next.js)
- TypeScript, App Router.
- Supabase JS client for reads and queue writes.
- Resend JS SDK for sending, only inside a server-side API route, never client-side.
- No secrets in client code. Only `NEXT_PUBLIC_` keys reach the browser.

### Email (Resend)
- Free tier, roughly 100 emails/day.
- Send only on rows with `status = approved` that passed the score or tier threshold.

### Notifications (Slack)
- Reuse the existing Pareto webhook. Post a summary when an agent writes new
  qualified rows.

---

## Input flow

Identical for all three agents:

1. The developer types a request in plain language in the UI.
2. `shared/llm.py` parses it into structured, editable fields (one small LLM call).
3. The fields appear filled in. The developer corrects them if needed.
4. The developer confirms, and the agent runs.

The confirm step is a deliberate checkpoint. It stops a misread query from spending
Apollo, Hunter, or SerpAPI credits on the wrong target.

Parsed fields by agent:

| Agent | Fields |
|---|---|
| lead | target_type (company or person), industry/domain, role or seniority, focus_keywords, exclusions, location |
| expert | field/domain, topic or specialty, credibility_signals, exclusions |
| jobs | target_role or skills, seniority, location |

Each run is logged to `search_runs` with the raw query and the parsed criteria.

---

## Output and activation

Each agent writes scored, enriched rows carrying both contact data and activation
fields. The `status` field drives the loop.

Status lifecycle: `new` → (`approved` or `skipped`) → (`sent` or `failed`).

- Every row starts `new`.
- In the Next.js queue, new rows show sorted by score. The developer reads the draft
  and flips each to `approved` or `skipped`.
- A "send approved" action calls Resend on approved rows and moves them to `sent` or
  `failed`, logging each to `outreach_log`.
- Job seekers reach the queue only at reachability tier 1 (a real public email
  exists). Lower tiers are stored but not actionable.

Two guardrails always hold: nothing sends without passing the threshold and a human
approval, and during the POC demo, sends go to the developer's own test inboxes, not
to the real contacts the agents surface.

---

## Supabase schema (`agency` schema)

### `leads`
```
id            uuid primary key default gen_random_uuid()
name          text
company       text
email         text
title         text
source        text          -- apollo | hunter | crunchbase
fit_score     integer        -- 0-100, set by the LLM
draft_message text
status        text default 'new'
search_run_id uuid
created_at    timestamptz default now()
updated_at    timestamptz default now()
unique (email)
```

### `experts`
```
id            uuid primary key default gen_random_uuid()
name          text
topic         text
url           text
platform      text          -- serpapi | pubmed | justia | github | devto | ...
score         integer        -- 0-100, set by the LLM
contact_signal text
draft_message text
status        text default 'new'
search_run_id uuid
created_at    timestamptz default now()
updated_at    timestamptz default now()
```

### `job_seekers`
```
id               uuid primary key default gen_random_uuid()
name             text
platform         text        -- wellfound | contra | portfolio | reddit
profile_url      text
skills           text[]
contact_email    text         -- null for tiers below 1
reachability_tier integer      -- 1 (email, send) to 4 (weak, no contact)
matched_role     text
draft_message    text
status           text default 'new'
search_run_id    uuid
created_at       timestamptz default now()
updated_at       timestamptz default now()
unique (profile_url)
```

### `outreach_log`
```
id          uuid primary key default gen_random_uuid()
target_id   uuid
target_type text          -- lead | expert | job_seeker
email       text
sent_at     timestamptz default now()
status      text          -- sent | failed | bounced
```

### `search_runs`
```
id              uuid primary key default gen_random_uuid()
agent_type      text        -- lead | expert | jobs
raw_query       text
parsed_criteria jsonb
created_at      timestamptz default now()
```

---

## Data sources by agent (all free)

| Agent | Sources |
|---|---|
| lead | Apollo free (~50 email credits/mo), Hunter.io free (~25 searches/mo), Crunchbase public pages |
| expert | SerpAPI free (~100/mo) as the universal layer, plus domain sources: PubMed (healthcare), Justia/Avvo (legal), SSRN/SEC EDGAR (finance), GitHub/Dev.to (tech) |
| jobs | Wellfound public, Contra, portfolio sites via SerpAPI ("open to work" searches). Reddit r/forhire is a discovery layer only and never an email source |

Respect every source's terms of service. Do not scrape LinkedIn or use its
unofficial APIs. Reddit gives usernames, not emails, so it never feeds outreach.

---

## Coding standards

- Functions under 40 lines. Split into helpers if longer.
- No global state outside `shared/` modules.
- Environment variables loaded through a `shared/utils.get_env` helper, never read
  ad hoc.
- Default 1 second between calls to any external API unless its docs allow faster.
- Log a warning when approaching a known rate limit.
- Error handling pattern:

```python
try:
    result = call_external_api()
except httpx.HTTPStatusError as e:
    logger.error(f"API call failed: {e.response.status_code} - {e.response.text}")
    raise
```

---

## Required environment variables

See `.env.example` for the full template.

```
# Supabase (Python)
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=

# Supabase (Next.js)
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=

# LLM
GROQ_API_KEY=

# Email
RESEND_API_KEY=
OUTREACH_FROM_EMAIL=

# Notifications
SLACK_WEBHOOK_URL=

# Agent: lead
APOLLO_API_KEY=
HUNTER_API_KEY=

# Agent: expert
SERPAPI_KEY=

# Agent: jobs (optional, for authenticated Reddit reads)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
```

---

## Skills and slash commands

The developer drives this build with Claude Skills. Keep workflows packaged and
named so they are repeatable.

| Command | Action |
|---|---|
| `/run-lead-agent` | Run the lead agent with given criteria |
| `/run-expert-agent` | Run the expert agent with given criteria |
| `/run-jobs-agent` | Run the job seeker agent with given criteria |
| `/check-db` | Print row counts for all `agency` tables |
| `/lint` | `black . && flake8 .` for Python; lint the Next.js app |
| `/test` | Run the test suite |
| `/explain-last` | Re-explain the reasoning behind the most recent change |

---

## Build order

Build in this sequence. Do not build all three agents in parallel.

1. **Foundation.** Repo, `DECISIONS.md`, `.env.example`, the `agency` schema and
   tables, and the three `shared/` modules.
2. **Lead agent, end to end.** It has the clearest contract and proves the shared
   plumbing. Get it writing scored, drafted rows to Supabase.
3. **Expert agent.** Clone the lead skeleton, swap sources and the LLM prompt, add
   the field/domain parameter.
4. **Job seeker agent.** Add the reachability tiering and the discovery-only Reddit
   handling.
5. **Next.js surface and Resend send.** Search input, parsed-field confirm, the live
   review queue, approve, and threshold-gated sending.

Build `shared/` modules as an agent needs them, not speculatively.

---

## Guardrails (never do these)

- Never commit directly to `main`. Always use a feature branch.
- Never hardcode API keys, emails, or URLs. Use environment variables.
- Never hard delete rows. Soft delete only.
- Never send email without a passing score or tier and a human approval.
- Never send POC outreach to real scraped contacts. Use test inboxes for the demo.
- Never install a package not in `requirements.txt` or `package.json` without
  asking first.
- Never scrape LinkedIn or bypass any source's terms of service.
- Never burn Apollo, Hunter, or SerpAPI credits while debugging. Use cached or
  mocked responses during development and spend real credits only to validate.

---

## Context for Pareto Labs

- Pareto Labs operates in the learning and talent space.
- This agent system supports internal growth and outreach operations.
- Outreach audience is professionals. Keep drafted messages direct and value-first,
  not spammy.
- Existing infrastructure to reuse: Supabase, GitHub Actions, a Slack webhook.
- The org pays for scale later, as it did with Codex and Supabase Pro, so design for
  a clean upgrade path rather than baking in free-tier assumptions that are hard to
  unwind.