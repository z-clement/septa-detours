import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter, ValidationError

from septa_detours.model import (
    AffectedShape,
    Detour,
    DetourNotice,
    Intersection,
    Location,
    RouteMatch,
    Segment,
    SkippedStretch,
    SourceText,
    StartPoint,
    dump_detours,
    read_detours,
)

PHILLY = ZoneInfo("America/New_York")

# Real entry from the 2026-11-25T025344Z snapshot (route 2), verbatim.
SOURCE_FIELDS = {
    "snapshot": "2026-11-25T025344Z.json",
    "route_id": "bus_route_2",
    "mode": "Bus",
    "location_start": "17th & Washington",
    "location_end": "17th &  Mifflin",
    "start": "11/11/2026   6:30 AM",
    "end": "11/27/2026   4:00 PM",
    "message": "7am - 4pm Mon thru Fri, 11/27/26, SB via 17th, Left on "
    "Washington, Right on Broad, Right on Passyunk, Left on 17th, Reg Rt",
    "reason": "Contractor",
}


def make_source(**overrides) -> SourceText:
    return SourceText(**(SOURCE_FIELDS | overrides))


def make_notice(**overrides) -> DetourNotice:
    fields = {
        "source": make_source(),
        "source_key": "abc123",
        "start": datetime(2026, 11, 11, 6, 30, tzinfo=PHILLY),
        "end": datetime(2026, 11, 27, 16, 0, tzinfo=PHILLY),
        "location_start": "17th & Washington",
        "location_end": "17th & Mifflin",
        "start_place": Intersection(streets=("17th", "Washington")),
        "end_place": Intersection(streets=("17th", "Mifflin")),
        "reason": "Contractor",
        "direction": "SB",
        "issues": (),
    }
    return DetourNotice(**(fields | overrides))


def make_start_point(**overrides) -> StartPoint:
    # Near 17th & Washington (route 2's start); lon ~ -75 so a swap shows.
    fields = {"node_id": 109729327, "lon": -75.1716, "lat": 39.9385}
    return StartPoint(**(fields | overrides))


def make_detour() -> Detour:
    match = RouteMatch(
        feed="bus",
        route_id="2",
        shapes=(AffectedShape(shape_id="001005", direction_id=1),),
        start_point=make_start_point(),
    )
    return Detour(notice=make_notice(), match=match, issues=("one issue",))


# --- status -----------------------------------------------------------------


def test_status_complete_when_all_required_fields_known():
    assert make_notice().status == "complete"


@pytest.mark.parametrize("field", ["location_end", "reason"])
def test_status_complete_without_optional_fields(field):
    assert make_notice(**{field: None}).status == "complete"


@pytest.mark.parametrize("field", ["start", "end", "direction"])
def test_status_partial_when_a_required_field_is_missing(field):
    assert make_notice(**{field: None}).status == "partial"


def test_status_partial_when_any_issue_is_recorded():
    assert make_notice(issues=("reason: odd",)).status == "partial"


def test_status_unknown_without_location_start():
    assert make_notice(location_start=None).status == "unknown"


def test_status_unknown_without_start_and_end():
    assert make_notice(start=None, end=None).status == "unknown"


def test_status_is_not_serialized():
    assert "status" not in make_notice().model_dump()


# --- round trip ---------------------------------------------------------------


def test_detour_round_trips_through_json():
    detour = make_detour()
    assert Detour.model_validate_json(detour.model_dump_json()) == detour


def test_round_trip_keeps_shape_id_leading_zeros():
    detour = Detour.model_validate_json(make_detour().model_dump_json())
    assert detour.match is not None
    assert detour.match.shapes[0].shape_id == "001005"


def test_failed_match_round_trips_as_null():
    detour = Detour(notice=make_notice(), match=None)
    assert '"match":null' in detour.model_dump_json()
    assert Detour.model_validate_json(detour.model_dump_json()) == detour


# --- strictness ---------------------------------------------------------------


def test_models_are_frozen():
    notice = make_notice()
    with pytest.raises(ValidationError):
        notice.reason = "Other"  # ty: ignore[invalid-assignment]


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        make_notice(colour="red")


def test_naive_datetime_is_rejected():
    with pytest.raises(ValidationError, match="timezone"):
        make_notice(start=datetime(2026, 11, 11, 6, 30))  # noqa: DTZ001


def test_aware_non_philly_datetime_is_accepted():
    # The model only requires *a* zone; choosing America/New_York is parse's job.
    assert make_notice(start=datetime(2026, 11, 11, tzinfo=UTC)).status == "complete"


def test_raw_string_is_not_coerced_to_datetime():
    with pytest.raises(ValidationError):
        make_notice(start="2026-11-11T06:30:00-05:00")


