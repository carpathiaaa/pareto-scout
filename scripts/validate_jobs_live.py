"""One-shot live validation of the jobs agent.

Standalone script (not a test) so the spend is always explicit. Runs the full pipeline
over a live SerpAPI 'open to work' search plus a live (free) Reddit r/forhire discovery
read, prints the tier histogram, then reads the stored rows back to confirm only
tier-1 seekers are actionable (status 'new') and the live response shape matched the
fixtures.

Usage (PowerShell):
    $env:JOBS_SOURCE_MODE = "live"
    python scripts/validate_jobs_live.py
"""

from __future__ import annotations

from shared import db
from shared.utils import get_env, get_logger
from agents.jobs.run import run_jobs_agent

logger = get_logger("validate_jobs_live")

QUERY = "open to work product designers, mid-level"
LIMIT = 10  # SerpAPI: one search regardless; Reddit: free, discovery only


def main() -> None:
    mode = get_env("JOBS_SOURCE_MODE", required=False, default="mock")
    if mode != "live":
        logger.warning(
            "JOBS_SOURCE_MODE=%s (not 'live'). Runs against fixtures, spends no "
            "credits. Set JOBS_SOURCE_MODE=live to validate.",
            mode,
        )

    logger.info("Running jobs agent: %r (limit=%d, mode=%s)", QUERY, LIMIT, mode)
    summary = run_jobs_agent(QUERY, limit=LIMIT)

    logger.info("--- run summary ---")
    for key, value in summary.items():
        logger.info("%-15s %s", key, value)

    stored = (
        db.get_client()
        .table(db.JOB_SEEKERS)
        .select("name, platform, reachability_tier, contact_email, status, profile_url")
        .eq("search_run_id", summary["search_run_id"])
        .order("reachability_tier", desc=False)
        .execute()
    )
    logger.info(
        "--- rows in agency.job_seekers for this run (%d) ---", len(stored.data)
    )
    for row in stored.data:
        logger.info(
            "tier %s  %-9s  %-8s  %-22s  %s",
            row.get("reachability_tier"),
            row.get("status"),
            row.get("platform"),
            (row.get("contact_email") or "—")[:22],
            (row.get("profile_url") or "")[:48],
        )


if __name__ == "__main__":
    main()
