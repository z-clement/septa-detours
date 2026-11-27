"""Check and unpack the GTFS feeds (maintenance, not a pipeline stage).

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.gtfs check
    uv run python -m septa_detours.gtfs unpack [release_zip]

``check`` prints one line per feed: ``bus GTFS v202611220 ends
2027-02-20`` when all is well, or ``::warning::<message>`` when the feed
ends within ``WARN_WITHIN_DAYS`` days, has ended, or its ``feed_info.txt``
can't be read. GitHub Actions shows ``::warning::`` lines as annotations
on the run; locally they're just text.

``unpack`` replaces ``data/gtfs/{bus,rail}/`` with the tables of a
release saved by ``ingest gtfs`` (default: the newest in
``data/raw/gtfs/``; ``gtfs/unpack.py``) and prints one ``unpacked ...``
line.

Exit codes:
    0: ``check`` always, warnings included: an old feed must never stop
       the hosted job (a missing feed fails ``match`` soon after).
       ``unpack``: ``data/gtfs/`` was replaced.
    1: ``unpack``: no saved release, or it isn't a valid release zip;
       ``data/gtfs/`` is left as it was.
    2: bad command-line arguments (argparse's own convention).
"""

import argparse
import sys
import zipfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from septa_detours.gtfs.expiry import WARN_WITHIN_DAYS, end_date_warning
from septa_detours.gtfs.load import ALL_FEEDS, DEFAULT_GTFS_ROOT, load_feed_info
from septa_detours.gtfs.unpack import find_latest_gtfs_zip, unpack_gtfs

GITHUB_WARNING = "::warning::"


def check_feeds(today: date, root: Path = DEFAULT_GTFS_ROOT) -> list[str]:
    """One output line per feed row (or per unreadable feed), in feed order.

    Each feed is read on its own, so one broken ``feed_info.txt`` doesn't
    hide the other feed's result. An empty ``feed_info.txt`` (header only)
    warns too: it would otherwise print nothing at all.
    """
    lines = []
    for feed in ALL_FEEDS:
        try:
            info = load_feed_info([feed], root)
        except (FileNotFoundError, ValueError) as exc:
            lines.append(f"{GITHUB_WARNING}{feed} GTFS: {exc}")
            continue
        if info.is_empty():
            lines.append(f"{GITHUB_WARNING}{feed} GTFS: feed_info.txt has no rows")
        for row in info.iter_rows(named=True):
            warning = end_date_warning(feed, row["feed_end_date"], today)
            if warning is None:
                end = row["feed_end_date"]
                ends = f"{end[:4]}-{end[4:6]}-{end[6:]}"
                lines.append(f"{feed} GTFS {row['feed_version']} ends {ends}")
            else:
                lines.append(f"{GITHUB_WARNING}{warning}")
    return lines


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m septa_detours.gtfs",
        description="Maintenance commands for the GTFS feeds in data/gtfs/.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "check",
        help=(
            f"warn if a feed ends within {WARN_WITHIN_DAYS} days or has ended "
            "(always exits 0)"
        ),
    )
    unpack = commands.add_parser(
        "unpack", help="replace data/gtfs/ with a saved SEPTA release"
    )
    unpack.add_argument(
        "release_zip",
        nargs="?",
        type=Path,
        help="gtfs_public-<tag>.zip (default: the newest in data/raw/gtfs/)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command from the command line.

    Args:
        argv: Arguments without the program name. ``None`` means
            ``sys.argv[1:]``, so tests can pass a list.

    Returns:
        Process exit code (see module docstring).
    """
    args = _build_parser().parse_args(argv)
    if args.command == "unpack":
        try:
            release_zip = args.release_zip or find_latest_gtfs_zip()
            tables = unpack_gtfs(release_zip)
        except (FileNotFoundError, ValueError, zipfile.BadZipFile) as exc:
            print(f"error: {exc}", file=sys.stderr)  # noqa: T201
            return 1
        summary = f"{DEFAULT_GTFS_ROOT} ({len(tables)} tables)"
        print(f"unpacked {release_zip} into {summary}")  # noqa: T201
        return 0
    for line in check_feeds(date.today()):  # noqa: DTZ011 (local date is fine)
        print(line)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
