"""One-shot live validation of the expert agent against real SerpAPI.

Standalone script (not a test) so the spend is always explicit and never triggered by
`pytest`. Runs the full pipeline over one search, prints a stage-by-stage summary,
then reads the stored rows back from Supabase to confirm the live SerpAPI response
shape matched our fixture and that scoring discriminates experts from noise.

Usage (PowerShell):
    $env:EXPERT_SOURCE_MODE = "live"
    python scripts/validate_expert_live.py
"""

from __future__ import annotations

from shared import db
from shared.utils import get_env, get_logger
from agents.expert.run import run_expert_agent

logger = get_logger("validate_expert_live")

QUERY = "experts in reinforcement learning for robotics"
LIMIT = 10  # results to request; one SerpAPI search regardless


def main() -> None:
    mode = get_env("EXPERT_SOURCE_MODE", required=False, default="mock")
    if mode != "live":
        logger.warning(
            "EXPERT_SOURCE_MODE=%s (not 'live'). This runs against the fixture and "
            "spends no SerpAPI credits. Set EXPERT_SOURCE_MODE=live to validate.",
            mode,
        )

    logger.info("Running expert agent: %r (limit=%d, mode=%s)", QUERY, LIMIT, mode)
    summary = run_expert_agent(QUERY, limit=LIMIT)

    logger.info("--- run summary ---")
    for key, value in summary.items():
        logger.info("%-15s %s", key, value)

    stored = (
        db.get_client()
        .table(db.EXPERTS)
        .select("name, platform, score, url, status")
        .eq("search_run_id", summary["search_run_id"])
        .order("score", desc=True)
        .execute()
    )
    logger.info("--- rows in agency.experts for this run (%d) ---", len(stored.data))
    for row in stored.data:
        logger.info(
            "%3s  %-10s  %-32s  %s",
            row.get("score"),
            (row.get("platform") or "")[:10],
            (row.get("name") or "")[:32],
            row.get("url"),
        )


if __name__ == "__main__":
    main()
