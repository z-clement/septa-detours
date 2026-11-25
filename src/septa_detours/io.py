"""Shared file-writing helpers (not a pipeline stage).

Like ``gtfs/``, this is a utility every stage may import; it knows nothing
about detours, GTFS, or GeoJSON. It works on ``bytes`` so callers decide
the encoding: ``ingest/`` saves response bytes exactly as received, while
``export/`` encodes its own text first.
"""

from pathlib import Path


def write_bytes_atomic(content: bytes, path: Path) -> None:
    """Write ``content`` to ``path``, replacing any old file atomically.

    Readers (a browser reloading the map, a parser reading a snapshot) see
    either the old complete file or the new complete one, never a
    truncated one, even if the process crashes or is interrupted mid-write.

    How:
        1. **Create the parent directory** (``parents=True, exist_ok=True``),
           so a fresh clone doesn't fail on a missing ``data/raw/`` or
           ``web/data/``.
        2. **Write ``<name>.tmp`` beside the target**, then ``Path.replace``
           it over the target. A rename within one directory is atomic. The
           temp file must be in the *same* directory: a rename across
           filesystems isn't atomic (``/tmp`` may be a different one).
        3. **Clean up on any failure**, including ``KeyboardInterrupt``
           (hence ``BaseException``), so no stray ``.tmp`` is left behind.

    Known limit: the temp name is fixed, so two processes writing the same
    ``path`` at once would share a temp file. Nothing in the project does
    that today; switch to ``tempfile.NamedTemporaryFile(dir=...)`` if it
    ever does.

    Args:
        content: The exact bytes to store.
        path: Destination file.

    Raises:
        OSError: If the directory or file can't be written (including when
            ``path`` is an existing directory).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_bytes(content)
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
