"""Keep every changed alerts snapshot on the repo's ``snapshots`` branch.

The hosted job's disk is thrown away after each run, so snapshots are
kept in git: an orphan branch (no history shared with ``main``) holding
``alerts/<stamp>.json``, byte-for-byte as ingested. A snapshot is
committed only when its bytes differ from the newest one stored, so a
quiet feed adds nothing.

The branch is never checked out: it gains a file on most runs (~16 MB a
day), and a checkout would write every snapshot ever stored. Git's own
object ids do the comparing instead, since a blob id is a hash of the
file's bytes: equal ids mean equal bytes, without downloading the old
file.
"""

import re
from typing import NamedTuple

STORE_DIR = "alerts"
"""The directory on the ``snapshots`` branch that holds the snapshots."""

_SNAPSHOT_NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z\.json")
"""``ingest/alerts.py``'s names, e.g. ``2026-11-27T134432Z.json``."""


class StoredSnapshot(NamedTuple):
    """One snapshot on the branch: its file name and git blob id."""

    name: str
    blob: str


def newest_stored(ls_tree: str) -> StoredSnapshot | None:
    """The newest snapshot in ``git ls-tree -z <ref> -- alerts/`` output.

    Entries are ``<mode> <type> <id>``, a tab, then the path; each
    ends in NUL.
    Fixed-width UTC stamps sort in time order, so the largest name is the
    newest. Only files (``blob``) named exactly ``<stamp>.json`` count: a
    README would otherwise sort after every stamp, and a subdirectory
    (``tree``) isn't a snapshot. None if there's no snapshot at all (the
    branch's first run).
    """
    stored = []
    for entry in ls_tree.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        _mode, kind, blob = meta.split(" ")
        directory, _, name = path.partition("/")
        if kind == "blob" and directory == STORE_DIR and _SNAPSHOT_NAME.fullmatch(name):
            stored.append(StoredSnapshot(name, blob))
    return max(stored, key=lambda snapshot: snapshot.name, default=None)
