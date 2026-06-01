// Presentational cards for each dataset. No data fetching here — the page passes
// already-loaded rows. A shared <ScoredCard> covers leads + experts (both gauge a
// 0-100 score); <SeekerCard> renders the reachability tier instead.

import type { Lead, Expert, JobSeeker } from "@/lib/types";
import { scoreColor, tierColor, tierLabel, statusClass } from "@/lib/format";

function Draft({ text }: { text: string | null }) {
  if (!text) return <p className="draft empty">No draft generated.</p>;
  return <p className="draft">{text}</p>;
}

function animDelay(i: number) {
  // Staggered reveal on load — capped so long lists don't crawl in.
  return { animationDelay: `${Math.min(i * 45, 600)}ms` };
}

export function ScoredCard({
  row,
  index,
  kind,
}: {
  row: Lead | Expert;
  index: number;
  kind: "leads" | "experts";
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
    </article>
  );
}

export function SeekerCard({ row, index }: { row: JobSeeker; index: number }) {
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
    </article>
  );
}