def test_unknown_direction_is_rejected():
    with pytest.raises(ValidationError):
        make_notice(direction="Eastbound")


@pytest.mark.parametrize("value", ["", " ", "Construction ", " Construction"])
def test_unclean_text_is_rejected(value):
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        make_notice(reason=value)


def test_inner_whitespace_is_allowed_in_clean_text():
    assert make_notice(location_start="17th &  Mifflin").location_start == (
        "17th &  Mifflin"
    )


def test_unclean_issue_is_rejected():
    with pytest.raises(ValidationError):
        make_notice(issues=("",))


def test_source_text_keeps_whitespace_verbatim():
    source = make_source(reason="Construction  ", location_end="")
    assert (source.reason, source.location_end) == ("Construction  ", "")


@pytest.mark.parametrize("value", [0, 1, None])
def test_direction_id_accepts_gtfs_values(value):
    assert AffectedShape(shape_id="1", direction_id=value).direction_id == value


@pytest.mark.parametrize("value", [2, -1, True, 1.0, "1"])
def test_direction_id_rejects_other_values(value):
    with pytest.raises(ValidationError):
        AffectedShape(shape_id="1", direction_id=value)


def test_unknown_feed_is_rejected():
    with pytest.raises(ValidationError):
        RouteMatch(feed="trolley", route_id="15", start_point=None)


# --- start point ----------------------------------------------------------------


def test_start_point_is_required():
    # Decided: no default, so a constructor that forgets it fails loudly.
    with pytest.raises(ValidationError, match="start_point"):
        RouteMatch(feed="bus", route_id="2")  # ty: ignore[missing-argument]


def test_missing_start_point_round_trips_as_null():
    detour = Detour(
        notice=make_notice(),
        match=RouteMatch(feed="bus", route_id="2", start_point=None),
    )
    assert '"start_point":null' in detour.model_dump_json()
    assert Detour.model_validate_json(detour.model_dump_json()) == detour


def test_start_point_json_keeps_named_coordinates():
    data = json.loads(make_start_point().model_dump_json())
    assert data == {"node_id": 109729327, "lon": -75.1716, "lat": 39.9385}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lon", -180),
        ("lon", 180),
        ("lat", -90),
        ("lat", 90),
        ("node_id", 1),
    ],
)
def test_start_point_accepts_bounds(field, value):
    assert getattr(make_start_point(**{field: value}), field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("node_id", 0),
        ("node_id", -5),
        ("node_id", True),
        ("node_id", 5.0),
        ("node_id", "5"),
        ("lon", -180.000001),
        ("lon", 180.000001),
        ("lat", -90.000001),
        ("lat", 90.000001),
        ("lon", float("nan")),
        ("lat", float("inf")),
        ("lat", "39.9"),
        ("lat", True),
    ],
)
def test_start_point_rejects_bad_values(field, value):
    with pytest.raises(ValidationError, match=field):
        make_start_point(**{field: value})


# --- tier B: rejoin point, skipped stretch ----------------------------------------

# Route 2 SB along 17th, from Washington to Passyunk (lon, lat).
STRETCH_LINE = ((-75.1716, 39.9385), (-75.1717, 39.9370), (-75.1719, 39.9352))


def test_route_match_written_before_tier_b_still_reads():
    old = '{"feed":"bus","route_id":"2","shapes":[],"start_point":null}'
    match = RouteMatch.model_validate_json(old)
    assert match.rejoin_point is None
    assert match.skipped is None


def test_tier_b_fields_round_trip_through_json():
    match = RouteMatch(
        feed="bus",
        route_id="2",
        start_point=make_start_point(),
        rejoin_point=make_start_point(node_id=42, lat=39.9352),
        skipped=SkippedStretch(shape_id="317310", line=STRETCH_LINE),
    )
    data = json.loads(match.model_dump_json())
    assert data["skipped"] == {
        "shape_id": "317310",
        "line": [[-75.1716, 39.9385], [-75.1717, 39.937], [-75.1719, 39.9352]],
    }
    assert RouteMatch.model_validate_json(match.model_dump_json()) == match


def test_skipped_stretch_needs_two_points():
    with pytest.raises(ValidationError, match="line"):
        SkippedStretch(shape_id="317310", line=STRETCH_LINE[:1])


@pytest.mark.parametrize(
    "point",
    [
        (-75.1, -90.000001),
        (-180.000001, 39.9),
        (-75.1, 90.000001),
        (float("nan"), 39.9),
        (-75.1, float("inf")),
    ],
)
def test_skipped_stretch_rejects_bad_points(point):
    with pytest.raises(ValidationError, match="line"):
        SkippedStretch(shape_id="317310", line=(STRETCH_LINE[0], point))


