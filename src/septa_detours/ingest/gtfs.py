"""Fetch SEPTA's static GTFS from its GitHub releases.

SEPTA publishes each feed as a release of ``septadev/GTFS``: tag
``v<YYYYMMDD><n>`` (the date service starts, then a revision number,
e.g. ``v202611220``), one asset ``gtfs_public.zip``, which holds
``google_bus.zip`` and ``google_rail.zip``. Releases appear 2-6 days
*before* their start date (``v202611220`` on 2026-11-18), and revisions
sometimes after it, so GitHub's "latest" release isn't the feed in
effect. :func:`pick_release` chooses the one that is.

Reading the release list is about *what* to download, not interpreting
data: the zip itself is saved untouched, as ingest always does.
"""

import re
from collections.abc import Sequence
from datetime import date
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, TypeAdapter

GTFS_ASSET = "gtfs_public.zip"

_TAG = re.compile(r"v([0-9]{4})([0-9]{2})([0-9]{2})([0-9]+)")
"""``v`` + service start date + revision; ASCII digits only."""


class _GitHubModel(BaseModel):
    """Only the fields we read; GitHub's many others are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)


class ReleaseAsset(_GitHubModel):
    """One file attached to a release."""

    name: str
    browser_download_url: str


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
        url = next(
            (a.browser_download_url for a in release.assets if a.name == GTFS_ASSET),
            None,
        )
        match = _TAG.fullmatch(release.tag_name)
        if url is None or match is None:
            continue
        year, month, day, revision = (int(part) for part in match.groups())
        try:
            start = date(year, month, day)
        except ValueError:
            continue
        if start <= today:
            candidates.append(GtfsRelease(release.tag_name, start, revision, url))
    if not candidates:
        msg = (
            f"no GTFS release in effect on {today.isoformat()} "
            f"among {len(releases)} releases"
        )
        raise ValueError(msg)
    return max(candidates, key=lambda r: (r.service_start, r.revision))
