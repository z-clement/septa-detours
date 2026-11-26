"""Tests for ``match.notice.match_notice`` and ``match_notices``.

Notices come from the real alert fixtures via ``parse_snapshot``. GTFS is
not committed, so ``routes``/``trips``/``directions`` are hand-built
(conftest builders) from real 2026-11-25 rows: every fixture route's real
direction names, and real shape IDs (all of them for routes 55, 24 and
L1_OWL; the first per direction for the rest).

Streets and shape points are invented, and only for two crossings:
17th & Washington (route 2 runs along 17th) and Broad & Chestnut (route 31
runs along Chestnut). Every other route's shapes are a short placeholder
line ~10 km away, so its Broad & Chestnut items are "not within 500 m",
and every other intersection is "no crossing in OSM".
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
from septa_detours.match.place import find_rejoin_point
from septa_detours.model import (
    AffectedShape,
    Detour,
    DetourNotice,
    RouteMatch,
    Segment,
    StartPoint,
    Step,
)
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

# Approximate real crossings. 0.001 deg is ~111 m north-south, ~85 m east-west.
WASHINGTON_17TH = (-75.1716, 39.9385)
BROAD_CHESTNUT = (-75.1636, 39.9508)

STREET_WAYS = [
    (1, "South 17th Street", [(10, 0, -1), (11, 0, 0), (12, 0, 1)], WASHINGTON_17TH),
    (2, "Washington Avenue", [(20, -1, 0), (11, 0, 0), (21, 1, 0)], WASHINGTON_17TH),
    (3, "South Broad Street", [(30, 0, -1), (31, 0, 0), (32, 0, 1)], BROAD_CHESTNUT),
    (4, "Chestnut Street", [(40, -1, 0), (31, 0, 0), (41, 1, 0)], BROAD_CHESTNUT),
    # One block north of Washington on 17th: a rejoin apart from the start.
    (5, "Federal Street", [(50, -1, 1), (12, 0, 1), (51, 1, 1)], WASHINGTON_17TH),
    # One block east of 17th, Washington to Federal: a path round the block.
    (6, "South Mole Street", [(21, 1, 0), (51, 1, 1)], WASHINGTON_17TH),
]
"""``(way_id, name, [(node_id, east, north)], origin)``; offsets in 0.001 deg."""

# Two-point lines through the crossing; everything else is placeholder.
ROUTE_LINES = {
    "2": [(0, -2), (0, 2)],  # along 17th, around WASHINGTON_17TH
    "31": [(-2, 0), (2, 0)],  # along Chestnut, around BROAD_CHESTNUT
}
PLACEHOLDER_LINE = [(-75.0, 40.1), (-75.0, 40.101)]


def street_ways() -> pl.DataFrame:
    rows = []
    for way_id, name, nodes, (lon, lat) in STREET_WAYS:
        points = [(n, lon + e / 1000, lat + d / 1000) for n, e, d in nodes]
        rows.append(
            (
                way_id,
                name,
                "residential",
                [n for n, _, _ in points],
                [[x, y] for _, x, y in points],
            )
        )
    return pl.DataFrame(rows, schema=STREET_WAYS_SCHEMA, orient="row")


def line_points(route_id: str) -> list[tuple[float, float]]:
    """``(lon, lat)`` points of every shape of ``route_id``."""
    if route_id not in ROUTE_LINES:
        return PLACEHOLDER_LINE
    lon, lat = WASHINGTON_17TH if route_id == "2" else BROAD_CHESTNUT
    return [(lon + e / 1000, lat + d / 1000) for e, d in ROUTE_LINES[route_id]]


def shape_points() -> pl.DataFrame:
    rows = [
        (shape_id, lat, lon, seq, "bus")
        for route_id, by_direction in SHAPES.items()
        for shape_ids in by_direction
        for shape_id in shape_ids
        for seq, (lon, lat) in enumerate(line_points(route_id), start=1)
    ]
    return pl.DataFrame(rows, schema=SHAPE_POINTS_SCHEMA, orient="row")


@pytest.fixture
def reference(routes_from_ids, trips_from_rows, directions_from_rows) -> MatchReference:
    """GTFS for every fixture route, plus rail AIR; streets for two crossings.

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
        shapes=shape_points(),
        ways=street_ways(),
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


