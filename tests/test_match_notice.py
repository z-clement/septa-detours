"""Tests for ``match.notice.match_notice`` and ``match_notices``.

Notices come from the real alert fixtures via ``parse_snapshot``. GTFS is
not committed, so ``routes``/``trips``/``directions`` are hand-built
(conftest builders) from real 2026-11-25 rows: every fixture route's real
direction names, and real shape IDs (all of them for routes 55, 24 and
L1_OWL; the first per direction for the rest). No shape points and no
streets yet: nothing reads them.
"""

from collections.abc import Callable
from dataclasses import replace

import polars as pl
import pytest
from polars.exceptions import ColumnNotFoundError

from septa_detours.match.notice import (
    MatchReference,
    build_match_reference,
    match_notice,
    match_notices,
)
from septa_detours.model import AffectedShape, Detour, DetourNotice, RouteMatch
from septa_detours.parse.notice import parse_snapshot
from septa_detours.streets.load import STREET_WAYS_SCHEMA

SNAPSHOT = "2026-11-25T025344Z.json"

# route_id -> (direction_id 0's name, direction_id 1's name), real.
DIRECTION_NAMES = {
    "2": ("Southbound", "Northbound"),
    "6": ("Southbound", "Northbound"),
    "7": ("Southbound", "Northbound"),
    "9": ("Southbound", "Northbound"),
    "24": ("Northbound", "Southbound"),
    "31": ("Eastbound", "Westbound"),
    "32": ("Southbound", "Northbound"),
    "44": ("Eastbound", "Westbound"),
    "49": ("Southbound", "Northbound"),
    "55": ("Northbound", "Southbound"),
    "61": ("Southbound", "Northbound"),
    "64": ("Westbound", "Eastbound"),
    "68": ("Northbound", "Southbound"),
    "103": ("Northbound", "Southbound"),
    "124": ("Westbound", "Eastbound"),
    "L1_OWL": ("Eastbound", "Westbound"),
    "B1_OWL": ("Southbound", "Northbound"),
}

# route_id -> (direction_id 0's shapes, direction_id 1's shapes), real, in
# first-appearance order.
SHAPES = {
    "2": (("317310",), ("317312",)),
    "6": (("317697",), ("317699",)),
    "7": (("317828",), ("317834",)),
    "9": (("317920",), ("317922",)),
    "24": (
        ("317352", "317355", "317353", "317354"),
        ("317356", "317359", "317358", "317357"),
    ),
    "31": (("319923",), ("319925",)),
    "32": (("317429",), ("317437",)),
    "44": (("320000",), ("319837",)),
    "49": (("319921",), ("319922",)),
    "55": (
        ("317626", "317630", "317631", "317628", "317629", "317627"),
        ("317636", "317638", "317633", "317634", "317635", "317637"),
    ),
    "61": (("319808",), ("319928",)),
    "64": (("317767",), ("317769",)),
    "68": (("317809",), ("317820",)),
    "103": (("319434",), ("319439",)),
    "124": (("319702",), ("319699",)),
    "L1_OWL": (("320009", "320010"), ("320011",)),
    "B1_OWL": (("317925",), ("317929",)),
}


SHAPE_POINTS_SCHEMA = {
    "shape_id": pl.String,
    "shape_pt_lat": pl.Float64,
    "shape_pt_lon": pl.Float64,
    "shape_pt_sequence": pl.Int32,
    "feed": pl.String,
}


@pytest.fixture
def reference(routes_from_ids, trips_from_rows, directions_from_rows) -> MatchReference:
    """GTFS for every fixture route, plus rail AIR; no shape points or streets.

    Trips interleave the two directions shape by shape, so filtering by
    direction must actually filter.
    """
    routes = routes_from_ids([("bus", r) for r in SHAPES] + [("rail", "AIR")])
    trip_rows = []
    for route_id, (shapes_0, shapes_1) in SHAPES.items():
        for i in range(max(len(shapes_0), len(shapes_1))):
            trip_rows += [("bus", route_id, 0, s) for s in shapes_0[i : i + 1]]
            trip_rows += [("bus", route_id, 1, s) for s in shapes_1[i : i + 1]]
    trips = trips_from_rows(trip_rows)
    direction_rows = [
        ("bus", route_id, direction_id, name)
        for route_id, names in DIRECTION_NAMES.items()
        for direction_id, name in enumerate(names)
    ]
    directions = directions_from_rows(
        [*direction_rows, ("rail", "AIR", 0, "Inbound"), ("rail", "AIR", 1, "Outbound")]
    )
    return build_match_reference(
        routes=routes,
        trips=trips,
        directions=directions,
        shapes=pl.DataFrame(schema=SHAPE_POINTS_SCHEMA),
        ways=pl.DataFrame(schema=STREET_WAYS_SCHEMA),
    )


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


