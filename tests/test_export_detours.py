"""Tests for ``export/detours.py`` (detour GeoJSON, pure)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from septa_detours.export.detours import (
    detour_properties,
    detours_feature_collection,
)
from septa_detours.model import (
    AffectedShape,
    Detour,
    DetourNotice,
    RouteMatch,
    StartPoint,
)
from septa_detours.parse.notice import parse_snapshot

PHILLY = ZoneInfo("America/New_York")
STAMP = "2026-11-25T025344Z"


@pytest.fixture
def route_2_notices(read_alert_fixture) -> list[DetourNotice]:
    content = read_alert_fixture(f"{STAMP}__bus_route_2.json")
    return parse_snapshot(b"[" + content + b"]", f"{STAMP}.json")


def placed(notice: DetourNotice, *issues: str) -> Detour:
    """Route 2 #0's real match: SB shape, start at 17th & Washington."""
    match = RouteMatch(
        feed="bus",
        route_id="2",
        shapes=(AffectedShape(shape_id="317310", direction_id=0),),
        start_point=StartPoint(node_id=11, lon=-75.1716, lat=39.9385),
    )
    return Detour(notice=notice, match=match, issues=issues)


def with_notice(notice: DetourNotice, **changes) -> DetourNotice:
    # model_copy(update=...) skips validation; re-validate so a test can't
    # build a notice the model would reject.
    return DetourNotice.model_validate(notice.model_copy(update=changes).model_dump())


# --- detour_properties ----------------------------------------------------------


def test_properties_of_a_complete_detour(route_2_notices):
    """The whole dict for route 2 #0, so any wrong or extra key fails."""
    assert detour_properties(placed(route_2_notices[0])) == {
        "source_key": "5d0d22dfe7d86935",
        "status": "complete",
        "direction": "SB",
        "location_start": "17th & Washington",
        "location_end": "17th & Mifflin",
        "start": "2026-11-11T06:30:00-05:00",
        "end": "2026-11-27T16:00:00-05:00",
        "reason": "Contractor",
        "message": "7am - 4pm Mon thru Fri, 11/27/26, SB via 17th, Left on "
        "Washington, Right on Broad, Right on Passyunk, Left on 17th, Reg Rt",
        "issues": None,
    }


def test_location_is_the_cleaned_one_message_is_verbatim(route_2_notices):
    # The raw LE has a double space; the property is the cleaned notice field.
    notice = route_2_notices[0]
    assert notice.source.location_end == "17th &  Mifflin"
    messy = with_notice(
        notice, source=notice.source.model_copy(update={"message": "SB  via 17th "})
    )
    props = detour_properties(placed(messy))
    assert props["location_end"] == "17th & Mifflin"
    assert props["message"] == "SB  via 17th "


def test_summer_times_keep_their_own_offset(route_2_notices):
    start = datetime(2026, 7, 1, 6, 30, tzinfo=PHILLY)
    end = datetime(2026, 12, 1, 6, 30, tzinfo=PHILLY)
    props = detour_properties(
        placed(with_notice(route_2_notices[0], start=start, end=end))
    )
    assert (props["start"], props["end"]) == (
        "2026-07-01T06:30:00-04:00",
        "2026-12-01T06:30:00-05:00",
    )


def test_unknowns_are_null_not_empty(route_2_notices):
    notice = with_notice(
        route_2_notices[0],
        start=None,
        end=None,
        location_start=None,
        location_end=None,
        start_place=None,
        end_place=None,
        reason=None,
        direction=None,
    )
    props = detour_properties(placed(notice))
    for key in ("start", "end", "location_start", "location_end", "reason"):
        assert props[key] is None, key
    assert props["direction"] is None
    assert props["status"] == "unknown"


def test_issues_parse_first_then_match(route_2_notices):
    notice = with_notice(
        route_2_notices[0], issues=("start: blank datetime ''", "direction: x")
    )
    detour = placed(notice, "start: no crossing of 'A' and 'B' in OSM")
    props = detour_properties(detour)
    assert props["issues"] == (
        "start: blank datetime ''; direction: x; "
        "start: no crossing of 'A' and 'B' in OSM"
    )
    assert props["status"] == "partial"


@pytest.mark.parametrize(
    ("notice_issues", "match_issues", "expected"),
    [
        (("parse: a",), (), "parse: a"),
        ((), ("match: b",), "match: b"),
    ],
    ids=["parse-only", "match-only"],
)
def test_issues_from_one_side_only(
    route_2_notices, notice_issues, match_issues, expected
):
    notice = with_notice(route_2_notices[0], issues=notice_issues)
    assert detour_properties(placed(notice, *match_issues))["issues"] == expected


