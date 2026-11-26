import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from septa_detours.export.contract import (
    NETWORK_PROPERTIES,
    PATH_PROPERTIES,
    SHAPE_PROPERTIES,
    SKIPPED_PROPERTIES,
    START_PROPERTIES,
    DirectionEntry,
    Mode,
    RouteEntry,
)
from septa_detours.export.site import (
    MODE_ORDER,
    RouteShape,
    detour_object,
    lines_bounds,
    network_collection,
    paths_collection,
    rejoin_streets,
    route_catalog,
    route_detail,
    route_directions,
    route_key,
    route_mode,
    route_shapes,
    route_sort_key,
    skipped_collection,
    starts_collection,
    status,
)
from septa_detours.export.write import route_geojson_path
from septa_detours.gtfs.load import Feed
from septa_detours.ingest.alerts import snapshot_path
from septa_detours.model import (
    AffectedShape,
    Detour,
    DetourNotice,
    RejoinBy,
    RouteMatch,
    SkippedStretch,
    StartPoint,
    Step,
    Turn,
)
from septa_detours.parse.notice import parse_snapshot


@pytest.mark.parametrize(
    ("route_type", "mode"),
    [(0, "trolley"), (1, "metro"), (2, "rail"), (3, "bus"), (11, "trackless")],
)
def test_route_mode(route_type: int, mode: Mode) -> None:
    assert route_mode(route_type) == mode


@pytest.mark.parametrize("route_type", [4, 7, 12, -1])
def test_route_mode_rejects_unknown_types(route_type: int) -> None:
    with pytest.raises(ValueError, match=f"unknown route_type {route_type}"):
        route_mode(route_type)


def test_mode_order() -> None:
    assert MODE_ORDER == ("metro", "trolley", "trackless", "bus", "rail")


def sort_names(mode: Mode, names: list[str]) -> list[str]:
    return sorted(names, key=lambda name: route_sort_key(mode, name))


def test_modes_sort_in_mode_order() -> None:
    routes: list[tuple[Mode, str]] = [
        ("rail", "AIR"),
        ("bus", "1"),
        ("trackless", "59"),
        ("metro", "L1"),
        ("trolley", "T1"),
    ]
    result = sorted(routes, key=lambda route: route_sort_key(*route))
    assert [mode for mode, _ in result] == list(MODE_ORDER)


def test_mode_beats_name() -> None:
    routes: list[tuple[Mode, str]] = [("bus", "1"), ("metro", "B1"), ("metro", "9")]
    result = sorted(routes, key=lambda route: route_sort_key(*route))
    assert result == [("metro", "9"), ("metro", "B1"), ("bus", "1")]


def test_numbers_sort_by_value() -> None:
    assert sort_names("bus", ["10", "9", "124", "2"]) == ["2", "9", "10", "124"]


def test_real_bus_names_sort_numbers_first_then_alphabetically() -> None:
    # The real non-numeric bus short names (GTFS, 2026-11-25), shuffled.
    names = [
        "WTR Bus", "K", "124", "LUCYGR", "D2 Bus", "MANN", "1", "B1 OWL",
        "NOR Bus", "FOX Bus", "L1 OWL", "T Bus", "BLVDDIR", "M1 Bus", "D1 Bus",
        "LUCYGO", "21",
    ]  # fmt: skip
    assert sort_names("bus", names) == [
        "1", "21", "124", "B1 OWL", "BLVDDIR", "D1 Bus", "D2 Bus", "FOX Bus",
        "K", "L1 OWL", "LUCYGO", "LUCYGR", "M1 Bus", "MANN", "NOR Bus",
        "T Bus", "WTR Bus",
    ]  # fmt: skip


def test_names_ignore_case() -> None:
    assert sort_names("bus", ["b", "C", "A"]) == ["A", "b", "C"]


@pytest.mark.parametrize("names", [["K", "k"], ["k", "K"]])
def test_names_equal_ignoring_case_have_a_fixed_order(names: list[str]) -> None:
    assert sort_names("bus", names) == ["K", "k"]


@pytest.mark.parametrize("name", ["10B", "1 Bus", "\u00b2", "\u0663", "-1", ""])
def test_names_that_are_not_plain_numbers_sort_as_text(name: str) -> None:
    assert sort_names("bus", [name, "999"]) == ["999", name]


@pytest.mark.parametrize(
    ("feed", "route_id", "key"),
    [
        ("bus", "21", "bus-21"),
        ("bus", "T_BUS", "bus-T_BUS"),
        ("rail", "AIR", "rail-AIR"),
    ],
)
def test_route_key(feed: Feed, route_id: str, key: str) -> None:
    assert route_key(feed, route_id) == key


UNSAFE_ROUTE_IDS = ["", "21 ", "a b", "../21", "21/x", "a.b", "\u00fc", "21\n"]


@pytest.mark.parametrize("route_id", UNSAFE_ROUTE_IDS)
def test_route_key_rejects_unsafe_ids(route_id: str) -> None:
    with pytest.raises(ValueError, match="not safe to use as a key"):
        route_key("bus", route_id)


@pytest.mark.parametrize("route_id", ["21", "L1_OWL", "a-b", *UNSAFE_ROUTE_IDS])
def test_route_key_accepts_what_route_geojson_path_accepts(route_id: str) -> None:
    # The pattern is duplicated from write.py on purpose; they must agree.
    def accepted(build: Callable[[], object]) -> bool:
        try:
            build()
        except ValueError:
            return False
        return True

    assert accepted(lambda: route_key("bus", route_id)) == accepted(
        lambda: route_geojson_path("bus", route_id)
    )


# Real-looking coordinates, all different, so a lon/lat or min/max swap shows.
def test_lines_bounds_of_one_line() -> None:
    line = [[-75.17, 39.94], [-75.15, 39.93], [-75.16, 39.96]]
    assert lines_bounds([line]) == ([-75.17, 39.93], [-75.15, 39.96])


def test_lines_bounds_spans_every_line() -> None:
    west = [[-75.26, 39.95], [-75.20, 39.96]]
    east = [[-75.14, 39.94], [-75.13, 39.97]]
    assert lines_bounds([west, east]) == ([-75.26, 39.94], [-75.13, 39.97])


def test_lines_bounds_accepts_a_generator_of_tuples() -> None:
    lines = (tuple(line) for line in [[(-75.2, 40.1), (-75.1, 40.0)]])
    assert lines_bounds(lines) == ([-75.2, 40.0], [-75.1, 40.1])


@pytest.mark.parametrize("lines", [[], [[]]])
def test_lines_bounds_rejects_no_points(lines: list[list[list[float]]]) -> None:
    with pytest.raises(ValueError, match="no points to bound"):
        lines_bounds(lines)


# --- route_catalog ---------------------------------------------------------------

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

type RouteRow = tuple[str, str | None, str | None, int, str | None, str | None, str]


def make_routes(rows: list[RouteRow]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=ROUTES_SCHEMA, orient="row")


