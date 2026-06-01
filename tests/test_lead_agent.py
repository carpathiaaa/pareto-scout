"""Offline tests for the lead agent — fixtures + stubbed LLM, no network, no credits."""

from __future__ import annotations

import json

import pytest

from agents.lead import enricher, run as run_mod
from agents.lead.sources import fetch_from_apollo


def test_apollo_mock_returns_normalized_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEAD_SOURCE_MODE", "mock")
    rows = fetch_from_apollo({})
    assert rows and all(
        set(r) >= {"name", "company", "email", "title", "source"} for r in rows
    )
    assert all(r["source"] == "apollo" for r in rows)


def test_enrich_lead_parses_and_clamps_score(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub the LLM: return an over-range score to prove clamping to 100.
    monkeypatch.setattr(
        enricher,
        "chat",
        lambda *a, **k: json.dumps({"fit_score": 150, "draft_message": "Hi"}),
    )
    out = enricher.enrich_lead({"name": "X", "email": "x@y.com"}, {"industry": "tech"})
    assert out["fit_score"] == 100
    assert out["draft_message"] == "Hi"


def test_enrich_lead_degrades_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    # A non-JSON model response must score 0, not crash the run.
    monkeypatch.setattr(enricher, "chat", lambda *a, **k: "not json at all")
    out = enricher.enrich_lead({"email": "x@y.com"}, {})
    assert out["fit_score"] == 0
    assert out["draft_message"] == ""


def test_run_pipeline_dedups_and_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wire the whole pipeline with stubs: fixed criteria, real mock fetch, fake enrich,
    # and capture what run.py would upsert — proving dedup + threshold + projection
    # without any network or DB.
    monkeypatch.setenv("LEAD_SOURCE_MODE", "mock")
    monkeypatch.setattr(
        run_mod, "parse_query_to_fields", lambda q, a: {"industry": "tech"}
    )
    monkeypatch.setattr(run_mod.db, "insert", lambda t, r: {"id": "run-123"})
    monkeypatch.setattr(
        run_mod,
        "enrich_lead",
        lambda c, crit: {**c, "fit_score": 70, "draft_message": "d"},
    )

    captured: dict[str, list] = {}
    monkeypatch.setattr(
        run_mod.db,
        "upsert",
        lambda t, rows, on_conflict=None: captured.setdefault("rows", rows),
    )

    summary = run_mod.run_lead_agent("find CTOs", score_threshold=50)

    # Fixture has 5 rows: one duplicate Maya collapses, the null-email Tomas stays.
    assert summary["fetched"] == 5
    assert summary["deduped"] == 4
    assert summary["search_run_id"] == "run-123"
    # Every written row carries the run id and only schema columns.
    assert all(r["search_run_id"] == "run-123" for r in captured["rows"])
    assert all("fit_score" in r and "draft_message" in r for r in captured["rows"])


def test_run_pipeline_threshold_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    # A threshold above the stubbed score must store nothing and skip the upsert.
    monkeypatch.setenv("LEAD_SOURCE_MODE", "mock")
    monkeypatch.setattr(run_mod, "parse_query_to_fields", lambda q, a: {})
    monkeypatch.setattr(run_mod.db, "insert", lambda t, r: {"id": "run-1"})
    monkeypatch.setattr(
        run_mod,
        "enrich_lead",
        lambda c, crit: {**c, "fit_score": 10, "draft_message": ""},
    )
    called = {"upsert": False}
    monkeypatch.setattr(
        run_mod.db, "upsert", lambda *a, **k: called.update(upsert=True) or []
    )

    summary = run_mod.run_lead_agent("x", score_threshold=50)
    assert summary["kept"] == 0
    assert summary["stored"] == 0
    assert called["upsert"] is False
