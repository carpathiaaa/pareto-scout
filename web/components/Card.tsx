// Presentational cards for each dataset. No data fetching here — the page passes
// already-loaded rows. A shared <ScoredCard> covers leads + experts (both gauge a
// 0-100 score); <SeekerCard> renders the reachability tier instead.

import type { Dataset, Lead, Expert, JobSeeker, Status } from "@/lib/types";
import { scoreColor, tierColor, tierLabel, statusClass } from "@/lib/format";

// A review action callback the page supplies; cards stay otherwise presentational.
export type OnReview = (dataset: Dataset, id: string, status: Status) => void;

function Draft({ text }: { text: string | null }) {
  if (!text) return <p className="draft empty">No draft generated.</p>;
  return <p className="draft">{text}</p>;
}

// Approve / skip controls. Shown for actionable ('new') rows; once reviewed, the row
// shows its decided state and offers a single "reopen" back to 'new'. Buttons are
// disabled while a write is in flight (pending) to prevent double-submits.
function ReviewActions({
  dataset,
  id,
  status,
  onReview,
  pending,
}: {
  dataset: Dataset;
  id: string;
  status: Status;
  onReview: OnReview;
  pending: boolean;
}) {
  if (status === "approved" || status === "skipped") {
    return (
      <button
        className="act act-reopen"
        disabled={pending}
        onClick={() => onReview(dataset, id, "new")}
      >
        ↺ reopen
      </button>
    );
  }
  return (
    <div className="actions">
      <button
        className="act act-skip"
        disabled={pending}
        onClick={() => onReview(dataset, id, "skipped")}
      >
        skip
      </button>
      <button
        className="act act-approve"
        disabled={pending}
        onClick={() => onReview(dataset, id, "approved")}
      >
        approve
      </button>
    </div>
  );
}

function animDelay(i: number) {
  // Staggered reveal on load — capped so long lists don't crawl in.
  return { animationDelay: `${Math.min(i * 45, 600)}ms` };
}

export function ScoredCard({
  row,
  index,
  kind,
  onReview,
  pending,
}: {
  row: Lead | Expert;
  index: number;
  kind: "leads" | "experts";
  onReview: OnReview;
  pending: boolean;
}) {
  const score = kind === "leads" ? (row as Lead).fit_score : (row as Expert).score;
  const spine = scoreColor(score);
  const title = kind === "leads" ? (row as Lead).title : (row as Expert).topic;
  const sub = kind === "leads" ? (row as Lead).company : (row as Expert).platform;
  const contact =
    kind === "leads" ? (row as Lead).email : (row as Expert).contact_signal;

  return (
    <article
      className="card"
      style={{ ["--spine" as string]: spine, ...animDelay(index) }}
    >
      <div className="card-head">
        <div>
          <div className="card-id">{row.name || "Unknown"}</div>
          <div className="card-meta">
            {title || "—"}
            {sub ? (
              <>
                {" · "}
                <span className="platform">{sub}</span>
              </>
            ) : null}
          </div>
        </div>
        <div className="gauge">
          <span className="num">{score ?? "—"}</span>
          <span className="den">/100</span>
          <span className="label">{kind === "leads" ? "fit" : "authority"}</span>
        </div>
      </div>

      <Draft text={row.draft_message} />

      <div className="card-foot">
        <span className="contact">{contact || "no contact signal"}</span>
        <span className={`status-pill ${statusClass(row.status)}`}>{row.status}</span>
      </div>

      <div className="review-bar">
        <ReviewActions
          dataset={kind}
          id={row.id}
          status={row.status}
          onReview={onReview}
          pending={pending}
        />
      </div>
    </article>
  );
}

export function SeekerCard({
  row,
  index,
  onReview,
  pending,
}: {
  row: JobSeeker;
  index: number;
  onReview: OnReview;
  pending: boolean;
}) {
  const spine = tierColor(row.reachability_tier);
  return (
    <article
      className="card"
      style={{ ["--spine" as string]: spine, ...animDelay(index) }}
    >
      <div className="card-head">
        <div>
          <div className="card-id">{row.name || "Unknown"}</div>
          <div className="card-meta">
            {row.matched_role || "—"}
            {row.platform ? (
              <>
                {" · "}
                <span className="platform">{row.platform}</span>
              </>
            ) : null}
          </div>
        </div>
        <span className="tier">{tierLabel(row.reachability_tier)}</span>
      </div>

      {row.skills && row.skills.length > 0 ? (
        <div className="skills">
          {row.skills.slice(0, 6).map((s) => (
            <span className="skill" key={s}>
              {s}
            </span>
          ))}
        </div>
      ) : null}

      <Draft text={row.draft_message} />

      <div className="card-foot">
        <span className="contact">{row.contact_email || "no public email"}</span>
        <span className={`status-pill ${statusClass(row.status)}`}>{row.status}</span>
      </div>

      <div className="review-bar">
        <ReviewActions
          dataset="jobs"
          id={row.id}
          status={row.status}
          onReview={onReview}
          pending={pending}
        />
      </div>
    </article>
  );
}
