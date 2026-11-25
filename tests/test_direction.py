import json
from collections.abc import Callable

import pytest

from septa_detours.model import Direction
from septa_detours.parse.direction import find_directions, normalize_direction

OLD = "2026-11-25T025344Z"
NEW = "2026-11-25T121123Z"


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


@pytest.mark.parametrize(
    ("stamp", "route_id", "index", "expected"),
    [
        (OLD, "bus_route_55", 0, ("SB",)),  # clean baseline
        (OLD, "bus_route_2", 2, ("SB",)),
        (OLD, "rr_route_mfo", 0, ("WB",)),  # "W/B via JFK,,"
        (OLD, "rr_route_mfo", 1, ("EB",)),
        (OLD, "bus_route_64", 3, ("EB",)),  # "..., Eastbound" at the end
        (OLD, "bus_route_64", 4, ("WB",)),  # "..., Westbound"
        (OLD, "bus_route_24", 0, ("NB",)),  # "NB Via ... Recover NB On"
        (OLD, "rr_route_bso", 0, ("SB",)),  # "11:59pm SB," after the time
        (OLD, "rr_route_bso", 1, ("NB",)),
        (OLD, "bus_route_44", 0, ("EB",)),  # direction before the location
        (OLD, "bus_route_49", 3, ("NB",)),  # "Discontinue the transit stop, NB on"
        (NEW, "bus_route_31", 6, ("WB",)),
        (NEW, "bus_route_124", 2, ("WB",)),
        # No direction at all.
        (OLD, "bus_route_24", 1, ()),  # "Via Huntingdon Pke"
        (OLD, "bus_route_6", 0, ()),  # discontinued stop
    ],
)
def test_fixture_messages(
    read_alert_fixture: Callable[[str], bytes],
    stamp: str,
    route_id: str,
    index: int,
    expected: tuple[Direction, ...],
) -> None:
    route = json.loads(read_alert_fixture(f"{stamp}__{route_id}.json"))
    assert find_directions(route["detour"][index]["message"]) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # Distinct directions, in first-appearance order (never sorted).
        ("SB via Broad, Recover NB on 15th", ("SB", "NB")),
        ("WB via Arch, then EB via Market", ("WB", "EB")),
        # Repeats keep their first position.
        ("NB via 16th, SB via 17th, NB again", ("NB", "SB")),
        # Different spellings of one direction are one direction.
        ("WB via JFK, Westbound, W/B, wb", ("WB",)),
        # Punctuation of every kind separates tokens.
        ("Until 11:59pm SB,", ("SB",)),
        ("(EB)", ("EB",)),
        ("Reg Rt-NB.", ("NB",)),
        ("L-Fairmount,EB:Broad", ("EB",)),
        ("NB\tvia\nBroad", ("NB",)),
        ("Until 12/31/26 W/B,, Left on Vine", ("WB",)),
        ("nb via Broad", ("NB",)),  # case ignored, as in normalize_direction
    ],
)
def test_finds_directions(message: str, expected: tuple[Direction, ...]) -> None:
    assert find_directions(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "",
        " , ,, ",
        # Words containing a spelling.
        "Left on Webster St, Right on Ebony Ave",
        "Via NBC Plaza",
        # Slashes elsewhere stay inside one token.
        "Gloria Dei Tower/Manor, Trips Only/ JFK/17th 12/31/26",
        # Split forms are not directions.
        "S.B. via Broad",
        "W / B via JFK",
        # Known gap: a slash between two directions is one token.
        "NB/SB via Broad",
    ],
)
def test_finds_nothing(message: str) -> None:
    assert find_directions(message) == ()
