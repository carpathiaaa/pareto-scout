import { createClient } from "@supabase/supabase-js";

// Browser Supabase client, pinned to the `agency` schema so every query targets the
// same isolated schema the Python agents write to. Uses the ANON key (the only key
// allowed in the browser); RLS read policies (migration 003) gate what it can see.
//
// The non-null assertions are deliberate: if these env vars are missing the app is
// misconfigured and should fail loudly at startup rather than silently querying null.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(url, anonKey, {
  db: { schema: "agency" },
});

import type { Dataset, Status } from "./types";

// Table name per dataset, kept next to the client since reviews write by dataset.
const TABLE: Record<Dataset, string> = {
  leads: "leads",
  experts: "experts",
  jobs: "job_seekers",
};

// Flip a row's review status. Only status is writable by the anon key (migration
// 004 grants UPDATE on that column alone and constrains the value), so this is the
// single write the browser is permitted to make.
export async function setStatus(
  dataset: Dataset,
  id: string,
  status: Status,
): Promise<{ error: string | null }> {
  const { error } = await supabase
    .from(TABLE[dataset])
    .update({ status })
    .eq("id", id);
  return { error: error?.message ?? null };
}
