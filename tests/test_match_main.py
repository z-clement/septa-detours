"""Tests for ``python -m septa_detours.match`` (parse + match one snapshot)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from septa_detours.match import __main__ as match_main
from septa_detours.match.__main__ import (
    DEFAULT_ALERTS_DIR,
    INGEST_COMMAND,
    find_latest_snapshot,
)

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
