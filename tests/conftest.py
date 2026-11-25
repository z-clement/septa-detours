"""Shared test helpers, as pytest fixtures.

``tests/`` has no ``__init__.py``, so test modules can't import from each
other; anything shared lives here as a fixture (a callable, if it needs
arguments).

- Saved real alerts in ``fixtures/alerts/``.
- Hand-built GTFS ``routes``, ``trips`` and ``directions`` frames (real
  GTFS is not committed), with the same columns and dtypes as the loaders.
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


# Must match what ``load.load_trips`` returns (column order and dtypes).
TRIPS_SCHEMA = {
    "route_id": pl.String,
    "service_id": pl.String,
    "trip_id": pl.String,
    "trip_headsign": pl.String,
    "direction_id": pl.Int8,
    "shape_id": pl.String,
    "feed": pl.String,
}


@pytest.fixture
def trips_from_rows() -> Callable[[list[tuple[str, str, int, str]]], pl.DataFrame]:
    """Return a builder: ``(feed, route_id, direction_id, shape_id)`` -> trips.

    One trip per row; ``trip_id`` is unique per row (as in real data),
    ``service_id``/``trip_headsign`` are placeholders.
    """

    def build(rows: list[tuple[str, str, int, str]]) -> pl.DataFrame:
        full_rows = [
            (route_id, "WKDY", f"trip{i}", "Somewhere", direction_id, shape_id, feed)
            for i, (feed, route_id, direction_id, shape_id) in enumerate(rows)
        ]
        return pl.DataFrame(full_rows, schema=TRIPS_SCHEMA, orient="row")

    return build


# Must match what ``load.load_directions`` returns (column order and dtypes).
DIRECTIONS_SCHEMA = {
    "route_id": pl.String,
    "direction_id": pl.Int8,
    "direction": pl.String,
    "direction_destination": pl.String,
    "feed": pl.String,
}


@pytest.fixture
def directions_from_rows() -> Callable[
    [list[tuple[str, str, int, str | None]]], pl.DataFrame
]:
    """Return a builder: ``(feed, route_id, direction_id, direction)`` -> frame.

    ``direction_destination`` is a placeholder (``match/`` doesn't read it).
    """

    def build(rows: list[tuple[str, str, int, str | None]]) -> pl.DataFrame:
        full_rows = [
            (route_id, direction_id, direction, "Somewhere", feed)
            for feed, route_id, direction_id, direction in rows
        ]
        return pl.DataFrame(full_rows, schema=DIRECTIONS_SCHEMA, orient="row")

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
