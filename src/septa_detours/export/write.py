"""Write GeoJSON to disk for the web map.

Writes the data contract; the only other file I/O in ``export/`` is
``deploy.py``, which copies ``web/`` as it's published. Everything that
decides *what* goes in the file lives in ``geojson.py`` (pure, tested
without touching disk); this module only decides *where* and *how* it is
written. Uses stdlib
``json``; no extra dependency needed.

Output format decisions (see ``write_geojson``):
    - UTF-8, compact separators, trailing newline.
    - ``allow_nan=False``: NaN/Infinity are not valid JSON.
    - Atomic replace: readers see the old file or the new one, never half.

``web/data/`` is gitignored: it is pipeline output, rebuilt on demand.
"""

import json
import re
from collections.abc import Mapping
from pathlib import Path

from septa_detours.export.geojson import FeatureCollection
from septa_detours.gtfs.load import Feed
from septa_detours.io import write_bytes_atomic

# The path assumes you run from the repo root
DEFAULT_WEB_DATA_DIR = Path("web/data")

# Characters allowed in a route_id that becomes part of a filename. Every
# SEPTA route_id matches today ("21", "L1", "AIR", ...), so this is a guard
# against future data, not a filter for current data.
_SAFE_ROUTE_ID = re.compile(r"[A-Za-z0-9_-]+")

SITE_FILES = frozenset(
    {
        "status.json",
        "routes.json",
        "network.geojson",
        "starts.geojson",
        "skipped.geojson",
        "paths.geojson",
    }
)
"""The contract's fixed files (``export/contract.py``); route details go in
``routes/<key>.json``."""

_ROUTE_FILE = re.compile(r"(?:bus|rail)-[A-Za-z0-9_-]+\.json")
"""A route detail file's name: ``<feed>-<route_id>.json``."""


def route_geojson_path(
    feed: Feed, route_id: str, root: Path = DEFAULT_WEB_DATA_DIR
) -> Path:
    """Return where a route's GeoJSON file goes, e.g. ``web/data/bus-21.geojson``.

    Decisions:
        - **Feed in the name.** ``route_id`` is only unique within a feed,
          so ``21.geojson`` could mean two different routes.
        - **Extension ``.geojson``, not ``.json``.** It says what the file
          is, and Python's ``http.server`` serves it as
          ``application/geo+json`` (the registered GeoJSON type). MapLibre
          parses either, so this costs nothing.
        - **Reject unsafe IDs instead of cleaning them.** ``route_id`` is
          data, not code. A value like ``"../x"`` would write outside
          ``root``, and ``"a/b"`` would create a subdirectory. Replacing bad
          characters (``"a/b"`` -> ``"a_b"``) would quietly let two
          different routes share one file, so it raises instead: the
          project rule is to refuse rather than guess.
        - **Pure.** Only builds a path; nothing is created or checked on
          disk. ``write_geojson`` creates the directory.

    Args:
        feed: The route's feed.
        route_id: The GTFS ``route_id`` (not ``route_short_name``).
        root: Output directory. Defaults to ``web/data``, relative to the
            current working directory (the repo root).

    Raises:
        ValueError: If ``route_id`` is empty or has characters outside
            letters, digits, ``_`` and ``-``.
    """
    if not _SAFE_ROUTE_ID.fullmatch(route_id):
        raise ValueError(f"route_id {route_id!r} is not safe to use in a filename.")
    return root / f"{feed}-{route_id}.geojson"


