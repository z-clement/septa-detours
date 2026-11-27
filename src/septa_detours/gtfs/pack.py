"""Zip the saved GTFS feeds for the hosted job (shared, not a stage).

The job can't download SEPTA's GTFS itself (it's fetched by hand), so the
feeds reach it as ``gtfs.zip``, an asset of the repo's ``reference``
release. The zip holds ``bus/<table>.txt`` and ``rail/<table>.txt``, so
``unzip gtfs.zip -d data/gtfs`` restores the layout ``gtfs/load.py``
reads.

The same files always give the same bytes (sorted members, fixed
timestamps and permissions), so comparing checksums tells whether a new
upload is needed.
"""

import io
import shutil
import zipfile
from pathlib import Path

from septa_detours.gtfs.load import ALL_FEEDS, DEFAULT_GTFS_ROOT, feed_dir
from septa_detours.io import write_bytes_atomic

DEFAULT_GTFS_ZIP = Path("data/processed/gtfs.zip")

_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
"""The earliest time a zip can store: no file's mtime leaks into the bytes."""

_FILE_MODE = 0o100644
"""A regular file, ``rw-r--r--``, so ``unzip`` gives normal permissions."""


def pack_gtfs(
    out: Path = DEFAULT_GTFS_ZIP, root: Path = DEFAULT_GTFS_ROOT
) -> list[str]:
    """Write every feed's ``*.txt`` tables to the zip ``out``; return its members.

    Members are ``<feed>/<name>.txt``, feeds in ``ALL_FEEDS`` order and
    names sorted within each feed. Only ``.txt`` files directly in each
    feed directory are packed (no subdirectories, no stray downloads).
    Each table is streamed in (``stop_times.txt`` is ~130 MB); the
    compressed zip is built in memory, then written atomically.

    Raises:
        FileNotFoundError: A feed directory is missing or holds no
            ``.txt`` files. Nothing is written, and an older ``out`` stays.
    """
    tables = []
    for feed in ALL_FEEDS:
        directory = feed_dir(feed, root)
        if not directory.is_dir():
            raise FileNotFoundError(f"no {feed} feed at {directory}")
        found = sorted(path for path in directory.glob("*.txt") if path.is_file())
        if not found:
            raise FileNotFoundError(f"no .txt tables in {directory}")
        tables.extend((f"{feed}/{path.name}", path) for path in found)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, path in tables:
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _FILE_MODE << 16
            with path.open("rb") as source, archive.open(info, "w") as target:
                shutil.copyfileobj(source, target)
    write_bytes_atomic(buffer.getvalue(), out)
    return [name for name, _ in tables]
