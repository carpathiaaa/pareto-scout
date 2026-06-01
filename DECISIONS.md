# DECISIONS.md — Pareto Labs Agent System

Append-only decision log. Newest entries at the top. One entry per architectural
choice: the decision, the alternatives considered, and why this one won.

---

## 2026-05-31 — Lead source is Hunter (domain-centric), Apollo kept as paid upgrade path

**Decision.** The live lead source is Hunter.io `/v2/domain-search`. `run_lead_agent`
now takes a `domains` list and fetches once per domain; the LLM score does the role
filtering. `fetch_from_apollo` stays in the codebase, unused by default, as the
upgrade path for a future paid Apollo plan.

**Why.** Apollo's `mixed_people/search` returns 403 `API_INACCESSIBLE` on the free
plan regardless of email-credit balance — programmatic people-search is a paid-tier
feature, confirmed by two live attempts (both spent zero credits, rejected at search).
Clay was evaluated and rejected: no free callable REST API (HTTP integration is
Growth-plan $495/mo+) and it is an orchestrator, not a source, so it duplicates our
pipeline. Hunter is the only genuinely free option that returns real names + emails.

**Tradeoff.** Hunter is domain-centric, not persona-centric: it returns everyone it
knows at a company, unfiltered by role. So the workflow changed from "describe a
persona" to "name the companies + describe who to prioritize," and the LLM ranks
within each company. This matches targeted B2B outreach and keeps the proven
parse→dedup→enrich→score→store pipeline — only the source edge changed.

**Validation.** Live run over zapier.com: 1 Hunter search, 10 people, scored 80
(people/talent roles) down to 20 (unrelated roles), 10 rows written to agency.leads.
The normalized candidate shape made the Apollo→Hunter swap a source-only change.

**Implication.** Each domain spends 1 of ~25 monthly Hunter searches. Use
`score_threshold` to drop low-fit people before they reach the review queue.

---

## 2026-05-31 — Lead agent: mock/live by env flag, one LLM call per lead, writes only in run.py

**Decision.** `LEAD_SOURCE_MODE` (default `mock`) chooses fixtures vs real Apollo at
each source call site. `enrich_lead` returns `fit_score` + `draft_message` from a
single Groq call. Only `run.py` touches the database; `sources.py` and `enricher.py`
are pure.

**Alternatives.**
- Mock via injected mock/real classes (DI) — rejected: more machinery than a POC
  needs, and identical call sites under one env flag can't drift the way two class
  implementations can.
- Two LLM calls (score, then draft) — rejected: doubles the 30 req/min Groq budget
  and lets score and message disagree. One JSON response keeps them consistent.
- Let sources/enricher write directly — rejected: pushing all writes into run.py
  keeps the expensive deps (network, DB) at the edges and the logic offline-testable.

**Why this won.** Mock-first is both credit-safe (CLAUDE.md: spend only to validate)
and a correctness tool: deterministic fixtures test dedup/threshold/projection so the
only thing real credits buy is "does the live response match the fixture's shape."

**Implication.** Dev and `pytest` spend zero Apollo credits. `LEAD_SOURCE_MODE=live`
is the deliberate, logged spend. llama-3.3 is best-effort JSON, so enrich validates
and clamps the score in Python; a bad parse degrades to 0, never crashes.

---

## 2026-05-31 — Custom `agency` schema needs explicit GRANTs to service_role

**Decision.** Migration 001 grants `usage` + `all` on the `agency` schema, its
tables, sequences, and routines to `service_role` only, plus matching DEFAULT
PRIVILEGES for future objects. `anon`/`authenticated` get nothing yet.

**Why.** Live connectivity tests failed with `42501: permission denied for schema
agency` even though the schema was exposed in the API settings and the service-role
key was used. Exposing a schema lets PostgREST see it; it does not grant privileges.
Supabase pre-grants the `public` schema but not hand-created ones. service_role
bypasses RLS but not base-table GRANTs, which are checked first.

**Alternatives.** Grant to all three API roles now — rejected: that would give the
public anon key full `agency` access before any RLS exists. Least privilege says the
anon role stays locked out until migration 002 enables RLS and writes policies.

**Implication.** Re-run migration 001 after any new table is added by hand;
DEFAULT PRIVILEGES handles tables created within the same role going forward. The
browser cannot touch `agency` until 002 lands.

---

## 2026-05-31 — LLM wrapper uses the `openai` SDK, not the `groq` SDK

**Decision.** `shared/llm.py` talks to Groq through the official `openai` Python SDK
with `base_url="https://api.groq.com/openai/v1"` and the model name from config.

**Alternatives.**
- `groq` SDK: first-party, but couples our code to Groq. Swapping to a paid Gemini
  or Claude key later would mean rewriting call sites.
- Raw `httpx`: maximum control and matches our "httpx everywhere" rule, but we would
  hand-roll retries, streaming, and response parsing the SDK already provides.

**Why this won.** CLAUDE.md's core decision is a provider-agnostic wrapper where a
paid key "swaps in later via one config value." Most serious providers expose an
OpenAI-compatible endpoint, so the `openai` SDK + a configurable `base_url`/`model`
is the literal embodiment of that goal. `httpx` is still the rule for the data-source
APIs (Apollo, Hunter, SerpAPI), which have no SDK we want.

**Implication.** Provider switch = change `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`
in env. No code change at call sites.

---

## 2026-05-31 — Schema lives in a versioned SQL migration file

**Decision.** The `agency` schema and its five tables are defined in
`db/migrations/001_agency_schema.sql`, run by hand in the Supabase SQL editor for the
POC.

**Alternatives.**
- Supabase CLI migrations: proper, but adds tooling/CI setup not justified for a
  zero-budget POC with one developer.
- Creating tables imperatively from Python on startup: hides the schema, risks
  partial state, and fights "never hard delete / careful migrations" guardrails.

**Why this won.** A single reviewable SQL file is the clearest artifact for a human to
read, run, and diff. It graduates cleanly into CLI migrations later if the org funds
scale.

**Implication.** The developer must run this SQL once in Supabase, and must expose the
`agency` schema in Supabase API settings (see foundation notes), or PostgREST/
supabase-py cannot see the tables.

---

## 2026-05-31 — Foundation built before any agent; no credits spent yet

**Decision.** Built `DECISIONS.md`, `.env.example`, `requirements.txt`, the schema
migration, and the three `shared/` modules first, per CLAUDE.md build order.

**Why.** The shared plumbing is a hard dependency of every agent, and none of it
touches a paid API. Building it first means the first credit we ever spend is a
deliberate validation of the lead agent, not debugging.

**Implication.** No Apollo / Hunter / SerpAPI / Groq credits consumed by this step.
