"""Tests for ``septa_detours.io``: ``write_bytes_atomic``, ``write_chunks_atomic``."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from septa_detours.io import write_bytes_atomic, write_chunks_atomic

# Not valid UTF-8 on purpose: proves bytes pass through with no decoding.
RAW = b'{"a": 1}\r\n\xff\x00 trailing'


def test_writes_exact_bytes(tmp_path):
    path = tmp_path / "out.json"
    write_bytes_atomic(RAW, path)
    assert path.read_bytes() == RAW
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_empty_content_writes_empty_file(tmp_path):
    path = tmp_path / "out.json"
    write_bytes_atomic(b"", path)
    assert path.read_bytes() == b""


def test_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "data" / "raw" / "alerts" / "out.json"
    write_bytes_atomic(RAW, path)
    assert path.read_bytes() == RAW


def test_replaces_existing_file(tmp_path):
    path = tmp_path / "out.json"
    write_bytes_atomic(b"old, and longer than the new content", path)
    write_bytes_atomic(b"new", path)
    assert path.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_failed_replace_removes_temp_file(tmp_path):
    """Target is a directory, so ``replace`` fails after the temp file exists."""
    path = tmp_path / "out.json"
    path.mkdir()
    with pytest.raises(OSError):  # noqa: PT011 - the exact subclass is OS-specific
        write_bytes_atomic(RAW, path)
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]
    assert path.is_dir()


@pytest.mark.parametrize(
    "error", [OSError("simulated disk full"), KeyboardInterrupt()], ids=["os", "ctrl-c"]
)
def test_interrupted_write_leaves_existing_file_unchanged(tmp_path, monkeypatch, error):
    """Half a write then a failure (incl. Ctrl+C): old file intact, no temp left."""
    path = tmp_path / "out.json"
    write_bytes_atomic(b"old complete file", path)

    real_write_bytes = Path.write_bytes

    def write_half_then_fail(self: Path, data: bytes) -> int:
        real_write_bytes(self, data[: len(data) // 2])
        raise error

    monkeypatch.setattr(Path, "write_bytes", write_half_then_fail)
    with pytest.raises(type(error)):
        write_bytes_atomic(b"new content that never fully lands", path)

    assert path.read_bytes() == b"old complete file"
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


# --- write_chunks_atomic ---------------------------------------------------

# RAW split unevenly, with an empty chunk in the middle (httpx can yield one).
CHUNKS = [RAW[:3], b"", RAW[3:10], RAW[10:]]


def test_chunks_writes_exact_bytes_in_order(tmp_path):
    path = tmp_path / "out.pbf"
    write_chunks_atomic(iter(CHUNKS), path)
    assert path.read_bytes() == RAW
    assert [p.name for p in tmp_path.iterdir()] == ["out.pbf"]


def test_chunks_no_chunks_writes_empty_file(tmp_path):
    path = tmp_path / "out.pbf"
    write_chunks_atomic(iter([]), path)
    assert path.read_bytes() == b""


def test_chunks_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "data" / "raw" / "osm" / "out.pbf"
    write_chunks_atomic(iter(CHUNKS), path)
    assert path.read_bytes() == RAW


def test_chunks_replaces_existing_file(tmp_path):
    path = tmp_path / "out.pbf"
    path.write_bytes(b"old, and longer than the new content")
    write_chunks_atomic(iter([b"ne", b"w"]), path)
    assert path.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["out.pbf"]


def test_chunks_streams_to_disk_before_iterator_ends(tmp_path):
    """The first chunk is on disk before the second is asked for: no joining in memory.

    The chunk is 1 MiB, far bigger than Python's write buffer, so a
    streaming write hits the disk at once; buffering can't hide it.
    """
    path = tmp_path / "out.pbf"
    tmp = tmp_path / "out.pbf.tmp"
    first = b"x" * 2**20
    sizes_on_disk: list[int] = []

    def chunks() -> Iterator[bytes]:
        yield first
        sizes_on_disk.append(tmp.stat().st_size if tmp.exists() else -1)
        yield b"second"

    write_chunks_atomic(chunks(), path)
    assert sizes_on_disk == [len(first)]
    assert path.read_bytes() == first + b"second"


def test_chunks_overwrites_stale_temp_file(tmp_path):
    """A ``.tmp`` left by a killed run (``kill -9``) is overwritten, not extended."""
    path = tmp_path / "out.pbf"
    (tmp_path / "out.pbf.tmp").write_bytes(b"half of an old download")
    write_chunks_atomic(iter(CHUNKS), path)
    assert path.read_bytes() == RAW
    assert [p.name for p in tmp_path.iterdir()] == ["out.pbf"]


def test_chunks_replace_waits_for_iterator_end(tmp_path):
    """Old file still in place while the last chunk is yielded."""
    path = tmp_path / "out.pbf"
    path.write_bytes(b"old")
    seen: list[bytes] = []

    def chunks() -> Iterator[bytes]:
        yield b"new"
        seen.append(path.read_bytes())

    write_chunks_atomic(chunks(), path)
    assert seen == [b"old"]
    assert path.read_bytes() == b"new"


@pytest.mark.parametrize(
    "error",
    [
        OSError("connection dropped"),
        ValueError("checksum mismatch"),
        KeyboardInterrupt(),
    ],
    ids=["os", "value", "ctrl-c"],
)
def test_chunks_iterator_failure_leaves_existing_file_unchanged(tmp_path, error):
    """A failure after some chunks, or after the last one: old file intact, no temp."""
    path = tmp_path / "out.pbf"
    path.write_bytes(b"old complete file")

    def chunks() -> Iterator[bytes]:
        yield b"new content that"
        yield b" never fully lands"
        raise error

    with pytest.raises(type(error)):
        write_chunks_atomic(chunks(), path)

    assert path.read_bytes() == b"old complete file"
    assert [p.name for p in tmp_path.iterdir()] == ["out.pbf"]


def test_chunks_failed_replace_removes_temp_file(tmp_path):
    """Target is a directory, so ``replace`` fails after the temp file exists."""
    path = tmp_path / "out.pbf"
    path.mkdir()
    with pytest.raises(OSError):  # noqa: PT011 - the exact subclass is OS-specific
        write_chunks_atomic(iter(CHUNKS), path)
    assert [p.name for p in tmp_path.iterdir()] == ["out.pbf"]
    assert path.is_dir()
