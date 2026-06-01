import { NextResponse } from "next/server";
import { Resend } from "resend";
import { supabaseAdmin } from "@/lib/supabaseServer";

// Server-side send route. The browser POSTs { dataset }; this route reads that
// dataset's APPROVED rows and emails each draft to the POC test inbox via Resend,
// then writes status 'sent'/'failed' and logs to outreach_log.
//
// Guardrails enforced here (CLAUDE.md):
//  - Only status='approved' rows are sent → human approval is structurally required.
//  - Every send goes to OUTREACH_TEST_INBOX, never the row's real contact. The
//    intended recipient is recorded in outreach_log for the audit trail.
//  - Resend key + service-role key are server-only; this file never ships to client.

const DATASETS = {
  leads: { table: "leads", targetType: "lead", emailField: "email" },
  experts: { table: "experts", targetType: "expert", emailField: "contact_signal" },
  jobs: { table: "job_seekers", targetType: "job_seeker", emailField: "contact_email" },
} as const;

type DatasetKey = keyof typeof DATASETS;

interface SendResultRow {
  id: string;
  name: string | null;
  status: "sent" | "failed";
  detail: string;
}

export async function POST(request: Request) {
  const { dataset } = (await request.json()) as { dataset?: string };
  if (!dataset || !(dataset in DATASETS)) {
    return NextResponse.json({ error: "unknown dataset" }, { status: 400 });
  }
  const cfg = DATASETS[dataset as DatasetKey];

  const testInbox = process.env.OUTREACH_TEST_INBOX;
  const fromEmail = process.env.OUTREACH_FROM_EMAIL;
  const apiKey = process.env.RESEND_API_KEY;
  if (!testInbox || !fromEmail || !apiKey) {
    return NextResponse.json(
      { error: "send not configured (RESEND_API_KEY / OUTREACH_FROM_EMAIL / OUTREACH_TEST_INBOX)" },
      { status: 500 },
    );
  }
  const resend = new Resend(apiKey);

  // Read approved rows only. The threshold gate was applied upstream by the agents;
  // approval is the human gate, and we trust nothing the browser claims about it.
  const { data: rows, error } = await supabaseAdmin
    .from(cfg.table)
    .select("*")
    .eq("status", "approved");
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  if (!rows || rows.length === 0) {
    return NextResponse.json({ sent: 0, failed: 0, results: [] });
  }

  const results: SendResultRow[] = [];
  for (const row of rows) {
    const intendedTo = row[cfg.emailField] ?? "(no contact on record)";
    const subject = subjectFor(dataset as DatasetKey, row);
    const body = row.draft_message || "(no draft message)";

    let ok = false;
    let detail = "";
    try {
      // Send to the TEST INBOX, not intendedTo. POC guardrail.
      const { error: sendErr } = await resend.emails.send({
        from: fromEmail,
        to: testInbox,
        subject,
        text: `[POC test send — intended recipient: ${intendedTo}]\n\n${body}`,
      });
      if (sendErr) {
        detail = sendErr.message;
      } else {
        ok = true;
        detail = `delivered to test inbox (intended: ${intendedTo})`;
      }
    } catch (e) {
      detail = e instanceof Error ? e.message : "send threw";
    }

    // Persist outcome: status (service-role bypasses RLS) + an outreach_log entry.
    const newStatus = ok ? "sent" : "failed";
    await supabaseAdmin.from(cfg.table).update({ status: newStatus }).eq("id", row.id);
    await supabaseAdmin.from("outreach_log").insert({
      target_id: row.id,
      target_type: cfg.targetType,
      email: intendedTo,
      status: ok ? "sent" : "failed",
    });

    results.push({ id: row.id, name: row.name ?? null, status: newStatus, detail });
  }

  const sent = results.filter((r) => r.status === "sent").length;
  return NextResponse.json({ sent, failed: results.length - sent, results });
}

function subjectFor(dataset: DatasetKey, row: Record<string, unknown>): string {
  // Lightweight, human subject lines per dataset. Kept here (not the agent) since
  // subject framing is an outreach/UI concern, not part of scoring.
  switch (dataset) {
    case "leads":
      return `Quick note for ${row.name ?? "you"} at ${row.company ?? "your team"}`;
    case "experts":
      return `Your work on ${row.topic ?? "your field"}`;
    case "jobs":
      return `An opportunity matching ${row.matched_role ?? "your skills"}`;
  }
}
