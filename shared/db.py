"""Supabase access, pinned to the `agency` schema.

Every agent writes through this module so the schema target and the upsert-not-insert
rule live in exactly one place. Reading or writing `public` from an agent is a bug;
this client defaults to `agency` so that mistake is hard to make.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from supabase import Client, create_client
from supabase.client import ClientOptions

from shared.utils import get_env, get_logger

logger = get_logger(__name__)

# Tables the agents own. Centralized so callers reference names through one source.
LEADS = "leads"
EXPERTS = "experts"
JOB_SEEKERS = "job_seekers"
OUTREACH_LOG = "outreach_log"
SEARCH_RUNS = "search_runs"


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Return a process-wide Supabase client bound to the `agency` schema.

    Cached so we reuse one client (and its connection pool) across an agent run
    rather than reconstructing it per call. Uses the service-role key because agents
    run server-side and must write all tables; this key must never reach the browser.

    The schema is set in ClientOptions so every .table(...) call targets `agency`
    without each caller remembering to qualify it.

    Returns:
        A configured supabase Client.
    """
    url = get_env("SUPABASE_URL")
    key = get_env("SUPABASE_SERVICE_ROLE_KEY")
    logger.info("Creating Supabase client for agency schema")
    return create_client(url, key, options=ClientOptions(schema="agency"))


def upsert(table: str, rows: list[dict[str, Any]], *, on_conflict: str | None = None) -> list[dict[str, Any]]:
    """Upsert rows into an `agency` table and return the stored records.

    CLAUDE.md mandates upsert over insert because agents re-run on overlapping data;
    a plain insert would raise on the unique constraints (leads.email,
    job_seekers.profile_url). on_conflict names the conflict target so a re-run
    updates the existing row instead of erroring.

    Args:
        table: One of the table-name constants in this module.
        rows: Records to write. Empty list is a no-op.
        on_conflict: Column(s) forming the unique key, e.g. "email". Omit for tables
            without a natural unique key (experts, outreach_log, search_runs).

    Returns:
        The upserted rows as returned by Supabase (empty list if rows was empty).
    """
    if not rows:
        return []
    query = get_client().table(table).upsert(rows, on_conflict=on_conflict)
    response = query.execute()
    logger.info("Upserted %d row(s) into %s", len(rows), table)
    return response.data


def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Insert a single row and return it.

    Used for append-only tables that have no natural unique key and should never be
    de-duplicated: search_runs (one row per run) and outreach_log (one row per send
    attempt). Everything else goes through upsert.

    Args:
        table: One of the append-only table constants (SEARCH_RUNS, OUTREACH_LOG).
        row: The record to insert.

    Returns:
        The inserted row, including server-generated id and timestamps.
    """
    response = get_client().table(table).insert(row).execute()
    logger.info("Inserted 1 row into %s", table)
    return response.data[0]


def count_rows(table: str) -> int:
    """Return the row count for a table (used by the /check-db workflow).

    Args:
        table: One of the table-name constants.

    Returns:
        The number of rows currently in the table.
    """
    response = get_client().table(table).select("id", count="exact").execute()
    return response.count or 0
