-- 003_rls_read_policies.sql
-- Open the agency dataset tables to the browser anon key for READS ONLY, so the
-- Next.js review queue can fetch rows and receive Supabase realtime updates.
--
-- Run once in the Supabase SQL editor. Idempotent.
--
-- Security posture (POC): the anon key ships to the browser, so anyone who opens
-- devtools can SELECT these rows (including draft messages and contact emails the
-- agents found). That is acceptable for this zero-budget POC on non-production data
-- and is what CLAUDE.md's "UI reads Supabase directly + realtime" implies. We scope
-- anon to SELECT only and leave outreach_log closed. When this graduates, tighten to
-- authenticated-only policies.
--
-- Why RLS at all: service_role (the agents) bypasses RLS, so this changes nothing for
-- them. It exists solely to let the anon role read — and Supabase realtime filters its
-- pushes through these same policies, so without a SELECT policy the live queue would
-- never receive updates.

-- The anon role needs schema usage + table SELECT before RLS policies can apply.
grant usage on schema agency to anon;
grant select on agency.leads, agency.experts, agency.job_seekers to anon;

-- Enable RLS. With RLS on and no policy, the default is deny-all; the policies below
-- re-open SELECT (only) for anon. INSERT/UPDATE/DELETE stay denied for anon — writes
-- happen via the service-role key (agents) or, later, server routes.
alter table agency.leads        enable row level security;
alter table agency.experts      enable row level security;
alter table agency.job_seekers  enable row level security;

-- Read policies. Dropped-then-created so re-running is clean.
drop policy if exists anon_read_leads on agency.leads;
create policy anon_read_leads on agency.leads
  for select to anon using (true);

drop policy if exists anon_read_experts on agency.experts;
create policy anon_read_experts on agency.experts
  for select to anon using (true);

drop policy if exists anon_read_job_seekers on agency.job_seekers;
create policy anon_read_job_seekers on agency.job_seekers
  for select to anon using (true);

-- Realtime: add the dataset tables to the supabase_realtime publication so row
-- changes are broadcast to subscribed clients (filtered by the policies above).
-- Guarded so re-running does not error if they are already members.
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'agency' and tablename = 'leads'
  ) then
    alter publication supabase_realtime add table agency.leads;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'agency' and tablename = 'experts'
  ) then
    alter publication supabase_realtime add table agency.experts;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'agency' and tablename = 'job_seekers'
  ) then
    alter publication supabase_realtime add table agency.job_seekers;
  end if;
end $$;
