"""Build the street cache from the newest saved OSM extracts.

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.streets

Reads ``data/raw/osm/<region>-<YYMMDD>.osm.pbf`` (the newest one per
region, all of ``GEOFABRIK_REGIONS``), clips to SEPTA's stops plus a 2 km
margin, and writes ``data/processed/streets.parquet``. Takes about 30 s.
Run it after fetching new extracts (``python -m septa_detours.ingest osm``);
bus routes change rarely, so that's occasional, not every day.

Glue only: the logic lives in ``streets/load.py`` and ``streets/cache.py``.

Output: ``reading <path>`` per extract on stderr (progress); one
``wrote <path> (...)`` line on stdout.

Exit codes:
    0: cache written.
    1: an extract or GTFS file is missing, or the extracts disagree
       (re-fetch them). Nothing is written; an older cache stays as it was.
    2: bad command-line arguments (argparse's own convention).
"""

import argparse
import sys
from collections.abc import Sequence

from septa_detours.gtfs.load import load_stops
from septa_detours.ingest.osm import GEOFABRIK_REGIONS
from septa_detours.streets.cache import (
    DEFAULT_STREET_CACHE,
    StreetCacheInfo,
    combine_street_ways,
    find_latest_extract,
    service_bbox,
    write_street_cache,
)
from septa_detours.streets.load import read_street_ways


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (no arguments yet; gives ``--help``)."""
    return argparse.ArgumentParser(
        prog="python -m septa_detours.streets",
        description=(
            "Build data/processed/streets.parquet from the newest OSM extracts "
            "in data/raw/osm/."
        ),
    )


def build_street_cache() -> str:
    """Build and write the cache; return a one-line summary.

    Cheapest checks first: every extract must exist before any is read
    (reading Pennsylvania alone takes about 25 s).

    Raises:
        FileNotFoundError: A missing extract or GTFS ``stops.txt``.
        ValueError: The extracts disagree about a way, or one is broken.
    """
    paths = [find_latest_extract(region) for region in GEOFABRIK_REGIONS]
    bbox = service_bbox(load_stops())

    frames = []
    for path in paths:
        print(f"reading {path}", file=sys.stderr)  # noqa: T201
        frames.append(read_street_ways(path, bbox))
    ways = combine_street_ways(frames)

    sources = tuple(path.name for path in paths)
    write_street_cache(ways, StreetCacheInfo(sources=sources, bbox=bbox))
    return (
        f"wrote {DEFAULT_STREET_CACHE} ({ways.height} ways from {', '.join(sources)})"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the build from the command line.

    Args:
        argv: Arguments without the program name. ``None`` means
            ``sys.argv[1:]``, so tests can pass a list.

    Returns:
        Process exit code (see module docstring).
    """
    _build_parser().parse_args(argv)
    try:
        summary = build_street_cache()
    except (FileNotFoundError, ValueError) as exc:
        # Expected, explainable failures only. Anything else (e.g. pyosmium's
        # RuntimeError for a corrupt file) keeps its traceback.
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print(summary)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
