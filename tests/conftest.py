"""Shared pytest fixtures and markers.

The suite is split into two tiers by marker so we never spend credits by accident:
- unmarked tests are pure logic and run anywhere, offline.
- `@pytest.mark.live` tests touch a real external service (Supabase, Groq) and are
  skipped unless RUN_LIVE_TESTS=1 is set in the environment.

Run offline (default):      pytest
Run everything incl. live:  RUN_LIVE_TESTS=1 pytest   (PowerShell: $env:RUN_LIVE_TESTS=1; pytest)
"""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: test hits a real external service (Supabase/Groq). Costs quota."
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip live tests unless explicitly opted in.

    Keeping the gate here (instead of inside each test) means a plain `pytest` run is
    always free and offline, which is what CI and routine dev should do.
    """
    if os.environ.get("RUN_LIVE_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="live test; set RUN_LIVE_TESTS=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
