"""Tests for ``export.__main__``: the route export entry point.

The ``mini_gtfs`` fixture writes a tiny fake bus feed under ``tmp_path``
and ``chdir``s there, so the real default paths (``data/gtfs``,
``web/data``) are exercised without touching the repo's data. There is
deliberately no rail feed on disk: any attempt to load it would fail.

Several tests delete GTFS files the code *shouldn't need* for a given
failure, which proves the cheapest-first check order in ``export_route``.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from septa_detours.export.__main__ import export_route, main

# Routes in the fake feed:
#   21      two shapes, one per direction (the happy path)
#   NS      a known route with no trips, so no shapes
#   BROKEN  a trip points at a shape_id missing from shapes.txt
ROUTES_TXT = """\
route_id,route_short_name,route_long_name,route_type,route_color,route_text_color
21,21,Chestnut-Walnut,3,EF3340,FFFFFF
NS,NS,No Service,3,,
BROKEN,BR,Broken Route,3,000000,FFFFFF
"""

TRIPS_TXT = """\
route_id,service_id,trip_id,trip_headsign,direction_id,shape_id
21,wk,t1,Penn's Landing,0,317337
21,wk,t2,69th St,1,317338
21,wk,t3,Penn's Landing,0,317337
BROKEN,wk,t4,Nowhere,0,999999
"""

# Realistic Philly coords (lon ~ -75, lat ~ 40), so a lat/lon swap can't
# cancel out. Sequences are out of file order on purpose.
SHAPES_TXT = """\
shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence
317337,39.9526,-75.1652,2
317337,39.961991,-75.25878,1
317338,39.9526,-75.1652,1
317338,39.961991,-75.25878,2
"""

ROUTE_21_PROPS = {
    "feed": "bus",
    "route_id": "21",
    "route_short_name": "21",
    "route_long_name": "Chestnut-Walnut",
    "route_type": 3,
    "route_color": "#EF3340",
    "route_text_color": "#FFFFFF",
}

EXPECTED_ROUTE_21 = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-75.25878, 39.961991], [-75.1652, 39.9526]],
            },
            "properties": {**ROUTE_21_PROPS, "shape_id": "317337", "direction_id": 0},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-75.1652, 39.9526], [-75.25878, 39.961991]],
            },
            "properties": {**ROUTE_21_PROPS, "shape_id": "317338", "direction_id": 1},
        },
    ],
}

BUS_DIR = Path("data/gtfs/bus")
WEB_DATA = Path("web/data")


@pytest.fixture
def mini_gtfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a fake bus feed under ``tmp_path`` and make it the cwd."""
    bus = tmp_path / BUS_DIR
    bus.mkdir(parents=True)
    (bus / "routes.txt").write_text(ROUTES_TXT, encoding="utf-8")
    (bus / "trips.txt").write_text(TRIPS_TXT, encoding="utf-8")
    (bus / "shapes.txt").write_text(SHAPES_TXT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


# --- export_route: success -------------------------------------------------


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_returns_default_path_and_writes_it():
    path = export_route("bus", "21")

    assert path == WEB_DATA / "bus-21.geojson"
    assert path.is_file()


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_writes_expected_feature_collection():
    path = export_route("bus", "21")

    assert read_json(path) == EXPECTED_ROUTE_21


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_overwrites_previous_output():
    WEB_DATA.mkdir(parents=True)
    (WEB_DATA / "bus-21.geojson").write_text("stale", encoding="utf-8")

    path = export_route("bus", "21")

    assert read_json(path) == EXPECTED_ROUTE_21


# --- export_route: failures ------------------------------------------------


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_unknown_route_raises_and_writes_nothing():
    with pytest.raises(ValueError, match="found 0"):
        export_route("bus", "NOPE")

    assert not WEB_DATA.exists()


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_route_without_shapes_raises_and_writes_nothing():
    with pytest.raises(ValueError, match=r"'NS'.*'bus'.*no shapes"):
        export_route("bus", "NS")

    assert not WEB_DATA.exists()


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_missing_coordinates_raises_and_writes_nothing():
    with pytest.raises(ValueError, match="999999"):
        export_route("bus", "BROKEN")

    assert not WEB_DATA.exists()


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_failure_leaves_existing_file_untouched():
    WEB_DATA.mkdir(parents=True)
    existing = WEB_DATA / "bus-NS.geojson"
    existing.write_text("previous good export", encoding="utf-8")

    with pytest.raises(ValueError, match="no shapes"):
        export_route("bus", "NS")

    assert existing.read_text(encoding="utf-8") == "previous good export"


# --- export_route: check order (fail before expensive loads) ---------------


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_rejects_unsafe_route_id_before_reading_gtfs():
    for table in ("routes", "trips", "shapes"):
        (BUS_DIR / f"{table}.txt").unlink()

    # A FileNotFoundError here would mean GTFS was read first.
    with pytest.raises(ValueError, match="not safe"):
        export_route("bus", "../x")


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_unknown_route_fails_before_reading_trips_or_shapes():
    (BUS_DIR / "trips.txt").unlink()
    (BUS_DIR / "shapes.txt").unlink()

    with pytest.raises(ValueError, match="found 0"):
        export_route("bus", "NOPE")


@pytest.mark.usefixtures("mini_gtfs")
def test_export_route_no_shapes_fails_before_reading_shapes():
    (BUS_DIR / "shapes.txt").unlink()

    with pytest.raises(ValueError, match="no shapes"):
        export_route("bus", "NS")


# --- main ------------------------------------------------------------------


@pytest.mark.usefixtures("mini_gtfs")
def test_main_success_returns_0_and_reports_path(capsys):
    code = main(["bus", "21"])

    out, err = capsys.readouterr()
    assert code == 0
    assert out == f"wrote {WEB_DATA / 'bus-21.geojson'}\n"
    assert err == ""
    assert read_json(WEB_DATA / "bus-21.geojson") == EXPECTED_ROUTE_21


@pytest.mark.usefixtures("mini_gtfs")
def test_main_value_error_returns_1_with_message_on_stderr(capsys):
    code = main(["bus", "NOPE"])

    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err == "error: Expected 1 route for ('bus', 'NOPE'), found 0.\n"


@pytest.mark.usefixtures("mini_gtfs")
@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["bsu", "21"], id="bad-feed"),
        pytest.param(["bus"], id="missing-route-id"),
        pytest.param([], id="no-args"),
        pytest.param(["bus", "21", "extra"], id="extra-arg"),
    ],
)
def test_main_bad_arguments_exit_2_without_writing(argv, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(argv)

    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err
    assert not WEB_DATA.exists()


@pytest.mark.usefixtures("mini_gtfs")
def test_main_does_not_catch_unexpected_errors():
    # A missing GTFS file is not a "can't export this route" case: it
    # should surface as its own exception with a traceback, not exit 1.
    (BUS_DIR / "routes.txt").unlink()

    with pytest.raises(FileNotFoundError):
        main(["bus", "21"])


# --- python -m entry point -------------------------------------------------


@pytest.mark.usefixtures("mini_gtfs")
@pytest.mark.parametrize(
    ("route_id", "expected_code"),
    [
        pytest.param("21", 0, id="success"),
        pytest.param("NOPE", 1, id="unknown-route"),
    ],
)
def test_python_dash_m_exit_code(route_id, expected_code):
    # Checks the `raise SystemExit(main())` wiring that in-process tests
    # can't reach.
    result = subprocess.run(
        [sys.executable, "-m", "septa_detours.export", "bus", route_id],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_code, result.stderr
