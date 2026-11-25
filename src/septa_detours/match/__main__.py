"""Command: ``python -m septa_detours.match [snapshot]``.

Parses one alerts snapshot, matches its notices to GTFS and OSM, and writes
the resulting ``Detour`` list to ``data/processed/``. Glue only; the work is
done by ``parse/`` and ``match/``.
"""

import re
from pathlib import Path

# Duplicated from ``ingest/alerts.py`` on purpose: one stage never imports
# another's internals. Both describe the files ``ingest`` writes.
DEFAULT_ALERTS_DIR = Path("data/raw/alerts")
INGEST_COMMAND = "uv run python -m septa_detours.ingest"

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
