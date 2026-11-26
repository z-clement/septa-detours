"""Tests for ``export.__main__``: the ``route`` command, argument handling,
and ``find_latest_detours`` (``site`` is in ``test_export_site.py``).

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

from septa_detours.export import __main__ as export_main
from septa_detours.export.__main__ import (
    DEFAULT_DETOURS_DIR,
    MATCH_COMMAND,
    export_route,
    find_latest_detours,
    main,
)

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
    code = main(["route", "bus", "21"])

    out, err = capsys.readouterr()
    assert code == 0
    assert out == f"wrote {WEB_DATA / 'bus-21.geojson'}\n"
    assert err == ""
    assert read_json(WEB_DATA / "bus-21.geojson") == EXPECTED_ROUTE_21


@pytest.mark.usefixtures("mini_gtfs")
def test_main_value_error_returns_1_with_message_on_stderr(capsys):
    code = main(["route", "bus", "NOPE"])

    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err == "error: Expected 1 route for ('bus', 'NOPE'), found 0.\n"


@pytest.mark.usefixtures("mini_gtfs")
def test_main_missing_gtfs_returns_1(capsys):
    # Decided: a missing file is an explainable failure (like the match and
    # streets commands), not a bug, so no traceback.
    (BUS_DIR / "routes.txt").unlink()

    code = main(["route", "bus", "21"])

    out, err = capsys.readouterr()
    assert (code, out) == (1, "")
    assert err.startswith("error: ")
    assert "routes.txt" in err
    assert not WEB_DATA.exists()


@pytest.mark.usefixtures("mini_gtfs")
@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="no-command"),
        pytest.param(["bus", "21"], id="old-form-without-command"),
        pytest.param(["routes", "bus", "21"], id="unknown-command"),
        pytest.param(["route", "bsu", "21"], id="bad-feed"),
        pytest.param(["route", "bus"], id="missing-route-id"),
        pytest.param(["route"], id="route-no-args"),
        pytest.param(["route", "bus", "21", "extra"], id="route-extra-arg"),
        pytest.param(["site", "a.json", "b.json"], id="site-extra-arg"),
        pytest.param(["detours"], id="removed-detours-command"),
    ],
)
def test_main_bad_arguments_exit_2_without_writing(argv, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(argv)

    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err
    assert not WEB_DATA.exists()


@pytest.mark.usefixtures("mini_gtfs")
def test_main_does_not_catch_unexpected_errors(monkeypatch):
    # Anything but FileNotFoundError / ValueError is a bug: keep the traceback.
    # (The same for `site` is in test_export_site.py.)
    def broken(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(export_main, "export_route", broken)

    with pytest.raises(RuntimeError, match="bug"):
        main(["route", "bus", "21"])


# --- python -m entry point -------------------------------------------------


@pytest.mark.usefixtures("mini_gtfs")
@pytest.mark.parametrize(
    ("argv", "expected_code"),
    [
        pytest.param(["route", "bus", "21"], 0, id="route-success"),
        pytest.param(["route", "bus", "NOPE"], 1, id="unknown-route"),
        pytest.param(["site"], 1, id="no-detours-file"),
        pytest.param(["detours"], 2, id="removed-detours-command"),
        pytest.param(["bus", "21"], 2, id="old-form"),
    ],
)
def test_python_dash_m_exit_code(argv, expected_code):
    # Checks the `raise SystemExit(main())` wiring that in-process tests
    # can't reach.
    result = subprocess.run(
        [sys.executable, "-m", "septa_detours.export", *argv],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_code, result.stderr


# --- find_latest_detours ----------------------------------------------------


def touch_all(root: Path, *names: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).touch()


def test_find_latest_detours_picks_newest_stamp(tmp_path):
    touch_all(
        tmp_path,
        "detours-2026-11-25T121123Z.json",
        "detours-2027-01-02T000000Z.json",
        "detours-2026-11-25T025344Z.json",
    )
    assert find_latest_detours(tmp_path).name == "detours-2027-01-02T000000Z.json"


@pytest.mark.parametrize(
    "stray",
    [
        "detours-2027-01-01T000000Z.json.tmp",  # write_bytes_atomic leftover
        "detours-mine.json",  # output of a hand-named snapshot
        "2027-01-01T000000Z.json",  # a snapshot, not detours
        "detours-2027-01-01T000000.json",  # no Z
        "xdetours-2027-01-01T000000Z.json",
        "detours-2027-01-01T000000Z.geojson",
        "streets.parquet",
    ],
)
def test_find_latest_detours_ignores_other_files(tmp_path, stray):
    touch_all(tmp_path, "detours-2026-11-25T025344Z.json", stray)
    assert find_latest_detours(tmp_path).name == "detours-2026-11-25T025344Z.json"


@pytest.mark.parametrize("make_dir", [False, True], ids=["no-directory", "empty"])
def test_find_latest_detours_none_names_match_command(tmp_path, make_dir):
    root = tmp_path / "processed"
    if make_dir:
        touch_all(root, "streets.parquet")
    with pytest.raises(FileNotFoundError, match="no detours file") as excinfo:
        find_latest_detours(root)
    assert str(root) in str(excinfo.value)
    assert MATCH_COMMAND in str(excinfo.value)
    assert MATCH_COMMAND == "uv run python -m septa_detours.match"


def test_find_latest_detours_default_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    touch_all(DEFAULT_DETOURS_DIR, "detours-2026-11-25T025344Z.json")
    assert Path("data/processed") == DEFAULT_DETOURS_DIR
    expected = DEFAULT_DETOURS_DIR / "detours-2026-11-25T025344Z.json"
    assert find_latest_detours() == expected


def test_detours_constants_match_the_match_command(tmp_path):
    # Duplicated on purpose (stages don't import each other); this test is
    # the only place that knows both.
    from septa_detours.match import __main__ as match_main

    assert match_main.DEFAULT_DETOURS_DIR == DEFAULT_DETOURS_DIR
    written = match_main.detours_path(Path("2027-03-04T050607Z.json"), tmp_path)
    touch_all(tmp_path, written.name)
    assert find_latest_detours(tmp_path) == written
