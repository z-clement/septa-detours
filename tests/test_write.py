"""Tests for ``export.write``.

Every test that touches disk uses pytest's ``tmp_path`` fixture (a fresh,
empty directory per test), so nothing is written to ``web/data/``.
"""

import json
import math
from pathlib import Path

import pytest

from septa_detours.export.write import (
    DEFAULT_WEB_DATA_DIR,
    route_geojson_path,
    write_geojson,
)

# Hand-built rather than made with ``geojson.py``, so these tests only
# depend on ``write.py``. Realistic Philly [lon, lat] coordinates.
ROUTE_21 = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-75.25878, 39.961991], [-75.1652, 39.9526]],
            },
            "properties": {
                "feed": "bus",
                "route_id": "21",
                "route_color": "#EF3340",
                "shape_id": "317337",
                "direction_id": 0,
            },
        }
    ],
}

EMPTY = {"type": "FeatureCollection", "features": []}


def with_first_coordinate(collection: dict, value: object) -> dict:
    """Return a deep copy of ``collection`` with its first lon set to ``value``."""
    copied = json.loads(json.dumps(collection))
    copied["features"][0]["geometry"]["coordinates"][0][0] = value
    return copied


def read_json(path: Path) -> object:
    """Read ``path`` back as UTF-8 JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


# --- route_geojson_path -------------------------------------------------------


@pytest.mark.parametrize(
    ("feed", "route_id", "filename"),
    [
        ("bus", "21", "bus-21.geojson"),
        ("bus", "L1", "bus-L1.geojson"),
        ("rail", "AIR", "rail-AIR.geojson"),
        ("bus", "a_b-1", "bus-a_b-1.geojson"),
    ],
)
def test_path_is_feed_dash_route_id(tmp_path, feed, route_id, filename):
    """Filename is ``<feed>-<route_id>.geojson`` directly under ``root``."""
    assert route_geojson_path(feed, route_id, tmp_path) == tmp_path / filename


def test_path_same_route_id_differs_by_feed(tmp_path):
    """A ``route_id`` in both feeds gets two different files."""
    bus = route_geojson_path("bus", "21", tmp_path)
    rail = route_geojson_path("rail", "21", tmp_path)
    assert bus != rail


def test_path_defaults_to_web_data():
    """Without ``root``, the file goes under ``web/data``."""
    assert route_geojson_path("bus", "21") == Path("web/data/bus-21.geojson")
    assert Path("web/data") == DEFAULT_WEB_DATA_DIR


@pytest.mark.parametrize(
    "route_id",
    ["../x", "a/b", "..", "", "21 ", " 21", "21\n", "a\\b", "21.geojson"],
)
def test_path_rejects_unsafe_route_id(tmp_path, route_id):
    """Anything outside letters, digits, ``_`` and ``-`` raises.

    ``"21\\n"`` checks that the whole string is matched: a regex ``$``
    also matches just before a trailing newline.
    """
    with pytest.raises(ValueError, match="not safe"):
        route_geojson_path("bus", route_id, tmp_path)


def test_path_does_not_touch_disk(tmp_path):
    """Building a path creates nothing; ``write_geojson`` does that."""
    root = tmp_path / "not" / "yet"
    route_geojson_path("bus", "21", root)
    assert not root.exists()


# --- write_geojson ------------------------------------------------------------


def test_write_round_trips(tmp_path):
    """Reading the file back gives the same collection."""
    path = tmp_path / "bus-21.geojson"
    write_geojson(ROUTE_21, path)
    assert read_json(path) == ROUTE_21


def test_write_empty_collection(tmp_path):
    """An empty FeatureCollection is still written as valid GeoJSON."""
    path = tmp_path / "bus-21.geojson"
    write_geojson(EMPTY, path)
    assert read_json(path) == EMPTY


def test_write_creates_missing_parent_directories(tmp_path):
    """A fresh clone has no ``web/data/``; writing creates it."""
    path = tmp_path / "web" / "data" / "bus-21.geojson"
    write_geojson(ROUTE_21, path)
    assert read_json(path) == ROUTE_21


def test_write_overwrites_with_shorter_content(tmp_path):
    """A smaller new file fully replaces a larger old one (no stale tail)."""
    path = tmp_path / "bus-21.geojson"
    write_geojson(ROUTE_21, path)
    write_geojson(EMPTY, path)
    assert read_json(path) == EMPTY


def test_write_leaves_no_temp_file(tmp_path):
    """After a successful write, only the target file is in the directory."""
    path = tmp_path / "bus-21.geojson"
    write_geojson(ROUTE_21, path)
    assert [p.name for p in tmp_path.iterdir()] == ["bus-21.geojson"]


def test_write_is_compact_with_one_trailing_newline(tmp_path):
    """No indentation or spaces; the file ends with exactly one newline."""
    path = tmp_path / "bus-21.geojson"
    write_geojson(ROUTE_21, path)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert text.count("\n") == 1
    assert '{"type":"FeatureCollection","features":[' in text


def test_write_keeps_non_ascii_as_utf8(tmp_path):
    """Non-ASCII text is stored as real UTF-8, not as backslash-u escapes."""
    name = "Broad\u2013Erie"  # en dash, written as an escape so it's visible
    collection = json.loads(json.dumps(ROUTE_21))
    collection["features"][0]["properties"]["route_long_name"] = name
    path = tmp_path / "bus-21.geojson"
    write_geojson(collection, path)
    raw = path.read_bytes()
    assert name.encode("utf-8") in raw
    assert b"\\u2013" not in raw
    assert read_json(path) == collection


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_write_rejects_nan_and_infinity(tmp_path, bad):
    """Non-JSON floats raise, and no file (or temp file) is created."""
    path = tmp_path / "bus-21.geojson"
    with pytest.raises(ValueError, match="JSON compliant"):
        write_geojson(with_first_coordinate(ROUTE_21, bad), path)
    assert list(tmp_path.iterdir()) == []


def test_write_rejects_unserializable_values(tmp_path):
    """A stray non-JSON object raises ``TypeError`` before anything is written."""
    path = tmp_path / "bus-21.geojson"
    collection = json.loads(json.dumps(ROUTE_21))
    collection["features"][0]["properties"]["oops"] = object()
    with pytest.raises(TypeError):
        write_geojson(collection, path)
    assert list(tmp_path.iterdir()) == []


def test_failed_write_leaves_existing_file_unchanged(tmp_path):
    """A bad export never damages the last good file."""
    path = tmp_path / "bus-21.geojson"
    write_geojson(ROUTE_21, path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="JSON compliant"):
        write_geojson(with_first_coordinate(ROUTE_21, math.nan), path)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["bus-21.geojson"]


def test_failed_replace_removes_temp_file(tmp_path):
    """If the final rename fails, the temp file is cleaned up.

    Making the target an existing directory forces ``Path.replace`` to
    fail *after* the temp file has been written, which exercises the
    cleanup branch (serialization errors fail before the temp file exists).
    """
    path = tmp_path / "bus-21.geojson"
    path.mkdir()
    with pytest.raises(OSError):  # noqa: PT011 - the exact subclass is OS-specific
        write_geojson(ROUTE_21, path)
    assert [p.name for p in tmp_path.iterdir()] == ["bus-21.geojson"]
    assert path.is_dir()


def test_interrupted_write_leaves_existing_file_unchanged(tmp_path, monkeypatch):
    """A write that dies halfway (disk full, crash) can't truncate the old file.

    ``Path.write_bytes`` is replaced with a version that writes half the
    data and then raises, simulating a failure mid-write. Writing straight
    to the target would leave it truncated; writing to a temp file and
    renaming leaves it intact. This is the test that proves atomicity: the
    others pass either way. (``io.py`` has its own copy of this test; this
    one proves ``write_geojson`` actually goes through the atomic path.)
    """
    path = tmp_path / "bus-21.geojson"
    write_geojson(ROUTE_21, path)
    before = path.read_bytes()

    real_write_bytes = Path.write_bytes

    def write_half_then_fail(self: Path, data: bytes) -> int:
        real_write_bytes(self, data[: len(data) // 2])
        raise OSError("simulated disk full")

    monkeypatch.setattr(Path, "write_bytes", write_half_then_fail)
    with pytest.raises(OSError, match="simulated disk full"):
        write_geojson(EMPTY, path)

    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["bus-21.geojson"]
