"""Tests for ``python -m septa_detours.match`` (parse + match one snapshot)."""

import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from septa_detours.match import __main__ as match_main
from septa_detours.match.__main__ import (
    DEFAULT_ALERTS_DIR,
    DEFAULT_DETOURS_DIR,
    INGEST_COMMAND,
    detours_path,
    find_latest_snapshot,
)
from septa_detours.model import read_detours
from septa_detours.streets.cache import (
    BUILD_COMMAND,
    StreetCacheInfo,
    write_street_cache,
)
from septa_detours.streets.load import STREET_WAYS_SCHEMA

# --- find_latest_snapshot ------------------------------------------------------


def touch_all(root: Path, *names: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).touch()


def test_find_latest_single_snapshot(tmp_path):
    touch_all(tmp_path, "2026-11-25T025344Z.json")
    assert find_latest_snapshot(tmp_path) == tmp_path / "2026-11-25T025344Z.json"


def test_find_latest_picks_newest_stamp(tmp_path):
    # Created out of order, and the newest is neither first nor last
    # alphabetically by anything but the stamp.
    touch_all(
        tmp_path,
        "2026-11-25T121123Z.json",
        "2027-01-02T000000Z.json",
        "2026-11-25T025344Z.json",
        "2026-12-31T235959Z.json",
    )
    assert find_latest_snapshot(tmp_path).name == "2027-01-02T000000Z.json"


def test_find_latest_same_day_compares_time(tmp_path):
    touch_all(tmp_path, "2026-11-25T025344Z.json", "2026-11-25T121123Z.json")
    assert find_latest_snapshot(tmp_path).name == "2026-11-25T121123Z.json"


@pytest.mark.parametrize(
    "stray",
    [
        "2027-01-01T000000Z.json.tmp",  # write_bytes_atomic leftover
        "2027-01-01T000000Z.JSON",  # case matters
        "2027-01-01T000000.json",  # no Z: not ingest's UTC name
        "2027-01-01T0000Z.json",  # seconds missing
        "2027-01-01 000000Z.json",  # space, not T
        "x2027-01-01T000000Z.json",  # prefix
        "2027-01-01T000000Z.json.bak",  # suffix
        "detours-2027-01-01T000000Z.json",  # match output, not a snapshot
        "latest.json",
        # Arabic-Indic digits for 2027 (``\d`` would match them, and they
        # sort after ASCII digits, so this would be "newest").
        "\u0662\u0660\u0662\u0667-01-01T000000Z.json",
        "2027-01-01T\u0660\u0660\u0660\u0660\u0660\u0660Z.json",  # and in the time
    ],
)
def test_find_latest_ignores_names_that_are_not_snapshots(tmp_path, stray):
    touch_all(tmp_path, "2026-11-25T025344Z.json", stray)
    assert find_latest_snapshot(tmp_path).name == "2026-11-25T025344Z.json"


def test_find_latest_checks_names_only_not_entry_type(tmp_path):
    # Only names are checked, so this pins today's behaviour: a directory
    # with a snapshot name *would* be returned. Not worth a stat per entry.
    touch_all(tmp_path, "2026-11-25T025344Z.json")
    (tmp_path / "2027-01-01T000000Z.json").mkdir()
    assert find_latest_snapshot(tmp_path).name == "2027-01-01T000000Z.json"


@pytest.mark.parametrize("make_dir", [False, True], ids=["no-directory", "empty"])
def test_find_latest_none_names_ingest_command(tmp_path, make_dir):
    root = tmp_path / "alerts"
    if make_dir:
        root.mkdir()
    with pytest.raises(FileNotFoundError, match="no alerts snapshot") as excinfo:
        find_latest_snapshot(root)
    assert str(root) in str(excinfo.value)
    assert INGEST_COMMAND in str(excinfo.value)
    assert INGEST_COMMAND == "uv run python -m septa_detours.ingest"


