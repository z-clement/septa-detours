import json
import re
from collections.abc import Callable
from datetime import datetime

import pytest
from pydantic import ValidationError

from septa_detours.model import DetourNotice, Intersection, Segment, SourceText
from septa_detours.parse._api import ApiDetour, ApiRoute, read_snapshot
from septa_detours.parse.notice import (
    SOURCE_KEY_LENGTH,
    make_source_key,
    parse_detour,
    parse_snapshot,
)
from septa_detours.parse.times import SEPTA_ZONE

OLD = "2026-11-25T025344Z"
NEW = "2026-11-25T121123Z"

ROUTE_31 = "bus_route_31"
BROAD_WALNUT = "Broad & Walnut"  # route 31 #4
START_31_4 = "11/25/2026   3:00 PM"


def route_key_fields(
    read_alert_fixture: Callable[[str], bytes], stamp: str, route_id: str
) -> list[tuple[str, str, str]]:
    """``(route_id, location_start, start)`` for each detour item in a fixture."""
    route = json.loads(read_alert_fixture(f"{stamp}__{route_id}.json"))
    return [
        (route["route_id"], item["location_start"], item["start"])
        for item in route["detour"]
    ]


# --- make_source_key -------------------------------------------------------


def test_source_key_is_short_lowercase_hex() -> None:
    key = make_source_key(ROUTE_31, BROAD_WALNUT, START_31_4)
    assert re.fullmatch(rf"[0-9a-f]{{{SOURCE_KEY_LENGTH}}}", key)


def test_source_key_is_pinned() -> None:
    """Keys are compared across snapshots parsed at different times, so the
    algorithm must not drift silently. Update this only on purpose."""
    assert make_source_key(ROUTE_31, BROAD_WALNUT, START_31_4) == "661b7024a25d2bbd"


@pytest.mark.parametrize("index", range(5))
def test_source_key_same_detour_across_snapshots(
    read_alert_fixture: Callable[[str], bytes], index: int
) -> None:
    """Route 31 items 0-4 appear unchanged in both snapshots."""
    old = route_key_fields(read_alert_fixture, OLD, ROUTE_31)[index]
    new = route_key_fields(read_alert_fixture, NEW, ROUTE_31)[index]
    assert make_source_key(*old) == make_source_key(*new)


def test_source_key_distinct_detours_differ(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """All 7 route 31 items in the newer snapshot get different keys
    (#3 and #4 share a start; #5 and #6 share a start)."""
    keys = [
        make_source_key(*f) for f in route_key_fields(read_alert_fixture, NEW, ROUTE_31)
    ]
    assert len(keys) == 7
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize(
    ("route_id", "location_start", "start"),
    [
        ("bus_route_32", BROAD_WALNUT, START_31_4),
        (ROUTE_31, "Broad & Chestnut", START_31_4),
        (ROUTE_31, BROAD_WALNUT, "11/25/2026   3:01 PM"),
    ],
)
def test_source_key_every_field_counts(
    route_id: str, location_start: str, start: str
) -> None:
    base = make_source_key(ROUTE_31, BROAD_WALNUT, START_31_4)
    assert make_source_key(route_id, location_start, start) != base


@pytest.mark.parametrize(
    ("route_id", "location_start", "start"),
    [
        # Whitespace: runs collapse, ends are stripped, in every field.
        (ROUTE_31, "Broad &  Walnut", START_31_4),
        (ROUTE_31, " Broad & Walnut\u00a0", START_31_4),
        (ROUTE_31, BROAD_WALNUT, "11/25/2026 3:00 PM"),
        (f" {ROUTE_31}\t", BROAD_WALNUT, START_31_4),
        # Case, in every field.
        (ROUTE_31, "BROAD & walnut", START_31_4),
        (ROUTE_31, BROAD_WALNUT, "11/25/2026   3:00 pm"),
        ("BUS_ROUTE_31", BROAD_WALNUT, START_31_4),
    ],
)
def test_source_key_ignores_cosmetic_edits(
    route_id: str, location_start: str, start: str
) -> None:
    base = make_source_key(ROUTE_31, BROAD_WALNUT, START_31_4)
    assert make_source_key(route_id, location_start, start) == base


def test_source_key_keeps_inner_spaces() -> None:
    """Whitespace collapses to one space; it isn't removed."""
    spaced = make_source_key(ROUTE_31, "Broad & Walnut", START_31_4)
    glued = make_source_key(ROUTE_31, "Broad &Walnut", START_31_4)
    assert spaced != glued


def test_source_key_does_not_normalize_times() -> None:
    """Only whitespace and case are forgiven, not zero-padding."""
    assert make_source_key(
        ROUTE_31, BROAD_WALNUT, "11/25/2026 3:00 PM"
    ) != make_source_key(ROUTE_31, BROAD_WALNUT, "11/25/2026 03:00 PM")


def test_source_key_blank_equals_whitespace_only() -> None:
    """Route 64 #1/#2 have blank locations; spaces-only reads as blank."""
    assert make_source_key("bus_route_64", "", START_31_4) == make_source_key(
        "bus_route_64", "   ", START_31_4
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # Text moved between fields must not collide.
        ((ROUTE_31, "Broad &", "Walnut"), (ROUTE_31, "Broad", "& Walnut")),
        ((ROUTE_31, "a|b", "c"), (ROUTE_31, "a", "b|c")),
        ((ROUTE_31, "", "x"), (ROUTE_31, "x", "")),
    ],
)
def test_source_key_field_boundaries_matter(
    first: tuple[str, str, str], second: tuple[str, str, str]
) -> None:
    assert make_source_key(*first) != make_source_key(*second)


