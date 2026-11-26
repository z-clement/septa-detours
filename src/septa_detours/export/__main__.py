"""Export data for the web map: the whole site, one route, or the detours.

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.export site [detours.json]
    uv run python -m septa_detours.export route bus 21

``site`` reads a ``match`` output (default: the newest
``data/processed/detours-*.json``) plus both GTFS feeds and writes the
data contract (``export/contract.py``) to ``web/data/``, which the map
page reads. ``route`` writes ``web/data/<feed>-<route_id>.geojson`` (a
debugging tool; the page doesn't read it). Glue only: every decision
about *what* goes in a file lives in ``gtfs/`` and the ``export/``
builders, and *how* it is written lives in ``export/write.py``.

Output: one ``wrote ...`` summary line on stdout.

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
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from septa_detours.export.geojson import (
    join_route_lines,
    route_feature_collection,
    route_properties,
)
from septa_detours.export.site import (
    lines_bounds,
    network_collection,
    route_catalog,
    route_detail,
    route_directions,
    route_key,
    route_shapes,
    skipped_collection,
    starts_collection,
    status,
)
from septa_detours.export.write import (
    DEFAULT_WEB_DATA_DIR,
    route_geojson_path,
    write_geojson,
    write_site,
)
from septa_detours.gtfs.load import (
    ALL_FEEDS,
    Feed,
    load_directions,
    load_feed_info,
    load_routes,
    load_shapes,
    load_trips,
)
from septa_detours.gtfs.routes import route_shape_ids
from septa_detours.gtfs.shapes import shape_coordinates
from septa_detours.model import Detour, read_detours

# Duplicated from ``match/__main__.py`` on purpose: one stage never imports
# another's internals. Both describe the files ``match`` writes.
DEFAULT_DETOURS_DIR = Path("data/processed")
MATCH_COMMAND = "uv run python -m septa_detours.match"

# ``match``'s output name for a stamped snapshot: ``detours-<stamp>.json``.
_DETOURS_NAME = re.compile(r"detours-\d{4}-\d{2}-\d{2}T\d{6}Z\.json")


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: a required ``site`` or ``route`` command.

    ``route``'s ``feed`` is limited to ``ALL_FEEDS`` via ``choices``, so a
    typo is rejected by argparse (exit 2, usage message) before any GTFS
    loads.
    """
    parser = argparse.ArgumentParser(
        prog="python -m septa_detours.export",
        description="Write data for the web map to web/data/.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    site = commands.add_parser("site", help="Write every file the map page reads.")
    site.add_argument(
        "detours_file",
        nargs="?",
        type=Path,
        help="match output to read (default: the newest in data/processed/).",
    )

    route = commands.add_parser("route", help="Write one route's shapes.")
    route.add_argument("feed", choices=ALL_FEEDS, help="GTFS feed to read.")
    route.add_argument(
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


def export_site(
    detours_file: Path,
    root: Path = DEFAULT_WEB_DATA_DIR,
    now: datetime | None = None,
) -> str:
    """Write the whole data contract for a detours file; return a summary.

    Reads the detours first (a bad file fails before ~1 s of GTFS
    loading), then both feeds. Every catalog route gets a detail file,
    even with no shapes or detours, so the page never asks for a missing
    one. A feed without ``feed_info.txt`` gets a ``null`` version.

    Args:
        detours_file: A ``match`` output.
        root: Where the page's data goes.
        now: The export time (``generated_at``, and the moment ``timing``
            is computed for); default: the current time.

    Raises:
        FileNotFoundError: ``detours_file`` or a required GTFS file is
            missing.
        ValueError: ``detours_file`` isn't a valid detours list, or the
            detours and GTFS disagree (see the ``export/site.py`` builders).
    """
    detours = read_detours(detours_file.read_bytes())
    now = now or datetime.now(UTC)
    coordinates = shape_coordinates(load_shapes())
    shapes = route_shapes(load_trips(), coordinates)
    bounds = {
        key: lines_bounds(shape.line for shape in route)
        for key, route in shapes.items()
    }
    catalog = route_catalog(load_routes(), bounds, detours)
    directions = route_directions(load_directions(), shapes)

    by_route: dict[str, list[Detour]] = {}
    for detour in detours:
        if detour.match is not None:
            key = route_key(detour.match.feed, detour.match.route_id)
            by_route.setdefault(key, []).append(detour)

    starts = starts_collection(catalog, detours, now)
    skipped = skipped_collection(catalog, detours, now)
    files: dict[str, object] = {
        "status.json": status(
            detours, _snapshot_name(detours, detours_file), _feed_versions(), now
        ),
        "routes.json": catalog,
        "network.geojson": network_collection(catalog, shapes, coordinates),
        "starts.geojson": starts,
        "skipped.geojson": skipped,
    }
    for entry in catalog:
        key = entry["key"]
        files[f"routes/{key}.json"] = route_detail(
            entry, directions.get(key, []), shapes.get(key, []), by_route.get(key, [])
        )
    written = write_site(files, root)

    size_mb = sum(path.stat().st_size for path in written) / 1_000_000
    return (
        f"wrote {len(written)} files to {root} ({size_mb:.1f} MB: "
        f"{len(catalog)} routes ({len(shapes)} with shapes), "
        f"{len(starts['features'])} start points from {len(detours)} detours "
        f"in {detours_file.name})"
    )


def _snapshot_name(detours: Sequence[Detour], detours_file: Path) -> str:
    """The alerts snapshot the detours came from, e.g. ``2026-11-25T121123Z.json``.

    Taken from the detours themselves (each notice records its snapshot),
    not from the detours file's name. With no detours to ask, the file
    name with ``match``'s ``detours-`` prefix removed.

    Raises:
        ValueError: The detours come from more than one snapshot.
    """
    names = sorted({detour.notice.source.snapshot for detour in detours})
    if len(names) > 1:
        raise ValueError(f"detours from more than one snapshot: {names}")
    if names:
        return names[0]
    return detours_file.name.removeprefix("detours-")


def _feed_versions() -> dict[Feed, str | None]:
    """Each feed's ``feed_version``; ``None`` without ``feed_info.txt``."""
    versions: dict[Feed, str | None] = {}
    for feed in ALL_FEEDS:
        try:
            rows = load_feed_info([feed])["feed_version"].to_list()
        except FileNotFoundError:
            rows = []
        versions[feed] = rows[0] if rows else None
    return versions


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
        if args.command == "site":
            summary = export_site(args.detours_file or find_latest_detours())
        else:
            # argparse types attributes as Any; `choices` guarantees a Feed.
            feed = cast("Feed", args.feed)
            summary = f"wrote {export_route(feed, args.route_id)}"
    except (FileNotFoundError, ValueError) as exc:
        # Expected, explainable failures only. Anything else is a bug and
        # should surface with its full traceback.
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print(summary)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