def test_unmatched_detour_still_has_properties(route_2_notices):
    detour = Detour(notice=route_2_notices[1], match=None, issues=("route: x",))
    props = detour_properties(detour)
    assert props["source_key"] == "7b34cab08bbda5a3"
    assert props["issues"] == "route: x"


def test_every_value_is_a_json_scalar(route_2_notices):
    for notice in route_2_notices:
        props = detour_properties(placed(notice))
        assert all(v is None or isinstance(v, str) for v in props.values())
        assert json.loads(json.dumps(props)) == props


def test_properties_are_a_fresh_dict(route_2_notices):
    detour = placed(route_2_notices[0])
    first = detour_properties(detour)
    first["status"] = "changed"
    assert detour_properties(detour)["status"] == "complete"


# --- detours_feature_collection --------------------------------------------------

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
# Must match ``shapes.shape_coordinates`` output.
COORDINATES_SCHEMA = {
    "feed": pl.String,
    "shape_id": pl.String,
    "coordinates": pl.List(pl.List(pl.Float64)),
}

# Distinct colors, so a route's props can't be taken from another route.
ROUTES = pl.DataFrame(
    [
        ("2", "2", "16th-17th", 3, "EF3340", "FFFFFF", "bus"),
        ("31", "31", "Market-Spruce", 3, "00A1DE", "000000", "bus"),
    ],
    schema=ROUTES_SCHEMA,
    orient="row",
)
# Lon ~ -75, lat ~ 40, every line distinct; 999999 is used by no detour.
SHAPE_LINES = {
    "317310": [[-75.1716, 39.9405], [-75.1716, 39.9365]],
    "317312": [[-75.1716, 39.9365], [-75.1716, 39.9405]],
    "319925": [[-75.1616, 39.9508], [-75.1656, 39.9508]],
    "999999": [[-75.0, 40.1], [-75.0, 40.2]],
}
COORDINATES = pl.DataFrame(
    [("bus", shape_id, line) for shape_id, line in SHAPE_LINES.items()],
    schema=COORDINATES_SCHEMA,
    orient="row",
)

ROUTE_2_PROPS = {
    "feed": "bus",
    "route_id": "2",
    "route_short_name": "2",
    "route_long_name": "16th-17th",
    "route_type": 3,
    "route_color": "#EF3340",
    "route_text_color": "#FFFFFF",
}


def matched(
    notice: DetourNotice,
    route_id: str,
    shapes: list[tuple[str, int | None]],
    start: tuple[int, float, float] | None,
) -> Detour:
    match = RouteMatch(
        feed="bus",
        route_id=route_id,
        shapes=tuple(AffectedShape(shape_id=s, direction_id=d) for s, d in shapes),
        start_point=None
        if start is None
        else StartPoint(node_id=start[0], lon=start[1], lat=start[2]),
    )
    return Detour(notice=notice, match=match)


def kinds(collection) -> list[tuple]:
    """``(geometry type, identifying props)`` per feature, in order."""
    out = []
    for feature in collection["features"]:
        props = feature["properties"]
        if feature["geometry"]["type"] == "LineString":
            out.append(
                (
                    "line",
                    props["route_id"],
                    props["shape_id"],
                    props["direction_id"],
                    props["detour_count"],
                )
            )
        else:
            out.append(("point", props["route_id"], props["source_key"]))
    return out


def test_one_line_and_one_point_whole_structure(route_2_notices):
    """The whole collection for route 2 #0, so any wrong key or value fails."""
    notice = route_2_notices[0]
    detour = matched(notice, "2", [("317310", 0)], (11, -75.1716, 39.9385))
    collection = detours_feature_collection([detour], ROUTES, COORDINATES)
    assert collection == {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": SHAPE_LINES["317310"],
                },
                "properties": {
                    **ROUTE_2_PROPS,
                    "shape_id": "317310",
                    "direction_id": 0,
                    "detour_count": 1,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-75.1716, 39.9385]},
                "properties": {
                    **ROUTE_2_PROPS,
                    **detour_properties(detour),
                    "node_id": 11,
                },
            },
        ],
    }


