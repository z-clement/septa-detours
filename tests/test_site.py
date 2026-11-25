from collections.abc import Callable

import polars as pl
import pytest

from septa_detours.export.contract import Mode
from septa_detours.export.site import (
    MODE_ORDER,
    lines_bounds,
    route_catalog,
    route_key,
    route_mode,
    route_sort_key,
)
from septa_detours.export.write import route_geojson_path
from septa_detours.gtfs.load import Feed
from septa_detours.model import Detour, DetourNotice, RouteMatch, StartPoint
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
        "detours": {"total": 0, "placed": 0},
    }
    return expected | changes


def test_catalog_whole_output(notice: DetourNotice) -> None:
    detours = [
        on_route(notice, "bus", "2", placed=True),
        on_route(notice, "bus", "21", placed=False),
        Detour(notice=notice, match=None),  # unmatched: skipped, not counted
        on_route(notice, "bus", "2", placed=False),
        on_route(notice, "bus", "2", placed=True),
    ]
    assert route_catalog(ROUTES, BOUNDS, detours) == [
        entry("L1"),
        entry("2", detours={"total": 3, "placed": 2}),
        entry("21", detours={"total": 1, "placed": 0}),
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
