"""Offline unit tests for shared/utils.py — pure logic, no network, no credits."""

from __future__ import annotations

import time

import pytest

from shared.utils import (
    ConfigError,
    RateLimiter,
    dedup_by,
    get_env,
    warn_if_near_limit,
)


def test_get_env_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_KEY", "value")
    assert get_env("SOME_KEY") == "value"


def test_get_env_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEFINITELY_MISSING", raising=False)
    with pytest.raises(ConfigError):
        get_env("DEFINITELY_MISSING")


def test_get_env_missing_optional_returns_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEFINITELY_MISSING", raising=False)
    assert get_env("DEFINITELY_MISSING", required=False, default="fallback") == "fallback"


def test_get_env_empty_string_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unfilled .env line (KEY=) should behave as unset, not as "".
    monkeypatch.setenv("EMPTY_KEY", "")
    with pytest.raises(ConfigError):
        get_env("EMPTY_KEY")


def test_rate_limiter_enforces_interval() -> None:
    # Two back-to-back waits must span at least the configured interval.
    limiter = RateLimiter(min_interval_seconds=0.2, name="test")
    start = time.monotonic()
    limiter.wait()  # first call returns immediately
    limiter.wait()  # second must block ~0.2s
    elapsed = time.monotonic() - start
    assert elapsed >= 0.2


def test_dedup_by_keeps_first_occurrence_order() -> None:
    rows = [
        {"email": "a@x.com", "n": 1},
        {"email": "b@x.com", "n": 2},
        {"email": "a@x.com", "n": 3},  # dup of first
    ]
    out = dedup_by(rows, key=lambda r: r["email"])
    assert [r["n"] for r in out] == [1, 2]


def test_dedup_by_keeps_falsy_keys() -> None:
    # Rows with no email are not true duplicates and must all survive.
    rows = [{"email": None}, {"email": None}, {"email": "a@x.com"}]
    out = dedup_by(rows, key=lambda r: r["email"])
    assert len(out) == 3


def test_warn_if_near_limit_no_crash_on_zero_limit() -> None:
    # Guard against division by zero; should simply do nothing.
    warn_if_near_limit(5, 0, label="x")