# Out of display order, every color distinct; T_BUS has no shapes.
ROUTES = make_routes(
    [
        ("21", "21", "Chestnut-Walnut", 3, "EF3340", "FFFFFF", "bus"),
        ("AIR", "AIR", "Airport Line", 2, "5A6F7B", "F0F0F0", "rail"),
        ("T_BUS", "T Bus", "T Shuttle", 3, "F26522", "000000", "bus"),
        ("2", "2", "16th-17th", 3, "00A1DE", "111111", "bus"),
        ("L1", "L1", "Market-Frankford", 1, "0072CE", "EEEEEE", "bus"),
    ]
)
BOUNDS = {
    "bus-21": ([-75.26, 39.94], [-75.14, 39.97]),
    "rail-AIR": ([-75.25, 39.87], [-75.16, 39.96]),
    "bus-2": ([-75.18, 39.91], [-75.16, 40.04]),
    "bus-L1": ([-75.26, 39.95], [-75.08, 40.03]),
}


@pytest.fixture
def notice(read_alert_fixture) -> DetourNotice:
    stamp = "2026-11-25T025344Z"
    content = read_alert_fixture(f"{stamp}__bus_route_2.json")
    return parse_snapshot(b"[" + content + b"]", f"{stamp}.json")[0]


def on_route(
    notice: DetourNotice, feed: Feed, route_id: str, *, placed: bool
) -> Detour:
    start = StartPoint(node_id=11, lon=-75.1716, lat=39.9385) if placed else None
    match = RouteMatch(feed=feed, route_id=route_id, start_point=start)
    return Detour(notice=notice, match=match)


def entry(route_id: str, feed: Feed = "bus", **changes: object) -> dict[str, object]:
    """The expected entry for a ``ROUTES`` row with no detours."""
    row = ROUTES.filter(pl.col("route_id") == route_id, pl.col("feed") == feed).row(
        0, named=True
    )
    key = f"{feed}-{route_id}"
    bounds = BOUNDS.get(key)
    expected: dict[str, object] = {
        "key": key,
        "feed": feed,
        "route_id": route_id,
        "short_name": row["route_short_name"],
        "long_name": row["route_long_name"],
        "mode": {1: "metro", 2: "rail", 3: "bus"}[row["route_type"]],
        "color": f"#{row['route_color']}",
        "text_color": f"#{row['route_text_color']}",
        "has_shapes": bounds is not None,
        "bounds": bounds,
        "detours": {"total": 0, "placed": 0, "windows": []},
    }
    return expected | changes


def test_catalog_whole_output(notice: DetourNotice) -> None:
    # The fixture runs 2026-11-11 06:30 to 2026-11-27 16:00 (-05:00).
    later = notice.model_copy(
        update={"start": datetime(2026, 12, 1, 9, 15, tzinfo=PHILLY), "end": None}
    )
    no_start = notice.model_copy(update={"start": None})
    detours = [
        on_route(notice, "bus", "2", placed=True),
        on_route(later, "bus", "21", placed=False),
        Detour(notice=notice, match=None),  # unmatched: skipped, not counted
        on_route(no_start, "bus", "2", placed=False),
        on_route(later, "bus", "2", placed=True),
    ]
    assert route_catalog(ROUTES, BOUNDS, detours) == [
        entry("L1"),
        entry(
            "2",
            detours={
                "total": 3,
                "placed": 2,
                "windows": [  # snapshot order, placed or not
                    ("2026-11-11T06:30:00-05:00", "2026-11-27T16:00:00-05:00"),
                    (None, "2026-11-27T16:00:00-05:00"),
                    ("2026-12-01T09:15:00-05:00", None),
                ],
            },
        ),
        entry(
            "21",
            detours={
                "total": 1,
                "placed": 0,
                "windows": [("2026-12-01T09:15:00-05:00", None)],
            },
        ),
        entry("T_BUS"),
        entry("AIR", feed="rail"),
    ]


def test_catalog_route_without_bounds_has_no_shapes() -> None:
    [result] = route_catalog(ROUTES.filter(pl.col("route_id") == "T_BUS"), {}, [])
    assert (result["has_shapes"], result["bounds"]) == (False, None)


def test_catalog_empty() -> None:
    assert route_catalog(make_routes([]), {}, []) == []


@pytest.mark.parametrize("short_name", [None, "", "  "])
def test_catalog_short_name_falls_back_to_route_id(short_name: str | None) -> None:
    routes = make_routes([("MANN", short_name, "Mann Shuttle", 3, None, None, "bus")])
    assert route_catalog(routes, {}, [])[0]["short_name"] == "MANN"


@pytest.mark.parametrize("long_name", [None, "", "  "])
def test_catalog_blank_long_name_is_none(long_name: str | None) -> None:
    routes = make_routes([("K", "K", long_name, 3, None, None, "bus")])
    assert route_catalog(routes, {}, [])[0]["long_name"] is None


def test_catalog_names_are_stripped() -> None:
    routes = make_routes([("K", " K ", " Kensington ", 3, None, None, "bus")])
    [result] = route_catalog(routes, {}, [])
    assert (result["short_name"], result["long_name"]) == ("K", "Kensington")


def test_catalog_missing_or_malformed_colors_are_none() -> None:
    routes = make_routes([("K", "K", "Kensington", 3, None, "#FFF", "bus")])
    [result] = route_catalog(routes, {}, [])
    assert (result["color"], result["text_color"]) == (None, None)


@pytest.mark.parametrize("order", [["X2", "X1"], ["X1", "X2"]])
def test_catalog_equal_names_sort_by_key(order: list[str]) -> None:
    routes = make_routes([(rid, "9", None, 3, None, None, "bus") for rid in order])
    assert [e["key"] for e in route_catalog(routes, {}, [])] == ["bus-X1", "bus-X2"]


def test_catalog_same_route_id_in_both_feeds_is_two_routes() -> None:
    routes = make_routes(
        [
            ("WTR", "WTR", None, 2, None, None, "rail"),
            ("WTR", "WTR", None, 3, None, None, "bus"),
        ]
    )
    assert [e["key"] for e in route_catalog(routes, {}, [])] == ["bus-WTR", "rail-WTR"]


def test_catalog_does_not_share_bounds_lists() -> None:
    bounds = {"bus-2": ([-75.18, 39.91], [-75.16, 40.04])}
    [result] = route_catalog(ROUTES.filter(pl.col("route_id") == "2"), bounds, [])
    assert result["bounds"] is not None
    result["bounds"][0][0] = 0.0
    assert bounds["bus-2"] == ([-75.18, 39.91], [-75.16, 40.04])


def test_catalog_rejects_a_duplicate_route() -> None:
    routes = make_routes([("2", "2", None, 3, None, None, "bus")] * 2)
    with pytest.raises(ValueError, match="'bus-2' appears more than once"):
        route_catalog(routes, {}, [])


def test_catalog_rejects_an_unknown_route_type() -> None:
    routes = make_routes([("F1", "F1", None, 4, None, None, "bus")])
    with pytest.raises(ValueError, match="unknown route_type 4"):
        route_catalog(routes, {}, [])


