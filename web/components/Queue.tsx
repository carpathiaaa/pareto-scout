"use client";

// The review desk. A client component because it holds tab state and a live
// Supabase realtime subscription. Reads are read-only for this first slice — no
// approve/send yet. Each dataset is fetched on demand when its channel opens, then
// kept fresh by a realtime subscription on that table.

import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Dataset, Expert, JobSeeker, Lead } from "@/lib/types";
import { ScoredCard, SeekerCard } from "./Card";

// Per-dataset config: the table name and how to order it for review.
const CHANNELS: { key: Dataset; label: string; table: string; orderBy: string }[] = [
  { key: "leads", label: "Leads", table: "leads", orderBy: "fit_score" },
  { key: "experts", label: "Experts", table: "experts", orderBy: "score" },
  { key: "jobs", label: "Job Seekers", table: "job_seekers", orderBy: "reachability_tier" },
];

type RowsByDataset = {
  leads: Lead[];
  experts: Expert[];
  jobs: JobSeeker[];
};

export default function Queue() {
  const [active, setActive] = useState<Dataset>("leads");
  const [rows, setRows] = useState<RowsByDataset>({ leads: [], experts: [], jobs: [] });
  const [loading, setLoading] = useState(true);

  const channel = useMemo(() => CHANNELS.find((c) => c.key === active)!, [active]);

  const load = useCallback(async (ds: Dataset) => {
    const cfg = CHANNELS.find((c) => c.key === ds)!;
    setLoading(true);
    // Jobs orders by tier ascending (1 is best); scores order descending (100 is best).
    const ascending = ds === "jobs";
    const { data, error } = await supabase
      .from(cfg.table)
      .select("*")
      .order(cfg.orderBy, { ascending, nullsFirst: false });
    if (!error && data) {
      setRows((prev) => ({ ...prev, [ds]: data }));
    }
    setLoading(false);
  }, []);

  // Load the active channel when it changes.
  useEffect(() => {
    void load(active);
  }, [active, load]);

  // Realtime: subscribe to the active table; any change reloads that channel. Simple
  // and correct for POC volumes — the subscription is the reason migration 003 adds
  // these tables to the supabase_realtime publication.
  useEffect(() => {
    const sub = supabase
      .channel(`rt-${channel.table}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "agency", table: channel.table },
        () => void load(active),
      )
      .subscribe();
    return () => {
      void supabase.removeChannel(sub);
    };
  }, [channel.table, active, load]);

  const counts = {
    leads: rows.leads.length,
    experts: rows.experts.length,
    jobs: rows.jobs.length,
  };

  return (
    <>
      <nav className="channels">
        {CHANNELS.map((c) => (
          <button
            key={c.key}
            className="channel"
            data-active={active === c.key}
            onClick={() => setActive(c.key)}
          >
            {c.label}
            <span className="count">{counts[c.key] || "·"}</span>
          </button>
        ))}
      </nav>

      {loading ? (
        <div className="grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div className="skeleton" key={i} />
          ))}
        </div>
      ) : (
        <Channel active={active} rows={rows} />
      )}
    </>
  );
}

function Channel({ active, rows }: { active: Dataset; rows: RowsByDataset }) {
  if (active === "jobs") {
    if (rows.jobs.length === 0) return <Empty dataset="jobs" />;
    return (
      <div className="grid">
        {rows.jobs.map((r, i) => (
          <SeekerCard row={r} index={i} key={r.id} />
        ))}
      </div>
    );
  }

  const list = active === "leads" ? rows.leads : rows.experts;
  if (list.length === 0) return <Empty dataset={active} />;
  return (
    <div className="grid">
      {list.map((r, i) => (
        <ScoredCard row={r} index={i} kind={active} key={r.id} />
      ))}
    </div>
  );
}

function Empty({ dataset }: { dataset: Dataset }) {
  const msg =
    dataset === "jobs"
      ? "No reachable seekers yet"
      : `No ${dataset} in the queue yet`;
  const hint =
    dataset === "jobs"
      ? "Tier-2+ seekers are discovered but not actionable. Run the jobs agent to populate."
      : `Run the ${dataset} agent to populate this channel.`;
  return (
    <div className="empty-state">
      <div className="big">{msg}</div>
      <div className="hint">{hint}</div>
    </div>
  );
}
