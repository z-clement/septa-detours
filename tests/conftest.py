"""Shared test helpers: access to the saved real alerts in fixtures/alerts/."""

from collections.abc import Callable
from pathlib import Path

import pytest

ALERT_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "alerts"


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