def test_catalog_rejects_an_unsafe_route_id() -> None:
    routes = make_routes([("2/x", "2", None, 3, None, None, "bus")])
    with pytest.raises(ValueError, match="not safe to use as a key"):
        route_catalog(routes, {}, [])


def test_catalog_rejects_bounds_for_an_unknown_route() -> None:
    bounds = BOUNDS | {"bus-99": ([-75.1, 40.0], [-75.0, 40.1])}
    with pytest.raises(
        ValueError, match=r"bounds for routes not in routes: \['bus-99'\]"
    ):
        route_catalog(ROUTES, bounds, [])


def test_catalog_rejects_a_detour_on_an_unknown_route(notice: DetourNotice) -> None:
    detours = [on_route(notice, "rail", "21", placed=False)]  # 21 is a bus route
    with pytest.raises(
        ValueError, match=f"{notice.source_key} is on unknown route 'rail-21'"
    ):
        route_catalog(ROUTES, BOUNDS, detours)


# --- detour_object ---------------------------------------------------------------


@pytest.fixture
def notices(read_alert_fixture) -> Callable[[str], list[DetourNotice]]:
    """Fixture route name (``bus_route_2``) -> its parsed notices."""
    stamp = "2026-11-25T025344Z"

    def parse(route: str) -> list[DetourNotice]:
        content = read_alert_fixture(f"{stamp}__{route}.json")
        return parse_snapshot(b"[" + content + b"]", f"{stamp}.json")

    return parse


def with_shapes(
    notice: DetourNotice, shapes: Sequence[tuple[str, int | None]], feed: Feed = "bus"
) -> Detour:
    match = RouteMatch(
        feed=feed,
        route_id="2" if feed == "bus" else "AIR",
        shapes=tuple(AffectedShape(shape_id=s, direction_id=d) for s, d in shapes),
        start_point=None,
    )
    return Detour(notice=notice, match=match)


# Route 2 #0's real skipped stretch, cut to its first two and last point.
# The second point is ~1 m from the first, so the 2 m simplification
# drops it; the rest are rounded to 5 decimals.
ROUTE_2_SKIPPED = (
    (-75.17157596637267, 39.93846011209412),
    (-75.171579, 39.93845),
    (-75.17460535658819, 39.92455858152203),
)


# Route 2 #0's walked path, first block: the start, a point ~1 m off the
# straight line (dropped at 2 m), the Broad corner, a block south on
# Broad. Rounded to 5 decimals.
ROUTE_2_PATH = (
    (-75.171604, 39.938503),
    (-75.1706, 39.93851),
    (-75.1696, 39.9385),
    (-75.16963, 39.937),
)


def test_detour_object_matched_and_placed(notices) -> None:
    # Route 2 #0 with its real match: SB shape, start at 17th & Washington,
    # rejoin at Passyunk & 17th.
    match = RouteMatch(
        feed="bus",
        route_id="2",
        shapes=(AffectedShape(shape_id="317310", direction_id=0),),
        start_point=StartPoint(node_id=110024066, lon=-75.1716, lat=39.9385),
        rejoin_point=StartPoint(node_id=110024247, lon=-75.1746167, lat=39.9245599),
        skipped=SkippedStretch(shape_id="317310", line=ROUTE_2_SKIPPED),
        path=ROUTE_2_PATH,
        rejoin_by="crossing",
    )
    detour = Detour(notice=notices("bus_route_2")[0], match=match, issues=("x: y",))
    assert detour_object(detour) == {
        "source_key": "5d0d22dfe7d86935",
        "route": "bus-2",
        "status": "complete",
        "direction": "SB",
        "direction_id": 0,
        "location_start": "17th & Washington",
        "location_end": "17th & Mifflin",
        "start": "2026-11-11T06:30:00-05:00",
        "end": "2026-11-27T16:00:00-05:00",
        "reason": "Contractor",
        "message": "7am - 4pm Mon thru Fri, 11/27/26, SB via 17th, Left on "
        "Washington, Right on Broad, Right on Passyunk, Left on 17th, Reg Rt",
        "issues": ["x: y"],
        "start_point": {"lon": -75.1716, "lat": 39.9385, "node_id": 110024066},
        "rejoin_point": {"lon": -75.1746167, "lat": 39.9245599, "node_id": 110024247},
        "rejoin_streets": ["Passyunk", "17th"],
        "skipped": [[-75.17158, 39.93846], [-75.17461, 39.92456]],
        "path": [[-75.1716, 39.9385], [-75.1696, 39.9385], [-75.16963, 39.937]],
        "shape_ids": ["317310"],
    }


def test_detour_object_unmatched(notices) -> None:
    # Route 68 #0: partial, a parse issue, a summer start and a winter end.
    notice = notices("bus_route_68")[0]
    detour = Detour(notice=notice, match=None, issues=("route: none",))
    assert detour_object(detour) == {
        "source_key": "697e7d24611e9d37",
        "route": "bus_route_68",
        "status": "partial",
        "direction": "EB",
        "direction_id": None,
        "location_start": "PNC Center",
        "location_end": "PNC Center",
        "start": "2026-09-05T17:58:00-04:00",
        "end": "2026-12-30T12:00:00-05:00",
        "reason": "Sidewalk Repair",
        "message": notice.source.message,
        "issues": ["location_start: unrecognized location 'PNC Center'", "route: none"],
        "start_point": None,
        "rejoin_point": None,
        "rejoin_streets": None,
        "skipped": None,
        "path": None,
        "shape_ids": [],
    }


@pytest.mark.parametrize(
    ("shapes", "direction_id"),
    [
        ([], None),
        ([("317310", 0)], 0),
        ([("317312", 1), ("317313", 1)], 1),
        ([("317310", 0), ("317312", 1)], None),
        ([("317310", None)], None),
        ([("317310", 0), ("317311", None)], None),
    ],
)
def test_detour_object_direction_id_only_when_shapes_agree(
    notices, shapes: list[tuple[str, int | None]], direction_id: int | None
) -> None:
    result = detour_object(with_shapes(notices("bus_route_2")[0], shapes))
    assert result["direction_id"] == direction_id


def test_detour_object_shape_ids_keep_match_order(notices) -> None:
    shapes = [("317312", 1), ("317310", 1), ("317311", 1)]
    result = detour_object(with_shapes(notices("bus_route_2")[0], shapes))
    assert result["shape_ids"] == ["317312", "317310", "317311"]


def test_detour_object_matched_but_not_placed(notices) -> None:
    result = detour_object(with_shapes(notices("bus_route_2")[0], [("317310", 0)]))
    assert (result["route"], result["start_point"]) == ("bus-2", None)


def test_detour_object_rail_route_key(notices) -> None:
    result = detour_object(with_shapes(notices("bus_route_2")[0], [], feed="rail"))
    assert result["route"] == "rail-AIR"


NOTICE_UNKNOWNS = (
    "start",
    "end",
    "location_start",
    "location_end",
    "reason",
    "direction",
)


