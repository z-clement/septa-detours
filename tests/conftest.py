"""Shared test helpers, as pytest fixtures.

``tests/`` has no ``__init__.py``, so test modules can't import from each
other; anything shared lives here as a fixture (a callable, if it needs
arguments).

- Saved real alerts in ``fixtures/alerts/``.
- Hand-built GTFS ``routes`` frames (real GTFS is not committed).
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

ALERT_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "alerts"

# Must match what ``load.load_routes`` returns (column order and dtypes).
ROUTES_SCHEMA = {
    "route_id": pl.String,
    "route_short_name": pl.String,
    "route_long_name": pl.String,
    "route_type": pl.Int16,
    "route_color": pl.String,
    "route_text_color": pl.String,
    "feed": pl.String,
}


@pytest.fixture
def routes_from_ids() -> Callable[[list[tuple[str, str]]], pl.DataFrame]:
    """Return a builder: ``(feed, route_id)`` pairs -> a ``routes`` frame.

    For code that reads only ``feed`` and ``route_id`` (``match/``). Other
    columns get placeholders: short name = ``route_id``, type 3 (bus),
    colors ``EF3340``/``FFFFFF``. Rows keep the given order.
    """

    def build(rows: list[tuple[str, str]]) -> pl.DataFrame:
        full_rows = [
            (route_id, route_id, "Somewhere", 3, "EF3340", "FFFFFF", feed)
            for feed, route_id in rows
        ]
        return pl.DataFrame(full_rows, schema=ROUTES_SCHEMA, orient="row")

    return build


@pytest.fixture
def read_alert_fixture() -> Callable[[str], bytes]:
    """Return a loader: fixture file name -> its raw bytes.

    Takes the full name, e.g. ``"2026-11-25T025344Z__bus_route_55.json"``,
    so a typo fails loudly with ``FileNotFoundError``.
    """

    def read(name: str) -> bytes:
        return (ALERT_FIXTURE_DIR / name).read_bytes()

    return read


@pytest.fixture
def alert_fixture_names() -> list[str]:
    """Every alert fixture file name, sorted (README.md excluded)."""
    return sorted(path.name for path in ALERT_FIXTURE_DIR.glob("*.json"))
