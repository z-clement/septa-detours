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

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

STORE_DIR = "alerts"
"""The directory on the ``snapshots`` branch that holds the snapshots."""

_SNAPSHOT_NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z\.json")
"""``ingest/alerts.py``'s names, e.g. ``2026-11-27T134432Z.json``."""


BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
"""The author GitHub uses for workflow commits: the job, not the maintainer."""


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


def commit_snapshot(
    snapshot: Path, parent: str | None, repo: Path = Path()
) -> str | None:
    """Commit ``snapshot`` on top of ``parent``; return the commit id, or None.

    ``parent`` is the ``snapshots`` branch tip (a commit id or ref), or
    None on the first run, which makes a root commit (an orphan branch).
    The commit adds ``alerts/<name>`` to the parent's files; no branch is
    moved and nothing is pushed (the caller pushes the returned id).

    None, and no commit, when nothing would change: the bytes equal the
    newest stored snapshot's, or the same name and bytes are already
    stored. The same bytes as an *older* snapshot are stored (the feed
    went back to an earlier state).

    Never touches ``repo``'s checkout or index: the commit is built in a
    temporary index. Never downloads old snapshots: their contents aren't
    needed (``write-tree --missing-ok``), and ``GIT_NO_LAZY_FETCH`` makes
    git fail rather than quietly fetch them in a partial clone. Unlike
    ``git commit``, ``commit-tree`` never signs (it ignores
    ``commit.gpgSign``), so a signing setup can't make it fail.

    Raises:
        ValueError: ``snapshot`` isn't named ``<stamp>.json``, or a
            different snapshot with its name is already stored.
        subprocess.CalledProcessError: A git command failed.
    """
    name = snapshot.name
    if not _SNAPSHOT_NAME.fullmatch(name):
        msg = f"not an alerts snapshot name: {name!r}"
        raise ValueError(msg)
    path = f"{STORE_DIR}/{name}"
    blob = _git(repo, "hash-object", "--", str(snapshot))

    if parent is not None:
        listing = _git(repo, "ls-tree", "-z", parent, "--", f"{STORE_DIR}/")
        newest = newest_stored(listing)
        if newest is not None and newest.blob == blob:
            return None
        same_name = _git(repo, "ls-tree", "-z", parent, "--", path)
        if same_name and newest_stored(same_name) != StoredSnapshot(name, blob):
            msg = f"{path} is already stored with different bytes"
            raise ValueError(msg)

    _git(repo, "hash-object", "-w", "--", str(snapshot))
    with tempfile.TemporaryDirectory() as scratch:
        index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        if parent is not None:
            _git(repo, "read-tree", parent, env=index)
        _git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{blob},{path}",
            env=index,
        )
        tree = _git(repo, "write-tree", "--missing-ok", env=index)

    if parent is not None and tree == _git(repo, "rev-parse", f"{parent}^{{tree}}"):
        return None
    parents = [] if parent is None else ["-p", parent]
    bot = {
        "GIT_AUTHOR_NAME": BOT_NAME,
        "GIT_AUTHOR_EMAIL": BOT_EMAIL,
        "GIT_COMMITTER_NAME": BOT_NAME,
        "GIT_COMMITTER_EMAIL": BOT_EMAIL,
    }
    message = f"{STORE_DIR}: {name.removesuffix('.json')}"
    return _git(repo, "commit-tree", tree, *parents, "-m", message, env=bot)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run ``git -C repo <args>``; return stdout without its final newline.

    Every call sets ``GIT_NO_LAZY_FETCH=1`` (see ``commit_snapshot``).

    Raises:
        subprocess.CalledProcessError: git exited non-zero (stderr kept).
    """
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", **(env or {})},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.removesuffix("\n")
