"""Candidate fetching for the jobs agent.

Two sources, both normalized to a stable candidate shape:
    {"name", "platform", "profile_url", "contact_email", "raw_text", "source"}

- SerpAPI "open to work" search across Wellfound/Contra/portfolio sites. A public
  email is extracted from the result text when present — that is the only way a
  candidate can become reachability tier 1.
- Reddit r/forhire, DISCOVERY ONLY. Reddit yields usernames, never emails, and never
  feeds outreach (CLAUDE.md). These candidates carry no email and are structurally
  barred from tier 1; the field `reddit_discovery_only=True` marks them so the
  classifier and run.py cannot promote them by accident.

Mock vs live is chosen by JOBS_SOURCE_MODE (default "mock"), mirroring the other
agents: mock loads fixtures and spends zero credits.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from shared.utils import RateLimiter, get_env, get_logger

logger = get_logger(__name__)

_FIXTURES = Path(__file__).parent / "fixtures"
_serpapi_limiter = RateLimiter(min_interval_seconds=1.0, name="serpapi-jobs")
_reddit_limiter = RateLimiter(min_interval_seconds=1.0, name="reddit")

CANDIDATE_KEYS = (
    "name",
    "platform",
    "profile_url",
    "contact_email",
    "raw_text",
    "source",
)

# Plain-text email matcher. We only ever read an email that the person published in a
# public result; we never guess or construct one.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _is_mock() -> bool:
    """True when sources should read fixtures instead of calling real APIs."""
    return get_env("JOBS_SOURCE_MODE", required=False, default="mock") == "mock"


def _load_fixture(name: str) -> dict[str, Any]:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _extract_email(text: str | None) -> str | None:
    """Return the first public email in the text, or None.

    A real, published email is the sole basis for tier 1, so this reads only what the
    source already exposed — it does not call any email-finder or build addresses.
    """
    if not text:
        return None
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else None


def _platform_from_url(url: str | None) -> str:
    """Coarse platform label from the profile URL host."""
    if not url:
        return "unknown"
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if "wellfound.com" in host:
        return "wellfound"
    if "contra.com" in host:
        return "contra"
    if "reddit.com" in host:
        return "reddit"
    return "portfolio" if host else "unknown"


def _normalize_serp_result(result: dict[str, Any]) -> dict[str, Any]:
    """Map one SerpAPI organic result to the normalized candidate shape."""
    url = result.get("link")
    text = result.get("snippet")
    return {
        "name": result.get("title"),
        "platform": _platform_from_url(url),
        "profile_url": url,
        "contact_email": _extract_email(text),
        "raw_text": text,
        "source": "serpapi",
        "reddit_discovery_only": False,
    }


def fetch_open_to_work(
    criteria: dict[str, Any], *, limit: int = 20
) -> list[dict[str, Any]]:
    """Fetch 'open to work' candidates via SerpAPI (or its fixture in mock mode)."""
    if _is_mock():
        logger.info("SerpAPI(jobs): mock mode, loading fixture (0 searches spent)")
        raw = _load_fixture("serpapi_jobs_sample.json")
        return [_normalize_serp_result(r) for r in raw.get("organic_results", [])]

    return _fetch_open_to_work_live(criteria, limit=limit)


# Bias the search toward individual job-seekers and away from job boards. The first
# live run returned Indeed/Upwork/ZipRecruiter listing pages (employers hiring), not
# people open to work, because "open to work" matches both. Profile sites surface
# individuals; the negative site filters exclude the commercial aggregators.
_SEEKER_SITES = (
    "(site:contra.com OR site:read.cv OR site:behance.net OR site:wellfound.com)"
)
_JOB_BOARD_EXCLUDES = (
    "-site:indeed.com -site:upwork.com -site:ziprecruiter.com "
    "-site:glassdoor.com -site:linkedin.com/jobs"
)


def _flatten(value: Any) -> str:
    """Render a criteria field (str | list | None) as a plain space-joined string.

    Parsed fields come back as lists (e.g. ['product designers']); str() on a list
    would leak brackets into the query. This flattens them to clean search terms.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    return str(value)


def _job_query(criteria: dict[str, Any]) -> str:
    """Build the people-biased search string from parsed jobs criteria."""
    base = " ".join(
        _flatten(criteria.get(k))
        for k in ("target_role_or_skills", "seniority", "location")
    ).strip()
    intent = '("open to work" OR "available for hire")'
    return f"{base} {intent} {_SEEKER_SITES} {_JOB_BOARD_EXCLUDES}".strip()


def _fetch_open_to_work_live(
    criteria: dict[str, Any], *, limit: int
) -> list[dict[str, Any]]:
    """Real SerpAPI call. Spends one search credit — gated by JOBS_SOURCE_MODE=live."""
    api_key = get_env("SERPAPI_KEY")
    logger.warning(
        "SerpAPI(jobs): LIVE mode — this spends 1 search (free tier ~100/month)"
    )
    _serpapi_limiter.wait()

    query = _job_query(criteria)
    logger.info("SerpAPI(jobs) query: %s", query)
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
    return [_normalize_serp_result(r) for r in results]


def _normalize_reddit_post(child: dict[str, Any]) -> dict[str, Any]:
    """Map one r/forhire post to the candidate shape, marked discovery-only.

    contact_email is always None and reddit_discovery_only is always True: Reddit
    gives a username and a post, never an email, and must never feed outreach. These
    invariants are enforced here so they cannot be lost downstream.
    """
    data = child.get("data", {})
    permalink = data.get("permalink") or ""
    return {
        "name": data.get("author"),
        "platform": "reddit",
        "profile_url": f"https://www.reddit.com{permalink}" if permalink else None,
        "contact_email": None,
        "raw_text": data.get("title"),
        "source": "reddit",
        "reddit_discovery_only": True,
    }


def fetch_reddit_forhire(*, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch r/forhire posts for DISCOVERY ONLY (or its fixture in mock mode).

    Never a source of emails or outreach. Results are capped below tier 1 downstream.
    """
    if _is_mock():
        logger.info("Reddit: mock mode, loading fixture (discovery only)")
        raw = _load_fixture("reddit_forhire_sample.json")
        children = raw.get("data", {}).get("children", [])
        return [_normalize_reddit_post(c) for c in children]

    return _fetch_reddit_forhire_live(limit=limit)


def _fetch_reddit_forhire_live(*, limit: int) -> list[dict[str, Any]]:
    """Real Reddit public JSON read. No credits, but discovery-only by policy."""
    logger.warning("Reddit: LIVE mode — DISCOVERY ONLY, never used for outreach")
    _reddit_limiter.wait()
    try:
        response = httpx.get(
            "https://www.reddit.com/r/forhire/new.json",
            params={"limit": limit},
            headers={"User-Agent": "pareto-scout/0.1 (jobs agent; discovery only)"},
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(f"API call failed: {e.response.status_code} - {e.response.text}")
        raise

    children = response.json().get("data", {}).get("children", [])
    return [_normalize_reddit_post(c) for c in children]
