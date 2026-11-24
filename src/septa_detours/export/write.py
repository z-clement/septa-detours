"""Write GeoJSON to disk for the web map.

The only file I/O in ``export/``. Everything that decides *what* goes in
the file lives in ``geojson.py`` (pure, tested without touching disk);
this module only decides *where* and *how* it is written. Uses stdlib
``json``; no extra dependency needed.

Output format decisions (see ``write_geojson``):
    - UTF-8, compact separators, trailing newline.
    - ``allow_nan=False``: NaN/Infinity are not valid JSON.
    - Atomic replace: readers see the old file or the new one, never half.

``web/data/`` is gitignored: it is pipeline output, rebuilt on demand.
"""

import json
import re
from pathlib import Path

from septa_detours.export.geojson import FeatureCollection
from septa_detours.gtfs.load import Feed

# The path assumes you run from the repo root
DEFAULT_WEB_DATA_DIR = Path("web/data")

# Characters allowed in a route_id that becomes part of a filename. Every
# SEPTA route_id matches today ("21", "L1", "AIR", ...), so this is a guard
# against future data, not a filter for current data.
_SAFE_ROUTE_ID = re.compile(r"[A-Za-z0-9_-]+")


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
    3. **``ensure_ascii=False`` + explicit ``encoding="utf-8"``.** JSON
       exchanged between systems must be UTF-8 (RFC 8259). Without
       ``ensure_ascii=False``, non-ASCII text in route names (an en dash,
       say) would be written as backslash-u escapes: valid, but harder to
       read. The explicit
       encoding matters because ``open``'s default depends on the OS
       locale.
    4. **Compact separators** (``","`` and ``":"``, no indent). The file is
       for the browser, not for people, and is gitignored, so readability
       loses to size. To inspect one: ``python -m json.tool <file>``.
    5. **Trailing newline.** Text-file convention; keeps ``cat`` and
       ``wc -l`` tidy.
    6. **Create the parent directory** (``parents=True, exist_ok=True``),
       so a fresh clone doesn't fail on a missing ``web/data/``.
    7. **Atomic replace.** Write to ``<name>.tmp`` beside the target, then
       ``Path.replace`` it over the target. A rename within one directory
       is atomic, so a browser reloading the map (or a crash mid-write)
       sees either the old complete file or the new complete one, never a
       truncated one. The temp file must be in the *same* directory: a
       rename across filesystems isn't atomic (``/tmp`` may be a
       different filesystem). On failure the temp file is removed.

    Args:
        collection: Output of ``geojson.route_feature_collection``.
        path: Destination, usually from ``route_geojson_path``.

    Raises:
        ValueError: If ``collection`` contains NaN or Infinity.
        TypeError: If ``collection`` contains a value ``json`` can't
            serialize (e.g. a stray polars object).
        OSError: If the directory or file can't be written.
    """
    text = json.dumps(
        collection, allow_nan=False, ensure_ascii=False, separators=(",", ":")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(text + "\n", encoding="utf-8")
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