def affected(
    shape_ids: tuple[str, ...], direction_id: int
) -> tuple[AffectedShape, ...]:
    return tuple(
        AffectedShape(shape_id=s, direction_id=direction_id) for s in shape_ids
    )


# --- Matched, with shapes ---------------------------------------------------


def test_complete_notice_gets_its_direction_shapes(
    fixture_notices, reference: MatchReference
):
    """Route 55 #0 is SB = direction_id 1: all six SB shapes, no issues."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0]
    expected = Detour(
        notice=notice,
        match=RouteMatch(
            feed="bus",
            route_id="55",
            shapes=(
                AffectedShape(shape_id="317636", direction_id=1),
                AffectedShape(shape_id="317638", direction_id=1),
                AffectedShape(shape_id="317633", direction_id=1),
                AffectedShape(shape_id="317634", direction_id=1),
                AffectedShape(shape_id="317635", direction_id=1),
                AffectedShape(shape_id="317637", direction_id=1),
            ),
            start_point=None,
        ),
        issues=(),
    )
    assert expected == match_notice(notice, reference)


def test_alias_route_gets_shapes(fixture_notices, reference: MatchReference):
    """MFO #0 (WB) -> ``L1_OWL`` direction_id 1 -> its one WB shape."""
    notice = fixture_notices("2026-11-25T025344Z__rr_route_mfo.json")[0]
    detour = match_notice(notice, reference)
    expected = RouteMatch(
        feed="bus",
        route_id="L1_OWL",
        shapes=affected(("320011",), 1),
        start_point=None,
    )
    assert expected == detour.match
    assert detour.issues == ()


@pytest.mark.parametrize(
    ("route_id", "index", "direction", "direction_id"),
    [
        # direction_id 0 means a different compass direction per route.
        ("2", 0, "SB", 0),
        ("2", 3, "NB", 1),
        ("24", 0, "NB", 0),
        ("24", 3, "SB", 1),
        ("64", 0, "EB", 1),
        ("64", 2, "WB", 0),
        ("31", 0, "EB", 0),
        ("31", 1, "WB", 1),
    ],
)
def test_direction_id_is_per_route(
    fixture_notices, reference: MatchReference, route_id, index, direction, direction_id
):
    name = f"2026-11-25T025344Z__bus_route_{route_id}.json"
    notice = fixture_notices(name)[index]
    assert notice.direction == direction  # the premise
    detour = match_notice(notice, reference)
    assert detour.match is not None
    expected = affected(SHAPES[route_id][direction_id], direction_id)
    assert expected == detour.match.shapes
    assert detour.issues == ()


def test_unknown_notice_still_gets_shapes(fixture_notices, reference: MatchReference):
    """Route 64 #1 is ``unknown`` (blank location) but EB: direction_id 1."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_64.json")[1]
    assert notice.status == "unknown"
    detour = match_notice(notice, reference)
    expected = RouteMatch(
        feed="bus", route_id="64", shapes=affected(("317769",), 1), start_point=None
    )
    assert expected == detour.match


# --- Matched, no shapes -----------------------------------------------------


def test_notice_without_direction(fixture_notices, reference: MatchReference):
    """Route 24 #1 has no direction: route matched, no shapes, one issue."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_24.json")[1]
    expected = Detour(
        notice=notice,
        match=RouteMatch(feed="bus", route_id="24", shapes=(), start_point=None),
        issues=("shapes: no direction in notice",),
    )
    assert expected == match_notice(notice, reference)


