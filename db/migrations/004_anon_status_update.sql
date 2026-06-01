-- 004_anon_status_update.sql
-- Let the browser (anon key) change ONLY the `status` column on the three dataset
-- tables, and only to the review verbs. This powers the approve/skip buttons.
--
-- Run once in the Supabase SQL editor. Idempotent.
--
-- Security scoping (three layers, all required):
--   1. Column GRANT: anon may UPDATE only the `status` column — Postgres rejects an
--      update that touches name/email/score/draft/etc. This is the real guard; an
--      RLS policy alone does NOT restrict columns.
--   2. RLS USING (true): anon may target any row (the queue acts on any visible row).
--   3. RLS WITH CHECK: the new status must be one of new/approved/skipped — anon
--      cannot set 'sent'/'failed' (owned by the send pipeline) or arbitrary values.
--
-- Net effect: the public anon key can move a row between review states and nothing
-- else. Sending still happens server-side and writes status 'sent'/'failed' there.

grant update (status) on agency.leads        to anon;
grant update (status) on agency.experts       to anon;
grant update (status) on agency.job_seekers   to anon;

-- leads
drop policy if exists anon_update_lead_status on agency.leads;
create policy anon_update_lead_status on agency.leads
  for update to anon
  using (true)
  with check (status in ('new', 'approved', 'skipped'));

-- experts
drop policy if exists anon_update_expert_status on agency.experts;
create policy anon_update_expert_status on agency.experts
  for update to anon
  using (true)
  with check (status in ('new', 'approved', 'skipped'));

-- job_seekers
drop policy if exists anon_update_seeker_status on agency.job_seekers;
create policy anon_update_seeker_status on agency.job_seekers
  for update to anon
  using (true)
  with check (status in ('new', 'approved', 'skipped'));
