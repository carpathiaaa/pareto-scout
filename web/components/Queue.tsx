"use client";

// The review desk. A client component because it holds tab state and a live
// Supabase realtime subscription. Reads are read-only for this first slice — no
// approve/send yet. Each dataset is fetched on demand when its channel opens, then
// kept fresh by a realtime subscription on that table.

import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase, setStatus } from "@/lib/supabase";
import type { Dataset, Expert, JobSeeker, Lead, Status } from "@/lib/types";
import type { OnReview } from "./Card";
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

  // quiet=true skips the skeleton: used for background refreshes (realtime events,
  // error rollback) so the grid doesn't flash on every approve/skip. The initial
  // channel open passes quiet=false to show the skeleton.
  const load = useCallback(async (ds: Dataset, quiet = false) => {
    const cfg = CHANNELS.find((c) => c.key === ds)!;
    if (!quiet) setLoading(true);
    // Jobs orders by tier ascending (1 is best); scores order descending (100 is best).
    const ascending = ds === "jobs";
    // Secondary sort by id is a STABLE tiebreaker: many rows share a score/tier, and
    // Postgres does not guarantee order for ties, so without this a re-fetch (e.g.
    // after an approve/skip realtime event) would return tied rows in a different
    // order and the cards would visibly reshuffle.
    const { data, error } = await supabase
      .from(cfg.table)
      .select("*")
      .order(cfg.orderBy, { ascending, nullsFirst: false })
      .order("id", { ascending: true });
    if (!error && data) {
      setRows((prev) => ({ ...prev, [ds]: data }));
    }
    if (!quiet) setLoading(false);
  }, []);

  // Ids with an in-flight status write, so their buttons disable until it resolves.
  const [pending, setPending] = useState<Set<string>>(new Set());

  // Optimistic review: update the row locally at once, then persist. On failure,
  // reload the channel to snap back to the true server state. Realtime would also
  // reconcile, but reloading on error makes the rollback immediate and obvious.
  const onReview: OnReview = useCallback(
    async (ds: Dataset, id: string, status: Status) => {
      setPending((p) => new Set(p).add(id));
      setRows((prev) => ({
        ...prev,
        [ds]: (prev[ds] as { id: string; status: Status }[]).map((r) =>
          r.id === id ? { ...r, status } : r,
        ),
      }));
      const { error } = await setStatus(ds, id, status);
      if (error) {
        console.error("review write failed:", error);
        await load(ds, true); // quiet rollback to true server state
      }
      setPending((p) => {
        const next = new Set(p);
        next.delete(id);
        return next;
      });
    },
    [load],
  );

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
        () => void load(active, true), // quiet: don't flash skeletons on live updates
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
        <Channel active={active} rows={rows} onReview={onReview} pending={pending} />
      )}
    </>
  );
}

function Channel({
  active,
  rows,
  onReview,
  pending,
}: {
  active: Dataset;
  rows: RowsByDataset;
  onReview: OnReview;
  pending: Set<string>;
}) {
  if (active === "jobs") {
    if (rows.jobs.length === 0) return <Empty dataset="jobs" />;
    return (
      <div className="grid">
        {rows.jobs.map((r, i) => (
          <SeekerCard
            row={r}
            index={i}
            key={r.id}
            onReview={onReview}
            pending={pending.has(r.id)}
          />
        ))}
      </div>
    );
  }

  const list = active === "leads" ? rows.leads : rows.experts;
  if (list.length === 0) return <Empty dataset={active} />;
  return (
    <div className="grid">
      {list.map((r, i) => (
        <ScoredCard
          row={r}
          index={i}
          kind={active}
          key={r.id}
          onReview={onReview}
          pending={pending.has(r.id)}
        />
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
