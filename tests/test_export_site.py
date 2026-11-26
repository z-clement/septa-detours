"""Tests for ``export.__main__``'s ``site`` command (``export_site``).

The ``site_gtfs`` fixture writes a tiny fake GTFS for *both* feeds under
``tmp_path`` and ``chdir``s there, so the real default paths are used.
The rail feed has no ``feed_info.txt`` (its version must come out null).
Detours are real route 2 notices matched onto the fake route 21.
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from septa_detours.export import __main__ as export_main
from septa_detours.export.__main__ import (
    DEFAULT_DETOURS_DIR,
    MATCH_COMMAND,
    export_site,
    main,
)
from septa_detours.model import (
    AffectedShape,
    Detour,
    DetourNotice,
    RouteMatch,
    StartPoint,
    dump_detours,
)
from septa_detours.parse.notice import parse_snapshot

BUS = {
    "routes.txt": (
        "route_id,route_short_name,route_long_name,route_type,route_color,route_text_color\n"
        "21,21,Chestnut-Walnut,3,EF3340,FFFFFF\n"
        "NS,NS,No Service,3,,\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
        "21,wk,t1,Penn's Landing,0,317337\n"
        "21,wk,t2,69th St,1,317338\n"
        "21,wk,t3,Penn's Landing,0,317337\n"
    ),
    "shapes.txt": (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
        "317337,39.961991,-75.258781,1\n"
        "317337,39.952600,-75.165200,2\n"
        "317338,39.952600,-75.165200,1\n"
        "317338,39.961991,-75.258781,2\n"
    ),
    "directions.txt": (
        "route_id,direction_id,direction,direction_destination\n"
        "21,0,Eastbound,Penn's Landing\n"
        "21,1,Westbound,69th St TC\n"
        "NS,0,Loop,Nowhere\n"
    ),
    "feed_info.txt": (
        "feed_publisher_name,feed_publisher_url,feed_lang,"
        "feed_start_date,feed_end_date,feed_version\r\n"
        "SEPTA,https://septa.org/,en,20261122,20270220,v202611220\r\n"
    ),
}
RAIL = {
    "routes.txt": (
        "route_id,route_short_name,route_long_name,route_type,route_color,route_text_color\r\n"
        "AIR,AIR,Airport Line,2,5A6F7B,FFFFFF\r\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\r\n"
        "AIR,wk,r1,Center City,0,001005\r\n"
    ),
    "shapes.txt": (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\r\n"
        "001005,39.876543,-75.241234,1\r\n"
        "001005,39.906543,-75.201234,2\r\n"
    ),
    "directions.txt": (
        "route_id,direction_id,direction,direction_destination\r\n"
        "AIR,0,Inbound,Center City Philadelphia\r\n"
    ),
}

STAMP = "2026-11-25T025344Z"
DETOURS_FILE = DEFAULT_DETOURS_DIR / f"detours-{STAMP}.json"
WEB_DATA = Path("web/data")
NOW = datetime(2026, 11, 25, 14, 0, tzinfo=UTC)


@pytest.fixture
def site_gtfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for feed, files in (("bus", BUS), ("rail", RAIL)):
        folder = tmp_path / "data" / "gtfs" / feed
        folder.mkdir(parents=True)
        for name, text in files.items():
            (folder / name).write_bytes(text.encode("utf-8"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def detours(read_alert_fixture) -> list[Detour]:
    """Route 2 #0 placed and #1 not placed on route 21; #3 unmatched."""
    content = read_alert_fixture(f"{STAMP}__bus_route_2.json")
    notices: list[DetourNotice] = parse_snapshot(b"[" + content + b"]", f"{STAMP}.json")
    shapes = (AffectedShape(shape_id="317337", direction_id=0),)
    start = StartPoint(node_id=11, lon=-75.2101, lat=39.9588)
    return [
        Detour(
            notice=notices[0],
            match=RouteMatch(
                feed="bus", route_id="21", shapes=shapes, start_point=start
            ),
        ),
        Detour(notice=notices[3], match=None),
        Detour(
            notice=notices[1],
            match=RouteMatch(
                feed="bus", route_id="21", shapes=shapes, start_point=None
            ),
        ),
    ]


def write_detours(detours: list[Detour], path: Path = DETOURS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump_detours(detours))


