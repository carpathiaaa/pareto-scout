"""LLM scoring and message drafting for lead candidates.

One LLM call per lead returns both a fit_score and a draft_message, so the score and
the message stay consistent and we spend half the Groq budget two calls would cost.
The function is pure (candidate + criteria in, enriched dict out) so it is unit-
testable by stubbing shared.llm.chat — no network in tests.
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm import chat
from shared.utils import get_logger

logger = get_logger(__name__)

# Clamp bounds for the score the model returns; defends against out-of-range values
# since llama-3.3 is best-effort JSON, not strict-schema.
_SCORE_MIN, _SCORE_MAX = 0, 100


def _build_messages(
    candidate: dict[str, Any], criteria: dict[str, Any]
) -> list[dict[str, str]]:
    """Construct the chat messages for scoring + drafting one candidate.

    Static instructions go first and dynamic data last, which is the ordering Groq's
    prompt cache rewards and keeps the variable part isolated at the tail.
    """
    system = (
        "You score B2B sales leads against a target profile and draft one short "
        "outreach email. 'Good' means fit to the provided criteria only — there is no "
        "other ideal. Return ONLY a JSON object with keys: "
        "fit_score (integer 0-100) and draft_message (string). The message must be "
        "direct, value-first, professional, under 90 words, reference the person's "
        "role and company, and never sound like spam."
    )
    user = (
        f"Target criteria:\n{json.dumps(criteria, indent=2)}\n\n"
        f"Lead:\n{json.dumps(candidate, indent=2)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def enrich_lead(candidate: dict[str, Any], criteria: dict[str, Any]) -> dict[str, Any]:
    """Score a candidate and draft its outreach message in one LLM call.

    Args:
        candidate: A normalized candidate dict from sources.py.
        criteria: The parsed lead fields for this run (the scoring rubric).

    Returns:
        The candidate dict augmented with fit_score (int) and draft_message (str).
        On a malformed model response, fit_score is 0 and draft_message is empty, so a
        bad parse degrades to "won't pass threshold" rather than crashing the run.
    """
    messages = _build_messages(candidate, criteria)
    # temperature 0.4: a little warmth for the draft, still mostly stable on score.
    content = chat(messages, temperature=0.4, max_tokens=400, json_mode=True)

    try:
        parsed = json.loads(content)
        score = int(parsed.get("fit_score", 0))
        draft = str(parsed.get("draft_message", "") or "")
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning(
            "Enrich: unparseable LLM response for %s; scoring 0", candidate.get("email")
        )
        score, draft = 0, ""

    score = max(_SCORE_MIN, min(_SCORE_MAX, score))
    return {**candidate, "fit_score": score, "draft_message": draft}
