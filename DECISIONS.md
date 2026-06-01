# DECISIONS.md — Pareto Labs Agent System

Append-only decision log. Newest entries at the top. One entry per architectural
choice: the decision, the alternatives considered, and why this one won.

---

## 2026-05-31 — Expert agent: SerpAPI universal source, scored by url, non-experts filtered by LLM

**Decision.** The expert agent clones the lead skeleton with three changes: source is
SerpAPI (one Google search), table is `agency.experts`, and the upsert conflict key is
`url` (migration 002 adds `unique(url)`). `score_expert` returns score + draft +
refined_name in one LLM call. Source/scorer are pure; only run.py writes.

**Why url as the key.** Experts have no email; an expert is identified by their
profile/article URL, and the same person under two platforms (a paper and a GitHub)
is two distinct pieces of evidence worth separate rows. In-run dedup alone was
rejected: it lets re-runs of the same search accumulate duplicate rows. A unique(url)
index makes upsert idempotent across runs, consistent with leads.email.

**Why not filter non-experts at the source.** SerpAPI returns listicles and ads, not
just people. We let the LLM score handle it (a roundup scores near 0 and drops below
threshold) rather than writing brittle URL/title heuristics. The score already exists;
reusing it for "is this even a person" costs nothing extra.

**Implication.** Run migration 002 once in Supabase before using the agent. Each live
run spends 1 of ~100 monthly SerpAPI searches + 1 Groq call per result.

**Live-validation follow-up (same day).** The first live run proved a plain topic
search (`q = topic`) returns *documents about the topic* (papers, docs, Reddit), not
people — all 9 results correctly scored 0. Fix: split the clean stored `topic` from
the SerpAPI `query`, and shape the query with person-intent signals
(`"professor" OR "researcher" OR "author" OR "scientist"` + `site:github.com OR
site:scholar.google.com OR site:.edu`) plus parsed exclusions as negative terms.
Re-validated: 7 named RL researchers (Sergey Levine, Pieter Abbeel, ...) scored 90–98,
institutional/non-person pages still scored 0. Lesson mirrors the Apollo paywall — the
live response shape differed from the fixture's assumption, which is what a validation
run exists to surface.

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
