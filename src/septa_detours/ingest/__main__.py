"""Fetch SEPTA's alerts once and save a raw snapshot.

Usage (from the repo root, since default paths are relative to it)::

    uv run python -m septa_detours.ingest

Writes ``data/raw/alerts/<UTC timestamp>.json``. Glue only: the logic
lives in ``ingest/alerts.py``. When the real ``septa-detours fetch`` CLI
arrives, its subcommand can call ``main``.

Exit codes:
    0: snapshot written.
    1: fetch failed (network, timeout, bad status, non-JSON response).
    2: bad command-line arguments (argparse's own convention).
"""

import argparse
import sys
from collections.abc import Sequence

import httpx

from septa_detours.ingest.alerts import make_client, save_alerts_snapshot


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (no arguments yet; gives ``--help``)."""
    return argparse.ArgumentParser(
        prog="python -m septa_detours.ingest",
        description="Fetch SEPTA's alerts API and save it to data/raw/alerts/.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one fetch from the command line.

    Args:
        argv: Arguments without the program name. ``None`` means
            ``sys.argv[1:]``, so tests can pass a list.

    Returns:
        Process exit code (see module docstring).
    """
    _build_parser().parse_args(argv)

    try:
        with make_client() as client:
            path = save_alerts_snapshot(client)
    except (httpx.HTTPError, ValueError) as exc:
        # Expected, explainable failures only (the network is unreliable).
        # Anything else, e.g. OSError on a read-only disk, keeps its traceback.
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print(f"wrote {path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
