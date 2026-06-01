"""Live smoke checks for shared/db.py and shared/llm.py.

These are marked `live`: they hit real Supabase and Groq and are skipped by default.
Run with RUN_LIVE_TESTS=1. The Groq call below spends exactly one small free-tier
request; the Supabase calls are reads/counts and cost nothing.
"""

from __future__ import annotations

import pytest

from shared import db
from shared.llm import parse_query_to_fields


@pytest.mark.live
def test_supabase_can_count_all_agency_tables() -> None:
    # Proves: client builds, service-role key works, agency schema is exposed,
    # and all five tables exist. count_rows raises if the schema is not exposed.
    for table in (db.LEADS, db.EXPERTS, db.JOB_SEEKERS, db.OUTREACH_LOG, db.SEARCH_RUNS):
        count = db.count_rows(table)
        assert count >= 0


@pytest.mark.live
def test_search_runs_insert_roundtrips() -> None:
    # Proves write access end to end on an append-only table, then deletes its own
    # row so the table count stays unchanged. The hard delete lives here, in
    # test-owned code, rather than in shared/db.py — the product rule is never hard
    # delete, and we don't want a delete helper sitting around to be misused.
    row = db.insert(
        db.SEARCH_RUNS,
        {
            "agent_type": "lead",
            "raw_query": "connectivity smoke test",
            "parsed_criteria": {"smoke": True},
        },
    )
    try:
        assert row["id"]
        assert row["agent_type"] == "lead"
    finally:
        db.get_client().table(db.SEARCH_RUNS).delete().eq("id", row["id"]).execute()


@pytest.mark.live
def test_parse_query_returns_lead_fields() -> None:
    # Proves: Groq key works, base_url routing works, JSON mode parses, and the
    # wrapper guarantees exactly the lead field set. Spends one small LLM call.
    fields = parse_query_to_fields(
        "Series A fintech founders in Singapore, exclude crypto", "lead"
    )
    expected = {
        "target_type",
        "industry",
        "role_or_seniority",
        "focus_keywords",
        "exclusions",
        "location",
    }
    assert set(fields.keys()) == expected
