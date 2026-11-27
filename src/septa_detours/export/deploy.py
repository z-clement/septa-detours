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
import shutil
from collections.abc import Mapping
from pathlib import Path

ASSET_DIRS = ("js", "css")
"""The page's code folders, renamed to ``<dir>-<version>`` when published."""

VERSION_LENGTH = 10
"""Hex digits kept from the hash (40 bits: collisions don't matter here,
since a new version only has to differ from the few before it)."""

NOT_PUBLISHED = frozenset({"test"})
"""Top-level ``web/`` entries left out of the published copy (node tests)."""

INDEX = "index.html"

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


def build_site(web: Path, out: Path) -> str:
    """Copy ``web/`` to ``out`` as it's published; return the code version.

    ``js/`` and ``css/`` land in ``js-<version>/`` and ``css-<version>/``,
    ``index.html`` points at them (``versioned_index``), ``test/`` is left
    out, and everything else (``data/``) is copied as is.

    Raises:
        FileExistsError: ``out`` exists and isn't an empty folder: a stale
            file there would be published too.
        FileNotFoundError: ``web`` has no ``data/status.json`` (the page
            would load without data), no ``index.html``, or no ``js/`` or
            ``css/`` folder (the page would load nothing).
        ValueError: ``index.html`` doesn't load its code from ``js/`` and
            ``css/`` (``versioned_index``).
    """
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        msg = f"{out} already exists and isn't empty; publish into a new folder"
        raise FileExistsError(msg)
    if not (web / "data" / "status.json").is_file():
        msg = (
            f"no {web / 'data' / 'status.json'}; make the data first: "
            "uv run python -m septa_detours.export site"
        )
        raise FileNotFoundError(msg)
    for name in ASSET_DIRS:
        if not (web / name).is_dir():
            raise FileNotFoundError(f"no {web / name} folder: the page's code")
    # Bytes, not read_text: universal newlines would rewrite any "\r\n".
    html = (web / INDEX).read_bytes().decode("utf-8")

    code = {
        path.relative_to(web).as_posix(): path.read_bytes()
        for name in ASSET_DIRS
        for path in sorted((web / name).rglob("*"))
        if path.is_file()
    }
    version = asset_version(code)
    index = versioned_index(html, version)

    out.mkdir(parents=True, exist_ok=True)
    for entry in sorted(web.iterdir()):
        if entry.name in NOT_PUBLISHED or entry.name == INDEX:
            continue
        target = out / entry.name
        if entry.name in ASSET_DIRS:
            target = out / f"{entry.name}-{version}"
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)
    (out / INDEX).write_bytes(index.encode("utf-8"))
    return version
