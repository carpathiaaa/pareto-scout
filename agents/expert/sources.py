"""Candidate fetching for the expert agent.

SerpAPI is the universal cross-domain source (CLAUDE.md): a Google search for a
field/topic surfaces experts wherever they publish — academia, GitHub, blogs,
conference pages. Each result is normalized to a stable candidate shape:
    {"name", "topic", "url", "platform", "contact_signal", "snippet"}
so scorer.py and run.py never care which search produced a candidate.

Mock vs live is chosen by EXPERT_SOURCE_MODE (default "mock"), mirroring the lead
agent: mock loads a fixture and spends zero SerpAPI credits; live calls the real API
through a RateLimiter. Identical call sites in both modes so logic cannot drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from shared.utils import RateLimiter, get_env, get_logger

logger = get_logger(__name__)

_FIXTURES = Path(__file__).parent / "fixtures"
_serpapi_limiter = RateLimiter(min_interval_seconds=1.0, name="serpapi")

# Normalized candidate keys every expert source must emit.
CANDIDATE_KEYS = ("name", "topic", "url", "platform", "contact_signal", "snippet")


def _is_mock() -> bool:
    """True when sources should read fixtures instead of calling real APIs."""
    return get_env("EXPERT_SOURCE_MODE", required=False, default="mock") == "mock"


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture from the fixtures directory."""
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _platform_from_url(url: str | None) -> str:
    """Derive a coarse platform label from a result URL's host.

    The host is a cheap, reliable signal of where an expert publishes (github.com,
    a .edu, medium.com), which feeds both the stored `platform` column and the
    LLM's credibility judgment. Unknown hosts fall back to the bare domain.
    """
    if not url:
        return "unknown"
    host = (urlparse(url).hostname or "").lower().lstrip("www.")
    if "github.com" in host:
        return "github"
    if host.endswith(".edu") or ".edu." in host:
        return "academia"
    if "medium.com" in host or "substack.com" in host:
        return "blog"
    if "youtube.com" in host:
        return "youtube"
    return host or "unknown"


def _normalize_serp_result(result: dict[str, Any], topic: str) -> dict[str, Any]:
    """Map one SerpAPI organic result to the normalized candidate shape.

    Kept separate so the same mapping serves mock and live responses. `name` comes
    from the result title; the LLM later refines it. `contact_signal` records where a
    reader could plausibly reach this person (the source page) — experts have no
    email field, so reachability is a URL, not an address.
    """
    url = result.get("link")
    return {
        "name": result.get("title"),
        "topic": topic,
        "url": url,
        "platform": _platform_from_url(url),
        "contact_signal": url,
        "snippet": result.get("snippet"),
    }


def fetch_from_serpapi(
    criteria: dict[str, Any], *, limit: int = 20
) -> list[dict[str, Any]]:
    """Fetch expert candidates via SerpAPI (or its fixture in mock mode).

    Args:
        criteria: Parsed expert fields (field_or_domain, topic_or_specialty, ...).
            Builds the live search query; ignored in mock mode.
        limit: Max results to request. Bounds the response size.

    Returns:
        Normalized candidate dicts. May contain duplicates and non-experts (listicles,
        ads); run.py dedups by url and the LLM score filters out non-experts.
    """
    topic = _query_topic(criteria)
    if _is_mock():
        logger.info("SerpAPI: mock mode, loading fixture (0 searches spent)")
        raw = _load_fixture("serpapi_sample.json")
        return [
            _normalize_serp_result(r, topic) for r in raw.get("organic_results", [])
        ]

    return _fetch_from_serpapi_live(criteria, topic, limit=limit)


# Person-intent signals appended to the live search. A bare topic search returns
# documents about the topic (papers, docs, tutorials); these terms and site-scopes
# bias Google toward named people and their profiles. The first live run proved a
# plain topic query surfaces almost no actual experts — only content about the topic.
_PERSON_INTENT = '("professor" OR "researcher" OR "author" OR "scientist")'
_PEOPLE_SITES = "(site:github.com OR site:scholar.google.com OR site:.edu)"


def _query_topic(criteria: dict[str, Any]) -> str:
    """Build the clean topic string stored on each row (no search operators).

    Kept separate from the search query so the `topic` column stays human-readable
    ("robotics reinforcement learning") rather than carrying Google operators.
    """
    parts = [criteria.get("field_or_domain"), criteria.get("topic_or_specialty")]
    return " ".join(str(p) for p in parts if p).strip()


def _search_query(topic: str, criteria: dict[str, Any]) -> str:
    """Build the SerpAPI query: the topic plus person-intent signals.

    Distinct from _query_topic because what we search for (people who work on the
    topic) is not what we store (the topic itself). Any parsed exclusions are appended
    as negative terms so the search itself does some of the filtering.
    """
    query = f"{topic} {_PERSON_INTENT} {_PEOPLE_SITES}".strip()
    for term in _as_list(criteria.get("exclusions")):
        query += f" -{term}"
    return query


def _fetch_from_serpapi_live(
    criteria: dict[str, Any], topic: str, *, limit: int
) -> list[dict[str, Any]]:
    """Real SerpAPI call. Spends one search credit — gated by EXPERT_SOURCE_MODE=live.

    Isolated from the mock path so the credit-spending code is never reached by
    accident during dev or tests.
    """
    api_key = get_env("SERPAPI_KEY")
    # WARNING: SerpAPI free tier is ~100 searches/month. Each call is one search
    # credit. Runs only when the developer has set EXPERT_SOURCE_MODE=live.
    logger.warning("SerpAPI: LIVE mode — this spends 1 search (free tier ~100/month)")
    _serpapi_limiter.wait()

    query = _search_query(topic, criteria)
    logger.info("SerpAPI query: %s", query)
    try:
        response = httpx.get(
            "https://serpapi.com/search",
            params={"engine": "google", "q": query, "num": limit, "api_key": api_key},
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(f"API call failed: {e.response.status_code} - {e.response.text}")
        raise

    results = response.json().get("organic_results", [])
    # Store the clean topic, not the operator-laden query, on each candidate.
    return [_normalize_serp_result(r, topic) for r in results]


def _as_list(value: Any) -> list[str]:
    """Coerce a criteria field to a list of strings (mirrors the lead agent helper)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]
