import json
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from septa_detours.parse._api import ApiDetour, ApiRoute, read_snapshot

OLD = "2026-11-25T025344Z"

DETOUR_KEYS = ("location_start", "location_end", "start", "end", "message", "reason")


def make_detour(**overrides: Any) -> dict[str, Any]:
    """A raw detour item (route 31 #4's key fields), with overrides."""
    item: dict[str, Any] = {
        "location_start": "Broad & Walnut",
        "location_end": "",
        "start": "11/25/2026   3:00 PM",
        "end": "11/26/2026   2:00 AM",
        "message": "EB via Broad St, Reg Rt",
        "reason": "Special Event",
    }
    return item | overrides


def make_entry(**overrides: Any) -> dict[str, Any]:
    """A raw route entry with one detour, with overrides."""
    entry: dict[str, Any] = {
        "route_id": "bus_route_31",
        "mode": "Bus",
        "detour": [make_detour()],
    }
    return entry | overrides


def to_bytes(value: Any) -> bytes:
    return json.dumps(value).encode()


def wrap_fixtures(read_alert_fixture: Callable[[str], bytes], *names: str) -> bytes:
    """Join fixture files (one route entry each) into a snapshot's bytes."""
    return b"[" + b",".join(read_alert_fixture(name) for name in names) + b"]"


# --- real fixtures ---------------------------------------------------------


def test_every_fixture_reads_verbatim(
    read_alert_fixture: Callable[[str], bytes], alert_fixture_names: list[str]
) -> None:
    """Each fixture entry validates, and every declared field equals the
    decoded JSON exactly: no cleaning, no reordering."""
    for name in alert_fixture_names:
        raw = json.loads(read_alert_fixture(name))
        (route,) = read_snapshot(wrap_fixtures(read_alert_fixture, name))

        assert (route.route_id, route.mode) == (raw["route_id"], raw["mode"]), name
        assert [[getattr(d, key) for key in DETOUR_KEYS] for d in route.detour] == [
            [item[key] for key in DETOUR_KEYS] for item in raw["detour"]
        ], name


def test_fixture_irregular_spaces_kept(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    (route,) = read_snapshot(
        wrap_fixtures(read_alert_fixture, f"{OLD}__bus_route_31.json")
    )
    assert route.detour[4].start == "11/25/2026   3:00 PM"


def test_entries_keep_api_order(read_alert_fixture: Callable[[str], bytes]) -> None:
    names = [
        f"{OLD}__bus_route_55.json",
        f"{OLD}__APP.json",
        f"{OLD}__bus_route_2.json",
    ]
    routes = read_snapshot(wrap_fixtures(read_alert_fixture, *names))
    assert [r.route_id for r in routes] == ["bus_route_55", "APP", "bus_route_2"]


def test_route_without_detours(read_alert_fixture: Callable[[str], bytes]) -> None:
    (route,) = read_snapshot(wrap_fixtures(read_alert_fixture, f"{OLD}__APP.json"))
    assert route.detour == ()


def test_unwrapped_fixture_is_rejected(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """A single route object at the top level isn't a snapshot."""
    with pytest.raises(ValidationError):
        read_snapshot(read_alert_fixture(f"{OLD}__bus_route_55.json"))


# --- hand-built ------------------------------------------------------------


def test_returns_models() -> None:
    routes = read_snapshot(to_bytes([make_entry()]))
    assert routes == [
        ApiRoute(
            route_id="bus_route_31", mode="Bus", detour=(ApiDetour(**make_detour()),)
        )
    ]


def test_escaped_slashes_decode() -> None:
    """The live API escapes ``/`` as ``\\/`` (the fixtures were re-encoded
    without it)."""
    content = to_bytes([make_entry(detour=[make_detour(start="START")])]).replace(
        b"START", b"11\\/25\\/2026   3:00 PM"
    )
    (route,) = read_snapshot(content)
    assert route.detour[0].start == "11/25/2026   3:00 PM"


@pytest.mark.parametrize(
    "location",
    [
        pytest.param("Broad\u00a0& Walnut".encode(), id="utf8-bytes"),
        pytest.param(b"Broad\\u00a0& Walnut", id="json-escape"),
    ],
)
def test_non_ascii_kept(location: bytes) -> None:
    content = to_bytes(
        [make_entry(detour=[make_detour(location_start="LOC")])]
    ).replace(b"LOC", location)
    (route,) = read_snapshot(content)
    assert route.detour[0].location_start == "Broad\u00a0& Walnut"


def test_unknown_keys_ignored() -> None:
    """Extra keys at either level change nothing (real entries carry
    ``isdetour``, ``advisory``, ...)."""
    entry = make_entry(detour=[make_detour(new_api_key=1)], isdetour="Y", extra=None)
    assert read_snapshot(to_bytes([entry])) == read_snapshot(to_bytes([make_entry()]))


def test_one_bad_entry_fails_whole_snapshot() -> None:
    with pytest.raises(ValidationError):
        read_snapshot(to_bytes([make_entry(), make_entry(mode=None), make_entry()]))


def without(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in mapping.items() if k != key}


@pytest.mark.parametrize(
    "content",
    [
        # Not (valid UTF-8) JSON.
        pytest.param(b"", id="empty-bytes"),
        pytest.param(b"<html>Service Unavailable</html>", id="html"),
        pytest.param(to_bytes([make_entry()])[:-5], id="truncated"),
        pytest.param(to_bytes([make_entry()]) + b" x", id="trailing-garbage"),
        pytest.param(b"\xef\xbb\xbf" + to_bytes([make_entry()]), id="bom"),
        pytest.param(
            to_bytes([make_entry(route_id="ROUTE")]).replace(b"ROUTE", b"\xe9"),
            id="invalid-utf8",
        ),
        # Wrong top level.
        pytest.param(b"[]", id="empty-list"),
        pytest.param(b"null", id="null"),
        pytest.param(to_bytes({"routes": [make_entry()]}), id="object"),
        # Route entry problems.
        pytest.param(to_bytes([without(make_entry(), "route_id")]), id="no-route_id"),
        pytest.param(to_bytes([without(make_entry(), "mode")]), id="no-mode"),
        pytest.param(to_bytes([without(make_entry(), "detour")]), id="no-detour"),
        pytest.param(to_bytes([make_entry(route_id=21)]), id="int-route_id"),
        pytest.param(to_bytes([make_entry(mode=None)]), id="null-mode"),
        pytest.param(to_bytes([make_entry(detour=None)]), id="null-detour"),
        pytest.param(to_bytes([make_entry(detour=make_detour())]), id="detour-object"),
        pytest.param(to_bytes(["bus_route_31"]), id="entry-string"),
        # Detour item problems.
        *(
            pytest.param(
                to_bytes([make_entry(detour=[without(make_detour(), key)])]),
                id=f"no-{key}",
            )
            for key in DETOUR_KEYS
        ),
        pytest.param(
            to_bytes([make_entry(detour=[make_detour(location_end=None)])]),
            id="null-location_end",
        ),
        pytest.param(
            to_bytes([make_entry(detour=[make_detour(start=1764100800)])]),
            id="int-start",
        ),
    ],
)
def test_rejected(content: bytes) -> None:
    with pytest.raises(ValidationError):
        read_snapshot(content)
