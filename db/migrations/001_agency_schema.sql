-- 001_agency_schema.sql
-- Pareto Labs Agent System — isolated schema + tables.
--
-- Run once in the Supabase SQL editor (Dashboard → SQL Editor → New query → Run).
-- Idempotent: safe to re-run. After running, expose the schema:
--   Dashboard → Project Settings → API → "Exposed schemas" → add `agency` → Save.
-- Without that step, supabase-py / PostgREST cannot see these tables.
--
-- Everything lives in `agency`, never `public`, so a bad migration here cannot
-- touch Pareto production data.

create schema if not exists agency;

-- Grant the agents' role access to the schema.
--
-- Exposing a schema in the API settings only lets PostgREST *see* it; the API roles
-- still hold no privileges on a hand-created schema (unlike `public`, which Supabase
-- pre-grants). Without these GRANTs every call fails with "permission denied for
-- schema agency" (Postgres error 42501) even for service_role, because base-table
-- privileges are checked before RLS ever runs.
--
-- We grant to service_role ONLY. The agents use the service-role key; the browser
-- anon key must stay locked out of `agency` until migration 002 adds RLS + policies.
-- DEFAULT PRIVILEGES covers tables created by future migrations so we never re-grant.
grant usage on schema agency to service_role;
grant all on all tables in schema agency to service_role;
grant all on all sequences in schema agency to service_role;
grant all on all routines in schema agency to service_role;

alter default privileges in schema agency
  grant all on tables to service_role;
alter default privileges in schema agency
  grant all on sequences to service_role;
alter default privileges in schema agency
  grant all on routines to service_role;

-- Shared trigger: keep updated_at honest on every UPDATE.
-- Defined once, attached to each table that has updated_at.
create or replace function agency.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------------
-- leads
-- ---------------------------------------------------------------------------
create table if not exists agency.leads (
  id            uuid primary key default gen_random_uuid(),
  name          text,
  company       text,
  email         text,
  title         text,
  source        text,          -- apollo | hunter | crunchbase
  fit_score     integer,       -- 0-100, set by the LLM
  draft_message text,
  status        text default 'new',
  search_run_id uuid,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now(),
  unique (email)
);

drop trigger if exists trg_leads_updated_at on agency.leads;
create trigger trg_leads_updated_at before update on agency.leads
  for each row execute function agency.set_updated_at();

-- ---------------------------------------------------------------------------
-- experts
-- ---------------------------------------------------------------------------
create table if not exists agency.experts (
  id             uuid primary key default gen_random_uuid(),
  name           text,
  topic          text,
  url            text,
  platform       text,         -- serpapi | pubmed | justia | github | devto | ...
  score          integer,      -- 0-100, set by the LLM
  contact_signal text,
  draft_message  text,
  status         text default 'new',
  search_run_id  uuid,
  created_at     timestamptz default now(),
  updated_at     timestamptz default now()
);

drop trigger if exists trg_experts_updated_at on agency.experts;
create trigger trg_experts_updated_at before update on agency.experts
  for each row execute function agency.set_updated_at();

-- ---------------------------------------------------------------------------
-- job_seekers
-- ---------------------------------------------------------------------------
create table if not exists agency.job_seekers (
  id                uuid primary key default gen_random_uuid(),
  name              text,
  platform          text,       -- wellfound | contra | portfolio | reddit
  profile_url       text,
  skills            text[],
  contact_email     text,       -- null for tiers below 1
  reachability_tier integer,    -- 1 (email, send) to 4 (weak, no contact)
  matched_role      text,
  draft_message     text,
  status            text default 'new',
  search_run_id     uuid,
  created_at        timestamptz default now(),
  updated_at        timestamptz default now(),
  unique (profile_url)
);

drop trigger if exists trg_job_seekers_updated_at on agency.job_seekers;
create trigger trg_job_seekers_updated_at before update on agency.job_seekers
  for each row execute function agency.set_updated_at();

-- ---------------------------------------------------------------------------
-- outreach_log  (append-only record of every send attempt)
-- ---------------------------------------------------------------------------
create table if not exists agency.outreach_log (
  id          uuid primary key default gen_random_uuid(),
  target_id   uuid,
  target_type text,            -- lead | expert | job_seeker
  email       text,
  sent_at     timestamptz default now(),
  status      text             -- sent | failed | bounced
);

-- ---------------------------------------------------------------------------
-- search_runs  (one row per agent run: raw query + parsed criteria)
-- ---------------------------------------------------------------------------
create table if not exists agency.search_runs (
  id              uuid primary key default gen_random_uuid(),
  agent_type      text,        -- lead | expert | jobs
  raw_query       text,
  parsed_criteria jsonb,
  created_at      timestamptz default now()
);
