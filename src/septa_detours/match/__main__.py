"""Parse and match one alerts snapshot; write its ``Detour`` list.

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.match [snapshot]

``snapshot`` defaults to the newest file in ``data/raw/alerts/``. Writes
``data/processed/detours-<snapshot stem>.json`` (see ``model.dump_detours``),
one file per snapshot. Needs the bus GTFS feed and the street cache.

Glue only: the work is done by ``parse/`` and ``match/``.

Output: one ``wrote <path> (N detours: M matched to a route, K placed)``
line on stdout.

Exit codes:
    0: file written.
    1: no snapshot, a missing GTFS file or street cache, or a snapshot that
       isn't the API's shape. Nothing is written; an older output stays.
    2: bad command-line arguments (argparse's own convention).
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from septa_detours.gtfs.load import (
    Feed,
    load_directions,
    load_routes,
    load_shapes,
    load_trips,
)
from septa_detours.io import write_bytes_atomic
from septa_detours.match.notice import build_match_reference, match_notices
from septa_detours.model import dump_detours
from septa_detours.parse.notice import parse_snapshot
from septa_detours.streets.cache import read_street_cache

# Duplicated from ``ingest/alerts.py`` on purpose: one stage never imports
# another's internals. Both describe the files ``ingest`` writes.
DEFAULT_ALERTS_DIR = Path("data/raw/alerts")
INGEST_COMMAND = "uv run python -m septa_detours.ingest"

DEFAULT_DETOURS_DIR = Path("data/processed")

# ``ingest``'s snapshot name: a UTC stamp, ``%Y-%m-%dT%H%M%SZ.json``.
_SNAPSHOT_NAME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{6}Z\.json")


def find_latest_snapshot(root: Path = DEFAULT_ALERTS_DIR) -> Path:
    """Return the newest saved alerts snapshot, by the UTC stamp in its name.

    Snapshots are saved as ``<YYYY-MM-DDTHHMMSSZ>.json``. Names are matched
    exactly, so leftovers like ``*.json.tmp`` and stray files are ignored.
    Fixed-width UTC stamps sort in time order, so the largest name is the
    newest. The stamp's digits aren't checked as a real date: ``ingest``
    only writes real ones.

    Only lists ``root``; doesn't open any file.

    Args:
        root: Directory holding the snapshots. Defaults to
            ``data/raw/alerts``.

    Raises:
        FileNotFoundError: If ``root`` doesn't exist or holds no snapshot;
            the message names the ingest command.
    """
    candidates = (
        [path for path in root.iterdir() if _SNAPSHOT_NAME.fullmatch(path.name)]
        if root.is_dir()
        else []
    )
    if not candidates:
        msg = f"no alerts snapshot in {root}; fetch one with: {INGEST_COMMAND}"
        raise FileNotFoundError(msg)
    return max(candidates, key=lambda path: path.name)


def detours_path(snapshot: Path, root: Path = DEFAULT_DETOURS_DIR) -> Path:
    """Return where the detours for ``snapshot`` go: ``detours-<stem>.json``.

    Pure. Any snapshot name is accepted (a hand-made one too); ``stem``
    never contains a ``/``, so the result is always directly in ``root``.
    """
    return root / f"detours-{snapshot.stem}.json"


def match_snapshot(snapshot: Path) -> str:
    """Parse and match ``snapshot``, write the detours; return a summary line.

    The snapshot is read and parsed before any reference data is loaded, so
    a broken snapshot fails fast. Only the bus feed is loaded: rail has no
    detours (``find_gtfs_route`` never returns rail).

    Raises:
        FileNotFoundError: ``snapshot``, a bus GTFS file, or the street
            cache is missing.
        ValueError: ``snapshot`` isn't the API's shape (pydantic's
            ``ValidationError`` is a ``ValueError``), or the street cache
            needs rebuilding.
    """
    notices = parse_snapshot(snapshot.read_bytes(), snapshot.name)

    feeds: tuple[Feed, ...] = ("bus",)
    reference = build_match_reference(
        routes=load_routes(feeds),
        trips=load_trips(feeds),
        directions=load_directions(feeds),
        shapes=load_shapes(feeds),
        ways=read_street_cache(),
    )
    detours = match_notices(notices, reference)

    path = detours_path(snapshot)
    write_bytes_atomic(dump_detours(detours), path)

    matched = [d.match for d in detours if d.match is not None]
    placed = sum(1 for m in matched if m.start_point is not None)
    return (
        f"wrote {path} ({len(detours)} detours: "
        f"{len(matched)} matched to a route, {placed} placed)"
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: one optional ``snapshot`` path."""
    parser = argparse.ArgumentParser(
        prog="python -m septa_detours.match",
        description=(
            "Parse and match an alerts snapshot; write "
            "data/processed/detours-<snapshot>.json."
        ),
    )
    parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        help="Snapshot file to read (default: the newest in data/raw/alerts/).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the match from the command line.

    Args:
        argv: Arguments without the program name. ``None`` means
            ``sys.argv[1:]``, so tests can pass a list.

    Returns:
        Process exit code (see module docstring).
    """
    args = _build_parser().parse_args(argv)
    try:
        snapshot: Path = args.snapshot or find_latest_snapshot()
        summary = match_snapshot(snapshot)
    except (FileNotFoundError, ValueError) as exc:
        # Expected, explainable failures only. Anything else is a bug and
        # keeps its traceback.
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print(summary)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
