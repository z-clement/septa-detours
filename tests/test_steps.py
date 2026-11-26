"""Tests for parse/steps.py: a detour's path from its message.

Messages are real (verbatim from the 2026-11-25 snapshots) unless a test
says it's hand-built.
"""

import re

import pytest

from septa_detours.model import Step
from septa_detours.parse.steps import MAX_STREET_WORDS, parse_route_steps

ROUTE_2 = (
    "7am - 4pm Mon thru Fri, 11/27/26, SB via 17th, Left on Washington, "
    "Right on Broad, Right on Passyunk, Left on 17th, Reg Rt"
)


def pairs(message: str) -> list[tuple[str, str]]:
    """The parsed steps as ``(turn, street)`` pairs, for whole comparisons."""
    return [(step.turn, step.street) for step in parse_route_steps(message)]


def test_route_2_whole_path() -> None:
    assert pairs(ROUTE_2) == [
        ("via", "17th"),
        ("left", "Washington"),
        ("right", "Broad"),
        ("right", "Passyunk"),
        ("left", "17th"),
    ]


def test_returns_steps() -> None:
    steps = parse_route_steps(ROUTE_2)
    assert isinstance(steps, tuple)
    assert steps[1] == Step(turn="left", street="Washington")


def test_short_turn_forms_and_split_names() -> None:
    message = (
        "3pm - 2am 11/25/26, - 11/26/26, SB via Pennsylvania, L-Fairmount "
        "R--23rd L-, Spring Garden R-Broad, Right on Arch L-15th L-S. Penn, "
        "Sq, Right on Broad R-Walnut L-, 23rd, Reg Rt"
    )
    assert pairs(message) == [
        ("via", "Pennsylvania"),
        ("left", "Fairmount"),
        ("right", "23rd"),
        ("left", "Spring Garden"),
        ("right", "Broad"),
        ("right", "Arch"),
        ("left", "15th"),
        ("left", "S. Penn Sq"),
        ("right", "Broad"),
        ("right", "Walnut"),
        ("left", "23rd"),
    ]


def test_spaced_short_turn_and_comma_after_on() -> None:
    message = (
        "Until 2am on Thurs 11/26/26, NB via 16th St, Right on Locust St, "
        "Left on Broad St, Right on S Penn Sq,L - JFK Blvd, Right on Broad "
        "St, Right on Vine St, Left on 13th St, Left on Vine St, Right on, "
        "16th St, Reg Rt"
    )
    assert pairs(message)[3:5] == [("right", "S Penn Sq"), ("left", "JFK Blvd")]
    assert pairs(message)[-1] == ("right", "16th St")


def test_parenthesized_aside_is_dropped() -> None:
    message = (
        "Until 1159 pm on 11/24/26, SB via Broad, Right on W Moyamensing Ave, "
        "Left on  Oregon Ave, Right on S 10th St, Right on Bigler St (slow, "
        "operation), Right on S Broad St, Reg Rt"
    )
    assert pairs(message)[-2:] == [("right", "Bigler St"), ("right", "S Broad St")]


def test_leading_dash_after_via() -> None:
    message = (
        "7am - 4pm Weekdays until, 12/4/26, WB via - Rockwell Ave, Left on "
        "Rhawn St, Left on Oxford Ave, Reg Rt"
    )
    assert pairs(message) == [
        ("via", "Rockwell Ave"),
        ("left", "Rhawn St"),
        ("left", "Oxford Ave"),
    ]


def test_reg_rte_and_text_after_reg_rt() -> None:
    rte = (
        "Until 8am 11/25/26, NB via 16th, Right on Pine, Left on Broad, Left "
        "on Spruce, Right on 16th, Reg Rte"
    )
    assert pairs(rte)[-1] == ("right", "16th")
    trailing = (
        "24/7 until 11:59pm on 7-1-27, EB via 34th, Left on Chestnut,, Left "
        "on 33rd,, Right on Market,, Reg Rt 24/7 11/16/26-, 07/01/27"
    )
    assert pairs(trailing) == [
        ("via", "34th"),
        ("left", "Chestnut"),
        ("left", "33rd"),
        ("right", "Market"),
    ]