# --- parse_detour ----------------------------------------------------------


def load_route(
    read_alert_fixture: Callable[[str], bytes], stamp: str, route_id: str
) -> ApiRoute:
    """A fixture's route entry as a real ``ApiRoute`` (via ``read_snapshot``)."""
    content = read_alert_fixture(f"{stamp}__{route_id}.json")
    (route,) = read_snapshot(b"[" + content + b"]")
    return route


def parse_fixture_item(
    read_alert_fixture: Callable[[str], bytes], stamp: str, route_id: str, index: int
) -> DetourNotice:
    route = load_route(read_alert_fixture, stamp, route_id)
    return parse_detour(route, route.detour[index], f"{stamp}.json")


def test_parse_detour_route_55_baseline(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """The clean baseline: every field, compared as one whole notice."""
    notice = parse_fixture_item(read_alert_fixture, OLD, "bus_route_55", 0)
    expected = DetourNotice(
        source=SourceText(
            snapshot=f"{OLD}.json",
            route_id="bus_route_55",
            mode="Bus",
            location_start="65th Ave & Broad St",
            location_end="Old York Rd Btwn 65th Ave & 66th Ave",
            start="9/23/2026  10:23 AM",
            end="12/31/2026  11:00 PM",
            message=(
                "24/7 until 12-31-2026, SB via Broad St, Right on 65th Ave, "
                "Left on Old York Rd, Reg Rt"
            ),
            reason="Sinkhole ",
        ),
        source_key=make_source_key(
            "bus_route_55", "65th Ave & Broad St", "9/23/2026  10:23 AM"
        ),
        start=datetime(2026, 9, 23, 10, 23, tzinfo=SEPTA_ZONE),
        end=datetime(2026, 12, 31, 23, 0, tzinfo=SEPTA_ZONE),
        location_start="65th Ave & Broad St",
        location_end="Old York Rd Btwn 65th Ave & 66th Ave",
        start_place=Intersection(streets=("65th Ave", "Broad St")),
        end_place=Segment(street="Old York Rd", between=("65th Ave", "66th Ave")),
        reason="Sinkhole",
        direction="SB",
    )
    assert notice == expected
    assert notice.status == "complete"


def test_parse_detour_source_key_is_pinned(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """Route 31 #4 through parse_detour gives the pinned key: the raw
    ``(route_id, location_start, start)`` reach ``make_source_key`` in order."""
    notice = parse_fixture_item(read_alert_fixture, OLD, ROUTE_31, 4)
    assert notice.source_key == "661b7024a25d2bbd"


def test_parse_detour_cleans_inner_whitespace(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """Route 7 #1: double spaces in LS and LE collapse; ``source`` keeps them."""
    notice = parse_fixture_item(read_alert_fixture, OLD, "bus_route_7", 1)
    assert notice.location_start == "22nd & Chestnut"
    assert notice.location_end == "JFK Between 17th & 30th Streets"
    assert notice.reason == "Thanksgiving Day Setup"
    assert notice.source.location_start == "22nd  &  Chestnut"
    assert notice.source.location_end == "JFK Between  17th & 30th  Streets"


def test_parse_detour_blank_location_end_is_none(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """Route 103 #0: blank LE is normal; it doesn't block ``complete``."""
    notice = parse_fixture_item(read_alert_fixture, OLD, "bus_route_103", 0)
    assert notice.location_end is None
    assert notice.source.location_end == ""
    assert notice.direction == "NB"
    assert notice.status == "complete"


# --- parse_detour: times ---------------------------------------------------

ROUTE_55 = ApiRoute(route_id="bus_route_55", mode="Bus", detour=())


def make_api_detour(**overrides: str) -> ApiDetour:
    """Route 55 #0's raw strings, with overrides (for cases no fixture has)."""
    fields = {
        "location_start": "65th Ave & Broad St",
        "location_end": "Old York Rd Btwn 65th Ave & 66th Ave",
        "start": "9/23/2026  10:23 AM",
        "end": "12/31/2026  11:00 PM",
        "message": "24/7 until 12-31-2026, SB via Broad St, Reg Rt",
        "reason": "Sinkhole ",
    }
    return ApiDetour(**(fields | overrides))


def parse_made(**overrides: str) -> DetourNotice:
    return parse_detour(ROUTE_55, make_api_detour(**overrides), f"{OLD}.json")


def test_parse_detour_made_baseline_has_no_issues() -> None:
    """Guards the helper: without overrides, nothing is flagged."""
    notice = parse_made()
    assert notice.issues == ()
    assert notice.status == "complete"


def test_parse_detour_unparseable_start() -> None:
    notice = parse_made(start="9/23/2026  10:23")
    assert notice.start is None
    assert notice.end == datetime(2026, 12, 31, 23, 0, tzinfo=SEPTA_ZONE)
    assert notice.issues == ("start: unrecognized datetime '9/23/2026  10:23'",)
    assert notice.status == "partial"


def test_parse_detour_blank_end() -> None:
    notice = parse_made(end="  ")
    assert notice.end is None
    assert notice.start == datetime(2026, 9, 23, 10, 23, tzinfo=SEPTA_ZONE)
    assert notice.issues == ("end: blank datetime '  '",)
    assert notice.status == "partial"


def test_parse_detour_both_times_bad_is_unknown() -> None:
    """Issues come in field order: start, then end."""
    notice = parse_made(start="soon", end="")
    assert (notice.start, notice.end) == (None, None)
    assert notice.issues == (
        "start: unrecognized datetime 'soon'",
        "end: blank datetime ''",
    )
    assert notice.status == "unknown"


def test_parse_detour_end_before_start_keeps_both() -> None:
    notice = parse_made(start="12/31/2026 11:00 PM", end="9/23/2026 10:23 AM")
    assert notice.start == datetime(2026, 12, 31, 23, 0, tzinfo=SEPTA_ZONE)
    assert notice.end == datetime(2026, 9, 23, 10, 23, tzinfo=SEPTA_ZONE)
    assert notice.issues == ("end: before start",)
    assert notice.status == "partial"


def test_parse_detour_end_equal_to_start_is_not_flagged() -> None:
    notice = parse_made(start="11/25/2026 3:00 PM", end="11/25/2026   3:00 PM")
    assert notice.issues == ()


def test_parse_detour_end_one_minute_before_start_is_flagged() -> None:
    notice = parse_made(start="11/25/2026 3:00 PM", end="11/25/2026 2:59 PM")
    assert notice.issues == ("end: before start",)


def test_parse_detour_dst_overlap_end() -> None:
    notice = parse_made(start="11/1/2027 9:00 AM", end="11/7/2027 1:30 AM")
    assert notice.end == datetime(2027, 11, 7, 1, 30, tzinfo=SEPTA_ZONE)
    assert notice.issues == (
        "end: ambiguous local time 2027-11-07 01:30 (DST overlap); read as EDT",
    )


def test_parse_detour_dst_gap_start_then_order_check() -> None:
    """Start 2:30 AM is in the gap (read as 07:30 UTC); end 3:10 AM EDT is
    07:10 UTC. Wall clocks say fine, real instants say end is first: the
    check compares instants. DST issues come before the order check."""
    notice = parse_made(start="3/14/2027 2:30 AM", end="3/14/2027 3:10 AM")
    assert notice.issues == (
        "start: nonexistent local time 2027-03-14 02:30 (DST gap); read as 03:30 EDT",
        "end: before start",
    )


def test_parse_detour_bad_start_skips_order_check() -> None:
    """With one side missing there's nothing to compare."""
    notice = parse_made(start="", end="1/1/2020 1:00 PM")
    assert notice.issues == ("start: blank datetime ''",)


# --- parse_detour: direction -----------------------------------------------

NONE_FOUND = "direction: none found in message"


@pytest.mark.parametrize(
    ("stamp", "route_id", "index", "direction", "issues"),
    [
        (OLD, "bus_route_24", 0, "NB", ()),  # "NB Via ... Recover NB On": once
        (OLD, "bus_route_24", 1, None, (NONE_FOUND,)),  # no direction at all
        (OLD, "bus_route_6", 0, None, (NONE_FOUND,)),  # discontinued stop
        (OLD, "rr_route_mfo", 0, "WB", ()),  # "W/B"
        (OLD, "bus_route_64", 3, "EB", ()),  # "Eastbound", at the end
        (OLD, "rr_route_bso", 0, "SB", ()),  # after the time: "11:59pm SB,"
    ],
)
def test_parse_detour_direction_fixtures(
    read_alert_fixture: Callable[[str], bytes],
    stamp: str,
    route_id: str,
    index: int,
    direction: str | None,
    issues: tuple[str, ...],
) -> None:
    notice = parse_fixture_item(read_alert_fixture, stamp, route_id, index)
    assert notice.direction == direction
    # Direction issues only: 24 #1 also has a location issue (pinned below).
    direction_issues = tuple(i for i in notice.issues if i.startswith("direction:"))
    assert direction_issues == issues


def test_parse_detour_no_direction_is_partial(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """Route 24 #1: everything else is known; the missing direction alone
    makes it partial (README guess confirmed)."""
    notice = parse_fixture_item(read_alert_fixture, OLD, "bus_route_24", 1)
    assert notice.location_start is not None
    assert notice.start is not None
    assert notice.end is not None
    assert notice.status == "partial"


def test_parse_detour_conflicting_directions() -> None:
    """Never pick one; list them in message order."""
    notice = parse_made(message="SB via Broad St, NB via 15th St, SB Reg Rt")
    assert notice.direction is None
    assert notice.issues == ("direction: conflicting SB, NB in message",)
    assert notice.status == "partial"


def test_parse_detour_three_conflicting_directions() -> None:
    notice = parse_made(message="Westbound via Vine, N/B on 16th, eb on Race")
    assert notice.issues == ("direction: conflicting WB, NB, EB in message",)


def test_parse_detour_direction_issue_comes_last() -> None:
    notice = parse_made(start="", message="via Broad St")
    assert notice.issues == ("start: blank datetime ''", NONE_FOUND)


@pytest.mark.parametrize("index", [1, 2])
def test_parse_detour_blank_location_start_is_unknown_without_issue(
    read_alert_fixture: Callable[[str], bytes], index: int
) -> None:
    """Route 64 #1/#2: blank LS -> None; status says unknown, no extra issue."""
    notice = parse_fixture_item(read_alert_fixture, OLD, "bus_route_64", index)
    assert notice.location_start is None
    assert notice.location_end is None
    assert not any(issue.startswith("location") for issue in notice.issues)
    assert notice.status == "unknown"


# --- parse_detour: locations -----------------------------------------------


def test_parse_detour_places_keep_location_text() -> None:
    """Text and structure side by side: the cleaned text is unchanged."""
    notice = parse_made(
        location_start="22nd  &  Chestnut", location_end="Spruce btw 34th & 36th"
    )
    assert notice.location_start == "22nd & Chestnut"
    assert notice.start_place == Intersection(streets=("22nd", "Chestnut"))
    assert notice.location_end == "Spruce btw 34th & 36th"
    assert notice.end_place == Segment(street="Spruce", between=("34th", "36th"))
    assert notice.issues == ()


@pytest.mark.parametrize("blank", ["", "   "])
def test_parse_detour_blank_location_end_has_no_issue(blank: str) -> None:
    notice = parse_made(location_end=blank)
    assert notice.location_end is None
    assert notice.end_place is None
    assert notice.issues == ()
    assert notice.status == "complete"


def test_parse_detour_blank_location_start_has_no_issue() -> None:
    """Blank LS is already ``unknown`` by status; no issue is added."""
    notice = parse_made(location_start=" ")
    assert notice.start_place is None
    assert notice.issues == ()
    assert notice.status == "unknown"


def test_parse_detour_unrecognized_location_start() -> None:
    notice = parse_made(location_start="Dickinson")
    assert notice.location_start == "Dickinson"
    assert notice.start_place is None
    assert notice.issues == ("location_start: unrecognized location 'Dickinson'",)
    assert notice.status == "partial"


def test_parse_detour_unrecognized_location_end() -> None:
    """An optional field, but unreadable text is still doubt: ``partial``."""
    notice = parse_made(location_end="Broad &")
    assert notice.end_place is None
    assert notice.start_place == Intersection(streets=("65th Ave", "Broad St"))
    assert notice.issues == ("location_end: unrecognized location 'Broad &'",)
    assert notice.status == "partial"


def test_parse_detour_same_street_twice_is_an_issue() -> None:
    notice = parse_made(location_start="Ridge Ave & Ridge Ave")
    assert notice.start_place is None
    assert notice.issues == (
        "location_start: same street twice in location 'Ridge Ave & Ridge Ave'",
    )


def test_parse_detour_location_issues_quote_raw_text() -> None:
    """The issue shows what SEPTA sent, spacing included."""
    notice = parse_made(location_start="Broad  & ")
    assert notice.issues == ("location_start: unrecognized location 'Broad  & '",)


def test_parse_detour_issue_order_with_locations() -> None:
    """start, end, the order check, location_start, location_end, direction."""
    notice = parse_made(
        start="",
        end="garbage",
        location_start="Dickinson",
        location_end="PNC Center",
        message="no direction here",
    )
    assert notice.issues == (
        "start: blank datetime ''",
        "end: unrecognized datetime 'garbage'",
        "location_start: unrecognized location 'Dickinson'",
        "location_end: unrecognized location 'PNC Center'",
        NONE_FOUND,
    )


def test_parse_detour_location_issue_after_order_check() -> None:
    notice = parse_made(
        start="1/2/2027 1:00 PM", end="1/1/2027 1:00 PM", location_start="Dickinson"
    )
    assert notice.issues == (
        "end: before start",
        "location_start: unrecognized location 'Dickinson'",
    )


# --- parse_detour: every fixture item --------------------------------------


def parse_all_fixtures(
    read_alert_fixture: Callable[[str], bytes], names: list[str]
) -> dict[tuple[str, int], DetourNotice]:
    """Every detour item in every fixture, keyed by ``(file name, index)``."""
    notices: dict[tuple[str, int], DetourNotice] = {}
    for name in names:
        stamp, route_file = name.split("__", 1)
        route_id = route_file.removesuffix(".json")
        route = load_route(read_alert_fixture, stamp, route_id)
        assert route.route_id == route_id, name  # file name matches content
        for index, detour in enumerate(route.detour):
            notices[name, index] = parse_detour(route, detour, f"{stamp}.json")
    return notices


def test_parse_detour_every_fixture_item_round_trips(
    read_alert_fixture: Callable[[str], bytes], alert_fixture_names: list[str]
) -> None:
    """Messy text never raises, and every notice survives a JSON round trip
    (so ``data/processed/`` can be read back)."""
    notices = parse_all_fixtures(read_alert_fixture, alert_fixture_names)
    for key, notice in notices.items():
        reloaded = DetourNotice.model_validate_json(notice.model_dump_json())
        assert reloaded == notice, key


JFK_TO_MARKET = "unrecognized location 'JFK/17th to 30th & Market 23rd to 19th'"
JFK_ART_MUSEUM = "unrecognized location 'JFK btwn 20th & 15th/ Art Museum 16th'"
VA_HOSPITAL = "unrecognized location 'University Ave at The VA Hospital'"
PNC_CENTER = "unrecognized location 'PNC Center'"
RIDGE_TWICE = "location_start: same street twice in location 'Ridge Ave & Ridge Ave'"

NOT_COMPLETE = {
    (f"{OLD}__bus_route_2.json", 3): ("partial", (f"location_end: {JFK_TO_MARKET}",)),
    (f"{OLD}__bus_route_24.json", 1): (
        "partial",
        ("location_start: unrecognized location 'Bethayres Station'", NONE_FOUND),
    ),
    (f"{OLD}__bus_route_44.json", 4): ("partial", (f"location_end: {JFK_TO_MARKET}",)),
    (f"{OLD}__bus_route_49.json", 2): (
        "partial",
        (f"location_start: {VA_HOSPITAL}", f"location_end: {VA_HOSPITAL}"),
    ),
    (f"{OLD}__bus_route_6.json", 0): ("partial", (NONE_FOUND,)),
    (f"{OLD}__bus_route_61.json", 0): ("partial", (RIDGE_TWICE,)),
    (f"{OLD}__bus_route_61.json", 1): ("partial", (RIDGE_TWICE,)),
    (f"{OLD}__bus_route_64.json", 1): ("unknown", ()),
    (f"{OLD}__bus_route_64.json", 2): ("unknown", ()),
    (f"{OLD}__bus_route_68.json", 0): (
        "partial",
        (f"location_start: {PNC_CENTER}", f"location_end: {PNC_CENTER}"),
    ),
    (f"{OLD}__bus_route_68.json", 1): (
        "partial",
        (f"location_start: {PNC_CENTER}", f"location_end: {PNC_CENTER}"),
    ),
    (f"{NEW}__bus_route_124.json", 2): (
        "partial",
        (f"location_end: {JFK_ART_MUSEUM}",),
    ),
    (f"{NEW}__bus_route_124.json", 3): (
        "partial",
        (f"location_end: {JFK_ART_MUSEUM}",),
    ),
    (f"{NEW}__bus_route_31.json", 5): ("partial", (f"location_end: {JFK_ART_MUSEUM}",)),
    (f"{NEW}__bus_route_31.json", 6): (
        "partial",
        (
            "location_start: unrecognized location 'Broad &'",
            f"location_end: {JFK_ART_MUSEUM}",
        ),
    ),
}
"""Every fixture item that isn't ``complete``, with its issues."""


def test_parse_detour_fixture_summary_is_pinned(
    read_alert_fixture: Callable[[str], bytes], alert_fixture_names: list[str]
) -> None:
    """A parser change that alters any item's quality shows up here. Adding a
    fixture changes the count on purpose: review its items, then update."""
    notices = parse_all_fixtures(read_alert_fixture, alert_fixture_names)
    assert len(notices) == 65
    not_complete = {
        key: (notice.status, notice.issues)
        for key, notice in notices.items()
        if notice.status != "complete"
    }
    assert not_complete == NOT_COMPLETE


# --- parse_snapshot --------------------------------------------------------

# Not sorted by route_id, with detour-less entries in between.
MINI_ROUTES = (
    "bus_route_55",
    "APP",
    "bus_route_64",
    "trolley_route_15",
    "bus_route_24",
)


def mini_snapshot(
    read_alert_fixture: Callable[[str], bytes], route_ids: tuple[str, ...]
) -> bytes:
    """Several fixtures from the earlier snapshot, joined into one API list."""
    entries = [read_alert_fixture(f"{OLD}__{route_id}.json") for route_id in route_ids]
    return b"[" + b",".join(entries) + b"]"


def test_parse_snapshot_api_order(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """Route order, then list order; detour-less routes contribute nothing."""
    content = mini_snapshot(read_alert_fixture, MINI_ROUTES)
    notices = parse_snapshot(content, f"{OLD}.json")
    expected = [
        parse_detour(route, detour, f"{OLD}.json")
        for route_id in MINI_ROUTES
        for route in [load_route(read_alert_fixture, OLD, route_id)]
        for detour in route.detour
    ]
    assert notices == expected
    # 55 has 1 item, 64 has 6, 24 has 4 (guards the expected list itself).
    assert [n.source.route_id for n in notices] == (
        ["bus_route_55"] + ["bus_route_64"] * 6 + ["bus_route_24"] * 4
    )
    # Within a route, list order: route 64's items in index order.
    route_64 = load_route(read_alert_fixture, OLD, "bus_route_64")
    assert [n.source.message for n in notices[1:7]] == [
        d.message for d in route_64.detour
    ]


def test_parse_snapshot_stores_snapshot_name(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    content = mini_snapshot(read_alert_fixture, MINI_ROUTES)
    notices = parse_snapshot(content, "other.json")
    assert {n.source.snapshot for n in notices} == {"other.json"}


def test_parse_snapshot_no_detours_anywhere(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    content = mini_snapshot(read_alert_fixture, ("APP", "trolley_route_15"))
    assert parse_snapshot(content, f"{OLD}.json") == []


@pytest.mark.parametrize(
    "content",
    [b"[]", b"not json", b'[{"route_id": "bus_route_1", "mode": "Bus"}]'],
)
def test_parse_snapshot_structural_error_raises(content: bytes) -> None:
    """The whole snapshot fails; nothing is partially returned."""
    with pytest.raises(ValidationError):
        parse_snapshot(content, f"{OLD}.json")
