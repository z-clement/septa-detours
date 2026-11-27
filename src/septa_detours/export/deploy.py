"""Build the site to publish: ``web/`` with versioned code URLs.

Hosting plan step 2b (``docs/hosting-plan.md``). GitHub Pages caches every
file for 10 minutes and can't be told otherwise, so a returning visitor
could run old page code against new data. The published copy moves
``js/`` and ``css/`` into folders named after their contents
(``js-<version>/``) and points ``index.html`` at them. The modules import
each other by relative path, so a page loads every module from one
folder: old and new code never mix. (Data files are versioned by the
page itself: ``web/js/data.js``, ``versioned``.)

The version is a hash of the code, not the commit: the job republishes
every 15 minutes from the same code, and a commit that only touches docs
changes nothing a browser runs, so cached code stays valid until the
code itself changes.
"""

import hashlib
import re
from collections.abc import Mapping

ASSET_DIRS = ("js", "css")
"""The page's code folders, renamed to ``<dir>-<version>`` when published."""

VERSION_LENGTH = 10
"""Hex digits kept from the hash (40 bits: collisions don't matter here,
since a new version only has to differ from the few before it)."""

_ASSET_REF = re.compile(r'(?<![\w-])(?P<attr>src|href)="(?:\./)?(?P<dir>js|css)/')
"""An ``index.html`` reference into a code folder: ``src="js/main.js"``,
``href="./css/app.css"``. Absolute URLs (the MapLibre CDN) and other
attributes ending in ``src`` (``data-src``) don't match."""


def asset_version(files: Mapping[str, bytes]) -> str:
    """A short hash of the page's code: every file's path and bytes.

    Args:
        files: Path relative to ``web/`` (``"js/main.js"``) -> contents.

    Order doesn't matter (paths are sorted). Each path and each file's
    bytes go in after their length, so no two different sets of files
    give the same stream to hash: moving bytes between files, or
    renaming one, changes the version.
    """
    digest = hashlib.sha256()
    for path in sorted(files):
        for part in (path.encode(), files[path]):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()[:VERSION_LENGTH]


def versioned_index(html: str, version: str) -> str:
    """``index.html`` pointed at the versioned code folders.

    ``src="js/main.js"`` -> ``src="js-<version>/main.js"``, and the same
    for ``css/`` (a leading ``./`` is dropped).

    Raises:
        ValueError: ``html`` never references one of ``ASSET_DIRS``: the
            page has changed how it loads its code, and publishing would
            leave a reference to a folder that no longer exists.
    """
    found = {match["dir"] for match in _ASSET_REF.finditer(html)}
    missing = [name for name in ASSET_DIRS if name not in found]
    if missing:
        names = ", ".join(f"{name}/" for name in missing)
        msg = f"index.html never references {names}; can't version its code"
        raise ValueError(msg)
    return _ASSET_REF.sub(
        lambda match: f'{match["attr"]}="{match["dir"]}-{version}/', html
    )
