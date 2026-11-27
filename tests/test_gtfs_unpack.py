"""Tests for ``gtfs/unpack.py`` and ``python -m septa_detours.gtfs unpack``.

Release zips are built in ``tmp_path`` in SEPTA's layout (an outer
``gtfs_public.zip`` holding ``google_bus.zip`` and ``google_rail.zip``),
with real headers and CRLF endings. Bus has three tables, rail two, so a
dropped or swapped feed shows.
"""

import io
import re
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from septa_detours.gtfs import __main__ as gtfs_main
from septa_detours.gtfs.load import load_feed_info
from septa_detours.gtfs.unpack import find_latest_gtfs_zip, unpack_gtfs

FEED_INFO = (
    "feed_publisher_name,feed_publisher_url,feed_lang,"
    "feed_start_date,feed_end_date,feed_version\r\n"
    "SEPTA,https://septa.org/,en,20261122,20270220,{version}\r\n"
)
BUS = {
    "routes.txt": b"route_id,route_short_name\r\n21,21\r\nL1,L1\r\n",
    "stops.txt": b"stop_id,stop_name\r\n1,Broad St & Washington Av\r\n",
    "feed_info.txt": FEED_INFO.format(version="v202611220").encode(),
}
RAIL = {
    "trips.txt": b"route_id,trip_id,shape_id\r\nAIR,101,001005\r\n",
    "feed_info.txt": FEED_INFO.format(version="v202611150").encode(),
}
TABLES = [
    "bus/feed_info.txt",
    "bus/routes.txt",
    "bus/stops.txt",
    "rail/feed_info.txt",
    "rail/trips.txt",
]


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def write_release(
    path: Path,
    bus: dict[str, bytes] | None = BUS,
    rail: dict[str, bytes] | None = RAIL,
) -> Path:
    """A release zip at ``path``; ``None`` leaves that feed's inner zip out."""
    outer = {}
    if bus is not None:
        outer["google_bus.zip"] = zip_bytes(bus)
    if rail is not None:
        outer["google_rail.zip"] = zip_bytes(rail)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zip_bytes(outer))
    return path


def tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (relative path -> bytes)."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def release(tmp_path: Path) -> Path:
    return write_release(tmp_path / "raw" / "gtfs_public-v202611220.zip")


def test_unpacks_each_feed_into_its_directory(release: Path, tmp_path: Path) -> None:
    root = tmp_path / "data" / "gtfs"
    assert unpack_gtfs(release, root) == TABLES
    assert tree(root) == {
        **{f"bus/{name}": content for name, content in BUS.items()},
        **{f"rail/{name}": content for name, content in RAIL.items()},
    }
    assert load_feed_info(root=root)["feed_version"].to_list() == [
        "v202611220",
        "v202611150",
    ]


def test_replaces_the_old_tree_entirely(release: Path, tmp_path: Path) -> None:
    root = tmp_path / "data" / "gtfs"
    (root / "bus").mkdir(parents=True)
    (root / "bus" / "levels.txt").write_bytes(b"dropped from the new release\r\n")
    (root / "bus" / "routes.txt").write_bytes(b"old routes\r\n")
    (root / "notes.md").write_text("mine\n")
    unpack_gtfs(release, root)
    assert sorted(tree(root)) == TABLES
    assert (root / "bus" / "routes.txt").read_bytes() == BUS["routes.txt"]


def test_leaves_no_temporary_directories(release: Path, tmp_path: Path) -> None:
    root = tmp_path / "data" / "gtfs"
    unpack_gtfs(release, root)
    unpack_gtfs(release, root)
    assert sorted(p.name for p in root.parent.iterdir()) == ["gtfs"]


@pytest.mark.parametrize(
    "unsafe",
    [
        "../evil.txt",
        "../../evil.txt",
        "/tmp/evil.txt",
        "sub/evil.txt",
        ".hidden.txt",
        "notes.md",
        "routes.txt.bak",
        "evil dir/",
    ],
)
def test_only_flat_table_names_are_written(tmp_path: Path, unsafe: str) -> None:
    release = write_release(
        tmp_path / "raw" / "gtfs_public-v202611220.zip",
        bus={**BUS, unsafe: b"should never be written\r\n"},
    )
    root = tmp_path / "work" / "data" / "gtfs"
    assert unpack_gtfs(release, root) == TABLES
    everything = {
        p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()
    }
    assert everything == {
        "raw/gtfs_public-v202611220.zip",
        *(f"work/data/gtfs/{table}" for table in TABLES),
    }


@pytest.mark.parametrize(
    ("bus", "rail", "message"),
    [
        (BUS, None, "gtfs_public-v202611220.zip has no google_rail.zip"),
        (None, RAIL, "gtfs_public-v202611220.zip has no google_bus.zip"),
        (
            BUS,
            {"README.md": b"no tables\n"},
            r"gtfs_public-v202611220.zip: google_rail.zip has no \.txt tables",
        ),
    ],
)
def test_a_bad_release_leaves_the_old_tree(
    tmp_path: Path,
    bus: dict[str, bytes] | None,
    rail: dict[str, bytes] | None,
    message: str,
) -> None:
    root = tmp_path / "data" / "gtfs"
    good = write_release(tmp_path / "raw" / "good.zip")
    unpack_gtfs(good, root)
    before = tree(root)
    bad = write_release(tmp_path / "raw" / "gtfs_public-v202611220.zip", bus, rail)
    with pytest.raises(ValueError, match=message):
        unpack_gtfs(bad, root)
    assert tree(root) == before
    assert sorted(p.name for p in root.parent.iterdir()) == ["gtfs"]