def shape_issues(detour: Detour) -> tuple[str, ...]:
    """The ``shapes:`` issues only (tests about shapes ignore start issues)."""
    return tuple(i for i in detour.issues if i.startswith("shapes: "))


# --- Matched, with shapes ---------------------------------------------------


def test_complete_notice_gets_its_direction_shapes(
    fixture_notices, reference: MatchReference
):
    """Route 55 #0 is SB = direction_id 1: all six SB shapes, no shapes issue.

    Its start (65th Ave & Broad St) isn't among the test streets.
    """
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
        issues=("start: no crossing of '65th Ave' and 'Broad St' in OSM",),
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
    assert shape_issues(detour) == ()


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
    assert shape_issues(detour) == ()


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
    """SB is direction_id 1, but (hypothetically) no trip runs it.

    Also pins the issue order: the shapes issue, then the start issue.
    """
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
        "start: no crossing of '65th Ave' and 'Broad St' in OSM",
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


# --- Start point ------------------------------------------------------------

ROUTE_2 = "2026-11-25T025344Z__bus_route_2.json"


def test_start_point_is_placed(fixture_notices, reference: MatchReference):
    """Route 2 #0 (SB) starts at 17th & Washington, on route 2's line."""
    notice = fixture_notices(ROUTE_2)[0]
    lon, lat = WASHINGTON_17TH
    expected = Detour(
        notice=notice,
        match=RouteMatch(
            feed="bus",
            route_id="2",
            shapes=affected(SHAPES["2"][0], 0),
            start_point=StartPoint(node_id=11, lon=lon, lat=lat),
        ),
        issues=(),
    )
    assert expected == match_notice(notice, reference)


def ending_at_washington_17th(notice: DetourNotice) -> DetourNotice:
    """``notice`` with a path whose last two streets cross at 17th & Washington.

    Route 2 #0's real path ends at Passyunk & 17th, which the test streets
    don't have.
    """
    steps = (
        Step(turn="via", street="Broad"),
        Step(turn="right", street="Washington"),
        Step(turn="right", street="17th"),
    )
    return notice.model_copy(update={"route_steps": steps})


def test_rejoin_point_is_placed(fixture_notices, reference: MatchReference):
    notice = ending_at_washington_17th(fixture_notices(ROUTE_2)[0])
    detour = match_notice(notice, reference)
    lon, lat = WASHINGTON_17TH
    assert detour.match is not None
    assert detour.match.rejoin_point == StartPoint(node_id=11, lon=lon, lat=lat)
    assert detour.match.rejoin_by == "crossing"
    assert detour.issues == ()


def test_real_path_ending_off_the_test_streets_has_no_rejoin(
    fixture_notices, reference: MatchReference
):
    """Route 2 #0 ends at Passyunk & 17th: not found, and no issue."""
    detour = match_notice(fixture_notices(ROUTE_2)[0], reference)
    assert detour.match is not None
    assert detour.match.rejoin_point is None
    assert detour.match.rejoin_by is None
    assert detour.issues == ()


def test_rejoin_point_uses_only_the_affected_shapes(
    fixture_notices, reference: MatchReference
):
    """Unlike the start: the NB shape on 17th doesn't count for an SB detour."""
    sb_shape = SHAPES["2"][0][0]  # route 2 has one SB shape
    shape_lines = dict(reference.shape_lines)
    shape_lines[("bus", sb_shape)] = [list(point) for point in PLACEHOLDER_LINE]
    notice = ending_at_washington_17th(fixture_notices(ROUTE_2)[0])
    detour = match_notice(notice, replace(reference, shape_lines=shape_lines))
    assert detour.match is not None
    assert detour.match.start_point is not None  # both directions
    assert detour.match.rejoin_point is None


def test_rejoin_point_needs_the_direction(fixture_notices, reference: MatchReference):
    notice = ending_at_washington_17th(fixture_notices(ROUTE_2)[0])
    notice = notice.model_copy(update={"direction": None})
    detour = match_notice(notice, reference)
    assert detour.match is not None
    assert detour.match.rejoin_point is None


