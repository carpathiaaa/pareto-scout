# DECISIONS.md — Pareto Labs Agent System

Append-only decision log. Newest entries at the top. One entry per architectural
choice: the decision, the alternatives considered, and why this one won.

---

## 2026-05-31 — Web UI: hand-scaffolded Next.js, anon+RLS reads, pinned to patched Next

**Decision.** The review desk is a hand-written `web/` (App Router, TS) rather than
`create-next-app`: lean deps (next, react, @supabase/supabase-js), a Supabase anon
client pinned to the `agency` schema, and a client `<Queue>` with realtime. First
slice is read-only (no approve/send). Migration 003 enables RLS SELECT-only policies
for anon + adds the dataset tables to the realtime publication.

**Alternatives.** create-next-app — rejected: pulls a large opinionated tree
(ESLint/Tailwind/turbopack config) we don't need for a POC and obscures what's
actually required. Server-route reads with service_role — rejected for this slice:
CLAUDE.md says the UI reads Supabase directly + realtime, which needs the anon key and
RLS policies (realtime filters pushes through them).

**Security note (accepted, documented).** The anon key ships to the browser; RLS
scopes it to SELECT on leads/experts/job_seekers only, outreach_log stays closed.
Acceptable for a POC on non-production data; tighten to authenticated-only on
graduation. Next was bumped 15.1.6 → 15.5.18 to clear a critical CVE (CVE-2025-66478).
Remaining `npm audit` advisories (PostCSS XSS-in-CSS-stringify, transitive) are build-
time only and not reachable at runtime; the suggested "fix" downgrades Next to 9.x
(six majors back), so we accept them rather than break the app.

---

## 2026-05-31 — Jobs agent: tier (not score) gates the queue; tier 1 is a fact; Reddit is discovery-only

**Decision.** The jobs agent classifies each seeker into a reachability tier 1–4. Tier
1 (a real public email exists) is the only actionable tier: those rows get status
`new` and reach the review queue; tiers 2–4 get status `archived` (stored, not
queued). Tier 1 is computed in Python from an email the source actually exposed
(`_extract_email`, regex over result text — never guessed or constructed) AND the
candidate not being a Reddit-discovery row. The LLM only assigns tiers 2–4.

**Why tier-not-score.** The jobs goal is reachability, not fit, so a 0–100 score is the
wrong gate. And the actionable decision ("can I email this person?") must be grounded
in a real email, not an LLM judgment — otherwise the system could "decide" someone is
reachable and there's no address. So email-existence is code, tier 2/3/4 nuance is the
LLM.

**Reddit guardrail (CLAUDE.md).** r/forhire is discovery-only: usernames, never emails,
never outreach. Enforced structurally — Reddit candidates carry
`reddit_discovery_only=True` and `contact_email=None`, and the classifier bars them
from tier 1 (and nulls any email) regardless of LLM output. Locked by a test.

**Tier-1 email source.** For the POC, an email counts only if present in the source
result text. Rejected: enriching name+domain via Hunter's email-finder — more tier-1
hits but spends credits and couples jobs to the lead source. Honest + zero extra spend
won.

**Bug found + fixed here:** `str.lstrip("www.")` strips a char SET, not a prefix, so it
mangled `wellfound.com` → `ellfound.com`. Switched to `removeprefix("www.")`. The same
bug exists in `expert/sources.py` (cosmetic platform label) and should be fixed there
in a follow-up.

**Implication.** Live jobs run spends 1 SerpAPI search; Reddit reads are free anonymous
public JSON. No new migration — `job_seekers` already has `unique(profile_url)`.

**Live-validation follow-ups (same day).** Three findings from validating live:
1. *Reddit blocks anonymous reads (403).* And worse, that failure originally crashed
   the whole run, discarding paid SerpAPI results. Fix: the Reddit (discovery, free)
   source is now wrapped in try/except in run.py — its failure is logged and the run
   continues on SerpAPI alone. The priority (paid primary vs free optional) is now
   enforced in code, not just intent. Locked by a test.
2. *Plain "open to work" search returned job boards (Indeed/Upwork/ZipRecruiter),
   i.e. employers hiring, not individuals.* Same shape as the expert topic-vs-people
   issue. Fix: bias the query to profile sites (contra/read.cv/behance/wellfound) and
   negative-filter the aggregators. Re-validated: results became real Behance/Contra
   individuals.
3. *Tier 1 is genuinely rare on portfolio platforms.* People expose contact forms/DMs,
   not raw emails, so most surfaced seekers are tier 2 (reachable, no public email →
   stored, not auto-sendable). This is correct behavior, not a miss; chasing tier-1
   would require a paid email-finder (declined). Also fixed a bug where list-valued
   criteria leaked brackets into the query (`['product designers']`) via `_flatten`.

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