def test_mixed_detours(route_2_notices):
    n = route_2_notices
    detours = [
        # Matched, no shapes (no direction), placed: a point but no line.
        matched(n[4], "2", [], (12, -75.1700, 39.9400)),
        matched(n[0], "2", [("317310", 0)], (11, -75.1716, 39.9385)),
        Detour(notice=n[1], match=None, issues=("route: x",)),  # draws nothing
        matched(n[2], "31", [("319925", 1)], (31, -75.1636, 39.9508)),
        matched(n[3], "2", [("317310", 0)], None),  # same line, not placed
    ]
    collection = detours_feature_collection(detours, ROUTES, COORDINATES)
    assert kinds(collection) == [
        # Lines first, in first-appearance order; 317310 listed twice.
        ("line", "2", "317310", 0, 2),
        ("line", "31", "319925", 1, 1),
        # Then points, in detour order; the unplaced and unmatched are absent.
        ("point", "2", n[4].source_key),
        ("point", "2", n[0].source_key),
        ("point", "31", n[2].source_key),
    ]
    # Each line carries its own shape's coordinates.
    line_coordinates = [f["geometry"]["coordinates"] for f in collection["features"]]
    assert line_coordinates[:2] == [SHAPE_LINES["317310"], SHAPE_LINES["319925"]]


def test_each_feature_gets_its_own_routes_props(route_2_notices):
    n = route_2_notices
    detours = [
        matched(n[0], "2", [("317310", 0)], (11, -75.1716, 39.9385)),
        matched(n[1], "31", [("319925", 1)], (31, -75.1636, 39.9508)),
    ]
    collection = detours_feature_collection(detours, ROUTES, COORDINATES)
    colors = [f["properties"]["route_color"] for f in collection["features"]]
    assert colors == ["#EF3340", "#00A1DE", "#EF3340", "#00A1DE"]


def test_point_coordinates_are_lon_lat(route_2_notices):
    detour = matched(route_2_notices[0], "2", [], (11, -75.1716, 39.9385))
    (point,) = detours_feature_collection([detour], ROUTES, COORDINATES)["features"]
    assert point["geometry"] == {"type": "Point", "coordinates": [-75.1716, 39.9385]}
    assert point["properties"]["node_id"] == 11


def test_one_shape_in_both_directions_is_two_lines(route_2_notices):
    n = route_2_notices
    detours = [
        matched(n[0], "2", [("317310", 0)], None),
        matched(n[1], "2", [("317310", 1)], None),
    ]
    collection = detours_feature_collection(detours, ROUTES, COORDINATES)
    assert kinds(collection) == [
        ("line", "2", "317310", 0, 1),
        ("line", "2", "317310", 1, 1),
    ]


def test_null_direction_id_is_its_own_line(route_2_notices):
    n = route_2_notices
    detours = [
        matched(n[0], "2", [("317310", None)], None),
        matched(n[1], "2", [("317310", 0)], None),
    ]
    collection = detours_feature_collection(detours, ROUTES, COORDINATES)
    assert kinds(collection) == [
        ("line", "2", "317310", None, 1),
        ("line", "2", "317310", 0, 1),
    ]


def test_counts_per_line_across_many_detours(route_2_notices):
    detours = [matched(n, "2", [("317310", 0)], None) for n in route_2_notices]
    collection = detours_feature_collection(detours, ROUTES, COORDINATES)
    assert kinds(collection) == [("line", "2", "317310", 0, 5)]


@pytest.mark.parametrize("unmatched", [False, True], ids=["empty", "all-unmatched"])
def test_nothing_to_draw_is_an_empty_collection(route_2_notices, unmatched):
    detours = (
        [Detour(notice=n, match=None) for n in route_2_notices] if unmatched else []
    )
    assert detours_feature_collection(detours, ROUTES, COORDINATES) == {
        "type": "FeatureCollection",
        "features": [],
    }


def test_unknown_route_raises(route_2_notices):
    detour = matched(route_2_notices[0], "999", [], (11, -75.1716, 39.9385))
    with pytest.raises(ValueError, match="'999'"):
        detours_feature_collection([detour], ROUTES, COORDINATES)


def test_unknown_route_raises_even_without_drawing(route_2_notices):
    # No shapes, not placed: nothing would be drawn, but GTFS still disagrees.
    detour = matched(route_2_notices[0], "999", [], None)
    with pytest.raises(ValueError, match="'999'"):
        detours_feature_collection([detour], ROUTES, COORDINATES)


def test_shape_without_coordinates_raises(route_2_notices):
    detour = matched(route_2_notices[0], "2", [("317312", 1), ("000000", 0)], None)
    with pytest.raises(ValueError, match="000000"):
        detours_feature_collection([detour], ROUTES, COORDINATES)


def test_collection_serializes_strictly(route_2_notices):
    n = route_2_notices
    detours = [
        matched(n[0], "2", [("317310", 0)], (11, -75.1716, 39.9385)),
        matched(n[1], "2", [("317312", None)], None),
    ]
    collection = detours_feature_collection(detours, ROUTES, COORDINATES)
    assert json.loads(json.dumps(collection, allow_nan=False)) == collection