def ending_at_federal_17th(notice: DetourNotice) -> DetourNotice:
    """``notice`` with a path rejoining 17th at Federal, a block north."""
    steps = (
        Step(turn="via", street="17th"),
        Step(turn="right", street="Federal"),
        Step(turn="right", street="17th"),
    )
    return notice.model_copy(update={"route_steps": steps})


def test_skipped_stretch_runs_from_start_to_rejoin(
    fixture_notices, reference: MatchReference
):
    """Route 2 #0 starts at Washington; this path rejoins at Federal.

    The test shapes run north along 17th (both directions share the
    line), so the rejoin comes after the start.
    """
    notice = ending_at_federal_17th(fixture_notices(ROUTE_2)[0])
    detour = match_notice(notice, reference)
    lon, lat = WASHINGTON_17TH
    assert detour.match is not None
    assert detour.match.rejoin_point == StartPoint(node_id=12, lon=lon, lat=lat + 0.001)
    skipped = detour.match.skipped
    assert skipped is not None
    assert skipped.shape_id == SHAPES["2"][0][0]
    assert skipped.line == (
        pytest.approx((lon, lat), abs=1e-7),
        pytest.approx((lon, lat + 0.001), abs=1e-7),
    )
    assert detour.issues == ()


def test_no_skipped_stretch_when_start_and_rejoin_are_one_place(
    fixture_notices, reference: MatchReference
):
    notice = ending_at_washington_17th(fixture_notices(ROUTE_2)[0])
    detour = match_notice(notice, reference)
    assert detour.match is not None
    assert detour.match.rejoin_point is not None
    assert detour.match.skipped is None


def test_no_skipped_stretch_without_a_rejoin(
    fixture_notices, reference: MatchReference
):
    detour = match_notice(fixture_notices(ROUTE_2)[0], reference)
    assert detour.match is not None
    assert detour.match.start_point is not None
    assert detour.match.skipped is None


def test_skipped_stretch_tries_the_next_shape(
    fixture_notices, reference: MatchReference
):
    """Route 55's first affected shape is far away; the next gives it."""
    notice = ending_at_federal_17th(
        with_api_route_id(fixture_notices(ROUTE_2)[0], "bus_route_55")
    )
    first_match = match_notice(notice, reference).match
    assert first_match is not None
    first, second, *rest = [shape.shape_id for shape in first_match.shapes]
    route_2_line = reference.shape_lines[("bus", SHAPES["2"][0][0])]
    shape_lines = dict(reference.shape_lines)
    shape_lines[("bus", first)] = [list(point) for point in PLACEHOLDER_LINE]
    for shape_id in [second, *rest]:
        shape_lines[("bus", shape_id)] = route_2_line
    detour = match_notice(notice, replace(reference, shape_lines=shape_lines))
    assert detour.match is not None
    assert detour.match.skipped is not None
    assert detour.match.skipped.shape_id == second


def round_the_block(notice: DetourNotice, *, last_is_17th: bool) -> DetourNotice:
    """``notice`` with a path from 17th & Washington round the block east:
    Washington, Mole, Federal, and (``last_is_17th``) back onto 17th."""
    steps = [
        Step(turn="via", street="17th"),
        Step(turn="right", street="Washington"),
        Step(turn="left", street="Mole"),
        Step(turn="left", street="Federal"),
    ]
    if last_is_17th:
        steps.append(Step(turn="right", street="17th"))
    return notice.model_copy(update={"route_steps": tuple(steps)})


def block_point(east: int, north: int) -> tuple[float, float]:
    lon, lat = WASHINGTON_17TH
    return (lon + east / 1000, lat + north / 1000)


ROUND_THE_BLOCK = tuple(block_point(*p) for p in [(0, 0), (1, 0), (1, 1), (0, 1)])


def test_path_is_walked_to_the_rejoin(fixture_notices, reference: MatchReference):
    notice = round_the_block(fixture_notices(ROUTE_2)[0], last_is_17th=True)
    detour = match_notice(notice, reference)
    assert detour.match is not None
    assert detour.match.path == ROUND_THE_BLOCK
    lon, lat = block_point(0, 1)
    assert detour.match.rejoin_point == StartPoint(node_id=12, lon=lon, lat=lat)
    assert detour.match.rejoin_by == "crossing"  # tier B's; the path ends on it
    assert detour.match.skipped is not None
    assert detour.issues == ()


