import pytest

from septa_detours.model import Direction
from septa_detours.parse.direction import normalize_direction


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        # Every spelling in the fixtures (snapshot 2026-11-25T025344Z).
        ("NB", "NB"),
        ("SB", "SB"),
        ("EB", "EB"),
        ("WB", "WB"),
        ("W/B", "WB"),  # rr_route_mfo #0
        ("Eastbound", "EB"),  # bus_route_64 #3
        ("Westbound", "WB"),  # bus_route_64 #4
    ],
)
def test_real_spellings(token: str, expected: Direction) -> None:
    assert normalize_direction(token) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("N/B", "NB"),
        ("S/B", "SB"),
        ("E/B", "EB"),
        ("Northbound", "NB"),
        ("Southbound", "SB"),
    ],
)
def test_unseen_forms_of_seen_patterns(token: str, expected: Direction) -> None:
    """Each pattern covers all four directions, not just those seen so far."""
    assert normalize_direction(token) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("nb", "NB"),
        ("Sb", "SB"),
        ("eB", "EB"),
        ("w/b", "WB"),
        ("W/b", "WB"),
        ("EASTBOUND", "EB"),
        ("westbound", "WB"),
        ("sOuThBoUnD", "SB"),
    ],
)
def test_case_is_ignored(token: str, expected: Direction) -> None:
    assert normalize_direction(token) == expected


@pytest.mark.parametrize(
    "token",
    [
        "",
        # Attached punctuation or whitespace: the tokenizer strips these.
        "SB,",  # as in rr_route_bso "11:59pm SB,"
        ",NB",
        "Eastbound.",
        " WB",
        "NB ",
        # Words containing a spelling.
        "Webster",
        "Ebony",
        "NBC",
        "SBX",
        "Westbounds",
        # Partial or broken forms.
        "N",
        "B",
        "W/",
        "/B",
        "W / B",
        "W//B",
        "N.B.",
        "S B",
        "East",
        "bound",
        # Directions outside the model.
        "inbound",
        "outbound",
        "NEB",
    ],
)
def test_non_directions_are_none(token: str) -> None:
    assert normalize_direction(token) is None
