"""Tests for ``match.routes.find_gtfs_route``.

GTFS is not committed, so ``routes`` is hand-built from real GTFS IDs
(2026-11-25 feed). API IDs come from the alert fixtures where possible.
"""

import json
from collections.abc import Callable

import polars as pl
import pytest

from septa_detours.match.routes import API_ROUTE_ALIASES, find_gtfs_route

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

BUS_ROUTE_IDS = (
    # Bus routes in the alert fixtures.
    *("2", "6", "7", "9", "24", "31", "32", "44", "49", "55", "61", "64"),
    *("68", "103", "124"),
    # Alias targets, plus routes that sit near them by name.
    *("L1_OWL", "B1_OWL", "L1", "B1", "B2", "B3", "M1", "G1", "D1", "D2"),
    *("T1", "T2", "T3", "T4", "T5", "K", "51"),
)
RAIL_ROUTE_IDS = ("AIR", "CHE", "MED")


def make_routes(rows: list[tuple[str, str]]) -> pl.DataFrame:
    """Build a routes frame from ``(feed, route_id)`` pairs.

    ``find_gtfs_route`` reads only ``feed`` and ``route_id``; the other
    columns get placeholder values.
    """
    full_rows = [
        (route_id, route_id, "Somewhere", 3, "EF3340", "FFFFFF", feed)
        for feed, route_id in rows
    ]
    return pl.DataFrame(full_rows, schema=ROUTES_SCHEMA, orient="row")


@pytest.fixture
def routes() -> pl.DataFrame:
    """Real GTFS route IDs from both feeds, bus first (as ``load_routes``)."""
    return make_routes(
        [("bus", r) for r in BUS_ROUTE_IDS] + [("rail", r) for r in RAIL_ROUTE_IDS]
    )


# --- Fixtures: every real API route ID we have ------------------------------

FIXTURE_EXPECTED: dict[str, tuple[str, str] | None] = {
    "2026-11-25T025344Z__APP.json": None,
    "2026-11-25T025344Z__bus_route_103.json": ("bus", "103"),
    "2026-11-25T025344Z__bus_route_24.json": ("bus", "24"),
    "2026-11-25T025344Z__bus_route_2.json": ("bus", "2"),
    "2026-11-25T025344Z__bus_route_31.json": ("bus", "31"),
    "2026-11-25T025344Z__bus_route_32.json": ("bus", "32"),
    "2026-11-25T025344Z__bus_route_44.json": ("bus", "44"),
    "2026-11-25T025344Z__bus_route_49.json": ("bus", "49"),
    "2026-11-25T025344Z__bus_route_55.json": ("bus", "55"),
    "2026-11-25T025344Z__bus_route_61.json": ("bus", "61"),
    "2026-11-25T025344Z__bus_route_64.json": ("bus", "64"),
    "2026-11-25T025344Z__bus_route_68.json": ("bus", "68"),
    "2026-11-25T025344Z__bus_route_6.json": ("bus", "6"),
    "2026-11-25T025344Z__bus_route_7.json": ("bus", "7"),
    "2026-11-25T025344Z__bus_route_9.json": ("bus", "9"),
    "2026-11-25T025344Z__rr_route_bso.json": ("bus", "B1_OWL"),
    "2026-11-25T025344Z__rr_route_mfo.json": ("bus", "L1_OWL"),
    "2026-11-25T025344Z__trolley_route_15.json": ("bus", "G1"),
    "2026-11-25T121123Z__bus_route_124.json": ("bus", "124"),
    "2026-11-25T121123Z__bus_route_31.json": ("bus", "31"),
}


def test_fixture_table_covers_every_fixture(alert_fixture_names: list[str]):
    """Adding a fixture must add a row here (forces a decision on it)."""
    assert sorted(FIXTURE_EXPECTED) == alert_fixture_names


@pytest.mark.parametrize(("name", "expected"), FIXTURE_EXPECTED.items())
def test_fixture_route_ids(
    name: str,
    expected: tuple[str, str] | None,
    routes: pl.DataFrame,
    read_alert_fixture: Callable[[str], bytes],
):
    """Each fixture's real API ``route_id`` resolves as expected (or raises)."""
    api_route_id = json.loads(read_alert_fixture(name))["route_id"]
    if expected is None:
        with pytest.raises(ValueError, match="no GTFS route"):
            find_gtfs_route(api_route_id, routes)
    else:
        assert find_gtfs_route(api_route_id, routes) == expected


# --- Aliases ----------------------------------------------------------------


def test_alias_table_is_pinned():
    """The alias table is exactly the evidence-backed Metro renames.

    Written out by hand so a typo in one alias fails here. Changing the
    table must be deliberate: BSL (-> B1/B2/B3) and Bus Revolution renames
    (H, L, R) are left out on purpose.
    """
    expected = {
        "rr_route_mfo": ("bus", "L1_OWL"),
        "rr_route_bso": ("bus", "B1_OWL"),
        "rr_route_mfl": ("bus", "L1"),
        "rr_route_nhsl": ("bus", "M1"),
        "trolley_route_10": ("bus", "T1"),
        "trolley_route_34": ("bus", "T2"),
        "trolley_route_13": ("bus", "T3"),
        "trolley_route_11": ("bus", "T4"),
        "trolley_route_36": ("bus", "T5"),
        "trolley_route_15": ("bus", "G1"),
        "trolley_route_101": ("bus", "D1"),
        "trolley_route_102": ("bus", "D2"),
    }
    assert expected == API_ROUTE_ALIASES


