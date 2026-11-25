"""Export GeoJSON for the web map: one route's shapes, or the detours.

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.export route bus 21
    uv run python -m septa_detours.export detours [detours.json]

``route`` writes ``web/data/<feed>-<route_id>.geojson``. ``detours`` reads
a ``match`` output (default: the newest ``data/processed/detours-*.json``)
and writes ``web/data/detours.geojson``. Glue only: every decision about
*what* goes in a file lives in ``gtfs/``, ``export/geojson.py`` and
``export/detours.py``, and *how* it is written lives in ``export/write.py``.

Output: one ``wrote <path>...`` line on stdout.

Exit codes:
    0: file written.
    1: nothing written: a missing file (GTFS, detours), or data that can't
       be exported (unknown route, no shapes, invalid detours, detours that
       disagree with GTFS). ``error: ...`` on stderr.
    2: bad command-line arguments (argparse's own convention).
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from septa_detours.export.detours import detours_feature_collection
from septa_detours.export.geojson import (
    FeatureCollection,
    join_route_lines,
    route_feature_collection,
    route_properties,
)
from septa_detours.export.write import (
    DEFAULT_WEB_DATA_DIR,
    route_geojson_path,
    write_geojson,
)
from septa_detours.gtfs.load import (
    ALL_FEEDS,
    Feed,
    load_routes,
    load_shapes,
    load_trips,
)
from septa_detours.gtfs.routes import route_shape_ids
from septa_detours.gtfs.shapes import shape_coordinates
from septa_detours.model import read_detours

# Duplicated from ``match/__main__.py`` on purpose: one stage never imports
# another's internals. Both describe the files ``match`` writes.
DEFAULT_DETOURS_DIR = Path("data/processed")
MATCH_COMMAND = "uv run python -m septa_detours.match"

# ``match``'s output name for a stamped snapshot: ``detours-<stamp>.json``.
_DETOURS_NAME = re.compile(r"detours-\d{4}-\d{2}-\d{2}T\d{6}Z\.json")

DETOURS_GEOJSON = DEFAULT_WEB_DATA_DIR / "detours.geojson"


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: a required ``route`` or ``detours`` command.

    ``route``'s ``feed`` is limited to ``ALL_FEEDS`` via ``choices``, so a
    typo is rejected by argparse (exit 2, usage message) before any GTFS
    loads.
    """
    parser = argparse.ArgumentParser(
        prog="python -m septa_detours.export",
        description="Write GeoJSON for the web map to web/data/.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    route = commands.add_parser("route", help="Write one route's shapes.")
    route.add_argument("feed", choices=ALL_FEEDS, help="GTFS feed to read.")
    route.add_argument(
        "route_id",
        help="GTFS route_id (e.g. 21, L1); not always the public route name.",
    )

    detours = commands.add_parser(
        "detours", help="Write detoured route lines and start points."
    )
    detours.add_argument(
        "detours_file",
        nargs="?",
        type=Path,
        help="match output to read (default: the newest in data/processed/).",
    )
    return parser


def export_route(feed: Feed, route_id: str) -> Path:
    """Load GTFS for ``feed`` and write one route's GeoJSON file.

    Loads only ``feed``'s tables. Checks run cheapest-first, so bad input
    fails before the expensive loads. Refuses to write an empty
    FeatureCollection: a blank map gives no hint that something is wrong.

    Args:
        feed: Which GTFS feed the route lives in.
        route_id: The route's GTFS ``route_id`` (e.g. ``"21"``).

    Returns:
        The path the GeoJSON was written to.

    Raises:
        ValueError: Unknown route (from ``route_properties``), a known
            route with no shapes, or broken data caught downstream
            (missing coordinates, bad ``route_id`` for a filename).
    """
    # Pure and instant: rejects an unsafe route_id before touching disk.
    path = route_geojson_path(feed, route_id)

    # routes.txt is tiny; an unknown route_id fails here, before trips/shapes.
    route_props = route_properties(load_routes([feed]), feed, route_id)

    route_shapes = route_shape_ids(load_trips([feed]), feed, route_id)
    if route_shapes.is_empty():
        msg = f"route {route_id!r} in feed {feed!r} has no shapes; nothing to map"
        raise ValueError(msg)

    # shapes.txt is the big one, so it loads last.
    lines = join_route_lines(route_shapes, shape_coordinates(load_shapes([feed])))
    collection = route_feature_collection(lines, route_props)

    write_geojson(collection, path)
    return path


def find_latest_detours(root: Path = DEFAULT_DETOURS_DIR) -> Path:
    """Return the newest ``detours-<stamp>.json`` in ``root``, by its stamp.

    Names are matched exactly, so leftovers (``*.tmp``), the street cache,
    and outputs of hand-named snapshots (``detours-mine.json``) are
    ignored; pass those explicitly. Only lists ``root``.

    Raises:
        FileNotFoundError: If ``root`` doesn't exist or holds no detours
            file; the message names the match command.
    """
    candidates = (
        [path for path in root.iterdir() if _DETOURS_NAME.fullmatch(path.name)]
        if root.is_dir()
        else []
    )
    if not candidates:
        msg = f"no detours file in {root}; make one with: {MATCH_COMMAND}"
        raise FileNotFoundError(msg)
    return max(candidates, key=lambda path: path.name)


def export_detours(detours_file: Path, path: Path = DETOURS_GEOJSON) -> str:
    """Write the GeoJSON for a detours file; return a summary line.

    Loads GTFS only for the feeds the matched detours use (none, if nothing
    matched). Unlike ``export_route``, an empty collection is written:
    "no detours to draw" is a true state, not a sign of a bug.

    Raises:
        FileNotFoundError: ``detours_file`` or a GTFS file is missing.
        ValueError: ``detours_file`` isn't a valid detours list (pydantic's
            ``ValidationError`` is a ``ValueError``), or it disagrees with
            GTFS (unknown route, shape without coordinates).
    """
    detours = read_detours(detours_file.read_bytes())
    feeds = sorted({d.match.feed for d in detours if d.match is not None})
    # Loaders treat an empty feed list as a bug, so with nothing matched
    # there's nothing to load: the collection is empty either way.
    collection = (
        detours_feature_collection(
            detours, load_routes(feeds), shape_coordinates(load_shapes(feeds))
        )
        if feeds
        else FeatureCollection(type="FeatureCollection", features=[])
    )

    write_geojson(collection, path)
    types = [feature["geometry"]["type"] for feature in collection["features"]]
    return (
        f"wrote {path} ({types.count('LineString')} lines, "
        f"{types.count('Point')} start points from {len(detours)} detours "
        f"in {detours_file.name})"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the export from the command line.

    Args:
        argv: Arguments without the program name. ``None`` means
            ``sys.argv[1:]`` (argparse's default), so tests can pass a list.

    Returns:
        Process exit code (see module docstring). Argument errors don't
        return: argparse raises ``SystemExit(2)`` itself.
    """
    args = _build_parser().parse_args(argv)

    try:
        if args.command == "route":
            # argparse types attributes as Any; `choices` guarantees a Feed.
            feed = cast("Feed", args.feed)
            summary = f"wrote {export_route(feed, args.route_id)}"
        else:
            detours_file: Path = args.detours_file or find_latest_detours()
            summary = export_detours(detours_file)
    except (FileNotFoundError, ValueError) as exc:
        # Expected, explainable failures only. Anything else is a bug and
        # should surface with its full traceback.
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print(summary)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