def test_find_latest_only_strays_is_none(tmp_path):
    touch_all(tmp_path, "2027-01-01T000000Z.json.tmp", "notes.txt")
    with pytest.raises(FileNotFoundError):
        find_latest_snapshot(tmp_path)


def test_find_latest_default_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    touch_all(DEFAULT_ALERTS_DIR, "2026-11-25T025344Z.json")
    assert Path("data/raw/alerts") == DEFAULT_ALERTS_DIR
    assert find_latest_snapshot() == DEFAULT_ALERTS_DIR / "2026-11-25T025344Z.json"


def test_default_dir_matches_ingest():
    # The constant is duplicated on purpose (stages don't import each
    # other); this test is the only place that knows both.
    from septa_detours.ingest.alerts import DEFAULT_ALERTS_DIR as INGEST_DIR

    assert INGEST_DIR == match_main.DEFAULT_ALERTS_DIR


def test_finds_names_ingest_writes(tmp_path):
    # The stamp pattern is duplicated too: whatever ``snapshot_path``
    # produces must be found.
    from septa_detours.ingest.alerts import snapshot_path

    written = snapshot_path(datetime(2027, 3, 4, 5, 6, 7, tzinfo=UTC), tmp_path)
    touch_all(tmp_path, written.name)
    assert find_latest_snapshot(tmp_path) == written


# --- the command ---------------------------------------------------------------

STAMP = "2026-11-25T025344Z"
SNAPSHOT_NAME = f"{STAMP}.json"

# Snapshot = these real fixtures, in this order: route 2 (5 items, in the
# mini GTFS), APP (0 items), route 55 (1 item, *not* in the mini GTFS).
SNAPSHOT_FIXTURES = (
    f"{STAMP}__bus_route_2.json",
    f"{STAMP}__APP.json",
    f"{STAMP}__bus_route_55.json",
)

# Route 2 only. Its two shapes run along 17th St through Washington Ave, one
# per direction (real shape IDs; real direction names: 0 is Southbound).
BUS_GTFS = {
    "routes.txt": (
        "route_id,route_short_name,route_long_name,route_type,route_color,"
        "route_text_color\n"
        "2,2,16th-17th,3,EF3340,FFFFFF\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
        "2,1,t1,Pier 70,0,317310\n"
        "2,1,t2,Wayne-Carpenter,1,317312\n"
    ),
    "directions.txt": (
        "route_id,direction_id,direction,direction_destination\n"
        "2,0,Southbound,Pier 70\n"
        "2,1,Northbound,Wayne-Carpenter\n"
    ),
    "shapes.txt": (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
        "317310,39.9405,-75.1716,1\n"
        "317310,39.9365,-75.1716,2\n"
        "317312,39.9365,-75.1716,1\n"
        "317312,39.9405,-75.1716,2\n"
    ),
}

# 17th & Washington: two ways sharing node 11.
STREET_ROWS = [
    (1, "South 17th Street", "secondary", [10, 11, 12],
     [[-75.1716, 39.9375], [-75.1716, 39.9385], [-75.1716, 39.9395]]),
    (2, "Washington Avenue", "secondary", [20, 11, 21],
     [[-75.1726, 39.9385], [-75.1716, 39.9385], [-75.1706, 39.9385]]),
]  # fmt: skip

EXPECTED_OUTPUT = DEFAULT_DETOURS_DIR / f"detours-{STAMP}.json"


def snapshot_bytes(read_alert_fixture, names=SNAPSHOT_FIXTURES) -> bytes:
    return b"[" + b",".join(read_alert_fixture(n) for n in names) + b"]"


