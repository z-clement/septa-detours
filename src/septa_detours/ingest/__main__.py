"""Fetch raw source data and save it untouched under ``data/raw/``.

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.ingest          # alerts (the default)
    uv run python -m septa_detours.ingest alerts   # same
    uv run python -m septa_detours.ingest osm      # Geofabrik OSM extracts
    uv run python -m septa_detours.ingest gtfs     # SEPTA's GTFS in effect
    uv run python -m septa_detours.ingest store <snapshot>   # hosted job only

``alerts`` writes ``data/raw/alerts/<UTC timestamp>.json``. ``osm`` writes
``data/raw/osm/<region>-<YYMMDD>.osm.pbf`` for each of
``GEOFABRIK_REGIONS`` (about 540 MB in total). ``gtfs`` writes
``data/raw/gtfs/gtfs_public-<tag>.zip`` (~26 MB), the release in effect
on New York's date, unless it's already there (``ingest/gtfs.py``); set
``GITHUB_TOKEN`` to lift GitHub's 60-an-hour API limit. Glue only: the logic lives
in ``ingest/alerts.py`` and ``ingest/osm.py``. When the real
``septa-detours fetch`` CLI arrives, its subcommand can call ``main``.

``store`` adds a saved snapshot to ``origin``'s ``snapshots`` branch if
its bytes changed (``ingest/store.py``). It pushes, so it's for the
hosted job's checkout, not for a local clone.

Output: ``wrote <path>`` on stdout for each file written (``gtfs``:
``wrote``/``have <path> (<tag>, in effect since <date>)``; ``store``:
``stored <name> on snapshots (<id>)`` or ``unchanged: ...``); progress
(``fetching ...``) and errors on stderr.

Exit codes:
    0: everything requested was written.
    1: a fetch failed (network, timeout, bad status, bad content). For
       ``osm``, the other regions are still fetched first. For ``store``,
       a git command failed (its stderr is printed) or the snapshot's
       name is wrong or clashes with a stored one.
    2: bad command-line arguments (argparse's own convention).
"""

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from septa_detours.ingest.alerts import make_client, save_alerts_snapshot
from septa_detours.ingest.gtfs import fetch_gtfs
from septa_detours.ingest.osm import GEOFABRIK_REGIONS, extract_url, fetch_extract
from septa_detours.ingest.store import STORE_BRANCH, store_snapshot

# Expected, explainable failures only (the network is unreliable). Anything
# else, e.g. OSError on a read-only disk, keeps its traceback. (pydantic's
# ValidationError is a ValueError.)
_FETCH_ERRORS = (httpx.HTTPError, ValueError)

_SEPTA_TIME_ZONE = ZoneInfo("America/New_York")


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser: optional ``source`` (default ``alerts``), ``snapshot``.

    ``snapshot`` belongs to ``store`` only; ``main`` checks that.
    """
    parser = argparse.ArgumentParser(
        prog="python -m septa_detours.ingest",
        description="Fetch raw source data and save it untouched to data/raw/.",
    )
    parser.add_argument(
        "source",
        nargs="?",
        choices=("alerts", "osm", "gtfs", "store"),
        default="alerts",
        help=(
            "alerts: one SEPTA alerts API snapshot (default); "
            "osm: Geofabrik OSM extracts for every region SEPTA serves; "
            "gtfs: SEPTA's GTFS release in effect today; "
            f"store: push a snapshot to the {STORE_BRANCH} branch if it changed "
            "(hosted job only)"
        ),
    )
    parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        help="store only: the snapshot file, e.g. data/raw/alerts/<stamp>.json",
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
    parser = _build_parser()
    args = parser.parse_args(argv)
    if (args.source == "store") != (args.snapshot is not None):
        parser.error("a snapshot file goes with store, and only with store")
    if args.source == "store":
        return _store(args.snapshot)
    if args.source == "osm":
        return _fetch_osm()
    if args.source == "gtfs":
        return _fetch_gtfs()
    return _fetch_alerts()


def _new_york_today() -> date:
    """Today in SEPTA's time zone (feeds start on New York dates)."""
    return datetime.now(_SEPTA_TIME_ZONE).date()


def _fetch_gtfs() -> int:
    """Save the GTFS release in effect; exit code 0 or 1."""
    token = os.environ.get("GITHUB_TOKEN") or None
    try:
        with make_client() as client:
            release, path, downloaded = fetch_gtfs(
                client, _new_york_today(), token=token
            )
    except _FETCH_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    verb = "wrote" if downloaded else "have"
    since = release.service_start.isoformat()
    print(f"{verb} {path} ({release.tag}, in effect since {since})")  # noqa: T201
    return 0


def _store(snapshot: Path) -> int:
    """Store one snapshot on the branch; exit code 0 or 1."""
    try:
        commit = store_snapshot(snapshot)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    except subprocess.CalledProcessError as exc:
        command = " ".join(exc.cmd[3:])  # without "git -C <repo>"
        print(f"error: git {command} failed:\n{exc.stderr}", file=sys.stderr)  # noqa: T201
        return 1

    if commit is None:
        print(f"unchanged: nothing new in {snapshot.name}; nothing pushed")  # noqa: T201
    else:
        print(f"stored {snapshot.name} on {STORE_BRANCH} ({commit[:12]})")  # noqa: T201
    return 0


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
