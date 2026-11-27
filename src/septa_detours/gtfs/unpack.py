"""Unpack a saved SEPTA GTFS release into ``data/gtfs/`` (shared, not a stage).

``ingest gtfs`` saves SEPTA's release untouched as
``data/raw/gtfs/gtfs_public-<tag>.zip``: an outer zip holding
``google_bus.zip`` and ``google_rail.zip``, each a flat set of ``.txt``
tables. This turns it into ``data/gtfs/bus/*.txt`` and
``data/gtfs/rail/*.txt``, the layout ``gtfs/load.py`` reads.

The zip comes from the internet, so only flat table names are written
(no paths, no hidden files), and the new tree replaces the old one only
once both feeds have been extracted.

``gtfs/`` never imports from a stage, so the raw directory and file
naming are repeated here from ``ingest/gtfs.py`` on purpose.
"""

import io
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from septa_detours.gtfs.load import ALL_FEEDS, DEFAULT_GTFS_ROOT

DEFAULT_RAW_GTFS_DIR = Path("data/raw/gtfs")

INGEST_COMMAND = "uv run python -m septa_detours.ingest gtfs"

_RELEASE_ZIP = re.compile(r"gtfs_public-v([0-9]{8})([0-9]+)\.zip")
"""``ingest/gtfs.py``'s names: tag = ``v`` + start date + revision."""

_TABLE_NAME = re.compile(r"[A-Za-z0-9_]+\.txt")
"""A flat table name: no directories, no ``..``, no leading dot."""


def find_latest_gtfs_zip(raw_root: Path = DEFAULT_RAW_GTFS_DIR) -> Path:
    """The saved release with the newest ``(start date, revision)``.

    Revisions compare as numbers (``...10`` after ``...9``). Other files
    (``*.zip.tmp`` leftovers, anything else) are ignored.

    Raises:
        FileNotFoundError: ``raw_root`` is missing or holds no release;
            the message names the ingest command.
    """
    releases = []
    if raw_root.is_dir():
        for path in raw_root.iterdir():
            match = _RELEASE_ZIP.fullmatch(path.name)
            if match is not None:
                releases.append(((match.group(1), int(match.group(2))), path))
    if not releases:
        msg = f"no GTFS release in {raw_root}; fetch one with: {INGEST_COMMAND}"
        raise FileNotFoundError(msg)
    return max(releases)[1]


def unpack_gtfs(release_zip: Path, root: Path = DEFAULT_GTFS_ROOT) -> list[str]:
    """Replace ``root`` with the release's tables; return them as ``<feed>/<name>``.

    Each feed's ``google_<feed>.zip`` inside ``release_zip`` gives
    ``root/<feed>/<name>.txt``; feeds in ``ALL_FEEDS`` order, names sorted.
    Only flat table names are extracted; anything else in the inner zips
    is skipped. The tree is built in a temporary directory beside
    ``root`` and swapped in at the end, so tables dropped from a release
    are dropped here too, and a failure leaves ``root`` as it was.

    Raises:
        ValueError: A feed's inner zip is missing or holds no tables.
        zipfile.BadZipFile: ``release_zip`` (or an inner zip) isn't a zip.
        OSError: ``release_zip`` can't be read, or ``root`` can't be written.
    """
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}-new-", dir=root.parent))
    try:
        tables = _extract_feeds(release_zip, staging)
        _swap_in(staging, root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return tables


def _extract_feeds(release_zip: Path, staging: Path) -> list[str]:
    """Extract every feed's tables into ``staging/<feed>/``."""
    tables = []
    with zipfile.ZipFile(release_zip) as outer:
        inner_names = set(outer.namelist())
        for feed in ALL_FEEDS:
            inner_name = f"google_{feed}.zip"
            if inner_name not in inner_names:
                msg = f"{release_zip.name} has no {inner_name}"
                raise ValueError(msg)
            inner_bytes = io.BytesIO(outer.read(inner_name))
            with zipfile.ZipFile(inner_bytes) as inner:
                # Directory entries end in "/", so they never match.
                names = sorted(
                    name for name in inner.namelist() if _TABLE_NAME.fullmatch(name)
                )
                if not names:
                    msg = f"{release_zip.name}: {inner_name} has no .txt tables"
                    raise ValueError(msg)
                feed_dir = staging / feed
                feed_dir.mkdir()
                for name in names:
                    with (
                        inner.open(name) as source,
                        (feed_dir / name).open("wb") as out,
                    ):
                        shutil.copyfileobj(source, out)
                tables.extend(f"{feed}/{name}" for name in names)
    return tables


def _swap_in(staging: Path, root: Path) -> None:
    """Put ``staging`` where ``root`` is; delete the old ``root``.

    Two renames (a directory can't replace a non-empty one in one step):
    ``root`` is briefly absent between them. If the second fails, the old
    tree is put back.
    """
    if not root.exists():
        staging.rename(root)
        return
    old = Path(tempfile.mkdtemp(prefix=f".{root.name}-old-", dir=root.parent))
    old.rmdir()  # only its unique name is wanted; rename needs it absent
    root.rename(old)
    try:
        staging.rename(root)
    except BaseException:
        old.rename(root)
        raise
    shutil.rmtree(old)
