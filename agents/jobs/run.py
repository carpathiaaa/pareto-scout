"""Jobs agent orchestrator — the only module here that touches the database.

Flow: parse query -> fetch (open-to-work + Reddit discovery) -> dedup by profile_url
-> classify reachability -> upsert to agency.job_seekers -> log the run. As with the
other agents, sources.py and classifier.py stay pure; only this module writes.

What makes the jobs agent different: the queue gate is a reachability TIER, not a
score. Only tier-1 seekers (a real public email) are actionable and get status 'new';
tiers 2-4 are stored with status 'archived' so the review queue ignores them but the
data is kept for later (CLAUDE.md: lower tiers are stored, not actionable).
"""

from __future__ import annotations

from typing import Any

from agents.jobs.classifier import classify_seeker
from agents.jobs.sources import fetch_open_to_work, fetch_reddit_forhire
from shared import db
from shared.llm import parse_query_to_fields
from shared.utils import dedup_by, get_logger

logger = get_logger(__name__)

# Tier-1 seekers enter the review queue; everyone else is kept but not actionable.
ACTIONABLE_TIER = 1


def run_jobs_agent(raw_query: str, *, limit: int = 20) -> dict[str, Any]:
    """Run the job-seeker pipeline end to end for one natural-language query.

    Args:
        raw_query: The developer's plain-language request (e.g. "open-to-work React
            engineers, mid-level, remote").
        limit: Max results per source. In live mode the SerpAPI source spends one
            search; Reddit is free but discovery-only.

    Returns:
        A summary: the search_run id, parsed criteria, counts, and the tier histogram.
    """
    criteria = parse_query_to_fields(raw_query, "jobs")
    logger.info("Parsed criteria: %s", criteria)

    run_row = db.insert(
        db.SEARCH_RUNS,
        {"agent_type": "jobs", "raw_query": raw_query, "parsed_criteria": criteria},
    )
    search_run_id = run_row["id"]

    # SerpAPI is the primary, credit-spending source. Reddit is an optional,
    # discovery-only layer, so its failure must NOT sink a run we already paid for:
    # catch and continue with whatever SerpAPI returned. (Reddit blocks anonymous
    # reads, so a 403 here is expected and non-fatal.)
    candidates = fetch_open_to_work(criteria, limit=limit)
    try:
        candidates += fetch_reddit_forhire(limit=limit)
    except Exception as e:  # noqa: BLE001 — discovery source must never sink the run
        logger.warning("Reddit discovery skipped (non-fatal): %s", e)

    deduped = dedup_by(candidates, key=lambda c: c.get("profile_url"))
    logger.info("Fetched %d candidates, %d after dedup", len(candidates), len(deduped))

    classified = [classify_seeker(c, criteria) for c in deduped]
    tiers = _tier_histogram(classified)
    logger.info("Tier histogram: %s", tiers)

    rows = [_to_seeker_row(c, search_run_id) for c in classified]
    stored = db.upsert(db.JOB_SEEKERS, rows, on_conflict="profile_url") if rows else []

    return {
        "search_run_id": search_run_id,
        "criteria": criteria,
        "fetched": len(candidates),
        "deduped": len(deduped),
        "stored": len(stored),
        "tiers": tiers,
        "actionable": tiers.get(1, 0),
    }


def _tier_histogram(classified: list[dict[str, Any]]) -> dict[int, int]:
    """Count candidates per reachability tier, for the run summary and Slack note."""
    hist: dict[int, int] = {}
    for c in classified:
        tier = c["reachability_tier"]
        hist[tier] = hist.get(tier, 0) + 1
    return hist


def _to_seeker_row(classified: dict[str, Any], search_run_id: str) -> dict[str, Any]:
    """Project a classified candidate onto the agency.job_seekers column set.

    Only tier-1 seekers are actionable, so they get status 'new' (the queue shows
    these). Lower tiers are stored with status 'archived' — kept for later, ignored by
    the review queue. This is how the tier gate is enforced at the data layer.
    """
    tier = classified["reachability_tier"]
    status = "new" if tier == ACTIONABLE_TIER else "archived"
    return {
        "name": classified.get("name"),
        "platform": classified.get("platform"),
        "profile_url": classified.get("profile_url"),
        "skills": classified.get("skills"),
        "contact_email": classified.get("contact_email"),
        "reachability_tier": tier,
        "matched_role": classified.get("matched_role"),
        "draft_message": classified.get("draft_message"),
        "status": status,
        "search_run_id": search_run_id,
    }