# --- tier C: the detour's path ----------------------------------------------------

# Route 2's detour: 17th & Washington, east to Broad, south (lon, lat).
PATH_LINE = ((-75.1716, 39.9385), (-75.1695, 39.9387), (-75.1699, 39.9369))


def make_route_match(**fields) -> RouteMatch:
    return RouteMatch(feed="bus", route_id="2", start_point=None, **fields)


def test_route_match_written_before_tier_c_still_reads():
    old = '{"feed":"bus","route_id":"2","shapes":[],"start_point":null}'
    assert RouteMatch.model_validate_json(old).path is None


def test_path_round_trips_through_json():
    match = make_route_match(path=PATH_LINE)
    data = json.loads(match.model_dump_json())
    assert data["path"] == [
        [-75.1716, 39.9385],
        [-75.1695, 39.9387],
        [-75.1699, 39.9369],
    ]
    assert RouteMatch.model_validate_json(match.model_dump_json()) == match


def test_path_needs_two_points():
    with pytest.raises(ValidationError, match="path"):
        make_route_match(path=PATH_LINE[:1])


@pytest.mark.parametrize(
    "point",
    [(-75.1, 90.000001), (-180.000001, 39.9), (float("nan"), 39.9)],
)
def test_path_rejects_bad_points(point):
    with pytest.raises(ValidationError, match="path"):
        make_route_match(path=(PATH_LINE[0], point))


@pytest.mark.parametrize("rejoin_by", ["crossing", "walk", None])
def test_rejoin_by_round_trips(rejoin_by):
    match = make_route_match(rejoin_by=rejoin_by)
    assert json.loads(match.model_dump_json())["rejoin_by"] == rejoin_by
    assert RouteMatch.model_validate_json(match.model_dump_json()) == match


def test_rejoin_by_defaults_to_none_and_rejects_others():
    old = '{"feed":"bus","route_id":"2","shapes":[],"start_point":null}'
    assert RouteMatch.model_validate_json(old).rejoin_by is None
    with pytest.raises(ValidationError, match="rejoin_by"):
        make_route_match(rejoin_by="guess")


LOCATION = TypeAdapter(Location)


@pytest.mark.parametrize(
    "location",
    [
        Intersection(streets=("Arch St", "15th St")),
        Segment(street="Market St", between=("23rd St", "19th St")),
    ],
)
def test_location_round_trips_through_json(location):
    assert LOCATION.validate_json(LOCATION.dump_json(location)) == location


def test_location_json_names_its_kind():
    assert LOCATION.dump_python(
        Intersection(streets=("17th", "Washington")), mode="json"
    ) == {"kind": "intersection", "streets": ["17th", "Washington"]}
    assert LOCATION.dump_python(
        Segment(street="Spruce", between=("34th", "36th")), mode="json"
    ) == {"kind": "segment", "street": "Spruce", "between": ["34th", "36th"]}


@pytest.mark.parametrize(
    "json_text",
    [
        # Fields of the other kind are rejected, not silently matched.
        '{"kind": "segment", "streets": ["17th", "Pine"]}',
        '{"kind": "intersection", "street": "Spruce", "between": ["34th", "36th"]}',
        # JSON must say which kind it is.
        '{"streets": ["17th", "Pine"]}',
        '{"kind": "corner", "streets": ["17th", "Pine"]}',
    ],
)
def test_location_kind_decides_the_type(json_text):
    # JSON, as data/processed/ is read back (strict Python input would
    # reject the lists for an unrelated reason).
    with pytest.raises(ValidationError):
        LOCATION.validate_json(json_text)


def test_location_json_with_matching_kind_is_accepted():
    # Control for the test above: the same JSON with the right kind is fine.
    assert LOCATION.validate_json(
        '{"kind": "intersection", "streets": ["17th", "Pine"]}'
    ) == Intersection(streets=("17th", "Pine"))


@pytest.mark.parametrize("streets", [("17th",), ("17th", "Pine", "Broad")])
def test_intersection_needs_exactly_two_streets(streets):
    with pytest.raises(ValidationError):
        Intersection(streets=streets)


@pytest.mark.parametrize("name", ["", " Pine", "Pine "])
def test_location_names_must_be_clean(name):
    with pytest.raises(ValidationError):
        Intersection(streets=("17th", name))
    with pytest.raises(ValidationError):
        Segment(street=name, between=("34th", "36th"))
    with pytest.raises(ValidationError):
        Segment(street="Spruce", between=(name, "36th"))


def test_location_kind_cannot_be_overridden():
    with pytest.raises(ValidationError):
        Intersection(kind="segment", streets=("17th", "Pine"))