def test_detour_object_unknowns_are_null(notices) -> None:
    unknown = dict.fromkeys((*NOTICE_UNKNOWNS, "start_place", "end_place"))
    original = notices("bus_route_2")[0]
    notice = DetourNotice.model_validate(
        original.model_copy(update=unknown).model_dump()
    )
    result = detour_object(Detour(notice=notice, match=None))
    assert {field: result[field] for field in NOTICE_UNKNOWNS} == dict.fromkeys(
        NOTICE_UNKNOWNS
    )
    assert (result["status"], result["issues"]) == ("unknown", [])


def test_detour_object_is_json_with_issues_as_a_list(notices) -> None:
    detour = Detour(notice=notices("bus_route_68")[0], match=None, issues=("a", "b"))
    decoded = json.loads(json.dumps(detour_object(detour), allow_nan=False))
    assert decoded["issues"] == [
        "location_start: unrecognized location 'PNC Center'",
        "a",
        "b",
    ]


def test_detour_object_message_is_verbatim(notices) -> None:
    # rr_route_mfo #1's real message ends with trailing spaces.
    notice = notices("rr_route_mfo")[1]
    assert notice.source.message != notice.source.message.rstrip()
    result = detour_object(Detour(notice=notice, match=None))
    assert result["message"] == notice.source.message


# --- route_detail ----------------------------------------------------------------

ROUTE_2: RouteEntry = {
    "key": "bus-2",
    "feed": "bus",
    "route_id": "2",
    "short_name": "2",
    "long_name": "16th-17th",
    "mode": "bus",
    "color": "#00A1DE",
    "text_color": "#FFFFFF",
    "has_shapes": True,
    "bounds": ([-75.18, 39.91], [-75.16, 40.04]),
    "detours": {"total": 2, "placed": 1, "windows": []},  # not read by these builders
}
# Route 2's real directions.txt rows.
ROUTE_2_DIRECTIONS: list[DirectionEntry] = [
    {"direction_id": 0, "name": "Southbound", "destination": "20th-Johnston"},
    {"direction_id": 1, "name": "Northbound", "destination": "Pulaski-Hunting Park"},
]
# Every line distinct, lon ~ -75, lat ~ 40; trip counts all different.
SOUTH = RouteShape("317310", 0, 301, True, [[-75.1716, 39.9405], [-75.1716, 39.9365]])
NORTH = RouteShape("317312", 1, 289, True, [[-75.1706, 39.9365], [-75.1706, 39.9405]])
SHORT = RouteShape("317315", 0, 14, False, [[-75.1716, 39.9405], [-75.1716, 39.9385]])


def line(shape: RouteShape, color: str | None = "#00A1DE") -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": shape.line},
        "properties": {
            "shape_id": shape.shape_id,
            "direction_id": shape.direction_id,
            "trip_count": shape.trip_count,
            "covering": shape.covering,
            "color": color,
        },
    }


def test_route_detail_whole_output(notices) -> None:
    route_2 = notices("bus_route_2")
    placed = Detour(
        notice=route_2[0],
        match=RouteMatch(
            feed="bus",
            route_id="2",
            shapes=(AffectedShape(shape_id="317310", direction_id=0),),
            start_point=StartPoint(node_id=110024066, lon=-75.1716, lat=39.9385),
        ),
    )
    not_placed = with_shapes(route_2[1], [("317310", 0)])
    detail = route_detail(
        ROUTE_2, ROUTE_2_DIRECTIONS, [SOUTH, SHORT, NORTH], [not_placed, placed]
    )
    assert detail == {
        "schema_version": 6,
        "key": "bus-2",
        "directions": ROUTE_2_DIRECTIONS,
        "shapes": {
            "type": "FeatureCollection",
            "features": [line(SOUTH), line(SHORT), line(NORTH)],
        },
        "detours": [detour_object(not_placed), detour_object(placed)],
    }


def test_route_detail_shape_properties_are_the_contract_ones() -> None:
    detail = route_detail(ROUTE_2, [], [SOUTH, NORTH], [])
    for feature in detail["shapes"]["features"]:
        assert tuple(feature["properties"]) == SHAPE_PROPERTIES


def test_route_detail_shape_in_both_directions_is_two_lines() -> None:
    both = [SOUTH, SOUTH._replace(direction_id=1, trip_count=3, covering=False)]
    detail = route_detail(ROUTE_2, [], both, [])
    assert detail["shapes"]["features"] == [line(both[0]), line(both[1])]


def test_route_detail_color_comes_from_the_entry() -> None:
    entry: RouteEntry = {**ROUTE_2, "color": None}
    detail = route_detail(entry, [], [SOUTH], [])
    assert detail["shapes"]["features"] == [line(SOUTH, color=None)]


def test_route_detail_without_shapes_or_detours() -> None:
    entry: RouteEntry = {**ROUTE_2, "has_shapes": False, "bounds": None}
    detail = route_detail(entry, ROUTE_2_DIRECTIONS, [], [])
    assert detail["shapes"] == {"type": "FeatureCollection", "features": []}
    assert detail["detours"] == []


def test_route_detail_does_not_share_directions() -> None:
    directions: list[DirectionEntry] = [
        {"direction_id": 0, "name": "Southbound", "destination": "20th-Johnston"}
    ]
    detail = route_detail(ROUTE_2, directions, [], [])
    detail["directions"][0]["name"] = "Northbound"
    assert directions[0]["name"] == "Southbound"


def test_route_detail_rejects_a_detour_on_another_route(notices) -> None:
    detour = with_shapes(notices("bus_route_2")[0], [], feed="rail")
    with pytest.raises(ValueError, match="is on 'rail-AIR', not 'bus-2'"):
        route_detail(ROUTE_2, [], [], [detour])


def test_route_detail_rejects_an_unmatched_detour(notices) -> None:
    detour = Detour(notice=notices("bus_route_2")[0], match=None)
    with pytest.raises(ValueError, match="is on 'bus_route_2', not 'bus-2'"):
        route_detail(ROUTE_2, [], [], [detour])


def test_route_detail_rejects_a_one_point_shape() -> None:
    shape = SOUTH._replace(line=[[-75.1716, 39.9405]])
    with pytest.raises(ValueError, match="317310"):
        route_detail(ROUTE_2, [], [shape], [])


# --- route_shapes ----------------------------------------------------------------

# Must match ``load.load_trips`` and ``shapes.shape_coordinates`` output.
TRIPS_SCHEMA = {
    "route_id": pl.String,
    "service_id": pl.String,
    "trip_id": pl.String,
    "trip_headsign": pl.String,
    "direction_id": pl.Int8,
    "shape_id": pl.String,
    "feed": pl.String,
}
COORDINATES_SCHEMA = {
    "feed": pl.String,
    "shape_id": pl.String,
    "coordinates": pl.List(pl.List(pl.Float64)),
}


def make_trips(
    rows: list[tuple[Feed, str, int | None, str | None, int]],
) -> pl.DataFrame:
    """``(feed, route_id, direction_id, shape_id, trip count)`` -> trips."""
    trips = [
        (
            route_id,
            "WK",
            f"{route_id}-{shape_id}-{n}",
            None,
            direction_id,
            shape_id,
            feed,
        )
        for feed, route_id, direction_id, shape_id, count in rows
        for n in range(count)
    ]
    return pl.DataFrame(trips, schema=TRIPS_SCHEMA, orient="row")