@pytest.fixture
def repo(tmp_path, monkeypatch, read_alert_fixture) -> Path:
    """A fake repo root (the cwd): one snapshot, bus GTFS, street cache.

    There's no rail feed, so loading rail would crash.
    """
    monkeypatch.chdir(tmp_path)
    alerts = tmp_path / DEFAULT_ALERTS_DIR
    alerts.mkdir(parents=True)
    (alerts / SNAPSHOT_NAME).write_bytes(snapshot_bytes(read_alert_fixture))

    bus = tmp_path / "data" / "gtfs" / "bus"
    bus.mkdir(parents=True)
    for name, text in BUS_GTFS.items():
        (bus / name).write_text(text)

    ways = pl.DataFrame(STREET_ROWS, schema=STREET_WAYS_SCHEMA, orient="row")
    info = StreetCacheInfo(sources=("test.osm.pbf",), bbox=(-76.0, 39.0, -75.0, 41.0))
    write_street_cache(ways, info)
    return tmp_path


def run_main(capsys, argv: list[str]) -> tuple[int, str, str]:
    code = match_main.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def test_detours_path_uses_snapshot_stem():
    assert detours_path(Path("a/b/2026-11-25T025344Z.json")) == Path(
        "data/processed/detours-2026-11-25T025344Z.json"
    )
    assert detours_path(Path("x.json"), Path("out")) == Path("out/detours-x.json")


def test_detours_path_stays_in_root():
    assert detours_path(Path("../../etc/x.json"), Path("out")).parent == Path("out")


def test_match_latest_snapshot_writes_detours(repo, capsys):
    code, out, err = run_main(capsys, [])
    assert (code, err) == (0, "")
    assert out == (
        f"wrote {EXPECTED_OUTPUT} (6 detours: 5 matched to a route, 1 placed)\n"
    )
    detours = read_detours(EXPECTED_OUTPUT.read_bytes())
    # Snapshot order: route 2's five items, then route 55's one.
    assert [d.notice.source.route_id for d in detours] == [
        *["bus_route_2"] * 5,
        "bus_route_55",
    ]
    assert {d.notice.source.snapshot for d in detours} == {SNAPSHOT_NAME}


def test_matched_detour_contents(repo, capsys):
    run_main(capsys, [])
    first, *_, last = read_detours(EXPECTED_OUTPUT.read_bytes())
    # Route 2 #0: 17th & Washington, SB -> direction 0's shape, placed.
    assert first.match is not None
    assert (first.match.feed, first.match.route_id) == ("bus", "2")
    assert [s.shape_id for s in first.match.shapes] == ["317310"]
    assert first.match.start_point is not None
    assert first.match.start_point.node_id == 11
    assert first.issues == ()
    # Route 55 isn't in the mini GTFS.
    assert last.match is None
    assert last.issues[0].startswith("route: ")


def test_unplaced_detours_keep_their_issue(repo, capsys):
    run_main(capsys, [])
    detours = read_detours(EXPECTED_OUTPUT.read_bytes())
    # Route 2 #1: 17th & Cecil B Moore; no such ways in the mini cache.
    assert detours[1].match is not None
    assert detours[1].match.start_point is None
    assert detours[1].issues == (
        "start: no crossing of '17th' and 'Cecil B Moore' in OSM",
    )


def test_newest_snapshot_is_used(repo, capsys, read_alert_fixture):
    # An older snapshot with no detours must be ignored.
    older = repo / DEFAULT_ALERTS_DIR / "2026-11-24T000000Z.json"
    older.write_bytes(snapshot_bytes(read_alert_fixture, [f"{STAMP}__APP.json"]))
    code, out, _ = run_main(capsys, [])
    assert code == 0
    assert str(EXPECTED_OUTPUT) in out
    assert not (DEFAULT_DETOURS_DIR / "detours-2026-11-24T000000Z.json").exists()


def test_explicit_snapshot_path(repo, capsys, read_alert_fixture):
    # Any name and place; the output still goes to data/processed/.
    mine = repo / "elsewhere" / "mine.json"
    mine.parent.mkdir()
    mine.write_bytes(snapshot_bytes(read_alert_fixture, [f"{STAMP}__APP.json"]))
    code, out, _ = run_main(capsys, [str(mine)])
    output = DEFAULT_DETOURS_DIR / "detours-mine.json"
    assert code == 0
    assert out == f"wrote {output} (0 detours: 0 matched to a route, 0 placed)\n"
    assert output.read_bytes() == b"[]\n"
    assert not EXPECTED_OUTPUT.exists()


