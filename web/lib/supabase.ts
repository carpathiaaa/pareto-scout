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
