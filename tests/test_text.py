import json
from collections.abc import Callable

import pytest
from pydantic import TypeAdapter

from septa_detours.model import CleanText
from septa_detours.parse.text import clean_text

CLEAN_TEXT = TypeAdapter(CleanText)
TEXT_FIELDS = ("location_start", "location_end", "reason")
NBSP = "\u00a0"  # non-breaking space; common in text pasted from web pages


@pytest.mark.parametrize("raw", ["", " ", "   ", "\t\n", NBSP, f" {NBSP}\t "])
def test_blank_is_none(raw: str) -> None:
    assert clean_text(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Real values from the fixtures.
        ("Construction ", "Construction"),
        ("22nd  &  Chestnut", "22nd & Chestnut"),
        ("JFK Between  17th & 30th  Streets", "JFK Between 17th & 30th Streets"),
        ("Thanksgiving  Day Setup", "Thanksgiving Day Setup"),
        # Leading, and both ends.
        ("  17th & Washington", "17th & Washington"),
        ("  Broad St  ", "Broad St"),
        # Whitespace other than plain spaces, at the ends and inside.
        ("Broad\tSt\n", "Broad St"),
        (f"{NBSP}Broad{NBSP} St{NBSP}", "Broad St"),
    ],
)
def test_trims_and_collapses(raw: str, expected: str) -> None:
    assert clean_text(raw) == expected


@pytest.mark.parametrize("raw", ["17th & Washington", "Contractor", "X"])
def test_clean_text_is_unchanged(raw: str) -> None:
    assert clean_text(raw) == raw


def test_every_fixture_text_field_becomes_clean_text_or_none(
    read_alert_fixture: Callable[[str], bytes],
    alert_fixture_names: list[str],
) -> None:
    """Over all real values: None only for blank input, else valid and collapsed."""
    checked = 0
    for name in alert_fixture_names:
        route = json.loads(read_alert_fixture(name))
        for detour in route["detour"]:
            for field in TEXT_FIELDS:
                raw = detour[field]
                cleaned = clean_text(raw)
                checked += 1
                if raw.strip() == "":
                    assert cleaned is None, (name, field, raw)
                else:
                    assert cleaned is not None, (name, field, raw)
                    assert CLEAN_TEXT.validate_python(cleaned) == cleaned
                    assert "  " not in cleaned, (name, field, raw)
    # Guard against the loop silently checking nothing (e.g. a bad glob).
    assert checked > 0