def test_direction_not_on_route(fixture_notices, reference: MatchReference):
    """Route 68 runs N/S; #0 says "EB Via Tinicum". Never both directions."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_68.json")[0]
    assert notice.direction == "EB"  # the premise
    expected = Detour(
        notice=notice,
        match=RouteMatch(feed="bus", route_id="68", shapes=(), start_point=None),
        issues=(
            "shapes: bus route '68' has no Eastbound direction"
            " (has Northbound, Southbound)",
        ),
    )
    assert expected == match_notice(notice, reference)


def test_direction_with_no_shapes(fixture_notices, reference: MatchReference):
    """SB is direction_id 1, but (hypothetically) no trip runs it."""
    trips = reference.trips.filter(
        ~((pl.col("route_id") == "55") & (pl.col("direction_id") == 1))
    )
    notice = fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0]
    detour = match_notice(notice, replace(reference, trips=trips))
    assert (
        RouteMatch(feed="bus", route_id="55", shapes=(), start_point=None)
        == detour.match
    )
    assert detour.issues == (
        "shapes: bus route '55' has no shapes with direction_id 1",
    )


def test_parse_issues_stay_on_notice(fixture_notices, reference: MatchReference):
    """``Detour.issues`` holds match issues only; parse issues aren't copied."""
    notice = fixture_notices("2026-11-25T025344Z__bus_route_24.json")[1]
    detour = match_notice(notice, reference)
    assert notice is detour.notice
    assert detour.notice.issues == (
        "location_start: unrecognized location 'Bethayres Station'",
        "direction: none found in message",
    )
    assert not set(detour.notice.issues) & set(detour.issues)


# --- Unmatched --------------------------------------------------------------


def test_unknown_route_gives_no_match(fixture_notices, reference: MatchReference):
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
    assert expected == match_notice(notice, reference)


def test_unmatched_route_skips_shape_lookup(fixture_notices, reference: MatchReference):
    """No route -> trips/directions are never read, and no shapes issue.

    Proven with frames that would crash if they were read.
    """
    broken = pl.DataFrame({"nothing": [1]})
    notice = with_api_route_id(
        fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0], "APP"
    )
    detour = match_notice(notice, replace(reference, trips=broken, directions=broken))
    assert detour.match is None
    assert detour.issues == ("route: no GTFS route for API route 'APP'",)


@pytest.mark.parametrize(
    ("frame", "column"),
    [("routes", "feed"), ("trips", "shape_id"), ("directions", "direction")],
)
def test_non_value_errors_propagate(
    fixture_notices, reference: MatchReference, frame: str, column: str
):
    """A malformed frame is a bug, not an unmatched notice or a shapes issue."""
    broken = replace(reference, **{frame: getattr(reference, frame).drop(column)})
    notice = fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0]
    with pytest.raises(ColumnNotFoundError):
        match_notice(notice, broken)


# --- build_match_reference --------------------------------------------------


def build_with(reference: MatchReference, **overrides) -> MatchReference:
    """Rebuild ``reference`` from its frames, with some inputs replaced."""
    inputs = {
        "routes": reference.routes,
        "trips": reference.trips,
        "directions": reference.directions,
        "shapes": pl.DataFrame(schema=SHAPE_POINTS_SCHEMA),
        "ways": reference.ways,
    }
    return build_match_reference(**(inputs | overrides))


def test_reference_keeps_gtfs_frames_as_given(reference: MatchReference):
    rebuilt = build_with(reference)
    assert rebuilt.routes is reference.routes
    assert rebuilt.trips is reference.trips
    assert rebuilt.directions is reference.directions


def test_reference_shape_lines_are_ordered_lon_lat_per_feed():
    # Points out of sequence order; shape "1" exists in both feeds.
    shapes = pl.DataFrame(
        [
            ("1", 39.95, -75.16, 2, "bus"),
            ("2", 39.90, -75.20, 1, "bus"),
            ("1", 39.94, -75.17, 1, "bus"),
            ("1", 40.01, -75.30, 1, "rail"),
        ],
        schema=SHAPE_POINTS_SCHEMA,
        orient="row",
    )
    reference = build_match_reference(
        routes=pl.DataFrame(),
        trips=pl.DataFrame(),
        directions=pl.DataFrame(),
        shapes=shapes,
        ways=pl.DataFrame(schema=STREET_WAYS_SCHEMA),
    )
    assert reference.shape_lines == {
        ("bus", "1"): [[-75.17, 39.94], [-75.16, 39.95]],
        ("bus", "2"): [[-75.20, 39.90]],
        ("rail", "1"): [[-75.30, 40.01]],
    }


def test_reference_street_keys_come_from_ways(reference: MatchReference):
    ways = pl.DataFrame(
        [(7, "South 17th Street", "residential", [1, 2], [[-75.17, 39.93]] * 2)],
        schema=STREET_WAYS_SCHEMA,
        orient="row",
    )
    rebuilt = build_with(reference, ways=ways)
    assert rebuilt.ways is ways
    assert rebuilt.street_keys.rows() == [
        (7, "south 17th", "street", False),
        (7, "17th", "street", True),
    ]


def test_reference_is_keyword_only_and_frozen(reference: MatchReference):
    with pytest.raises(TypeError):
        MatchReference(*vars(reference).values())  # ty: ignore[missing-argument]
    with pytest.raises(AttributeError):
        reference.trips = reference.routes  # ty: ignore[invalid-assignment]