@pytest.mark.parametrize(
    ("corrupt", "error"),
    [
        (lambda good: b"<html>Service unavailable</html>", zipfile.BadZipFile),
        # A cut-off zip may still open, with a partial listing.
        (lambda good: good[:1000], (zipfile.BadZipFile, ValueError)),
    ],
    ids=["not-a-zip", "truncated"],
)
def test_a_corrupt_zip_leaves_the_old_tree(
    release: Path,
    tmp_path: Path,
    corrupt: Callable[[bytes], bytes],
    error: type[Exception] | tuple[type[Exception], ...],
) -> None:
    root = tmp_path / "data" / "gtfs"
    unpack_gtfs(release, root)
    before = tree(root)
    bad = tmp_path / "raw" / "gtfs_public-v202612060.zip"
    bad.write_bytes(corrupt(release.read_bytes()))
    with pytest.raises(error):
        unpack_gtfs(bad, root)
    assert tree(root) == before
    assert sorted(p.name for p in root.parent.iterdir()) == ["gtfs"]


def test_a_failed_swap_puts_the_old_tree_back(
    release: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data" / "gtfs"
    unpack_gtfs(release, root)
    (root / "bus" / "routes.txt").write_bytes(b"current routes\r\n")
    before = tree(root)
    real_rename = Path.rename

    def staging_rename_fails(self: Path, target: Path) -> Path:
        if self.name.startswith(".gtfs-new-"):
            raise OSError("disk trouble")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", staging_rename_fails)
    with pytest.raises(OSError, match="disk trouble"):
        unpack_gtfs(release, root)
    monkeypatch.undo()
    assert tree(root) == before
    assert sorted(p.name for p in root.parent.iterdir()) == ["gtfs"]


def test_finds_the_newest_release_by_date_then_revision(tmp_path: Path) -> None:
    for name in [
        "gtfs_public-v202611010.zip",
        "gtfs_public-v202611229.zip",
        "gtfs_public-v2026112210.zip",  # revision 10 beats 9
        "gtfs_public-v202611220.zip",
        "gtfs_public-v202612060.zip.tmp",  # an interrupted download
        "gtfs_public-latest.zip",
        "gtfs.zip",
    ]:
        (tmp_path / name).write_bytes(b"")
    assert find_latest_gtfs_zip(tmp_path) == tmp_path / "gtfs_public-v2026112210.zip"


def test_a_later_date_beats_any_revision(tmp_path: Path) -> None:
    for name in ["gtfs_public-v2026110199.zip", "gtfs_public-v202611220.zip"]:
        (tmp_path / name).write_bytes(b"")
    assert find_latest_gtfs_zip(tmp_path) == tmp_path / "gtfs_public-v202611220.zip"


@pytest.mark.parametrize("make_dir", [True, False])
def test_no_release_names_the_ingest_command(tmp_path: Path, make_dir: bool) -> None:
    raw = tmp_path / "raw"
    if make_dir:
        raw.mkdir()
        (raw / "gtfs_public-v202611220.zip.tmp").write_bytes(b"")
    with pytest.raises(
        FileNotFoundError,
        match=re.escape("fetch one with: uv run python -m septa_detours.ingest gtfs"),
    ):
        find_latest_gtfs_zip(raw)


def test_main_unpacks_the_newest_saved_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_release(
        tmp_path / "data" / "raw" / "gtfs" / "gtfs_public-v202611010.zip",
        rail={"trips.txt": b"old\r\n"},
    )
    write_release(tmp_path / "data" / "raw" / "gtfs" / "gtfs_public-v202611220.zip")
    monkeypatch.chdir(tmp_path)
    assert gtfs_main.main(["unpack"]) == 0
    assert capsys.readouterr().out == (
        "unpacked data/raw/gtfs/gtfs_public-v202611220.zip into data/gtfs (5 tables)\n"
    )
    assert sorted(tree(tmp_path / "data" / "gtfs")) == TABLES


def test_main_unpacks_a_given_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_release(tmp_path / "data" / "raw" / "gtfs" / "gtfs_public-v202611220.zip")
    older = write_release(
        tmp_path / "elsewhere" / "gtfs_public-v202611010.zip",
        rail={"trips.txt": b"old\r\n"},
    )
    monkeypatch.chdir(tmp_path)
    assert gtfs_main.main(["unpack", str(older)]) == 0
    assert capsys.readouterr().out == (f"unpacked {older} into data/gtfs (4 tables)\n")
    assert (tmp_path / "data/gtfs/rail/trips.txt").read_bytes() == b"old\r\n"


@pytest.mark.parametrize(
    ("setup", "error"),
    [
        ("none", "error: no GTFS release in data/raw/gtfs; fetch one with: "),
        ("no-rail", "error: gtfs_public-v202611220.zip has no google_rail.zip\n"),
        ("corrupt", "error: File is not a zip file\n"),
    ],
)
def test_main_errors_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    setup: str,
    error: str,
) -> None:
    path = tmp_path / "data" / "raw" / "gtfs" / "gtfs_public-v202611220.zip"
    if setup == "no-rail":
        write_release(path, rail=None)
    elif setup == "corrupt":
        path.parent.mkdir(parents=True)
        path.write_bytes(b"<html>not a zip</html>")
    monkeypatch.chdir(tmp_path)
    assert gtfs_main.main(["unpack"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(error)
    assert not (tmp_path / "data" / "gtfs").exists()
