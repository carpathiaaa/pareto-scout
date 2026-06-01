-- 002_experts_unique_url.sql
-- Add a unique key to agency.experts so the expert agent can upsert on re-runs,
-- the same way the lead agent upserts on leads.email.
--
-- Run once in the Supabase SQL editor. Idempotent via the DO block guard.
--
-- An expert is identified by their profile/article URL: the same person can appear
-- under several platforms (a PubMed paper and a GitHub profile), and each distinct
-- URL is a distinct piece of evidence worth its own row. So we key on url, not name.

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'experts_url_key'
  ) then
    alter table agency.experts add constraint experts_url_key unique (url);
  end if;
end $$;
