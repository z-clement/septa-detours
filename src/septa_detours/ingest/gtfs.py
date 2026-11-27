"""Fetch SEPTA's static GTFS from its GitHub releases.

SEPTA publishes each feed as a release of ``septadev/GTFS``: tag
``v<YYYYMMDD><n>`` (the date service starts, then a revision number,
e.g. ``v202611220``), one asset ``gtfs_public.zip``, which holds
``google_bus.zip`` and ``google_rail.zip``. Releases appear 2-6 days
*before* their start date (``v202611220`` on 2026-11-18), and revisions
sometimes after it, so GitHub's "latest" release isn't the feed in
effect. :func:`pick_release` chooses the one that is.

Reading the release list is about *what* to download, not interpreting
data: the zip itself is saved untouched, as ingest always does, to
``data/raw/gtfs/gtfs_public-<tag>.zip``.
"""

import hashlib
import re
from collections.abc import Iterable, Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import NamedTuple

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter

from septa_detours.io import write_chunks_atomic

RELEASES_URL = "https://api.github.com/repos/septadev/GTFS/releases"

GTFS_ASSET = "gtfs_public.zip"

# The path assumes you run from the repo root (data/raw/ is gitignored).
DEFAULT_GTFS_DIR = Path("data/raw/gtfs")

_RELEASES_PER_PAGE = 30
"""Newest first; the feed in effect is among the newest few."""

_SHA256_DIGEST = re.compile(r"sha256:([0-9a-f]{64})")

_TAG = re.compile(r"v([0-9]{4})([0-9]{2})([0-9]{2})([0-9]+)")
"""``v`` + service start date + revision; ASCII digits only."""


class _GitHubModel(BaseModel):
    """Only the fields we read; GitHub's many others are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)


class ReleaseAsset(_GitHubModel):
    """One file attached to a release."""

    name: str
    browser_download_url: str
    size: int
    digest: str | None = None
    """``sha256:<hex>``, computed by GitHub (absent on old assets)."""


class Release(_GitHubModel):
    """One entry of GitHub's release list, verbatim."""

    tag_name: str
    draft: bool
    prerelease: bool
    assets: tuple[ReleaseAsset, ...]


_RELEASES = TypeAdapter(list[Release])


def parse_releases(content: bytes) -> list[Release]:
    """Validate GitHub's release-list JSON (``/repos/<o>/<r>/releases``).

    Raises:
        pydantic.ValidationError: Not JSON, not a list, or an entry
            missing a declared field or with the wrong type: GitHub's API
            changed, and that should be loud. An empty list is valid here
            (:func:`pick_release` then finds nothing).
    """
    return _RELEASES.validate_json(content)


class GtfsRelease(NamedTuple):
    """The release chosen to download."""

    tag: str
    service_start: date
    revision: int
    url: str
    size: int
    sha256: str | None
    """Hex, from the asset's ``digest``; None if absent or not SHA-256."""


def pick_release(releases: Sequence[Release], today: date) -> GtfsRelease:
    """The newest release in effect on ``today``: SEPTA's current feed.

    Candidates: not a draft or pre-release, a ``gtfs_public.zip`` asset,
    and a tag that is exactly ``v<YYYYMMDD><n>`` with a real date. Of
    those whose date is on or before ``today`` (the start day counts),
    the largest ``(date, revision)`` wins; revisions compare as numbers.
    List order doesn't matter. Anything else is skipped, not guessed at.

    ``today`` should be SEPTA's local date (New York), so the switch
    happens when the new service starts, not at UTC midnight.

    Raises:
        ValueError: No release qualifies (e.g. SEPTA renamed its tags).
    """
    candidates = []
    for release in releases:
        if release.draft or release.prerelease:
            continue
        asset = next((a for a in release.assets if a.name == GTFS_ASSET), None)
        match = _TAG.fullmatch(release.tag_name)
        if asset is None or match is None:
            continue
        year, month, day, revision = (int(part) for part in match.groups())
        try:
            start = date(year, month, day)
        except ValueError:
            continue
        if start <= today:
            digest = _SHA256_DIGEST.fullmatch(asset.digest or "")
            candidates.append(
                GtfsRelease(
                    release.tag_name,
                    start,
                    revision,
                    asset.browser_download_url,
                    asset.size,
                    digest.group(1) if digest else None,
                )
            )
    if not candidates:
        msg = (
            f"no GTFS release in effect on {today.isoformat()} "
            f"among {len(releases)} releases"
        )
        raise ValueError(msg)
    return max(candidates, key=lambda r: (r.service_start, r.revision))


