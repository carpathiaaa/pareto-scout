"""Offline tests for the jobs agent — fixtures + stubbed LLM, no network, no credits."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agents.jobs import classifier, run as run_mod
from agents.jobs.sources import (
    _extract_email,
    _job_query,
    _platform_from_url,
    fetch_open_to_work,
    fetch_reddit_forhire,
)


def test_job_query_flattens_lists_and_excludes_job_boards() -> None:
    # Parsed fields arrive as lists; the query must not leak brackets, must bias
    # toward profile sites, and must exclude commercial job boards (the first live
    # run returned Indeed/Upwork listings instead of people).
    q = _job_query(
        {"target_role_or_skills": ["product designers"], "seniority": ["mid"]}
    )
    assert "['product designers']" not in q and "product designers" in q
    assert "site:contra.com" in q
    assert "-site:indeed.com" in q and "-site:upwork.com" in q


def test_email_extraction() -> None:
    assert (
        _extract_email("reach me at ava@avareyes.design today") == "ava@avareyes.design"
    )
    assert _extract_email("contact via the form") is None
    assert _extract_email(None) is None


def test_platform_label_uses_removeprefix_not_lstrip() -> None:
    # Regression: lstrip('www.') would mangle 'wellfound.com' -> 'ellfound.com'.
    assert _platform_from_url("https://wellfound.com/u/x") == "wellfound"
    assert _platform_from_url("https://www.contra.com/x") == "contra"
    assert _platform_from_url("https://reddit.com/r/forhire") == "reddit"


def test_open_to_work_extracts_public_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBS_SOURCE_MODE", "mock")
    rows = fetch_open_to_work({})
    ava = next(r for r in rows if r["profile_url"] == "https://avareyes.design")
    assert ava["contact_email"] == "ava@avareyes.design"


def test_reddit_is_discovery_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBS_SOURCE_MODE", "mock")
    rows = fetch_reddit_forhire()
    assert rows and all(r["contact_email"] is None for r in rows)
    assert all(r["reddit_discovery_only"] for r in rows)


def test_classify_tier1_requires_email(monkeypatch: pytest.MonkeyPatch) -> None:
    # The LLM is told never to return tier 1; tier 1 comes from a real email in Python.
    monkeypatch.setattr(
        classifier,
        "chat",
        lambda *a, **k: json.dumps(
            {
                "skills": ["Figma"],
                "matched_role": "Designer",
                "reachability_tier": 3,
                "draft_message": "hi",
            }
        ),
    )
    out = classifier.classify_seeker(
        {"contact_email": "ava@x.com", "reddit_discovery_only": False, "name": "Ava"},
        {},
    )
    assert out["reachability_tier"] == 1
    assert out["contact_email"] == "ava@x.com"


def test_classify_reddit_never_tier1_even_with_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The hard guardrail: a Reddit candidate is barred from tier 1 by policy, even if
    # an email somehow slipped into the record. contact_email must be nulled.
    monkeypatch.setattr(
        classifier,
        "chat",
        lambda *a, **k: json.dumps(
            {
                "skills": [],
                "matched_role": "",
                "reachability_tier": 2,
                "draft_message": "",
            }
        ),
    )
    out = classifier.classify_seeker(
        {"contact_email": "leaked@x.com", "reddit_discovery_only": True, "name": "u/x"},
        {},
    )
    assert out["reachability_tier"] != 1
    assert out["contact_email"] is None


def test_classify_no_email_uses_llm_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        classifier,
        "chat",
        lambda *a, **k: json.dumps(
            {
                "skills": [],
                "matched_role": "",
                "reachability_tier": 2,
                "draft_message": "",
            }
        ),
    )
    out = classifier.classify_seeker(
        {"contact_email": None, "reddit_discovery_only": False}, {}
    )
    assert out["reachability_tier"] == 2
    assert out["contact_email"] is None


def test_classify_degrades_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classifier, "chat", lambda *a, **k: "not json")
    out = classifier.classify_seeker(
        {"contact_email": None, "reddit_discovery_only": False}, {}
    )
    assert out["reachability_tier"] == 4  # worst tier on a failed parse


def test_run_continues_when_reddit_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reddit is an optional discovery source; its failure must not sink a run whose
    # paid SerpAPI source already succeeded.
    monkeypatch.setenv("JOBS_SOURCE_MODE", "mock")
    monkeypatch.setattr(run_mod, "parse_query_to_fields", lambda q, a: {})
    monkeypatch.setattr(run_mod.db, "insert", lambda t, r: {"id": "run-r"})
    monkeypatch.setattr(
        run_mod,
        "classify_seeker",
        lambda c, crit: {
            **c,
            "skills": [],
            "matched_role": "",
            "reachability_tier": 3,
            "contact_email": None,
            "draft_message": "",
        },
    )
    monkeypatch.setattr(run_mod.db, "upsert", lambda t, rows, on_conflict=None: rows)

    def boom(*a, **k):
        raise RuntimeError("reddit 403")

    monkeypatch.setattr(run_mod, "fetch_reddit_forhire", boom)

    summary = run_mod.run_jobs_agent("designers")
    # SerpAPI fixture still yields its 4 deduped candidates; the run did not crash.
    assert summary["deduped"] == 4


def test_run_pipeline_tiers_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tier-1 rows get status 'new' (queue); lower tiers get 'archived' (stored only).
    monkeypatch.setenv("JOBS_SOURCE_MODE", "mock")
    monkeypatch.setattr(run_mod, "parse_query_to_fields", lambda q, a: {})
    monkeypatch.setattr(run_mod.db, "insert", lambda t, r: {"id": "run-j"})

    # Classify: email present -> tier 1, else tier 3.
    def fake_classify(c, crit):
        has = bool(c.get("contact_email")) and not c.get("reddit_discovery_only")
        return {
            **c,
            "skills": [],
            "matched_role": "",
            "reachability_tier": 1 if has else 3,
            "contact_email": c.get("contact_email") if has else None,
            "draft_message": "d",
        }

    monkeypatch.setattr(run_mod, "classify_seeker", fake_classify)

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        run_mod.db,
        "upsert",
        lambda t, rows, on_conflict=None: captured.update(
            rows=rows, on_conflict=on_conflict
        )
        or rows,
    )

    summary = run_mod.run_jobs_agent("react devs open to work")

    assert captured["on_conflict"] == "profile_url"
    # Fixture: 5 serp results (1 dup -> 4) + 2 reddit = 6 deduped.
    assert summary["deduped"] == 6
    # Only Ava has a public email -> exactly one tier-1 / actionable seeker.
    assert summary["actionable"] == 1
    new_rows = [r for r in captured["rows"] if r["status"] == "new"]
    assert len(new_rows) == 1 and new_rows[0]["reachability_tier"] == 1
    # Every non-tier-1 row is archived and has no email.
    archived = [r for r in captured["rows"] if r["status"] == "archived"]
    assert all(r["contact_email"] is None for r in archived)
