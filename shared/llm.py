"""Provider-agnostic LLM wrapper.

Every LLM call in the system goes through this module. Agents never import the
`openai` SDK directly, so swapping Groq for a paid Gemini or Claude key is a config
change (LLM_BASE_URL / LLM_API_KEY / LLM_MODEL), not a code change. See DECISIONS.md
2026-05-31 for why the OpenAI-compatible SDK was chosen over the groq SDK.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from openai import OpenAI

from shared.utils import RateLimiter, get_env, get_logger

logger = get_logger(__name__)

# Groq free tier is 30 requests/minute at the org level. One call per second leaves
# headroom and, more importantly, prevents bursts that trip the per-minute ceiling.
_limiter = RateLimiter(min_interval_seconds=1.0, name="llm")

# The structured fields each agent expects from a parsed query, straight from
# CLAUDE.md's "Parsed fields by agent" table. Kept here so the parser and the agents
# agree on one contract.
AGENT_FIELDS: dict[str, list[str]] = {
    "lead": [
        "target_type",  # "company" or "person"
        "industry",
        "role_or_seniority",
        "focus_keywords",
        "exclusions",
        "location",
    ],
    "expert": [
        "field_or_domain",
        "topic_or_specialty",
        "credibility_signals",
        "exclusions",
    ],
    "jobs": [
        "target_role_or_skills",
        "seniority",
        "location",
    ],
}


@lru_cache(maxsize=1)
def get_llm_client() -> OpenAI:
    """Return a cached OpenAI-SDK client pointed at the configured provider.

    base_url and api_key come from env so the provider is swappable. Cached because
    the client is stateless and reusable across a run.

    Returns:
        A configured OpenAI client (talking to Groq by default).
    """
    base_url = get_env("LLM_BASE_URL")
    api_key = get_env("LLM_API_KEY")
    logger.info("Creating LLM client (base_url=%s)", base_url)
    return OpenAI(base_url=base_url, api_key=api_key)


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    json_mode: bool = False,
) -> str:
    """Run a chat completion and return the assistant's text.

    The single choke point for LLM traffic: it enforces the rate limit and reads the
    model from config so no caller hardcodes it. Low default temperature suits the
    system's work (scoring, extraction, classification) where consistency beats
    creativity; drafting callers can raise it.

    Args:
        messages: OpenAI-style role/content dicts.
        temperature: Sampling temperature. Default 0.3 for deterministic-ish output.
        max_tokens: Cap on completion length. Keep tight to respect tokens/minute.
        json_mode: If True, ask the provider to constrain output to a JSON object.

    Returns:
        The assistant message content as a string.
    """
    _limiter.wait()
    model = get_env("LLM_MODEL")
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        # response_format json_object is the portable structured-output mode shared by
        # Groq and OpenAI. We still validate/parse on our side (see parse_query_to_fields).
        kwargs["response_format"] = {"type": "json_object"}
    response = get_llm_client().chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def parse_query_to_fields(raw_query: str, agent_type: str) -> dict[str, Any]:
    """Turn a plain-language search request into the agent's structured fields.

    This is the one LLM call behind the UI's confirm step: it converts free text into
    editable fields so a human can correct a misread before any paid source is hit.
    JSON mode plus an explicit key list makes the output reliable enough to render
    straight into a form.

    Args:
        raw_query: What the developer typed, e.g. "fintech founders in SE Asia".
        agent_type: One of "lead", "expert", "jobs".

    Returns:
        A dict containing exactly the keys in AGENT_FIELDS[agent_type]. Missing values
        come back as null/empty rather than being dropped, so the form is stable.

    Raises:
        ValueError: If agent_type is unknown or the model returns unparseable JSON.
    """
    if agent_type not in AGENT_FIELDS:
        raise ValueError(f"Unknown agent_type {agent_type!r}; expected one of {list(AGENT_FIELDS)}")

    fields = AGENT_FIELDS[agent_type]
    system = (
        "You extract structured search criteria from a recruiter's plain-language "
        "request. Return ONLY a JSON object with exactly these keys: "
        f"{', '.join(fields)}. Use null for anything the request does not specify. "
        "List-like fields (keywords, exclusions, skills) must be arrays of strings."
    )
    content = chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": raw_query},
        ],
        temperature=0.0,  # extraction must be repeatable
        max_tokens=512,
        json_mode=True,
    )

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error("LLM returned non-JSON for query parse: %s", content)
        raise ValueError("Could not parse LLM response as JSON") from e

    # Guarantee a stable shape: every expected key present, extras dropped.
    return {field: parsed.get(field) for field in fields}
