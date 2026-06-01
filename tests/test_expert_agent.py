"""Offline tests for the expert agent — fixtures + stubbed LLM, no network, no credits."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agents.expert import run as run_mod, scorer
from agents.expert.sources import (
    _platform_from_url,
    _search_query,
    fetch_from_serpapi,
)


def test_serpapi_mock_returns_normalized_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPERT_SOURCE_MODE", "mock")
    rows = fetch_from_serpapi({"field_or_domain": "ML", "topic_or_specialty": "RL"})
    assert rows and all(
        set(r) >= {"name", "topic", "url", "platform", "contact_signal"} for r in rows
    )
    # topic is stitched from the criteria, not the result.
    assert all(r["topic"] == "ML RL" for r in rows)


def test_search_query_adds_person_intent_and_exclusions() -> None:
    # The live query must bias toward people (not topic docs) and honor exclusions,
    # while the stored topic stays clean — that separation is the fix for the first
    # live run where topic-only search returned only documents.
    q = _search_query("robotics RL", {"exclusions": ["beginner", "course"]})
    assert "robotics RL" in q
    assert "professor" in q and "researcher" in q
    assert "site:github.com" in q
    assert "-beginner" in q and "-course" in q


def test_platform_detection() -> None:
    assert _platform_from_url("https://github.com/x") == "github"
    assert _platform_from_url("https://mit.edu/~y") == "academia"
    assert _platform_from_url("https://medium.com/@z") == "blog"
    assert _platform_from_url(None) == "unknown"


def test_platform_uses_removeprefix_not_lstrip() -> None:
    # Regression: lstrip("www.") strips any leading {w, .} char, so "web.dev" became
    # "eb.dev" in the fallback. removeprefix strips only the literal "www." prefix.
    assert _platform_from_url("https://web.dev/article") == "web.dev"
    assert _platform_from_url("https://www.github.com/x") == "github"
    assert _platform_from_url("https://wired.com/story") == "wired.com"


def test_score_expert_clamps_and_keeps_refined_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scorer,
        "chat",
        lambda *a, **k: json.dumps(
            {"score": 250, "refined_name": "Dr. Elena Vasquez", "draft_message": "Hi"}
        ),
    )
    out = scorer.score_expert(
        {"name": "Dr. Elena Vasquez — RL for Robotics", "url": "u"},
        {"field_or_domain": "ML"},
    )
    assert out["score"] == 100
    assert out["name"] == "Dr. Elena Vasquez"  # refined name replaces the raw title
    assert out["draft_message"] == "Hi"


def test_score_expert_degrades_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scorer, "chat", lambda *a, **k: "not json")
    out = scorer.score_expert({"name": "raw title", "url": "u"}, {})
    assert out["score"] == 0
    assert out["draft_message"] == ""
    assert out["name"] == "raw title"  # falls back to original name on bad parse


def test_run_pipeline_dedups_by_url_and_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERT_SOURCE_MODE", "mock")
    monkeypatch.setattr(
        run_mod, "parse_query_to_fields", lambda q, a: {"field_or_domain": "ML"}
    )
    monkeypatch.setattr(run_mod.db, "insert", lambda t, r: {"id": "run-9"})
    monkeypatch.setattr(
        run_mod,
        "score_expert",
        lambda c, crit: {**c, "score": 75, "draft_message": "d"},
    )

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        run_mod.db,
        "upsert",
        lambda t, rows, on_conflict=None: captured.update(
            rows=rows, on_conflict=on_conflict
        )
        or rows,
    )

    summary = run_mod.run_expert_agent("RL experts", score_threshold=50)

    # Fixture has 5 results: duplicate Stanford link collapses -> 4 after dedup.
    assert summary["fetched"] == 5
    assert summary["deduped"] == 4
    assert captured["on_conflict"] == "url"  # upsert keyed on url, not email
    assert all(r["search_run_id"] == "run-9" for r in captured["rows"])
    assert all("score" in r and "draft_message" in r for r in captured["rows"])


def test_run_pipeline_threshold_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERT_SOURCE_MODE", "mock")
    monkeypatch.setattr(run_mod, "parse_query_to_fields", lambda q, a: {})
    monkeypatch.setattr(run_mod.db, "insert", lambda t, r: {"id": "run-1"})
    monkeypatch.setattr(
        run_mod, "score_expert", lambda c, crit: {**c, "score": 10, "draft_message": ""}
    )
    called = {"upsert": False}
    monkeypatch.setattr(
        run_mod.db, "upsert", lambda *a, **k: called.update(upsert=True) or []
    )

    summary = run_mod.run_expert_agent("x", score_threshold=50)
    assert summary["kept"] == 0
    assert summary["stored"] == 0
    assert called["upsert"] is False
