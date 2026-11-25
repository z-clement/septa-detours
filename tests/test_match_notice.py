"""Tests for ``match.notice.match_notice`` and ``match_notices``.

Notices come from the real alert fixtures via ``parse_snapshot``; ``routes``
is hand-built from real GTFS route IDs with ``routes_from_ids`` (conftest;
GTFS is not committed).
"""

from collections.abc import Callable

import polars as pl
import pytest
from polars.exceptions import ColumnNotFoundError

from septa_detours.match.notice import match_notice, match_notices
from septa_detours.model import Detour, DetourNotice, RouteMatch
from septa_detours.parse.notice import parse_snapshot

type RoutesFromIds = Callable[[list[tuple[str, str]]], pl.DataFrame]

# Every route with detours in the fixtures, plus a rail route.
ROUTE_IDS = [
    *[("bus", r) for r in ("2", "6", "7", "9", "24", "31", "32", "44", "49")],
    *[("bus", r) for r in ("55", "61", "64", "68", "103", "124")],
    ("bus", "L1_OWL"),
    ("bus", "B1_OWL"),
    ("rail", "AIR"),
]

SNAPSHOT = "2026-11-25T025344Z.json"


@pytest.fixture
def routes(routes_from_ids: RoutesFromIds) -> pl.DataFrame:
    return routes_from_ids(ROUTE_IDS)


@pytest.fixture
def fixture_notices(
    read_alert_fixture: Callable[[str], bytes],
) -> Callable[[str], list[DetourNotice]]:
    """Parse one fixture file (a single route entry) into its notices."""

    def parse(name: str) -> list[DetourNotice]:
        return parse_snapshot(b"[" + read_alert_fixture(name) + b"]", SNAPSHOT)

    return parse


def with_api_route_id(notice: DetourNotice, api_route_id: str) -> DetourNotice:
    """Copy ``notice`` with a different raw API ``route_id``."""
    source = notice.source.model_copy(update={"route_id": api_route_id})
    return notice.model_copy(update={"source": source})


# --- Matched ----------------------------------------------------------------


def test_complete_notice_matches_route(fixture_notices, routes: pl.DataFrame):
    """Route 55 #0 (SB, complete): whole ``Detour`` compared."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0]
    expected = Detour(
        notice=notice,
        match=RouteMatch(feed="bus", route_id="55", shapes=()),
        issues=("shapes: direction 'SB' not mapped to a GTFS direction_id yet",),
    )
    assert expected == match_notice(notice, routes)


def test_alias_route_matches(fixture_notices, routes: pl.DataFrame):
    """MFO #0 goes through the alias table to the Owl bus ``L1_OWL``."""
    notice = fixture_notices("2026-11-25T025344Z__rr_route_mfo.json")[0]
    detour = match_notice(notice, routes)
    assert RouteMatch(feed="bus", route_id="L1_OWL") == detour.match
    expected = ("shapes: direction 'WB' not mapped to a GTFS direction_id yet",)
    assert expected == detour.issues


def test_notice_without_direction(fixture_notices, routes: pl.DataFrame):
    """Route 24 #1 has no direction: still matched, different shapes issue."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_24.json")[1]
    detour = match_notice(notice, routes)
    assert RouteMatch(feed="bus", route_id="24") == detour.match
    assert detour.issues == ("shapes: no direction in notice",)


def test_unknown_notice_is_still_matched(fixture_notices, routes: pl.DataFrame):
    """Route 64 #1 is ``unknown`` (blank location), but its route is known."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_64.json")[1]
    assert notice.status == "unknown"
    detour = match_notice(notice, routes)
    assert RouteMatch(feed="bus", route_id="64") == detour.match


def test_parse_issues_stay_on_notice(fixture_notices, routes: pl.DataFrame):
    """``Detour.issues`` holds match issues only; parse issues aren't copied."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_24.json")[1]
    detour = match_notice(notice, routes)
    assert notice is detour.notice
    assert detour.notice.issues == ("direction: none found in message",)
    assert "direction: none found in message" not in detour.issues


# --- Unmatched --------------------------------------------------------------


def test_unknown_route_gives_no_match(fixture_notices, routes: pl.DataFrame):
    """A retired API route: ``match=None`` and the lookup reason, prefixed."""
    notice = with_api_route_id(
        fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0], "bus_route_H"
    )
    expected = Detour(
        notice=notice,
        match=None,
        issues=(
            "route: no GTFS route for API route 'bus_route_H'"
            " (looked for bus route 'H')",
        ),
    )
    assert expected == match_notice(notice, routes)


def test_unmatched_notice_has_no_shapes_issue(fixture_notices, routes):
    """With no route there are no shapes to talk about: one issue only."""
    notice = with_api_route_id(
        fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0], "APP"
    )
    detour = match_notice(notice, routes)
    assert detour.match is None
    assert detour.issues == ("route: no GTFS route for API route 'APP'",)


def test_non_value_errors_propagate(fixture_notices, routes: pl.DataFrame):
    """A malformed ``routes`` frame is a bug, not an unmatched notice."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0]
    broken = routes.drop("feed")
    with pytest.raises(ColumnNotFoundError):
        match_notice(notice, broken)


