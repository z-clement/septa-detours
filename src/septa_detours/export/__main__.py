"""Export one route's shapes as GeoJSON for the web map.

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.export bus 21

Writes ``web/data/<feed>-<route_id>.geojson``. Glue only: every decision
about *what* goes in the file lives in ``gtfs/`` and ``export/geojson.py``,
and *how* it is written lives in ``export/write.py``.

Exit codes:
    0: file written.
    1: the route can't be exported (unknown route, no shapes, bad data).
    2: bad command-line arguments (argparse's own convention).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from septa_detours.export.geojson import (
    join_route_lines,
    route_feature_collection,
    route_properties,
)
from septa_detours.export.write import route_geojson_path, write_geojson
from septa_detours.gtfs.load import (
    ALL_FEEDS,
    Feed,
    load_routes,
    load_shapes,
    load_trips,
)
from septa_detours.gtfs.routes import route_shape_ids
from septa_detours.gtfs.shapes import shape_coordinates


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: positional ``feed`` and ``route_id``.

    ``feed`` is limited to ``ALL_FEEDS`` via ``choices``, so a typo is
    rejected by argparse (exit 2, usage message) before any GTFS loads.
    """
    parser = argparse.ArgumentParser(
        prog="python -m septa_detours.export",
        description="Write one route's shapes to web/data/ as GeoJSON.",
    )
    parser.add_argument("feed", choices=ALL_FEEDS, help="GTFS feed to read.")
    parser.add_argument(
        "route_id",
        help="GTFS route_id (e.g. 21, L1); not always the public route name.",
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
    # argparse types attributes as Any; `choices` guarantees it's a Feed.
    feed = cast("Feed", args.feed)

    try:
        path = export_route(feed, args.route_id)
    except ValueError as exc:
        # Expected, explainable failures only. Anything else is a bug and
        # should surface with its full traceback.
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print(f"wrote {path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
