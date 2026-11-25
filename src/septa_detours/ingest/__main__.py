"""Fetch raw source data and save it untouched under ``data/raw/``.

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.ingest          # alerts (the default)
    uv run python -m septa_detours.ingest alerts   # same
    uv run python -m septa_detours.ingest osm      # Geofabrik OSM extracts

``alerts`` writes ``data/raw/alerts/<UTC timestamp>.json``. ``osm`` writes
``data/raw/osm/<region>-<YYMMDD>.osm.pbf`` for each of
``GEOFABRIK_REGIONS`` (about 540 MB in total). Glue only: the logic lives
in ``ingest/alerts.py`` and ``ingest/osm.py``. When the real
``septa-detours fetch`` CLI arrives, its subcommand can call ``main``.

Output: ``wrote <path>`` on stdout for each file written; progress
(``fetching ...``) and errors on stderr.

Exit codes:
    0: everything requested was written.
    1: a fetch failed (network, timeout, bad status, bad content). For
       ``osm``, the other regions are still fetched first.
    2: bad command-line arguments (argparse's own convention).
"""

import argparse
import sys
from collections.abc import Sequence

import httpx

from septa_detours.ingest.alerts import make_client, save_alerts_snapshot
from septa_detours.ingest.osm import GEOFABRIK_REGIONS, extract_url, fetch_extract

# Expected, explainable failures only (the network is unreliable). Anything
# else, e.g. OSError on a read-only disk, keeps its traceback.
_FETCH_ERRORS = (httpx.HTTPError, ValueError)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: one optional ``source`` (default ``alerts``)."""
    parser = argparse.ArgumentParser(
        prog="python -m septa_detours.ingest",
        description="Fetch raw source data and save it untouched to data/raw/.",
    )
    parser.add_argument(
        "source",
        nargs="?",
        choices=("alerts", "osm"),
        default="alerts",
        help=(
            "alerts: one SEPTA alerts API snapshot (default); "
            "osm: Geofabrik OSM extracts for every region SEPTA serves"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one fetch from the command line.

    Args:
        argv: Arguments without the program name. ``None`` means
            ``sys.argv[1:]``, so tests can pass a list.

    Returns:
        Process exit code (see module docstring).
    """
    args = _build_parser().parse_args(argv)
    if args.source == "osm":
        return _fetch_osm()
    return _fetch_alerts()


def _fetch_alerts() -> int:
    """Fetch one alerts snapshot; exit code 0 or 1."""
    try:
        with make_client() as client:
            path = save_alerts_snapshot(client)
    except _FETCH_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print(f"wrote {path}")  # noqa: T201
    return 0


def _fetch_osm() -> int:
    """Fetch every region's extract; keep going past a failed region.

    The regions are independent, so one failure (say Delaware) shouldn't
    throw away the others. Exit code 1 if any region failed.
    """
    failed: list[str] = []
    with make_client() as client:
        for region in GEOFABRIK_REGIONS:
            print(f"fetching {region} ({extract_url(region)})", file=sys.stderr)  # noqa: T201
            try:
                path = fetch_extract(client, region)
            except _FETCH_ERRORS as exc:
                print(f"error: {region}: {exc}", file=sys.stderr)  # noqa: T201
                failed.append(region)
                continue
            print(f"wrote {path}")  # noqa: T201

    if failed:
        total = len(GEOFABRIK_REGIONS)
        msg = f"error: {len(failed)} of {total} regions failed: {', '.join(failed)}"
        print(msg, file=sys.stderr)  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
