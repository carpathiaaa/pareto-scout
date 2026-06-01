"""Expert agent orchestrator — the only module here that touches the database.

Flow: parse query -> SerpAPI search -> dedup by url -> score each -> upsert to
agency.experts -> log the run to agency.search_runs. Keeping all writes here means
sources.py and scorer.py stay pure and offline-testable; the DB and network live only
at the edges (sources, llm) and at this seam. Mirrors the lead agent deliberately —
the only differences are the source (SerpAPI), the table, and the conflict key (url).
"""

from __future__ import annotations

from typing import Any

from agents.expert.scorer import score_expert
from agents.expert.sources import fetch_from_serpapi
from shared import db
from shared.llm import parse_query_to_fields
from shared.utils import dedup_by, get_logger

logger = get_logger(__name__)


def run_expert_agent(
    raw_query: str, *, score_threshold: int = 0, limit: int = 20
) -> dict[str, Any]:
    """Run the expert pipeline end to end for one natural-language query.

    Args:
        raw_query: The developer's plain-language request (e.g. "experts in
            reinforcement learning for robotics, exclude pure theorists").
        score_threshold: Minimum score to keep. 0 stores everything (the queue sorts
            by score); raise it to discard low-credibility results before review.
        limit: Max search results to fetch. In live mode this is one SerpAPI search
            regardless of limit.

    Returns:
        A summary: the search_run id, parsed criteria, and counts at each stage.
    """
    criteria = parse_query_to_fields(raw_query, "expert")
    logger.info("Parsed criteria: %s", criteria)

    # Log the run first so every candidate row can reference its search_run_id, and so
    # even a run that surfaces nothing leaves an audit trail.
    run_row = db.insert(
        db.SEARCH_RUNS,
        {"agent_type": "expert", "raw_query": raw_query, "parsed_criteria": criteria},
    )
    search_run_id = run_row["id"]

    candidates = fetch_from_serpapi(criteria, limit=limit)
    # Dedup by url: an expert is identified by their profile/article URL, matching the
    # unique(url) constraint that makes the upsert below idempotent across re-runs.
    deduped = dedup_by(candidates, key=lambda c: c.get("url"))
    logger.info("Fetched %d results, %d after dedup", len(candidates), len(deduped))

    scored = [score_expert(c, criteria) for c in deduped]
    kept = [s for s in scored if s["score"] >= score_threshold]
    logger.info(
        "Scored %d, %d passed threshold %d", len(scored), len(kept), score_threshold
    )

    rows = [_to_expert_row(s, search_run_id) for s in kept]
    stored = db.upsert(db.EXPERTS, rows, on_conflict="url") if rows else []

    return {
        "search_run_id": search_run_id,
        "criteria": criteria,
        "fetched": len(candidates),
        "deduped": len(deduped),
        "kept": len(kept),
        "stored": len(stored),
    }


def _to_expert_row(scored: dict[str, Any], search_run_id: str) -> dict[str, Any]:
    """Project a scored candidate onto the agency.experts column set.

    Only writes columns the schema defines; status defaults to 'new' in the DB so the
    review queue picks it up. Drops extra keys the scorer carried (e.g. snippet).
    """
    return {
        "name": scored.get("name"),
        "topic": scored.get("topic"),
        "url": scored.get("url"),
        "platform": scored.get("platform"),
        "score": scored.get("score"),
        "contact_signal": scored.get("contact_signal"),
        "draft_message": scored.get("draft_message"),
        "search_run_id": search_run_id,
    }
