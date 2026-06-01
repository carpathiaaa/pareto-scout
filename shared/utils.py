"""Cross-cutting helpers: env loading, logging, rate limiting, dedup.

Everything that more than one agent needs but that is not the database or the LLM
lives here. Importing this module loads the .env file once as a side effect, so any
module that calls get_env gets a populated environment without repeating dotenv setup.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Iterable, TypeVar

from dotenv import load_dotenv
import os

# Load .env from the repo root exactly once, at import time. find_dotenv would also
# work, but an explicit path makes the source obvious and avoids surprises if the
# process is launched from a subdirectory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")

T = TypeVar("T")


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


def get_env(name: str, *, required: bool = True, default: str | None = None) -> str | None:
    """Read an environment variable through the one sanctioned entry point.

    CLAUDE.md forbids reading os.environ ad hoc so that every required key is
    validated the same way and missing config fails loudly instead of as a None
    surfacing deep in a request.

    Args:
        name: The variable name, e.g. "LLM_API_KEY".
        required: If True, a missing or empty value raises ConfigError.
        default: Value returned when the variable is unset and not required.

    Returns:
        The variable's value, or default when unset and not required.

    Raises:
        ConfigError: If required and the variable is missing or empty.
    """
    value = os.environ.get(name)
    if value is None or value == "":
        if required:
            raise ConfigError(f"Required environment variable {name} is not set")
        return default
    return value


def get_logger(name: str) -> logging.Logger:
    """Return a module logger with a sane default handler.

    Using a shared configurator keeps log format consistent across agents and
    honors the "never print()" rule. Idempotent: repeated calls do not stack
    handlers.

    Args:
        name: Usually __name__ of the calling module.

    Returns:
        A configured Logger.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


_rate_log = get_logger(__name__)


class RateLimiter:
    """Enforce a minimum interval between calls to one external service.

    A per-instance limiter (one per API) is simpler and safer than a global clock:
    Apollo and Hunter have unrelated limits, so they should not throttle each other.
    Thread-safe so the FastAPI trigger can run agents concurrently without two
    requests racing past the gate.

    CLAUDE.md mandates a default of 1 second between calls to any external API
    unless its docs allow faster.
    """

    def __init__(self, min_interval_seconds: float = 1.0, *, name: str = "api") -> None:
        """Create a limiter.

        Args:
            min_interval_seconds: Minimum seconds between successive wait() returns.
            name: Label used in warning logs, e.g. "apollo".
        """
        self._min_interval = min_interval_seconds
        self._name = name
        self._lock = threading.Lock()
        self._last_call: float = 0.0

    def wait(self) -> None:
        """Block until at least min_interval has passed since the last call."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                sleep_for = self._min_interval - elapsed
                _rate_log.debug("%s rate limiter sleeping %.2fs", self._name, sleep_for)
                time.sleep(sleep_for)
            self._last_call = time.monotonic()


def warn_if_near_limit(
    used: int, limit: int, *, label: str, threshold: float = 0.8
) -> None:
    """Log a warning when usage of a finite quota crosses a threshold.

    Free-tier credits (Apollo emails, Hunter searches, SerpAPI calls) are scarce.
    Surfacing the approach to a limit early is required by CLAUDE.md so the developer
    is never surprised by an exhausted quota mid-run.

    Args:
        used: Credits or calls consumed so far.
        limit: The known ceiling.
        label: Human label, e.g. "Apollo email credits".
        threshold: Fraction of limit at which to warn (default 0.8).
    """
    if limit <= 0:
        return
    if used / limit >= threshold:
        _rate_log.warning(
            "%s at %d/%d (%.0f%% of free tier)", label, used, limit, 100 * used / limit
        )


def dedup_by(items: Iterable[T], key) -> list[T]:
    """Return items with duplicates removed, keeping first occurrence order.

    Agents may re-run on overlapping source pages, so candidate lists need a stable
    dedup before they hit the database. Keying on a caller-supplied function lets the
    same helper dedup leads by email and job seekers by profile URL.

    Args:
        items: The candidates to dedup.
        key: Callable mapping an item to its dedup key. Items whose key is falsy
            (e.g. None email) are kept as-is, since they are not true duplicates.

    Returns:
        A new list with duplicates removed.
    """
    seen: set = set()
    out: list[T] = []
    for item in items:
        k = key(item)
        if not k:
            out.append(item)
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out