def test_path_finds_a_rejoin_tier_b_cannot(fixture_notices, reference: MatchReference):
    """Ending "Left on Federal, Reg Rt": Mole & Federal is ~85 m off 17th,
    so no tier B rejoin; the walk west along Federal finds 17th."""
    notice = round_the_block(fixture_notices(ROUTE_2)[0], last_is_17th=False)
    assert (
        find_rejoin_point(
            notice.route_steps,
            reference.ways,
            reference.street_keys,
            [reference.shape_lines[("bus", SHAPES["2"][0][0])]],
        )
        is None
    )
    detour = match_notice(notice, reference)
    assert detour.match is not None
    assert detour.match.path == ROUND_THE_BLOCK
    lon, lat = block_point(0, 1)
    assert detour.match.rejoin_point == StartPoint(node_id=12, lon=lon, lat=lat)
    assert detour.match.rejoin_by == "walk"
    # The new rejoin gives a skipped stretch too.
    assert detour.match.skipped is not None
    assert detour.match.skipped.line[-1] == pytest.approx((lon, lat), abs=1e-7)


def test_no_path_without_a_start(fixture_notices, reference: MatchReference):
    notice = round_the_block(fixture_notices(ROUTE_2)[0], last_is_17th=True)
    detour = match_notice(notice.model_copy(update={"start_place": None}), reference)
    assert detour.match is not None
    assert detour.match.start_point is None
    assert detour.match.path is None
    assert detour.match.rejoin_point is not None  # tier B's, kept


def test_no_path_keeps_tier_b(fixture_notices, reference: MatchReference):
    """The Federal path can't be walked (Federal doesn't touch the start)."""
    detour = match_notice(
        ending_at_federal_17th(fixture_notices(ROUTE_2)[0]), reference
    )
    assert detour.match is not None
    assert detour.match.path is None
    assert detour.match.rejoin_point is not None


def test_path_uses_only_the_affected_shapes(fixture_notices, reference: MatchReference):
    """Without a tier B rejoin, the walk looks for the SB shape only."""
    sb_shape = SHAPES["2"][0][0]
    shape_lines = dict(reference.shape_lines)
    shape_lines[("bus", sb_shape)] = [list(point) for point in PLACEHOLDER_LINE]
    notice = round_the_block(fixture_notices(ROUTE_2)[0], last_is_17th=False)
    detour = match_notice(notice, replace(reference, shape_lines=shape_lines))
    assert detour.match is not None
    assert detour.match.start_point is not None
    assert detour.match.path is None


def test_start_point_uses_shapes_of_both_directions(
    fixture_notices, reference: MatchReference
):
    """SB (direction_id 0) is placed even if only the NB shape is nearby."""
    (sb_shape,) = SHAPES["2"][0]
    shape_lines = dict(reference.shape_lines)
    shape_lines[("bus", sb_shape)] = [list(point) for point in PLACEHOLDER_LINE]
    detour = match_notice(
        fixture_notices(ROUTE_2)[0], replace(reference, shape_lines=shape_lines)
    )
    assert detour.match is not None
    assert detour.match.start_point is not None
    assert detour.match.start_point.node_id == 11


def test_start_point_is_placed_without_a_direction(
    fixture_notices, reference: MatchReference
):
    notice = fixture_notices(ROUTE_2)[0].model_copy(update={"direction": None})
    detour = match_notice(notice, reference)
    assert detour.match is not None
    assert detour.match.start_point is not None
    assert detour.match.start_point.node_id == 11
    assert detour.issues == ("shapes: no direction in notice",)


def test_same_crossing_is_checked_per_route(fixture_notices, reference: MatchReference):
    """Broad & Chestnut: placed for route 31 (on Chestnut), not route 32."""
    on_31 = match_notice(
        fixture_notices("2026-11-25T025344Z__bus_route_31.json")[3], reference
    )
    on_32 = match_notice(
        fixture_notices("2026-11-25T025344Z__bus_route_32.json")[0], reference
    )
    lon, lat = BROAD_CHESTNUT
    assert on_31.match is not None
    assert on_31.match.start_point == StartPoint(node_id=31, lon=lon, lat=lat)
    assert on_32.match is not None
    assert on_32.match.start_point is None
    assert on_32.issues == (
        "start: no crossing of 'Broad St' and 'Chestnut St' within 500 m of the route",
    )