def write_geojson(collection: FeatureCollection, path: Path) -> None:
    """Write ``collection`` to ``path`` as UTF-8 JSON, replacing any old file.

    Steps, and why each one is there:

    1. **Serialize first, in memory** (``json.dumps``, not ``json.dump`` to
       an open file). If serialization fails (e.g. a NaN), nothing has been
       written yet, so a bad export can't leave a broken file behind. The
       cost is holding the whole string in memory; route files are tens
       of KB, so that is fine. Revisit if one file ever holds every shape.
    2. **``allow_nan=False``.** By default ``json`` writes ``NaN`` and
       ``Infinity``, which are not valid JSON; browsers' ``JSON.parse``
       rejects them and the map would fail to load. Better to fail here,
       loudly, with a Python traceback.
    3. **``ensure_ascii=False`` + explicit ``.encode("utf-8")``.** JSON
       exchanged between systems must be UTF-8 (RFC 8259). Without
       ``ensure_ascii=False``, non-ASCII text in route names (an en dash,
       say) would be written as backslash-u escapes: valid, but harder to
       read. Encoding explicitly avoids ``open``'s default, which depends
       on the OS locale.
    4. **Compact separators** (``","`` and ``":"``, no indent). The file is
       for the browser, not for people, and is gitignored, so readability
       loses to size. To inspect one: ``python -m json.tool <file>``.
    5. **Trailing newline.** Text-file convention; keeps ``cat`` and
       ``wc -l`` tidy.
    6. **Atomic replace via ``septa_detours.io.write_bytes_atomic``**,
       which also creates the parent directory. A browser reloading the
       map (or a crash mid-write) sees either the old complete file or the
       new complete one, never a truncated one.

    Args:
        collection: Output of ``geojson.route_feature_collection``.
        path: Destination, usually from ``route_geojson_path``.

    Raises:
        ValueError: If ``collection`` contains NaN or Infinity.
        TypeError: If ``collection`` contains a value ``json`` can't
            serialize (e.g. a stray polars object).
        OSError: If the directory or file can't be written.
    """
    write_bytes_atomic(_encode_json(collection), path)


def write_site(
    files: Mapping[str, object], root: Path = DEFAULT_WEB_DATA_DIR
) -> list[Path]:
    """Write the data contract's files under ``root``, replacing old ones.

    Steps:

    1. Check every path: only ``SITE_FILES`` and ``routes/<key>.json``
       (so nothing can land outside ``root``). Nothing is written if any
       is wrong.
    2. Encode every file in memory (as ``write_geojson`` does), so a NaN
       anywhere fails before any file changes.
    3. Write each atomically: route files, then the rest, ``status.json``
       last (the page reads it first, so it should describe a finished
       export). A failure part-way leaves some files new and some old:
       accepted (plain overwrite, decided), and the next export fixes it.
    4. Delete stale route files: ``routes/*.json`` with a route-file name
       that wasn't written now (a route gone from GTFS). Other files are
       left alone.

    Args:
        files: Relative path (``"routes/bus-21.json"``) -> JSON value.
        root: The page's data directory.

    Returns:
        The paths written, in writing order.

    Raises:
        ValueError: A path isn't part of the contract, or a value has NaN
            or Infinity.
        TypeError: A value ``json`` can't serialize.
        OSError: A file can't be written or deleted.
    """
    bad = sorted(name for name in files if not _is_site_file(name))
    if bad:
        raise ValueError(f"not data contract files: {bad}")
    encoded = {name: _encode_json(value) for name, value in files.items()}
    order = sorted(
        encoded, key=lambda name: (name == "status.json", name in SITE_FILES)
    )
    written = []
    for name in order:
        path = root / name
        write_bytes_atomic(encoded[name], path)
        written.append(path)
    routes_dir = root / "routes"
    if routes_dir.is_dir():
        for path in routes_dir.iterdir():
            stale = f"routes/{path.name}" not in encoded
            if stale and path.is_file() and _ROUTE_FILE.fullmatch(path.name):
                path.unlink()
    return written


def _is_site_file(name: str) -> bool:
    """Whether ``name`` is a contract file's path relative to the data dir."""
    if name in SITE_FILES:
        return True
    folder, _, file_name = name.partition("/")
    return folder == "routes" and _ROUTE_FILE.fullmatch(file_name) is not None


def _encode_json(value: object) -> bytes:
    """Compact UTF-8 JSON plus a newline (see ``write_geojson``'s steps 1-5)."""
    text = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")
