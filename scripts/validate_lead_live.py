"""One-shot live validation of the lead agent against real Hunter.io.

This is the deliberate first credit spend for the lead pipeline. It is a standalone
script (not a test) so it never runs by accident under `pytest` and the spend is
always an explicit, human-initiated command.

Usage (PowerShell):
    $env:LEAD_SOURCE_MODE = "live"
    python scripts/validate_lead_live.py

Hunter is domain-centric, so we search a small set of company domains (one search
credit each), run the full pipeline, print a stage-by-stage summary, then read the
stored rows back from Supabase to confirm the live Hunter response shape matched our
fixture.
"""

from __future__ import annotations

from shared import db
from shared.utils import get_env, get_logger
from agents.lead.run import run_lead_agent

logger = get_logger("validate_lead_live")

QUERY = "Heads of L&D / People Development at mid-size tech companies"
# One Hunter search credit per domain (free tier ~25/month). Keep this list short.
DOMAINS = ["zapier.com"]
LIMIT = 10  # max emails per domain; does not affect credit cost


def main() -> None:
    mode = get_env("LEAD_SOURCE_MODE", required=False, default="mock")
    if mode != "live":
        logger.warning(
            "LEAD_SOURCE_MODE=%s (not 'live'). This will run against the fixture and "
            "spend no Hunter credits. Set LEAD_SOURCE_MODE=live to validate for real.",
            mode,
        )

    logger.info(
        "Running lead agent: %r over domains=%s (mode=%s)", QUERY, DOMAINS, mode
    )
    summary = run_lead_agent(QUERY, domains=DOMAINS, limit=LIMIT)

    logger.info("--- run summary ---")
    for key, value in summary.items():
        logger.info("%-15s %s", key, value)

    # Read back what landed, scoped to this run, to confirm the write end to end.
    stored = (
        db.get_client()
        .table(db.LEADS)
        .select("name, company, title, email, fit_score, status")
        .eq("search_run_id", summary["search_run_id"])
        .order("fit_score", desc=True)
        .execute()
    )
    logger.info("--- rows in agency.leads for this run (%d) ---", len(stored.data))
    for row in stored.data:
        logger.info(
            "%3s  %-22s  %-28s  %s",
            row.get("fit_score"),
            (row.get("name") or "")[:22],
            (row.get("company") or "")[:28],
            row.get("email"),
        )


if __name__ == "__main__":
    main()
