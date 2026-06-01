import Queue from "@/components/Queue";

// Server component shell; the live, stateful queue is the client <Queue>.
export default function Page() {
  return (
    <main className="shell">
      <header className="masthead">
        <h1>
          Pareto <span className="glyph">/</span> Scout
        </h1>
        <div className="sub">
          <span className="live-dot" />
          Review Desk · live
          <br />
          scored &amp; drafted candidates
        </div>
      </header>
      <Queue />
    </main>
  );
}