# --- Fixture sweep ----------------------------------------------------------


def test_every_fixture_notice_matches_and_round_trips(
    alert_fixture_names: list[str], fixture_notices, routes: pl.DataFrame
):
    """All 65 fixture items match a route and survive a JSON round trip."""
    detours = [
        match_notice(notice, routes)
        for name in alert_fixture_names
        for notice in fixture_notices(name)
    ]
    assert len(detours) == 65
    assert all(detour.match is not None for detour in detours)
    assert all(detour.match.shapes == () for detour in detours if detour.match)
    for detour in detours:
        assert detour == Detour.model_validate_json(detour.model_dump_json())


# --- match_notices ----------------------------------------------------------

# Deliberately unsorted (by name and by route), and APP has no items.
MINI_SNAPSHOT_FIXTURES = (
    "2026-11-25T025344Z__bus_route_55.json",  # 1 item
    "2026-11-25T025344Z__APP.json",  # 0 items
    "2026-11-25T025344Z__rr_route_mfo.json",  # 6 items
    "2026-11-25T025344Z__bus_route_24.json",  # 4 items
)


@pytest.fixture
def mini_notices(read_alert_fixture: Callable[[str], bytes]) -> list[DetourNotice]:
    """Notices from several fixture entries parsed as one snapshot."""
    entries = b",".join(read_alert_fixture(name) for name in MINI_SNAPSHOT_FIXTURES)
    return parse_snapshot(b"[" + entries + b"]", SNAPSHOT)


def test_batch_keeps_input_order(mini_notices, routes: pl.DataFrame):
    """One ``Detour`` per notice, in the same order (not sorted by route)."""
    detours = match_notices(mini_notices, routes)
    assert [detour.notice for detour in detours] == mini_notices
    route_ids = [detour.match.route_id for detour in detours if detour.match]
    assert route_ids == ["55", *["L1_OWL"] * 6, *["24"] * 4]


def test_batch_equals_one_by_one(mini_notices, routes: pl.DataFrame):
    """The batch adds nothing and drops nothing beyond ``match_notice``."""
    expected = [match_notice(notice, routes) for notice in mini_notices]
    assert match_notices(mini_notices, routes) == expected


def test_batch_keeps_unmatched_in_place(mini_notices, routes: pl.DataFrame):
    """An unmatched notice stays at its index with ``match=None``."""
    notices = list(mini_notices)
    notices[3] = with_api_route_id(notices[3], "bus_route_H")
    detours = match_notices(notices, routes)
    assert len(detours) == len(notices)
    assert detours[3].notice == notices[3]
    assert detours[3].match is None
    assert all(d.match is not None for i, d in enumerate(detours) if i != 3)


def test_batch_keeps_equal_notices(fixture_notices, routes: pl.DataFrame):
    """Equal notices each get their own ``Detour``; nothing is deduplicated.

    Route 31 items 0-4 are byte-identical in both snapshots, so parsing
    both fixtures under one snapshot name gives equal notices.
    """
    notices = fixture_notices("2026-11-25T025344Z__bus_route_31.json")
    notices += fixture_notices("2026-11-25T121123Z__bus_route_31.json")
    assert notices[0] in notices[1:]  # the premise: duplicates exist
    detours = match_notices(notices, routes)
    assert [detour.notice for detour in detours] == notices


def test_batch_accepts_any_iterable(mini_notices, routes: pl.DataFrame):
    """A one-shot generator works (consumed once) and gives a list."""
    detours = match_notices((notice for notice in mini_notices), routes)
    assert type(detours) is list
    assert len(detours) == 11


def test_batch_of_nothing_is_empty(routes: pl.DataFrame):
    assert match_notices([], routes) == []


def test_batch_propagates_non_value_errors(mini_notices, routes: pl.DataFrame):
    """A bug in one lookup fails the whole batch; nothing is skipped."""
    with pytest.raises(ColumnNotFoundError):
        match_notices(mini_notices, routes.drop("feed"))