def test_glued_via_and_reg_rt_without_comma() -> None:
    # Hand-built: the real "viaTasker" message fails later (a layover).
    assert pairs("WB viaTasker, Left on Point Breeze, Reg Rt") == [
        ("via", "Tasker"),
        ("left", "Point Breeze"),
    ]
    # Real ending: "Left on 31st Reg Rt", no comma.
    assert pairs("WB via 33rd, Right on Spring Garden, Left on 31st Reg Rt")[-1] == (
        "left",
        "31st",
    )


def test_only_via_as_a_word_and_reg_rt_after_it_count() -> None:
    # Hand-built: "Aviation" isn't "via"; a "Reg Rt" before "via" isn't the end.
    message = "Aviation Rd Reg Rt change: SB via 17th, Left on Washington, Reg Rt"
    assert pairs(message) == [("via", "17th"), ("left", "Washington")]


def test_case_of_turns_ignored() -> None:
    assert pairs("SB VIA 17th, LEFT ON Washington, r - Broad, reg rt") == [
        ("via", "17th"),
        ("left", "Washington"),
        ("right", "Broad"),
    ]


@pytest.mark.parametrize(
    ("message", "error"),
    [
        # A stop closure: no path.
        (
            "24/7 Mon - Sun, until 12/31/26 discontinued, bus stop NB Broad "
            "St &, Arch St",
            "no 'via' in message",
        ),
        # A layover: no rejoin.
        (
            "7am - 4pm Weekdays until, 12/4/26, EB via - Oxford Ave, R - Rockwell "
            "Ave, (Lay over on Rockwell Ave, at Rhawn St.)",
            "no 'Reg Rt' after 'via'",
        ),
    ],
)
def test_no_path(message: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        parse_route_steps(message)


@pytest.mark.parametrize(
    ("message", "street"),
    [
        (
            "until 7pm 11/25/26, WB viaTasker, Left on Point Breeze, Right on "
            "Snyder, Right on Vare,, Layover on Vare until 1900, Reg Rt",
            "Vare,, Layover on Vare until 1900,",
        ),
        (
            "Until 2am on Thurs 11/26/26, NB via 20th St, Right on Locust St, "
            "Right on W, Rittenhouse Sq, L S, Rittenhouse Sq, Left on 18th St,, "
            "Right on Locust St, Left on Broad St,, Right on S Penn Sq, Right on "
            "Market, St,, Reg Rt",
            "W, Rittenhouse Sq, L S, Rittenhouse Sq,",
        ),
        (
            "Mon thru Fri 7am - 5:30pm, 12/26/26, SB via Ridge Ave, Stay on "
            "Ridge Ave, Reg Rt",
            "Ridge Ave, Stay on Ridge Ave,",
        ),
        (
            "Until 3pm on Weds 11/25/26, WB via J.F.K. Blvd, Right on Schuylkill "
            "Ave, Left on Around 30th St, Right on Market St, Right on 32nd St, "
            "Left on Powelton Ave, Right on 33rd, Right on Spring Garden, Left on "
            "31st Reg Rt",
            "Around 30th St,",
        ),
        # Hand-built: a short "Stay on" (within the word limit), caught by "on".
        ("SB via Main, Stay on Main, Reg Rt", "Main, Stay on Main,"),
        # Hand-built: an empty step.
        ("SB via 17th, Left on , Reg Rt", ","),
        # Hand-built: not plain words.
        ("SB via 17th, Left on Broad/Erie, Reg Rt", "Broad/Erie,"),
    ],
)
def test_not_a_street(message: str, street: str) -> None:
    with pytest.raises(ValueError, match=re.escape(f"not a street: {street!r}")):
        parse_route_steps(message)


def test_longest_street_name_is_allowed() -> None:
    assert MAX_STREET_WORDS == 4
    message = (
        "24/7 Until 11:59pm 12/1/26, SB via 17th, Left on Cecil B Moore Ave, "
        "Right on Broad St, Right on Fairmount Ave, Right on Ridge Ave, Left on "
        "Francis St, Reg Rt"
    )
    assert pairs(message)[1] == ("left", "Cecil B Moore Ave")
    with pytest.raises(ValueError, match="not a street"):
        parse_route_steps("SB via 17th, Left on Cecil B Moore Ave Ext, Reg Rt")