# --- Fixture sweep ----------------------------------------------------------

# Every fixture item that gets no shapes, and why. All others get shapes and
# no issues. Adding a fixture breaks this on purpose: review its items.
NO_SHAPES = {
    ("2026-11-25T025344Z__bus_route_24.json", 1): "shapes: no direction in notice",
    ("2026-11-25T025344Z__bus_route_6.json", 0): "shapes: no direction in notice",
    ("2026-11-25T025344Z__bus_route_68.json", 0): (
        "shapes: bus route '68' has no Eastbound direction (has Northbound, Southbound)"
    ),
    ("2026-11-25T025344Z__bus_route_68.json", 1): (
        "shapes: bus route '68' has no Eastbound direction (has Northbound, Southbound)"
    ),
}

COMPASS = {"NB": "Northbound", "SB": "Southbound", "EB": "Eastbound", "WB": "Westbound"}


def test_fixture_sweep(
    alert_fixture_names: list[str], fixture_notices, reference: MatchReference
):
    """All 65 fixture items: route matched; shapes or a pinned reason.

    Shapes must all carry the direction_id whose real name is the notice's
    direction. Every ``Detour`` round-trips through JSON.
    """
    no_shapes = {}
    count = 0
    for name in alert_fixture_names:
        for index, notice in enumerate(fixture_notices(name)):
            count += 1
            detour = match_notice(notice, reference)
            assert detour == Detour.model_validate_json(detour.model_dump_json())
            assert detour.match is not None
            if not detour.match.shapes:
                (no_shapes[(name, index)],) = detour.issues
                continue
            assert detour.issues == ()
            assert notice.direction is not None
            names = DIRECTION_NAMES[detour.match.route_id]
            direction_id = names.index(COMPASS[notice.direction])
            expected = affected(
                SHAPES[detour.match.route_id][direction_id], direction_id
            )
            assert expected == detour.match.shapes
    assert count == 65
    assert no_shapes == NO_SHAPES


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


def test_batch_keeps_input_order(mini_notices, reference: MatchReference):
    """One ``Detour`` per notice, in the same order (not sorted by route)."""
    detours = match_notices(mini_notices, reference)
    assert [detour.notice for detour in detours] == mini_notices
    route_ids = [detour.match.route_id for detour in detours if detour.match]
    assert route_ids == ["55", *["L1_OWL"] * 6, *["24"] * 4]


def test_batch_equals_one_by_one(mini_notices, reference: MatchReference):
    """The batch adds nothing and drops nothing beyond ``match_notice``."""
    expected = [match_notice(notice, reference) for notice in mini_notices]
    assert match_notices(mini_notices, reference) == expected


def test_batch_keeps_unmatched_in_place(mini_notices, reference: MatchReference):
    """An unmatched notice stays at its index with ``match=None``."""
    notices = list(mini_notices)
    notices[3] = with_api_route_id(notices[3], "bus_route_H")
    detours = match_notices(notices, reference)
    assert len(detours) == len(notices)
    assert detours[3].notice == notices[3]
    assert detours[3].match is None
    assert all(d.match is not None for i, d in enumerate(detours) if i != 3)


def test_batch_keeps_equal_notices(fixture_notices, reference: MatchReference):
    """Equal notices each get their own ``Detour``; nothing is deduplicated.

    Route 31 items 0-4 are byte-identical in both snapshots, so parsing
    both fixtures under one snapshot name gives equal notices.
    """
    notices = fixture_notices("2026-11-25T025344Z__bus_route_31.json")
    notices += fixture_notices("2026-11-25T121123Z__bus_route_31.json")
    assert notices[0] in notices[1:]  # the premise: duplicates exist
    detours = match_notices(notices, reference)
    assert [detour.notice for detour in detours] == notices


def test_batch_accepts_any_iterable(mini_notices, reference: MatchReference):
    """A one-shot generator works (consumed once) and gives a list."""
    detours = match_notices((notice for notice in mini_notices), reference)
    assert type(detours) is list
    assert len(detours) == 11


def test_batch_of_nothing_is_empty(reference: MatchReference):
    assert match_notices([], reference) == []


def test_batch_propagates_non_value_errors(mini_notices, reference: MatchReference):
    """A bug in one lookup fails the whole batch; nothing is skipped."""
    broken = replace(reference, trips=reference.trips.drop("shape_id"))
    with pytest.raises(ColumnNotFoundError):
        match_notices(mini_notices, broken)