def make_coordinates(lines: dict[tuple[Feed, str], list[list[float]]]) -> pl.DataFrame:
    rows = [(feed, shape_id, line) for (feed, shape_id), line in lines.items()]
    return pl.DataFrame(rows, schema=COORDINATES_SCHEMA, orient="row")


# Raw lines: 6 decimals (rounding shows); 317310's midpoint is 0.85 m off
# its line (dropped at 2 m, not at 0). 317315 is a short-turn along 317310
# ending 8.5 m beside it (covered at 20 m, not at 0).
# "001005" exists in both feeds with different lines: feed must be used.
RAW_LINES: dict[tuple[Feed, str], list[list[float]]] = {
    ("bus", "317310"): [
        [-75.171612, 39.940512],
        [-75.171602, 39.938512],
        [-75.171612, 39.936512],
    ],
    ("bus", "317315"): [[-75.171612, 39.940512], [-75.171512, 39.938512]],
    ("bus", "317312"): [[-75.170612, 39.936512], [-75.170612, 39.940512]],
    ("bus", "001005"): [[-75.0, 40.1], [-75.0, 40.2]],
    ("rail", "001005"): [[-75.241234, 39.876543], [-75.201234, 39.906543]],
}
COORDINATES = make_coordinates(RAW_LINES)


def test_route_shapes_whole_output() -> None:
    trips = make_trips(
        [
            ("bus", "2", 0, "317315", 5),
            ("bus", "2", 1, "317312", 2),
            ("bus", "2", 0, "317310", 3),
            ("rail", "AIR", 1, "001005", 4),
        ]
    )
    assert route_shapes(trips, COORDINATES) == {
        "bus-2": [
            RouteShape(
                "317310", 0, 3, True, [[-75.17161, 39.94051], [-75.17161, 39.93651]]
            ),
            RouteShape(
                "317315", 0, 5, False, [[-75.17161, 39.94051], [-75.17151, 39.93851]]
            ),
            RouteShape(
                "317312", 1, 2, True, [[-75.17061, 39.93651], [-75.17061, 39.94051]]
            ),
        ],
        "rail-AIR": [
            RouteShape(
                "001005", 1, 4, True, [[-75.24123, 39.87654], [-75.20123, 39.90654]]
            )
        ],
    }


@pytest.mark.parametrize("tied", [("b", "a"), ("a", "b")])
def test_route_shapes_order_within_a_direction(tied: tuple[str, str]) -> None:
    # Three separate branches (all covering) and a direction-less shape.
    # The tied pair comes in both orders, so the result can't be input order.
    lines: dict[tuple[Feed, str], list[list[float]]] = {
        ("bus", "b"): [[-75.10, 40.00], [-75.10, 40.01]],
        ("bus", "a"): [[-75.12, 40.00], [-75.12, 40.01]],
        ("bus", "c"): [[-75.14, 40.00], [-75.14, 40.01]],
        ("bus", "n"): [[-75.16, 40.00], [-75.16, 40.01]],
    }
    trips = make_trips(
        [
            ("bus", "9", None, "n", 9),
            ("bus", "9", 1, tied[0], 2),
            ("bus", "9", 1, "c", 7),
            ("bus", "9", 1, tied[1], 2),
            ("bus", "9", 0, "b", 1),
        ]
    )
    result = route_shapes(trips, make_coordinates(lines))
    assert [(s.direction_id, s.shape_id) for s in result["bus-9"]] == [
        (0, "b"),
        (1, "c"),  # most trips
        (1, "a"),  # tie on trips: by shape_id
        (1, "b"),
        (None, "n"),  # no direction: last
    ]


def test_route_shapes_shape_in_both_directions_is_two_separate_shapes() -> None:
    trips = make_trips([("bus", "2", 0, "317312", 1), ("bus", "2", 1, "317312", 6)])
    first, second = route_shapes(trips, COORDINATES)["bus-2"]
    assert [(s.direction_id, s.trip_count) for s in (first, second)] == [(0, 1), (1, 6)]
    assert first.line == second.line
    assert first.line is not second.line


def test_route_shapes_skips_trips_without_a_shape() -> None:
    trips = make_trips([("bus", "2", 0, "317310", 1), ("bus", "47", 0, None, 3)])
    assert list(route_shapes(trips, COORDINATES)) == ["bus-2"]


def test_route_shapes_no_trips() -> None:
    assert route_shapes(make_trips([]), COORDINATES) == {}


def test_route_shapes_rejects_a_shape_without_coordinates() -> None:
    trips = make_trips([("bus", "2", 0, "317310", 1), ("rail", "AIR", 0, "317310", 1)])
    with pytest.raises(ValueError, match=r"no coordinates: \[\('rail', '317310'\)\]"):
        route_shapes(trips, COORDINATES)


# --- route_directions --------------------------------------------------------------

# Must match ``load.load_directions`` output.
DIRECTIONS_SCHEMA = {
    "route_id": pl.String,
    "direction_id": pl.Int8,
    "direction": pl.String,
    "direction_destination": pl.String,
    "feed": pl.String,
}


def make_directions(
    rows: list[tuple[str, int | None, str | None, str | None, Feed]],
) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=DIRECTIONS_SCHEMA, orient="row")


def shape_in(direction_id: int | None) -> RouteShape:
    return RouteShape(
        "317310", direction_id, 1, True, [[-75.17, 39.94], [-75.17, 39.93]]
    )


def test_route_directions_whole_output() -> None:
    # Real rows for route 2 (out of order) and the Airport Line.
    directions = make_directions(
        [
            ("2", 1, "Northbound", "Pulaski-Hunting Park", "bus"),
            ("AIR", 0, "Inbound", "Center City Philadelphia", "rail"),
            ("2", 0, "Southbound", "20th-Johnston", "bus"),
            ("AIR", 1, "Outbound", "Philadelphia International Airport", "rail"),
        ]
    )
    shapes = {"bus-2": [shape_in(0), shape_in(1)]}
    assert route_directions(directions, shapes) == {
        "bus-2": ROUTE_2_DIRECTIONS,
        "rail-AIR": [
            {
                "direction_id": 0,
                "name": "Inbound",
                "destination": "Center City Philadelphia",
            },
            {
                "direction_id": 1,
                "name": "Outbound",
                "destination": "Philadelphia International Airport",
            },
        ],
    }


def test_route_directions_adds_a_drawn_direction_the_file_lacks() -> None:
    directions = make_directions(
        [("2", 1, "Northbound", "Pulaski-Hunting Park", "bus")]
    )
    shapes = {"bus-2": [shape_in(1), shape_in(0), shape_in(None)]}
    assert route_directions(directions, shapes) == {
        "bus-2": [
            {"direction_id": 0, "name": None, "destination": None},
            {
                "direction_id": 1,
                "name": "Northbound",
                "destination": "Pulaski-Hunting Park",
            },
        ]
    }


def test_route_directions_route_only_in_shapes() -> None:
    assert route_directions(make_directions([]), {"bus-9": [shape_in(1)]}) == {
        "bus-9": [{"direction_id": 1, "name": None, "destination": None}]
    }