def fetch_releases(client: httpx.Client, token: str | None = None) -> list[Release]:
    """GET SEPTA's newest GTFS releases from GitHub's API.

    ``token`` (e.g. Actions' ``GITHUB_TOKEN``) is optional: without one
    GitHub allows 60 API requests an hour per address, which runners
    share. It's sent with this request only, never with a download.

    Raises:
        httpx.HTTPError: Network failure, timeout, or non-2xx status.
        pydantic.ValidationError: The response isn't the expected list.
    """
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.get(
        RELEASES_URL, params={"per_page": _RELEASES_PER_PAGE}, headers=headers
    )
    response.raise_for_status()
    return parse_releases(response.content)


def raw_gtfs_path(tag: str, root: Path = DEFAULT_GTFS_DIR) -> Path:
    """Where a release's zip is saved: ``root/gtfs_public-<tag>.zip``."""
    return root / f"gtfs_public-{tag}.zip"


def fetch_gtfs(
    client: httpx.Client,
    today: date,
    root: Path = DEFAULT_GTFS_DIR,
    token: str | None = None,
) -> tuple[GtfsRelease, Path, bool]:
    """Save the GTFS release in effect on ``today``; skip it if already saved.

    Returns the release, its path, and whether it was downloaded now
    (False: the file was already there and checks out, e.g. restored from
    the job's cache). An existing file that fails the check is downloaded
    again. The download is checked against the API's size and SHA-256
    (when given) as it streams; a mismatch leaves no file behind (and an
    older one untouched).

    Raises:
        httpx.HTTPError: Network failure, timeout, or non-2xx status.
        pydantic.ValidationError: From :func:`fetch_releases`.
        ValueError: No release in effect, or the download doesn't match.
    """
    release = pick_release(fetch_releases(client, token), today)
    path = raw_gtfs_path(release.tag, root)
    if path.is_file() and _matches(path, release):
        return release, path, False
    with client.stream("GET", release.url) as response:
        response.raise_for_status()
        write_chunks_atomic(_verified_chunks(response.iter_bytes(), release), path)
    return release, path, True


def _matches(path: Path, release: GtfsRelease) -> bool:
    """Whether the file at ``path`` has the release's size and SHA-256."""
    with path.open("rb") as file:
        chunks = iter(lambda: file.read(1 << 20), b"")
        try:
            for _ in _verified_chunks(chunks, release):
                pass
        except ValueError:
            return False
    return True


def _verified_chunks(chunks: Iterable[bytes], release: GtfsRelease) -> Iterator[bytes]:
    """Yield ``chunks`` unchanged; after the last, raise if size or hash differ.

    Raising after the last chunk is what lets ``write_chunks_atomic``
    discard the temp file instead of replacing the target.

    Raises:
        ValueError: Wrong size, or wrong SHA-256 (when the release has one).
    """
    size = 0
    digest = hashlib.sha256()
    for chunk in chunks:
        size += len(chunk)
        digest.update(chunk)
        yield chunk
    if size != release.size:
        msg = f"{release.tag}: expected {release.size} bytes, got {size}"
        raise ValueError(msg)
    if release.sha256 is not None and digest.hexdigest() != release.sha256:
        msg = (
            f"{release.tag}: SHA-256 mismatch: expected {release.sha256}, "
            f"got {digest.hexdigest()}"
        )
        raise ValueError(msg)