def read(name: str) -> Any:
    return json.loads((WEB_DATA / name).read_text(encoding="utf-8"))


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_writes_every_file_and_summarizes(detours) -> None:
    write_detours(detours)
    summary = export_site(DETOURS_FILE, now=NOW)
    names = sorted(p.relative_to(WEB_DATA).as_posix() for p in WEB_DATA.rglob("*.*"))
    assert names == [
        "network.geojson",
        "paths.geojson",
        "routes.json",
        "routes/bus-21.json",
        "routes/bus-NS.json",
        "routes/rail-AIR.json",
        "skipped.geojson",
        "starts.geojson",
        "status.json",
    ]
    assert summary == (
        "wrote 9 files to web/data (0.0 MB: 3 routes (2 with shapes), "
        f"1 start points from 3 detours in detours-{STAMP}.json)"
    )


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_status(detours) -> None:
    write_detours(detours)
    export_site(DETOURS_FILE, now=NOW)
    result = read("status.json")
    assert {key: value for key, value in result.items() if key != "unmatched"} == {
        "schema_version": 9,
        "generated_at": "2026-11-25T14:00:00Z",
        "snapshot": f"{STAMP}.json",
        "snapshot_fetched_at": "2026-11-25T02:53:44Z",
        "gtfs": {"bus": "v202611220", "rail": None},
        "detours": {"total": 3, "matched": 2, "placed": 1},
    }
    assert [d["source_key"] for d in result["unmatched"]] == [
        detours[1].notice.source_key
    ]


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_catalog_and_details(detours) -> None:
    write_detours(detours)
    export_site(DETOURS_FILE, now=NOW)
    catalog = read("routes.json")
    assert [(e["key"], e["has_shapes"], e["detours"]) for e in catalog] == [
        (
            "bus-21",
            True,
            {
                "total": 2,
                "placed": 1,
                "windows": [  # JSON: each window a 2-item list
                    ["2026-11-11T06:30:00-05:00", "2026-11-27T16:00:00-05:00"],
                    ["2026-11-19T10:00:00-05:00", "2026-12-01T23:59:00-05:00"],
                ],
            },
        ),
        ("bus-NS", False, {"total": 0, "placed": 0, "windows": []}),
        ("rail-AIR", True, {"total": 0, "placed": 0, "windows": []}),
    ]
    route_21 = read("routes/bus-21.json")
    assert [d["name"] for d in route_21["directions"]] == ["Eastbound", "Westbound"]
    assert [
        (f["properties"]["shape_id"], f["properties"]["trip_count"])
        for f in route_21["shapes"]["features"]
    ] == [("317337", 2), ("317338", 1)]
    assert [d["source_key"] for d in route_21["detours"]] == [
        detours[0].notice.source_key,
        detours[2].notice.source_key,
    ]
    no_service = read("routes/bus-NS.json")
    assert (no_service["directions"], no_service["shapes"]["features"]) == (
        [{"direction_id": 0, "name": "Loop", "destination": "Nowhere"}],
        [],
    )


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_network_and_starts(detours) -> None:
    write_detours(detours)
    export_site(DETOURS_FILE, now=NOW)
    network = read("network.geojson")
    assert [
        (f["properties"]["key"], f["properties"]["direction_id"])
        for f in network["features"]
    ] == [("bus-21", 0), ("bus-21", 1), ("rail-AIR", 0)]
    [dot] = read("starts.geojson")["features"]
    assert dot == {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-75.2101, 39.9588]},
        "properties": {
            "key": "bus-21",
            "source_key": detours[0].notice.source_key,
            "color": "#EF3340",
            "start": "2026-11-11T06:30:00-05:00",
            "end": "2026-11-27T16:00:00-05:00",
            "hours_days": "01234",
            "hours_start": "07:00",
            "hours_end": "16:00",
        },
    }


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_removes_files_of_routes_that_are_gone(detours) -> None:
    (WEB_DATA / "routes").mkdir(parents=True)
    (WEB_DATA / "routes" / "bus-99.json").write_text("{}")
    write_detours(detours)
    export_site(DETOURS_FILE, now=NOW)
    assert not (WEB_DATA / "routes" / "bus-99.json").exists()


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_uses_the_current_time_by_default(detours) -> None:
    write_detours(detours)
    before = datetime.now(UTC).replace(microsecond=0)
    export_site(DETOURS_FILE)
    generated = datetime.fromisoformat(read("status.json")["generated_at"])
    assert before <= generated <= datetime.now(UTC)


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_invalid_detours_fail_before_gtfs(site_gtfs: Path) -> None:
    write_detours([])
    DETOURS_FILE.write_text("not json")
    for feed in ("bus", "rail"):
        (site_gtfs / "data" / "gtfs" / feed / "shapes.txt").unlink()
    with pytest.raises(ValueError, match="Invalid JSON"):
        export_site(DETOURS_FILE, now=NOW)
    assert not WEB_DATA.exists()


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_missing_gtfs_raises_and_writes_nothing(
    site_gtfs: Path, detours
) -> None:
    write_detours(detours)
    (site_gtfs / "data" / "gtfs" / "rail" / "directions.txt").unlink()
    with pytest.raises(FileNotFoundError):
        export_site(DETOURS_FILE, now=NOW)
    assert not WEB_DATA.exists()


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_snapshot_comes_from_the_detours(detours) -> None:
    # The detours file's own name doesn't matter: each notice records its
    # snapshot.
    path = Path("anything.json")
    write_detours(detours, path)
    export_site(path, now=NOW)
    result = read("status.json")
    assert (result["snapshot"], result["snapshot_fetched_at"]) == (
        f"{STAMP}.json",
        "2026-11-25T02:53:44Z",
    )