def test_rerun_replaces_output(repo, capsys):
    EXPECTED_OUTPUT.write_bytes(b"old")
    assert run_main(capsys, [])[0] == 0
    assert len(read_detours(EXPECTED_OUTPUT.read_bytes())) == 6


def test_no_snapshot_names_ingest_command(repo, capsys):
    (repo / DEFAULT_ALERTS_DIR / SNAPSHOT_NAME).unlink()
    code, out, err = run_main(capsys, [])
    assert (code, out) == (1, "")
    assert err.startswith("error: no alerts snapshot")
    assert INGEST_COMMAND in err
    assert not DEFAULT_DETOURS_DIR.joinpath(EXPECTED_OUTPUT.name).exists()


def test_missing_explicit_snapshot(repo, capsys):
    code, out, err = run_main(capsys, ["nope.json"])
    assert (code, out) == (1, "")
    assert err.startswith("error: ")
    assert "nope.json" in err


def test_bad_snapshot_fails_before_loading_reference(repo, capsys):
    # With GTFS and the street cache gone, a *reference* error would mean
    # they were loaded before the snapshot was parsed.
    shutil.rmtree(repo / "data" / "gtfs")
    (repo / DEFAULT_DETOURS_DIR / "streets.parquet").unlink()
    (repo / DEFAULT_ALERTS_DIR / SNAPSHOT_NAME).write_bytes(b"[]")
    code, out, err = run_main(capsys, [])
    assert (code, out) == (1, "")
    assert "validation error" in err
    assert not EXPECTED_OUTPUT.exists()


def test_bad_snapshot_keeps_older_output(repo, capsys):
    EXPECTED_OUTPUT.write_bytes(b"older")
    (repo / DEFAULT_ALERTS_DIR / SNAPSHOT_NAME).write_bytes(b"not json")
    assert run_main(capsys, [])[0] == 1
    assert EXPECTED_OUTPUT.read_bytes() == b"older"


def test_missing_street_cache_names_build_command(repo, capsys):
    (repo / DEFAULT_DETOURS_DIR / "streets.parquet").unlink()
    code, out, err = run_main(capsys, [])
    assert (code, out) == (1, "")
    assert BUILD_COMMAND in err
    assert not EXPECTED_OUTPUT.exists()


@pytest.mark.parametrize("table", sorted(BUS_GTFS))
def test_missing_bus_gtfs_table(repo, capsys, table):
    (repo / "data" / "gtfs" / "bus" / table).unlink()
    code, out, err = run_main(capsys, [])
    assert (code, out) == (1, "")
    assert err.startswith("error: ")
    assert not EXPECTED_OUTPUT.exists()


def test_extra_argument_is_rejected(repo, capsys):
    with pytest.raises(SystemExit) as excinfo:
        match_main.main(["a.json", "b.json"])
    assert excinfo.value.code == 2


def test_runs_as_module(repo):
    result = subprocess.run(
        [sys.executable, "-m", "septa_detours.match"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"wrote {EXPECTED_OUTPUT} (6 detours")


def test_detours_path_is_always_json():
    assert detours_path(Path("mine.txt")).name == "detours-mine.json"


def test_failure_while_writing_keeps_older_output(repo, capsys, monkeypatch):
    EXPECTED_OUTPUT.write_bytes(b"older")

    def broken_dump(detours):
        raise RuntimeError("boom")

    monkeypatch.setattr(match_main, "dump_detours", broken_dump)
    with pytest.raises(RuntimeError, match="boom"):  # a bug: keeps traceback
        match_main.main([])
    assert EXPECTED_OUTPUT.read_bytes() == b"older"


def test_runs_as_module_failure_exit_code(repo):
    result = subprocess.run(
        [sys.executable, "-m", "septa_detours.match", "nope.json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr.startswith("error: ")
