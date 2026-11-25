"""Tests for ``export/detours.py`` (detour GeoJSON, pure)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from septa_detours.export.detours import detour_properties
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
