"""Candidate fetching for the lead agent.

Each source returns a list of normalized candidate dicts with a stable shape:
    {"name", "company", "email", "title", "source"}
so the enricher and run.py never care which provider a lead came from.

Mock vs live is chosen by LEAD_SOURCE_MODE (default "mock"). Mock loads JSON
fixtures and spends zero credits; live calls the real API through a per-source
RateLimiter. The call sites are identical in both modes, so logic cannot drift
between them. See DECISIONS.md for why this is an env flag, not injected classes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from shared.utils import RateLimiter, get_env, get_logger

logger = get_logger(__name__)

_FIXTURES = Path(__file__).parent / "fixtures"

# One limiter per provider: Apollo and Hunter have unrelated quotas and must not
# throttle each other. 1s default per CLAUDE.md.
_apollo_limiter = RateLimiter(min_interval_seconds=1.0, name="apollo")

# Normalized candidate keys every source must emit.
CANDIDATE_KEYS = ("name", "company", "email", "title", "source")


def _is_mock() -> bool:
    """True when sources should read fixtures instead of calling real APIs."""
    return get_env("LEAD_SOURCE_MODE", required=False, default="mock") == "mock"


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture from the fixtures directory."""
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _normalize_apollo_person(person: dict[str, Any]) -> dict[str, Any]:
    """Map one Apollo person object to the normalized candidate shape.

    Kept separate so the same mapping serves both mock and live responses — they
    share Apollo's schema, so normalization must not depend on the mode.
    """
    org = person.get("organization") or {}
    return {
        "name": person.get("name"),
        "company": org.get("name"),
        "email": person.get("email"),
        "title": person.get("title"),
        "source": "apollo",
    }


def fetch_from_apollo(
    criteria: dict[str, Any], *, limit: int = 25
) -> list[dict[str, Any]]:
    """Fetch lead candidates from Apollo (or its fixture in mock mode).

    Args:
        criteria: Parsed lead fields (industry, role_or_seniority, location, ...).
            Used to build the live query; ignored in mock mode.
        limit: Max candidates to request. Bounds live credit spend.

    Returns:
        Normalized candidate dicts. May contain duplicates and null emails; run.py
        dedups and the enricher tolerates missing fields.
    """
    if _is_mock():
        logger.info("Apollo: mock mode, loading fixture (0 credits spent)")
        raw = _load_fixture("apollo_sample.json")
        return [_normalize_apollo_person(p) for p in raw.get("people", [])]

    return _fetch_from_apollo_live(criteria, limit=limit)


def _fetch_from_apollo_live(
    criteria: dict[str, Any], *, limit: int
) -> list[dict[str, Any]]:
    """Real Apollo call. Spends email-reveal credits — gated by LEAD_SOURCE_MODE=live.

    Isolated from the mock path so the credit-spending code is never reached by
    accident during dev or tests.
    """
    api_key = get_env("APOLLO_API_KEY")
    # WARNING: Apollo free tier is ~50 email credits/month. Each revealed email is a
    # spent credit and is effectively irreversible for the month. This runs only when
    # the developer has explicitly set LEAD_SOURCE_MODE=live.
    logger.warning(
        "Apollo: LIVE mode — this spends email credits (free tier ~50/month)"
    )
    _apollo_limiter.wait()

    payload = {
        "person_titles": _as_list(criteria.get("role_or_seniority")),
        "q_keywords": " ".join(_as_list(criteria.get("focus_keywords"))),
        "person_locations": _as_list(criteria.get("location")),
        "page": 1,
        "per_page": limit,
    }
    try:
        response = httpx.post(
            "https://api.apollo.io/v1/mixed_people/search",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(f"API call failed: {e.response.status_code} - {e.response.text}")
        raise

    people = response.json().get("people", [])
    return [_normalize_apollo_person(p) for p in people]


def _as_list(value: Any) -> list[str]:
    """Coerce a criteria field to a list of strings.

    Parsed criteria fields may be a string, a list, or None depending on the query.
    Apollo's API wants arrays, so we normalize here rather than at each call site.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]