@pytest.mark.parametrize("api_route_id", sorted(API_ROUTE_ALIASES))
def test_every_alias_resolves(api_route_id: str, routes: pl.DataFrame):
    """Each alias target exists in the (real-ID) routes frame and is returned."""
    assert find_gtfs_route(api_route_id, routes) == API_ROUTE_ALIASES[api_route_id]


def test_alias_wins_over_name_match():
    """If GTFS reused an old name, the alias still decides."""
    routes = make_routes([("bus", "15"), ("bus", "G1")])
    assert find_gtfs_route("trolley_route_15", routes) == ("bus", "G1")


def test_alias_target_missing_raises():
    """An alias whose target isn't in ``routes`` raises, naming the target."""
    routes = make_routes([("bus", "L1")])
    with pytest.raises(ValueError, match="bus route 'L1_OWL'") as excinfo:
        find_gtfs_route("rr_route_mfo", routes)
    assert "'rr_route_mfo'" in str(excinfo.value)


def test_unaliased_rename_has_no_name_fallback(routes: pl.DataFrame):
    """``rr_route_bsl`` is not aliased and ``rr_`` never name-matches."""
    with pytest.raises(ValueError, match="no GTFS route for API route 'rr_route_bsl'"):
        find_gtfs_route("rr_route_bsl", routes)


# --- Name matching ----------------------------------------------------------


def test_bus_prefix_name_matches():
    routes = make_routes([("bus", "21")])
    assert find_gtfs_route("bus_route_21", routes) == ("bus", "21")


def test_trolley_prefix_name_matches():
    """A ``trolley_route_`` ID with no alias still name-matches the bus feed."""
    routes = make_routes([("bus", "99")])
    assert find_gtfs_route("trolley_route_99", routes) == ("bus", "99")


def test_letter_route_name_matches(routes: pl.DataFrame):
    assert find_gtfs_route("bus_route_K", routes) == ("bus", "K")


def test_name_match_keeps_underscores_in_remainder():
    """Real GTFS IDs like ``T_BUS`` contain ``_``; only the prefix is removed."""
    routes = make_routes([("bus", "BUS"), ("bus", "T_BUS")])
    assert find_gtfs_route("bus_route_T_BUS", routes) == ("bus", "T_BUS")


def test_name_match_is_case_sensitive(routes: pl.DataFrame):
    """``k`` is not ``K``: GTFS IDs are matched exactly."""
    with pytest.raises(ValueError, match="bus route 'k'"):
        find_gtfs_route("bus_route_k", routes)


def test_name_match_uses_bus_feed_only():
    """A rail ``route_id`` never satisfies a ``bus_route_`` name."""
    routes = make_routes([("rail", "AIR")])
    with pytest.raises(ValueError, match="bus route 'AIR'"):
        find_gtfs_route("bus_route_AIR", routes)


def test_rail_routes_never_name_match(routes: pl.DataFrame):
    """``rr_route_med`` doesn't find rail ``MED``, even with matching case."""
    for api_route_id in ("rr_route_med", "rr_route_MED"):
        with pytest.raises(ValueError, match=f"API route '{api_route_id}'$"):
            find_gtfs_route(api_route_id, routes)


def test_retired_bus_route_raises(routes: pl.DataFrame):
    """Bus Revolution renames like ``H`` have no GTFS route and no alias."""
    with pytest.raises(ValueError, match="bus_route_H") as excinfo:
        find_gtfs_route("bus_route_H", routes)
    expected = "no GTFS route for API route 'bus_route_H' (looked for bus route 'H')"
    assert expected == str(excinfo.value)


@pytest.mark.parametrize(
    "api_route_id",
    [
        "bus_route_",  # empty remainder
        "bus_route_21 ",  # trailing space: verbatim IDs are not cleaned
        "Bus_route_21",  # prefix is case-sensitive too
        "xbus_route_21",  # prefix must be at the start
        "21",  # bare GTFS ID is not an API ID
        "",
    ],
)
def test_malformed_ids_raise(api_route_id: str):
    routes = make_routes([("bus", "21")])
    with pytest.raises(ValueError, match="no GTFS route"):
        find_gtfs_route(api_route_id, routes)


def test_routes_without_bus_feed_match_nothing():
    """With only rail loaded, a bus route can't match."""
    routes = make_routes([("rail", "21")])
    with pytest.raises(ValueError, match="bus route '21'"):
        find_gtfs_route("bus_route_21", routes)


def test_returns_plain_tuple(routes: pl.DataFrame):
    result = find_gtfs_route("bus_route_55", routes)
    assert type(result) is tuple
    assert all(type(part) is str for part in result)
