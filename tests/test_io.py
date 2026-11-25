"""Tests for ``septa_detours.io.write_bytes_atomic``."""

from pathlib import Path

import pytest

from septa_detours.io import write_bytes_atomic

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
