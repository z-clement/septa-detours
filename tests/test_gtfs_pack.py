"""Tests for ``gtfs.pack.pack_gtfs`` and ``python -m septa_detours.gtfs pack``.

Fake feeds under ``tmp_path``: bus has three tables, rail two (unequal so
a dropped or swapped feed shows), plus things that must stay out: a
stray download and a subdirectory with its own ``.txt``. ``feed_info``
rows are the real header and CRLF endings.
"""

import os
import zipfile
from pathlib import Path

import pytest

from septa_detours.gtfs import __main__ as gtfs_main
from septa_detours.gtfs.load import load_feed_info
from septa_detours.gtfs.pack import DEFAULT_GTFS_ZIP, pack_gtfs

FEED_INFO = (
    "feed_publisher_name,feed_publisher_url,feed_lang,"
    "feed_start_date,feed_end_date,feed_version\r\n"
    "SEPTA,https://septa.org/,en,20261122,20270220,{version}\r\n"
)
TABLES = {
    "bus/routes.txt": "route_id,route_short_name\r\n21,21\r\nL1,L1\r\n",
    "bus/stops.txt": "stop_id,stop_name\r\n1,Broad St & Washington Av\r\n",
    "bus/feed_info.txt": FEED_INFO.format(version="v202611220"),
    "rail/trips.txt": "route_id,trip_id,shape_id\r\nAIR,101,001005\r\n",
    "rail/feed_info.txt": FEED_INFO.format(version="v202611150"),
}
MEMBERS = [
    "bus/feed_info.txt",
    "bus/routes.txt",
    "bus/stops.txt",
    "rail/feed_info.txt",
    "rail/trips.txt",
]


@pytest.fixture
def gtfs_root(tmp_path: Path) -> Path:
    root = tmp_path / "gtfs"
    for name, text in TABLES.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(text.encode("utf-8"))
    (root / "bus" / "google_bus.zip").write_bytes(b"PK not packed")
    (root / "rail" / "old").mkdir()
    (root / "rail" / "old" / "routes.txt").write_text("not packed\n")
    return root


def test_packs_each_feeds_txt_tables_sorted(gtfs_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "gtfs.zip"
    assert pack_gtfs(out, gtfs_root) == MEMBERS
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist() == MEMBERS


def test_unzips_back_to_the_layout_load_reads(gtfs_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "gtfs.zip"
    pack_gtfs(out, gtfs_root)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(out) as archive:
        archive.extractall(unpacked)
    for name, text in TABLES.items():
        assert (unpacked / name).read_bytes() == text.encode("utf-8")  # CRLF kept
    assert load_feed_info(root=unpacked)["feed_version"].to_list() == [
        "v202611220",
        "v202611150",
    ]


def test_members_are_deflated_files_with_fixed_time_and_mode(
    gtfs_root: Path, tmp_path: Path
) -> None:
    out = tmp_path / "gtfs.zip"
    pack_gtfs(out, gtfs_root)
    with zipfile.ZipFile(out) as archive:
        for info in archive.infolist():
            assert info.compress_type == zipfile.ZIP_DEFLATED
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.external_attr >> 16 == 0o100644


def test_same_tables_give_the_same_bytes_whatever_their_mtimes(
    gtfs_root: Path, tmp_path: Path
) -> None:
    first, second, changed = (tmp_path / f"{n}.zip" for n in ("a", "b", "c"))
    pack_gtfs(first, gtfs_root)
    os.utime(gtfs_root / "bus" / "routes.txt", (1_800_000_000, 1_800_000_000))
    pack_gtfs(second, gtfs_root)
    assert second.read_bytes() == first.read_bytes()

    (gtfs_root / "bus" / "routes.txt").write_text("route_id\r\n21\r\n")
    pack_gtfs(changed, gtfs_root)
    assert changed.read_bytes() != first.read_bytes()


def test_overwrites_an_older_zip(gtfs_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "gtfs.zip"
    out.write_bytes(b"old")
    pack_gtfs(out, gtfs_root)
    assert zipfile.is_zipfile(out)
    assert not out.with_name("gtfs.zip.tmp").exists()


@pytest.mark.parametrize("feed", ["bus", "rail"])
def test_missing_feed_is_refused_and_nothing_written(
    gtfs_root: Path, tmp_path: Path, feed: str
) -> None:
    out = tmp_path / "gtfs.zip"
    out.write_bytes(b"old")
    for path in sorted((gtfs_root / feed).rglob("*"), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    (gtfs_root / feed).rmdir()
    with pytest.raises(FileNotFoundError, match=f"no {feed} feed at "):
        pack_gtfs(out, gtfs_root)
    assert out.read_bytes() == b"old"


def test_feed_without_txt_tables_is_refused(gtfs_root: Path, tmp_path: Path) -> None:
    # Only the stray zip is left: the bus feed looks present but isn't.
    for name in MEMBERS[:3]:
        (gtfs_root / name).unlink()
    out = tmp_path / "gtfs.zip"
    with pytest.raises(FileNotFoundError, match=r"no \.txt tables in "):
        pack_gtfs(out, gtfs_root)
    assert not out.exists()


def test_main_packs_to_the_default_path(
    gtfs_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # main reads data/gtfs relative to the repo root.
    (tmp_path / "data").mkdir()
    gtfs_root.rename(tmp_path / "data" / "gtfs")
    monkeypatch.chdir(tmp_path)
    assert gtfs_main.main(["pack"]) == 0
    with zipfile.ZipFile(DEFAULT_GTFS_ZIP) as archive:
        assert archive.namelist() == MEMBERS
    assert capsys.readouterr().out == (f"wrote {DEFAULT_GTFS_ZIP} (5 files, 0.0 MB)\n")


def test_main_packs_to_a_given_path(
    gtfs_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "data").mkdir()
    gtfs_root.rename(tmp_path / "data" / "gtfs")
    monkeypatch.chdir(tmp_path)
    assert gtfs_main.main(["pack", "upload/gtfs.zip"]) == 0
    assert zipfile.is_zipfile(tmp_path / "upload" / "gtfs.zip")
    assert not (tmp_path / DEFAULT_GTFS_ZIP).exists()
    assert capsys.readouterr().out == "wrote upload/gtfs.zip (5 files, 0.0 MB)\n"


def test_main_reports_a_missing_feed_and_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert gtfs_main.main(["pack"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: no bus feed at data/gtfs/bus\n"
    assert not (tmp_path / DEFAULT_GTFS_ZIP).exists()
