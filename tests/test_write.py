"""Tests for ``export.write``.

Every test that touches disk uses pytest's ``tmp_path`` fixture (a fresh,
empty directory per test), so nothing is written to ``web/data/``.
"""

import json
import math
from pathlib import Path

import pytest

from septa_detours.export import write
from septa_detours.export.write import (
    DEFAULT_WEB_DATA_DIR,
    SITE_FILES,
    route_geojson_path,
    write_geojson,
    write_site,
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


# --- write_site ------------------------------------------------------------------

# Small stand-ins: write_site only encodes, so any JSON value will do.
SITE = {
    "status.json": {"schema_version": 1, "snapshot": "2026-11-25T121123Z.json"},
    "routes/bus-21.json": {"key": "bus-21", "long_name": "Chestnut\u2013Walnut"},
    "routes.json": [{"key": "bus-21"}, {"key": "rail-AIR"}],
    "network.geojson": {"type": "FeatureCollection", "features": []},
    "routes/rail-AIR.json": {"key": "rail-AIR"},
    "starts.geojson": {"type": "FeatureCollection", "features": []},
}


def files_under(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_site_files_are_the_contract_ones() -> None:
    assert {
        "status.json",
        "routes.json",
        "network.geojson",
        "starts.geojson",
        "skipped.geojson",
    } == SITE_FILES


def test_write_site_writes_every_file(tmp_path: Path) -> None:
    write_site(SITE, tmp_path)
    assert files_under(tmp_path) == {
        name: (
            json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode()
        for name, value in SITE.items()
    }


def test_write_site_keeps_non_ascii_text(tmp_path: Path) -> None:
    write_site(SITE, tmp_path)
    text = (tmp_path / "routes" / "bus-21.json").read_text(encoding="utf-8")
    assert text == '{"key":"bus-21","long_name":"Chestnut\u2013Walnut"}\n'


def test_write_site_writes_routes_first_and_status_last(tmp_path: Path) -> None:
    written = write_site(SITE, tmp_path)
    assert [path.relative_to(tmp_path).as_posix() for path in written] == [
        "routes/bus-21.json",
        "routes/rail-AIR.json",
        "routes.json",
        "network.geojson",
        "starts.geojson",
        "status.json",
    ]


def test_write_site_replaces_old_files(tmp_path: Path) -> None:
    (tmp_path / "status.json").write_text("old")
    write_site({"status.json": {"schema_version": 1}}, tmp_path)
    assert (tmp_path / "status.json").read_text() == '{"schema_version":1}\n'


def test_write_site_deletes_stale_route_files_only(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    routes.mkdir()
    for name in (
        "bus-9.json",
        "rail-CHW.json",
        "notes.txt",
        "README.json",
        "bus-9.json.bak",
    ):
        (routes / name).write_text("old")
    (routes / "bus-1.json").mkdir()  # a directory with a route-file name
    write_site(SITE, tmp_path)
    assert sorted(path.name for path in routes.iterdir()) == [
        "README.json",
        "bus-1.json",
        "bus-21.json",
        "bus-9.json.bak",
        "notes.txt",
        "rail-AIR.json",
    ]


def test_write_site_without_route_files(tmp_path: Path) -> None:
    write_site({"status.json": {}, "routes.json": []}, tmp_path)
    assert sorted(files_under(tmp_path)) == ["routes.json", "status.json"]


@pytest.mark.parametrize(
    "name",
    [
        "../status.json",
        "/tmp/status.json",
        "other.json",
        "routes/../status.json",
        "routes/sub/bus-1.json",
        "routes/bus 21.json",
        "routes/tram-1.json",
        "routes/bus-21.geojson",
        "routes/",
        "routes/bus-21xjson",
        "routes/bus-21.json.bak",
        "stops/bus-21.json",
    ],
)
def test_write_site_rejects_other_paths_and_writes_nothing(
    tmp_path: Path, name: str
) -> None:
    with pytest.raises(ValueError, match="not data contract files"):
        write_site({**SITE, name: {}}, tmp_path)
    assert files_under(tmp_path) == {}


def test_write_site_nan_anywhere_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "status.json").write_text("old")
    files = {**SITE, "starts.geojson": {"x": math.nan}}
    with pytest.raises(ValueError, match="Out of range float"):
        write_site(files, tmp_path)
    assert files_under(tmp_path) == {"status.json": b"old"}


def test_write_site_failed_write_keeps_stale_files(tmp_path: Path, monkeypatch) -> None:
    routes = tmp_path / "routes"
    routes.mkdir()
    (routes / "bus-9.json").write_text("old")
    real_write = write.write_bytes_atomic

    def fail_on_network(content: bytes, path: Path) -> None:
        if path.name == "network.geojson":
            raise OSError("disk full")
        real_write(content, path)

    monkeypatch.setattr(write, "write_bytes_atomic", fail_on_network)
    with pytest.raises(OSError, match="disk full"):
        write_site(SITE, tmp_path)
    assert (routes / "bus-9.json").read_text() == "old"
    assert not (tmp_path / "status.json").exists()