def test_route_directions_route_without_shapes_keeps_its_rows() -> None:
    directions = make_directions([("MANN", 0, "Loop", "Mann Center", "bus")])
    assert route_directions(directions, {}) == {
        "bus-MANN": [{"direction_id": 0, "name": "Loop", "destination": "Mann Center"}]
    }


def test_route_directions_shape_without_direction_adds_nothing() -> None:
    assert route_directions(make_directions([]), {"bus-9": [shape_in(None)]}) == {
        "bus-9": []
    }


@pytest.mark.parametrize(
    ("name", "destination", "expected"),
    [
        ("Inbound\r", " Center City ", ("Inbound", "Center City")),
        ("", "  ", (None, None)),
        (None, None, (None, None)),
    ],
)
def test_route_directions_names_are_stripped(
    name: str | None, destination: str | None, expected: tuple[str | None, str | None]
) -> None:
    directions = make_directions([("AIR", 0, name, destination, "rail")])
    [entry] = route_directions(directions, {})["rail-AIR"]
    assert (entry["name"], entry["destination"]) == expected


def test_route_directions_same_route_id_in_both_feeds() -> None:
    directions = make_directions(
        [("WTR", 0, "Inbound", None, "rail"), ("WTR", 0, "Eastbound", None, "bus")]
    )
    result = route_directions(directions, {})
    assert (result["rail-WTR"][0]["name"], result["bus-WTR"][0]["name"]) == (
        "Inbound",
        "Eastbound",
    )


def test_route_directions_rejects_a_duplicate() -> None:
    directions = make_directions([("2", 0, "Southbound", None, "bus")] * 2)
    with pytest.raises(
        ValueError, match="direction 0 of 'bus-2' appears more than once"
    ):
        route_directions(directions, {})


def test_route_directions_rejects_a_missing_direction_id() -> None:
    directions = make_directions([("2", None, "Southbound", None, "bus")])
    with pytest.raises(ValueError, match="'bus-2' has no direction_id"):
        route_directions(directions, {})


# --- network_collection ------------------------------------------------------------

AIR: RouteEntry = {
    "key": "rail-AIR",
    "feed": "rail",
    "route_id": "AIR",
    "short_name": "AIR",
    "long_name": "Airport Line",
    "mode": "rail",
    "color": "#5A6F7B",
    "text_color": "#FFFFFF",
    "has_shapes": True,
    "bounds": ([-75.25, 39.87], [-75.16, 39.96]),
    "detours": {"total": 0, "placed": 0, "windows": []},
}
# Raw lines. 317312's midpoint is 3.4 m off its line: kept at 2 m, dropped
# at 5 m. "001005" is in both feeds with different lines.
NETWORK_RAW = make_coordinates(
    {
        ("bus", "317310"): [[-75.171612, 39.940512], [-75.171612, 39.936512]],
        ("bus", "317312"): [
            [-75.170612, 39.936512],
            [-75.170652, 39.938512],
            [-75.170612, 39.940512],
        ],
        ("bus", "001005"): [[-75.0, 40.1], [-75.0, 40.2]],
        ("rail", "001005"): [[-75.241234, 39.876543], [-75.201234, 39.906543]],
    }
)
# ``line`` isn't used by network_collection (it reads the raw lines).
UNUSED_LINE = [[0.0, 0.0], [1.0, 1.0]]


def overview(
    entry: RouteEntry, direction_id: int | None, coordinates: list[list[float]]
):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {
            "key": entry["key"],
            "direction_id": direction_id,
            "mode": entry["mode"],
            "color": entry["color"],
        },
    }


def test_network_whole_output() -> None:
    shapes = {
        "rail-AIR": [RouteShape("001005", 1, 4, True, UNUSED_LINE)],
        "bus-2": [
            RouteShape("317310", 0, 3, True, UNUSED_LINE),
            RouteShape("317315", 0, 5, False, UNUSED_LINE),  # not drawn
            RouteShape("317312", 1, 2, True, UNUSED_LINE),
        ],
    }
    assert network_collection([ROUTE_2, AIR], shapes, NETWORK_RAW) == {
        "type": "FeatureCollection",
        "features": [
            overview(ROUTE_2, 0, [[-75.17161, 39.94051], [-75.17161, 39.93651]]),
            overview(ROUTE_2, 1, [[-75.17061, 39.93651], [-75.17061, 39.94051]]),
            overview(AIR, 1, [[-75.24123, 39.87654], [-75.20123, 39.90654]]),
        ],
    }


def test_network_properties_are_the_contract_ones() -> None:
    shapes = {"bus-2": [RouteShape("317310", 0, 3, True, UNUSED_LINE)]}
    [feature] = network_collection([ROUTE_2], shapes, NETWORK_RAW)["features"]
    assert tuple(feature["properties"]) == NETWORK_PROPERTIES


def test_network_shape_covering_both_directions_is_two_lines() -> None:
    shapes = {
        "bus-2": [
            RouteShape("317310", 0, 3, True, UNUSED_LINE),
            RouteShape("317310", 1, 1, True, UNUSED_LINE),
        ]
    }
    line = [[-75.17161, 39.94051], [-75.17161, 39.93651]]
    assert network_collection([ROUTE_2], shapes, NETWORK_RAW)["features"] == [
        overview(ROUTE_2, 0, line),
        overview(ROUTE_2, 1, line),
    ]


def test_network_route_without_shapes_draws_nothing() -> None:
    entry: RouteEntry = {**ROUTE_2, "has_shapes": False, "bounds": None}
    assert network_collection([entry], {}, NETWORK_RAW)["features"] == []


def test_network_color_may_be_null() -> None:
    entry: RouteEntry = {**ROUTE_2, "color": None}
    shapes = {"bus-2": [RouteShape("317310", 0, 3, True, UNUSED_LINE)]}
    [feature] = network_collection([entry], shapes, NETWORK_RAW)["features"]
    assert feature["properties"]["color"] is None


def test_network_rejects_shapes_for_a_route_not_in_the_catalog() -> None:
    shapes = {"bus-9": [RouteShape("317310", 0, 3, True, UNUSED_LINE)]}
    with pytest.raises(ValueError, match=r"not in the catalog: \['bus-9'\]"):
        network_collection([ROUTE_2], shapes, NETWORK_RAW)


def test_network_rejects_a_covering_shape_without_coordinates() -> None:
    shapes = {"rail-AIR": [RouteShape("317310", 0, 3, True, UNUSED_LINE)]}
    with pytest.raises(ValueError, match=r"\('rail', '317310'\) has no coordinates"):
        network_collection([AIR], shapes, NETWORK_RAW)


PHILLY = ZoneInfo("America/New_York")


# --- starts_collection -------------------------------------------------------------

# Route 2 #0, #2 and #4's real overall windows, as features carry them.
WINDOW_0 = ("2026-11-11T06:30:00-05:00", "2026-11-27T16:00:00-05:00")
WINDOW_2 = ("2026-11-25T15:00:00-05:00", "2026-11-26T02:00:00-05:00")
WINDOW_4 = ("2026-11-24T19:33:00-05:00", "2026-11-25T08:00:00-05:00")