def test_missing_shape_points_are_a_bug(fixture_notices, reference: MatchReference):
    """A trip's shape absent from ``shape_lines`` means the wrong feed loaded."""
    notice = fixture_notices(ROUTE_2)[0]
    with pytest.raises(KeyError):
        match_notice(notice, replace(reference, shape_lines={}))


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
    """No route -> trips/directions/streets/shapes are never read, no issues.

    Proven with frames that would crash if they were read.
    """
    broken = pl.DataFrame({"nothing": [1]})
    notice = with_api_route_id(
        fixture_notices("2026-11-25T025344Z__bus_route_55.json")[0], "APP"
    )
    unreadable = replace(
        reference,
        trips=broken,
        directions=broken,
        ways=broken,
        street_keys=broken,
        shape_lines={},
    )
    detour = match_notice(notice, unreadable)
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

# Fixture items placed on the test streets: (file, index) -> node_id.
PLACED = {
    ("2026-11-25T025344Z__bus_route_2.json", 0): 11,  # 17th & Washington
    ("2026-11-25T025344Z__bus_route_31.json", 3): 31,  # Broad & Chestnut
    ("2026-11-25T121123Z__bus_route_31.json", 3): 31,
}

# Broad & Chestnut on routes whose (placeholder) line is far away.
NOT_NEAR_ROUTE = {
    ("2026-11-25T025344Z__bus_route_32.json", 0),
    ("2026-11-25T025344Z__bus_route_44.json", 2),
    ("2026-11-25T025344Z__bus_route_49.json", 4),
    ("2026-11-25T025344Z__bus_route_49.json", 5),
}

# How many fixture items end each way. Adding a fixture breaks this on
# purpose: review its items.
START_OUTCOMES = {
    "placed": 3,
    "not near route": 4,
    "not in OSM": 47,
    "segment": 2,
    "no start place": 9,
}


def expected_start(key: tuple[str, int], notice: DetourNotice) -> tuple[str, str]:
    """``(outcome, expected start issue or "")`` for an unplaced item."""
    place = notice.start_place
    if place is None:
        return "no start place", ""
    if isinstance(place, Segment):
        return "segment", "start: segments are not placed yet"
    first, second = place.streets
    if key in NOT_NEAR_ROUTE:
        where, outcome = "within 500 m of the route", "not near route"
    else:
        where, outcome = "in OSM", "not in OSM"
    return outcome, f"start: no crossing of '{first}' and '{second}' {where}"


def test_fixture_sweep(
    alert_fixture_names: list[str], fixture_notices, reference: MatchReference
):
    """All 65 fixture items: route matched; shapes or a pinned reason; the
    start point placed, or the issue its pinned outcome predicts.

    Shapes must all carry the direction_id whose real name is the notice's
    direction. Every ``Detour`` round-trips through JSON.
    """
    no_shapes = {}
    outcomes: dict[str, int] = {}
    count = 0
    for name in alert_fixture_names:
        for index, notice in enumerate(fixture_notices(name)):
            count += 1
            key = (name, index)
            detour = match_notice(notice, reference)
            assert detour == Detour.model_validate_json(detour.model_dump_json())
            assert detour.match is not None
            shapes_part = shape_issues(detour)
            start_part = detour.issues[len(shapes_part) :]

            if key in PLACED:
                outcome = "placed"
                assert detour.match.start_point is not None
                assert detour.match.start_point.node_id == PLACED[key]
                assert start_part == ()
            else:
                outcome, issue = expected_start(key, notice)
                assert detour.match.start_point is None
                assert start_part == ((issue,) if issue else ())
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

            if not detour.match.shapes:
                (no_shapes[key],) = shapes_part
                continue
            assert shapes_part == ()
            assert notice.direction is not None
            names = DIRECTION_NAMES[detour.match.route_id]
            direction_id = names.index(COMPASS[notice.direction])
            expected = affected(
                SHAPES[detour.match.route_id][direction_id], direction_id
            )
            assert expected == detour.match.shapes
    assert count == 65
    assert no_shapes == NO_SHAPES
    assert outcomes == START_OUTCOMES


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