@pytest.mark.parametrize("field", ["start_place", "end_place"])
def test_places_are_required(field):
    # Decided: no default, so a constructor that forgets them fails loudly.
    fields = make_notice().model_dump()
    del fields[field]
    with pytest.raises(ValidationError, match=field):
        DetourNotice.model_validate(fields)


@pytest.mark.parametrize("field", ["start_place", "end_place"])
def test_place_json_without_kind_is_rejected(field):
    data = json.loads(make_notice().model_dump_json())
    del data[field]["kind"]
    with pytest.raises(ValidationError, match=field):
        DetourNotice.model_validate_json(json.dumps(data))


def test_notice_places_round_trip_with_both_kinds():
    notice = make_notice(
        end_place=Segment(street="Spruce", between=("34th", "36th")),
    )
    reloaded = DetourNotice.model_validate_json(notice.model_dump_json())
    assert reloaded == notice
    assert isinstance(reloaded.end_place, Segment)


# --- dump_detours / read_detours ------------------------------------------------


def make_detours() -> list[Detour]:
    # Three different shapes of Detour, in a non-sorted order: matched and
    # placed; matched but not placed, with a segment; route not matched.
    placed = make_detour()
    unplaced = Detour(
        notice=make_notice(
            source_key="zzz999",
            start_place=Segment(street="Spruce", between=("34th", "36th")),
        ),
        match=RouteMatch(feed="bus", route_id="40", start_point=None),
        issues=("start: segments are not placed yet",),
    )
    unmatched = Detour(
        notice=make_notice(source_key="000aaa", direction=None),
        match=None,
        issues=("route: no GTFS route for 'bus_route_H'",),
    )
    return [placed, unplaced, unmatched]


def test_detours_round_trip_in_order():
    detours = make_detours()
    assert read_detours(dump_detours(detours)) == detours


def test_dump_accepts_any_sequence():
    detours = make_detours()
    assert dump_detours(tuple(detours)) == dump_detours(detours)


def test_empty_detours_round_trip():
    assert dump_detours([]) == b"[]\n"
    assert read_detours(b"[]\n") == []


def test_dump_is_compact_json_with_trailing_newline():
    content = dump_detours(make_detours())
    assert content.endswith(b"]\n")
    assert content.count(b"\n") == 1
    assert content.startswith(b'[{"notice":{"source":{"snapshot":')  # no spaces
    assert json.loads(content)[0]["match"]["route_id"] == "2"


def test_dump_writes_utf8_not_escapes():
    # The en dash must survive as UTF-8 bytes, and read back equal.
    detour = Detour(
        notice=make_notice(reason="Parade \u2013 Thanksgiving"),
        match=None,
    )
    content = dump_detours([detour])
    assert "Parade \u2013 Thanksgiving".encode() in content
    assert read_detours(content) == [detour]


def test_dump_omits_status():
    # ``status`` is a plain property; a dumped copy would be rejected on
    # reload by extra="forbid".
    assert b"status" not in dump_detours(make_detours())


def test_read_accepts_no_trailing_newline():
    content = dump_detours(make_detours()).rstrip(b"\n")
    assert read_detours(content) == make_detours()


def broken_detours(edit) -> bytes:
    data = json.loads(dump_detours(make_detours()))
    edit(data)
    return json.dumps(data).encode()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty-bytes"),
        pytest.param(b"[", id="truncated"),
        pytest.param(b"{}", id="object-top-level"),
        pytest.param(b"null", id="null"),
        pytest.param(b"[null]", id="null-entry"),
        pytest.param(b"[{}]", id="empty-entry"),
        pytest.param(
            broken_detours(lambda d: d[1].update(extra=1)), id="unknown-field"
        ),
        pytest.param(
            broken_detours(lambda d: d[0]["notice"].update(status="complete")),
            id="status-field",
        ),
        pytest.param(
            broken_detours(lambda d: d[0]["match"].pop("start_point")),
            id="missing-start-point",
        ),
        pytest.param(
            broken_detours(lambda d: d[2]["notice"].update(start="2026-11-11T06:30")),
            id="naive-datetime",
        ),
        pytest.param(
            broken_detours(lambda d: d[0]["match"].update(route_id=2)),
            id="int-route-id",
        ),
        pytest.param(
            # Lax mode would coerce "1" to 1; strict must not.
            broken_detours(
                lambda d: d[0]["match"]["shapes"][0].update(direction_id="1")
            ),
            id="string-direction-id",
        ),
    ],
)
def test_read_rejects_invalid_content(content):
    with pytest.raises(ValidationError):
        read_detours(content)