def placed_at(
    notice: DetourNotice,
    lon: float,
    lat: float,
    feed: Feed = "bus",
    route_id: str = "2",
) -> Detour:
    start = StartPoint(node_id=110024066, lon=lon, lat=lat)
    return Detour(
        notice=notice,
        match=RouteMatch(feed=feed, route_id=route_id, start_point=start),
    )


def dot(
    lon: float,
    lat: float,
    key: str,
    source_key: str,
    color: str | None,
    window: tuple[str | None, str | None],
):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "key": key,
            "source_key": source_key,
            "color": color,
            "start": window[0],
            "end": window[1],
        },
    }


def test_starts_whole_output(notices) -> None:
    # Each dot carries its detour's overall window (the page times it).
    route_2 = notices("bus_route_2")
    detours = [
        placed_at(route_2[2], -75.1690, 39.9620),
        with_shapes(route_2[1], [("317310", 0)]),  # matched, not placed
        Detour(notice=route_2[3], match=None),  # unmatched
        placed_at(route_2[4], -75.2345, 39.8765, feed="rail", route_id="AIR"),
        placed_at(route_2[0], -75.1716, 39.9385),
    ]
    assert starts_collection([ROUTE_2, AIR], detours) == {
        "type": "FeatureCollection",
        "features": [
            dot(-75.1690, 39.9620, "bus-2", "f92dcfe1cd1904c8", "#00A1DE", WINDOW_2),
            dot(-75.2345, 39.8765, "rail-AIR", "ff53152c4c7f9011", "#5A6F7B", WINDOW_4),
            dot(-75.1716, 39.9385, "bus-2", "5d0d22dfe7d86935", "#00A1DE", WINDOW_0),
        ],
    }


def test_starts_properties_are_the_contract_ones(notices) -> None:
    detours = [placed_at(notices("bus_route_2")[0], -75.1716, 39.9385)]
    [feature] = starts_collection([ROUTE_2], detours)["features"]
    assert tuple(feature["properties"]) == START_PROPERTIES


def test_starts_color_may_be_null(notices) -> None:
    entry: RouteEntry = {**ROUTE_2, "color": None}
    detours = [placed_at(notices("bus_route_2")[0], -75.1716, 39.9385)]
    [feature] = starts_collection([entry], detours)["features"]
    assert feature["properties"]["color"] is None


def test_starts_no_placed_detours(notices) -> None:
    detours = [Detour(notice=notices("bus_route_2")[0], match=None)]
    assert starts_collection([ROUTE_2], detours) == {
        "type": "FeatureCollection",
        "features": [],
    }


def test_starts_rejects_a_route_not_in_the_catalog(notices) -> None:
    notice = notices("bus_route_2")[0]
    detours = [placed_at(notice, -75.1716, 39.9385, route_id="21")]
    with pytest.raises(
        ValueError, match=f"{notice.source_key} is on unknown route 'bus-21'"
    ):
        starts_collection([ROUTE_2], detours)


# --- skipped_collection -----------------------------------------------------------


def skipping(
    notice: DetourNotice,
    line: tuple[tuple[float, float], ...],
    feed: Feed = "bus",
    route_id: str = "2",
) -> Detour:
    """A placed detour with a skipped stretch along ``line``."""
    start = StartPoint(node_id=110024066, lon=line[0][0], lat=line[0][1])
    match = RouteMatch(
        feed=feed,
        route_id=route_id,
        start_point=start,
        skipped=SkippedStretch(shape_id="317310", line=line),
    )
    return Detour(notice=notice, match=match)


def stretch_feature(
    line: list[list[float]],
    key: str,
    source_key: str,
    color: str | None,
    window: tuple[str | None, str | None],
):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": line},
        "properties": {
            "key": key,
            "source_key": source_key,
            "color": color,
            "start": window[0],
            "end": window[1],
        },
    }


AIR_STRETCH = ((-75.2345, 39.8765), (-75.2301, 39.8812))


def test_skipped_whole_output(notices) -> None:
    # Windows as in test_starts_whole_output; only detours with a stretch.
    route_2 = notices("bus_route_2")
    detours = [
        placed_at(route_2[2], -75.1690, 39.9620),  # placed, no stretch
        Detour(notice=route_2[3], match=None),  # unmatched
        skipping(route_2[4], AIR_STRETCH, feed="rail", route_id="AIR"),
        skipping(route_2[0], ROUTE_2_SKIPPED),
    ]
    assert skipped_collection([ROUTE_2, AIR], detours) == {
        "type": "FeatureCollection",
        "features": [
            stretch_feature(
                [[-75.2345, 39.8765], [-75.2301, 39.8812]],
                "rail-AIR",
                "ff53152c4c7f9011",
                "#5A6F7B",
                WINDOW_4,
            ),
            stretch_feature(
                [[-75.17158, 39.93846], [-75.17461, 39.92456]],  # as the detour object
                "bus-2",
                "5d0d22dfe7d86935",
                "#00A1DE",
                WINDOW_0,
            ),
        ],
    }


def test_skipped_properties_are_the_contract_ones(notices) -> None:
    assert SKIPPED_PROPERTIES == START_PROPERTIES
    detours = [skipping(notices("bus_route_2")[0], ROUTE_2_SKIPPED)]
    [feature] = skipped_collection([ROUTE_2], detours)["features"]
    assert tuple(feature["properties"]) == SKIPPED_PROPERTIES


def test_skipped_rejects_a_route_not_in_the_catalog(notices) -> None:
    notice = notices("bus_route_2")[0]
    detours = [skipping(notice, ROUTE_2_SKIPPED, route_id="21")]
    with pytest.raises(
        ValueError, match=f"{notice.source_key} is on unknown route 'bus-21'"
    ):
        skipped_collection([ROUTE_2], detours)


# --- paths_collection -------------------------------------------------------------


def walking(
    notice: DetourNotice,
    path: tuple[tuple[float, float], ...] | None,
    *,
    skipped: tuple[tuple[float, float], ...] | None = None,
    feed: Feed = "bus",
    route_id: str = "2",
) -> Detour:
    """A placed detour with a path (and maybe a skipped stretch)."""
    start = StartPoint(node_id=110024066, lon=-75.1716, lat=39.9385)
    stretch = (
        None if skipped is None else SkippedStretch(shape_id="317310", line=skipped)
    )
    match = RouteMatch(
        feed=feed,
        route_id=route_id,
        start_point=start,
        skipped=stretch,
        path=path,
    )
    return Detour(notice=notice, match=match)


AIR_PATH = ((-75.2345, 39.8765), (-75.2401, 39.8799), (-75.2301, 39.8812))