@pytest.mark.usefixtures("site_gtfs")
@pytest.mark.parametrize(
    ("file_name", "snapshot", "fetched_at"),
    [
        (f"detours-{STAMP}.json", f"{STAMP}.json", "2026-11-25T02:53:44Z"),
        ("detours-mine.json", "mine.json", None),
        ("mine.json", "mine.json", None),
    ],
)
def test_export_site_no_detours_takes_the_snapshot_from_the_file_name(
    file_name: str, snapshot: str, fetched_at: str | None
) -> None:
    path = DEFAULT_DETOURS_DIR / file_name
    write_detours([], path)
    export_site(path, now=NOW)
    result = read("status.json")
    assert (result["snapshot"], result["snapshot_fetched_at"]) == (snapshot, fetched_at)


@pytest.mark.usefixtures("site_gtfs")
def test_export_site_rejects_detours_from_two_snapshots(
    detours, read_alert_fixture
) -> None:
    content = read_alert_fixture(f"{STAMP}__bus_route_2.json")
    later = parse_snapshot(b"[" + content + b"]", "2026-11-26T000000Z.json")[0]
    write_detours([*detours, Detour(notice=later, match=None)])
    with pytest.raises(ValueError, match="more than one snapshot"):
        export_site(DETOURS_FILE, now=NOW)
    assert not WEB_DATA.exists()


# --- main and python -m ---------------------------------------------------------


@pytest.mark.usefixtures("site_gtfs")
def test_main_site_uses_newest_detours_file(detours, capsys) -> None:
    write_detours([], DEFAULT_DETOURS_DIR / "detours-2026-11-24T000000Z.json")
    write_detours(detours)
    assert main(["site"]) == 0
    assert f"from 3 detours in detours-{STAMP}.json" in capsys.readouterr().out


@pytest.mark.usefixtures("site_gtfs")
def test_main_site_explicit_file(detours, capsys) -> None:
    path = Path("mine.json")
    write_detours(detours, path)
    assert main(["site", "mine.json"]) == 0
    assert "in mine.json)" in capsys.readouterr().out


@pytest.mark.usefixtures("site_gtfs")
def test_main_site_without_detours_names_match_command(capsys) -> None:
    assert main(["site"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: no detours file")
    assert MATCH_COMMAND in err


@pytest.mark.usefixtures("site_gtfs")
def test_main_site_does_not_catch_unexpected_errors(monkeypatch) -> None:
    def broken(*args: object, **kwargs: object) -> str:
        raise RuntimeError("bug")

    monkeypatch.setattr(export_main, "export_site", broken)
    with pytest.raises(RuntimeError, match="bug"):
        main(["site", "x.json"])


@pytest.mark.usefixtures("site_gtfs")
def test_python_dash_m_site(detours) -> None:
    write_detours(detours)
    result = subprocess.run(
        [sys.executable, "-m", "septa_detours.export", "site"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("wrote 9 files to web/data")
