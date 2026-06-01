"""LLM credibility scoring and message drafting for expert candidates.

One LLM call per candidate returns both a score (0-100) and a draft_message, so the
score and message stay consistent and we spend half the Groq budget two calls would
cost. Pure function (candidate + criteria in, scored dict out) so it unit-tests by
stubbing shared.llm.chat — no network.

Distinct from the lead enricher in what it judges: credibility/authority on the topic
(publications, stars, talks, seniority) and whether the result is even a person —
SerpAPI returns listicles and ads, which must score low.
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm import chat
from shared.utils import get_logger

logger = get_logger(__name__)

_SCORE_MIN, _SCORE_MAX = 0, 100


def _build_messages(
    candidate: dict[str, Any], criteria: dict[str, Any]
) -> list[dict[str, str]]:
    """Construct the chat messages for scoring + drafting one expert candidate.

    Static instructions first, dynamic candidate data last — the ordering Groq's
    prompt cache rewards and which isolates the variable part at the tail.
    """
    system = (
        "You assess whether a web search result is a credible subject-matter expert "
        "on the target topic, and draft one short outreach message. Score 0-100 on "
        "demonstrated authority: publications, citations, open-source impact, talks, "
        "seniority, and clear focus on the topic. Score near 0 if the result is not a "
        "person (a listicle, ad, or roundup) or is only a beginner. Honor the "
        "credibility_signals and exclusions in the criteria. Return ONLY a JSON object "
        "with keys: score (integer 0-100), refined_name (string: the expert's name, or "
        "empty if not a person), and draft_message (string: direct, respectful, "
        "references their specific work, under 90 words, never spammy)."
    )
    user = (
        f"Target criteria:\n{json.dumps(criteria, indent=2)}\n\n"
        f"Search result:\n{json.dumps(candidate, indent=2)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def score_expert(candidate: dict[str, Any], criteria: dict[str, Any]) -> dict[str, Any]:
    """Score one expert candidate and draft its outreach in a single LLM call.

    Args:
        candidate: A normalized candidate dict from sources.py.
        criteria: The parsed expert fields for this run (the scoring rubric).

    Returns:
        The candidate augmented with score (int), draft_message (str), and a possibly
        refined name. A malformed model response degrades to score 0 / empty draft so
        a bad parse drops below threshold rather than crashing the run.
    """
    messages = _build_messages(candidate, criteria)
    content = chat(messages, temperature=0.4, max_tokens=400, json_mode=True)

    try:
        parsed = json.loads(content)
        score = int(parsed.get("score", 0))
        draft = str(parsed.get("draft_message", "") or "")
        refined = str(parsed.get("refined_name", "") or "").strip()
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning(
            "Score: unparseable LLM response for %s; scoring 0", candidate.get("url")
        )
        score, draft, refined = 0, "", ""

    score = max(_SCORE_MIN, min(_SCORE_MAX, score))
    # Keep the LLM's cleaned-up name when it gave one; otherwise keep the raw title.
    name = refined or candidate.get("name")
    return {**candidate, "name": name, "score": score, "draft_message": draft}