def test_paths_whole_output(notices) -> None:
    # Only detours with a path; a stretch alone isn't one.
    route_2 = notices("bus_route_2")
    detours = [
        walking(route_2[2], None, skipped=ROUTE_2_SKIPPED),  # stretch, no path
        Detour(notice=route_2[3], match=None),  # unmatched
        walking(route_2[4], AIR_PATH, feed="rail", route_id="AIR"),
        walking(route_2[0], ROUTE_2_PATH, skipped=ROUTE_2_SKIPPED),
    ]
    assert paths_collection([ROUTE_2, AIR], detours) == {
        "type": "FeatureCollection",
        "features": [
            stretch_feature(
                [[-75.2345, 39.8765], [-75.2401, 39.8799], [-75.2301, 39.8812]],
                "rail-AIR",
                "ff53152c4c7f9011",
                "#5A6F7B",
                WINDOW_4,
            ),
            stretch_feature(
                [[-75.1716, 39.9385], [-75.1696, 39.9385], [-75.16963, 39.937]],
                "bus-2",
                "5d0d22dfe7d86935",
                "#00A1DE",
                WINDOW_0,
            ),
        ],
    }


def test_path_properties_are_the_contract_ones(notices) -> None:
    assert PATH_PROPERTIES == START_PROPERTIES
    detours = [walking(notices("bus_route_2")[0], ROUTE_2_PATH)]
    [feature] = paths_collection([ROUTE_2], detours)["features"]
    assert tuple(feature["properties"]) == PATH_PROPERTIES


def test_paths_reject_a_route_not_in_the_catalog(notices) -> None:
    notice = notices("bus_route_2")[0]
    detours = [walking(notice, ROUTE_2_PATH, route_id="21")]
    with pytest.raises(
        ValueError, match=f"{notice.source_key} is on unknown route 'bus-21'"
    ):
        paths_collection([ROUTE_2], detours)


# --- status ----------------------------------------------------------------------

SNAPSHOT = "2026-11-25T121123Z.json"
VERSIONS: dict[Feed, str | None] = {"bus": "v202611220", "rail": None}
GENERATED_AT = datetime(2026, 11, 25, 12, 2, 11, 987654, tzinfo=PHILLY)


def test_status_whole_output(notices) -> None:
    route_2 = notices("bus_route_2")
    unmatched = [notices("bus_route_68")[0], route_2[3]]
    detours = [
        placed_at(route_2[0], -75.1716, 39.9385),
        Detour(notice=unmatched[0], match=None, issues=("route: none",)),
        with_shapes(route_2[1], [("317310", 0)]),  # matched, not placed
        Detour(notice=unmatched[1], match=None),
    ]
    assert status(detours, SNAPSHOT, VERSIONS, GENERATED_AT) == {
        "schema_version": 6,
        "generated_at": "2026-11-25T17:02:11Z",
        "snapshot": "2026-11-25T121123Z.json",
        "snapshot_fetched_at": "2026-11-25T12:11:23Z",
        "gtfs": {"bus": "v202611220", "rail": None},
        "detours": {"total": 4, "matched": 2, "placed": 1},
        "unmatched": [detour_object(detours[1]), detour_object(detours[3])],
    }


def test_status_no_detours() -> None:
    result = status([], SNAPSHOT, VERSIONS, GENERATED_AT)
    assert (result["detours"], result["unmatched"]) == (
        {"total": 0, "matched": 0, "placed": 0},
        [],
    )


@pytest.mark.parametrize(
    "snapshot",
    [
        "mine.json",
        "detours-2026-11-25T121123Z.json",
        "2026-11-25T121123Z.json.bak",
        "2026-11-25T121123Z",
        "2026-13-25T121123Z.json",  # no month 13
        "2026-11-25T251123Z.json",  # no hour 25
        "2026-1-25T121123Z.json",  # strptime alone would accept this
    ],
)
def test_status_hand_named_snapshot_has_no_fetch_time(snapshot: str) -> None:
    result = status([], snapshot, VERSIONS, GENERATED_AT)
    assert (result["snapshot"], result["snapshot_fetched_at"]) == (snapshot, None)


@pytest.mark.parametrize(
    "fetched_at",
    [
        datetime(2026, 11, 25, 12, 11, 23, tzinfo=UTC),
        datetime(2026, 7, 4, 8, 5, 9, tzinfo=PHILLY),  # summer, not UTC
    ],
)
def test_status_reads_names_that_ingest_writes(fetched_at: datetime) -> None:
    # The name pattern is duplicated from ingest on purpose; they must agree.
    name = snapshot_path(fetched_at).name
    result = status([], name, VERSIONS, GENERATED_AT)
    expected = fetched_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert result["snapshot_fetched_at"] == expected


def test_status_does_not_share_versions() -> None:
    versions: dict[Feed, str | None] = {"bus": "v1", "rail": "v2"}
    result = status([], SNAPSHOT, versions, GENERATED_AT)
    versions["bus"] = "v9"
    assert result["gtfs"] == {"bus": "v1", "rail": "v2"}


def test_status_rejects_a_naive_generated_at() -> None:
    with pytest.raises(ValueError, match="generated_at must have a time zone"):
        status([], SNAPSHOT, VERSIONS, datetime(2026, 11, 25, 17, 2, 11))  # noqa: DTZ001


# --- rejoin_streets ----------------------------------------------------------------


def rejoining(
    notice: DetourNotice, rejoin_by: RejoinBy | None, *, rejoin: bool = True
) -> Detour:
    point = StartPoint(node_id=110024247, lon=-75.1746167, lat=39.9245599)
    match = RouteMatch(
        feed="bus",
        route_id="2",
        start_point=None,
        rejoin_point=point if rejoin else None,
        rejoin_by=rejoin_by,
    )
    return Detour(notice=notice, match=match)


def with_steps(notice: DetourNotice, *streets: str) -> DetourNotice:
    def turn(index: int) -> Turn:
        return "via" if index == 0 else "left"

    steps = tuple(Step(turn=turn(i), street=s) for i, s in enumerate(streets))
    return notice.model_copy(update={"route_steps": steps})


def test_rejoin_streets_crossing_is_the_last_two(notices) -> None:
    # Route 2 #0: "..., Right on Passyunk, Left on 17th, Reg Rt".
    detour = rejoining(notices("bus_route_2")[0], "crossing")
    assert rejoin_streets(detour) == ["Passyunk", "17th"]


def test_rejoin_streets_walk_is_the_last_street(notices) -> None:
    notice = with_steps(notices("bus_route_2")[0], "Ridge Ave", "Francis St")
    assert rejoin_streets(rejoining(notice, "walk")) == ["Francis St"]


def test_rejoin_streets_none_without_a_rejoin(notices) -> None:
    notice = notices("bus_route_2")[0]
    assert rejoin_streets(rejoining(notice, None)) is None
    assert rejoin_streets(rejoining(notice, "crossing", rejoin=False)) is None
    assert rejoin_streets(Detour(notice=notice, match=None)) is None


def test_rejoin_streets_none_when_the_steps_cant_name_it(notices) -> None:
    notice = notices("bus_route_2")[0]
    assert rejoin_streets(rejoining(with_steps(notice, "17th"), "crossing")) is None
    assert rejoin_streets(rejoining(with_steps(notice), "walk")) is None
    assert rejoin_streets(rejoining(with_steps(notice, "17th"), "walk")) == ["17th"]
