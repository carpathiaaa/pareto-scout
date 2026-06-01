import "server-only";
import { createClient } from "@supabase/supabase-js";

// Server-ONLY Supabase client using the service-role key. The `server-only` import
// makes the build fail if this module is ever pulled into a client bundle, so the
// service-role key can never leak to the browser. Used by the send route to write
// status 'sent'/'failed' — which the anon key is forbidden to do (migration 004).
const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY!;

export const supabaseAdmin = createClient(url, serviceKey, {
  db: { schema: "agency" },
  auth: { persistSession: false },
});
