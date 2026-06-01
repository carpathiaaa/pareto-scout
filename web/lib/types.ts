// Row shapes for the three agency datasets, mirroring the Supabase schema. Only the
// fields the queue UI reads are typed; the agents own the full schema.

export type Status = "new" | "approved" | "skipped" | "sent" | "failed" | "archived";

export interface Lead {
  id: string;
  name: string | null;
  company: string | null;
  email: string | null;
  title: string | null;
  source: string | null;
  fit_score: number | null;
  draft_message: string | null;
  status: Status;
  created_at: string;
}

export interface Expert {
  id: string;
  name: string | null;
  topic: string | null;
  url: string | null;
  platform: string | null;
  score: number | null;
  contact_signal: string | null;
  draft_message: string | null;
  status: Status;
  created_at: string;
}

export interface JobSeeker {
  id: string;
  name: string | null;
  platform: string | null;
  profile_url: string | null;
  skills: string[] | null;
  contact_email: string | null;
  reachability_tier: number | null;
  matched_role: string | null;
  draft_message: string | null;
  status: Status;
  created_at: string;
}

// The three datasets the UI knows about. Used to drive the tabbed queue.
export type Dataset = "leads" | "experts" | "jobs";
