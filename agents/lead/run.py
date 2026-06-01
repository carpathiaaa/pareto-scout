"""Lead agent orchestrator — the only module here that touches the database.

Flow: parse query -> fetch candidates -> dedup by email -> enrich each -> upsert to
agency.leads -> log the run to agency.search_runs. Keeping all writes here means
sources.py and enricher.py stay pure and offline-testable; the DB and network live
only at the edges (sources, llm) and at this seam.
"""

from __future__ import annotations

from typing import Any

from agents.lead.enricher import enrich_lead
from agents.lead.sources import fetch_from_apollo
from shared import db
from shared.llm import parse_query_to_fields
from shared.utils import dedup_by, get_logger

logger = get_logger(__name__)


def run_lead_agent(raw_query: str, *, score_threshold: int = 0) -> dict[str, Any]:
    """Run the lead pipeline end to end for one natural-language query.

    Args:
        raw_query: The developer's plain-language request.
        score_threshold: Minimum fit_score to keep. 0 stores everything (the queue
            sorts by score); raise it to discard weak leads before they reach review.

    Returns:
        A summary: the search_run id, parsed criteria, and counts at each stage.
    """
    criteria = parse_query_to_fields(raw_query, "lead")
    logger.info("Parsed criteria: %s", criteria)

    # Log the run first so every candidate row can reference its search_run_id, and so
    # even a run that surfaces nothing leaves an audit trail.
    run_row = db.insert(
        db.SEARCH_RUNS,
        {"agent_type": "lead", "raw_query": raw_query, "parsed_criteria": criteria},
    )
    search_run_id = run_row["id"]

    candidates = fetch_from_apollo(criteria)
    deduped = dedup_by(candidates, key=lambda c: c.get("email"))
    logger.info("Fetched %d candidates, %d after dedup", len(candidates), len(deduped))

    enriched = [enrich_lead(c, criteria) for c in deduped]
    kept = [e for e in enriched if e["fit_score"] >= score_threshold]
    logger.info(
        "Enriched %d, %d passed threshold %d", len(enriched), len(kept), score_threshold
    )

    rows = [_to_lead_row(e, search_run_id) for e in kept]
    stored = db.upsert(db.LEADS, rows, on_conflict="email") if rows else []

    return {
        "search_run_id": search_run_id,
        "criteria": criteria,
        "fetched": len(candidates),
        "deduped": len(deduped),
        "kept": len(kept),
        "stored": len(stored),
    }


def _to_lead_row(enriched: dict[str, Any], search_run_id: str) -> dict[str, Any]:
    """Project an enriched candidate onto the agency.leads column set.

    Only writes columns the schema defines; status defaults to 'new' in the DB so the
    review queue picks it up. Drops any extra keys the enricher carried.
    """
    return {
        "name": enriched.get("name"),
        "company": enriched.get("company"),
        "email": enriched.get("email"),
        "title": enriched.get("title"),
        "source": enriched.get("source"),
        "fit_score": enriched.get("fit_score"),
        "draft_message": enriched.get("draft_message"),
        "search_run_id": search_run_id,
    }
