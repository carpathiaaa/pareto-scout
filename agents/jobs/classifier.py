"""Reachability classification and message drafting for job-seeker candidates.

Unlike the lead/expert agents, the gate here is a reachability TIER (1-4), not a
score. Tier 1 means a real public email exists and the candidate is actionable; tiers
2-4 are stored but never sent. Two facts drive the tier and are decided in Python, not
by the LLM, so the actionable gate stays grounded:

  - tier 1 requires a non-empty contact_email that the source actually exposed.
  - Reddit candidates (reddit_discovery_only) can never be tier 1, by policy.

The LLM does the softer work: extract skills, confirm the role matches, and — for
candidates without an email — judge tier 2 vs 3 vs 4 from the available contact
signals. It also drafts a message, but only tier-1 candidates will ever use it.
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm import chat
from shared.utils import get_logger

logger = get_logger(__name__)

_TIER_MIN, _TIER_MAX = 1, 4


def _build_messages(
    candidate: dict[str, Any], criteria: dict[str, Any]
) -> list[dict[str, str]]:
    """Construct the chat messages for classifying one job-seeker candidate."""
    system = (
        "You analyze a job-seeker's public web presence. Extract their skills, decide "
        "if they match the target role, and assess how reachable they are. Return ONLY "
        "a JSON object with keys: skills (array of strings), matched_role (string), "
        "reachability_tier (integer: 2 = a contact form or DM path exists but no email; "
        "3 = a profile exists but no contact route; 4 = only a name/weak signal), and "
        "draft_message (string: warm, specific, under 90 words). Do NOT return tier 1 — "
        "tier 1 is assigned separately only when a real public email was found."
    )
    user = (
        f"Target criteria:\n{json.dumps(criteria, indent=2)}\n\n"
        f"Candidate:\n{json.dumps(_llm_view(candidate), indent=2)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _llm_view(candidate: dict[str, Any]) -> dict[str, Any]:
    """The subset of candidate fields the LLM should see (no internal flags)."""
    return {
        "name": candidate.get("name"),
        "platform": candidate.get("platform"),
        "profile_url": candidate.get("profile_url"),
        "raw_text": candidate.get("raw_text"),
        "has_email": bool(candidate.get("contact_email")),
    }


def classify_seeker(
    candidate: dict[str, Any], criteria: dict[str, Any]
) -> dict[str, Any]:
    """Classify reachability and draft outreach for one job-seeker candidate.

    Returns the candidate augmented with skills, matched_role, reachability_tier
    (1-4), contact_email (null below tier 1), and draft_message. Tier 1 is decided
    here in Python from email presence + the Reddit policy, never by the LLM.
    """
    has_email = bool(candidate.get("contact_email"))
    is_reddit = bool(candidate.get("reddit_discovery_only"))

    content = chat(
        _build_messages(candidate, criteria),
        temperature=0.4,
        max_tokens=400,
        json_mode=True,
    )
    try:
        parsed = json.loads(content)
        skills = list(parsed.get("skills") or [])
        matched_role = str(parsed.get("matched_role", "") or "")
        llm_tier = int(parsed.get("reachability_tier", 4))
        draft = str(parsed.get("draft_message", "") or "")
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning(
            "Classify: unparseable LLM response for %s; tier 4",
            candidate.get("profile_url"),
        )
        skills, matched_role, llm_tier, draft = [], "", 4, ""

    # The LLM is only trusted for tiers 2-4; clamp it out of tier 1's range.
    llm_tier = max(2, min(_TIER_MAX, llm_tier))

    # Tier 1 is a fact, not an opinion: a real email AND not a Reddit-discovery
    # candidate. Reddit can never be tier 1 even if an email somehow appeared.
    if has_email and not is_reddit:
        tier = 1
        email = candidate.get("contact_email")
    else:
        tier = llm_tier
        email = None  # contact_email is null for every tier below 1

    return {
        **candidate,
        "skills": skills,
        "matched_role": matched_role,
        "reachability_tier": tier,
        "contact_email": email,
        "draft_message": draft,
    }
