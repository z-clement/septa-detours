"""Tests for ``ingest/gtfs.py`` (choosing SEPTA's GTFS release).

``REAL`` is SEPTA's real release list (12 newest, 2026-11-27, trimmed;
``tests/fixtures/gtfs/``). It has both cases that matter: a release
published before its start date (``v202611220``: 11-18 for 11-22) and
same-date revisions (``v202609270`` / ``v202609271``).
"""

import json
from datetime import date
from pathlib import Path

import pydantic
import pytest

from septa_detours.ingest.gtfs import (
    GtfsRelease,
    Release,
    parse_releases,
    pick_release,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gtfs" / "releases-2026-11-27.json"
REAL = parse_releases(FIXTURE.read_bytes())
DOWNLOAD = "https://github.com/septadev/GTFS/releases/download"


def release(
    tag: str,
    *,
    draft: bool = False,
    prerelease: bool = False,
    asset: str = "gtfs_public.zip",
) -> Release:
    return Release(
        tag_name=tag,
        draft=draft,
        prerelease=prerelease,
        assets=({"name": asset, "browser_download_url": f"{DOWNLOAD}/{tag}/{asset}"},),
    )


def expected(tag: str, start: date, revision: int) -> GtfsRelease:
    return GtfsRelease(tag, start, revision, f"{DOWNLOAD}/{tag}/gtfs_public.zip")


def test_real_list_parses_in_api_order() -> None:
    assert len(REAL) == 12
    assert [r.tag_name for r in REAL[:3]] == ["v202611220", "v202611010", "v202609271"]
    assert REAL[0].assets[0].name == "gtfs_public.zip"


def test_today_gets_the_current_feed() -> None:
    assert pick_release(REAL, date(2026, 11, 27)) == expected(
        "v202611220", date(2026, 11, 22), 0
    )


def test_a_feed_published_early_waits_for_its_start_day() -> None:
    # v202611220 was published 11-18; until 11-22 the old feed runs.
    assert pick_release(REAL, date(2026, 11, 21)) == expected(
        "v202611010", date(2026, 11, 1), 0
    )
    assert pick_release(REAL, date(2026, 11, 22)) == expected(
        "v202611220", date(2026, 11, 22), 0
    )


# On a date tie, max() keeps the first candidate: each order is tried so
# the revision, not the list order, decides.
@pytest.mark.parametrize("reverse", [False, True])
def test_the_newest_revision_of_a_date_wins(reverse: bool) -> None:
    releases = list(reversed(REAL)) if reverse else REAL
    assert pick_release(releases, date(2026, 10, 1)) == expected(
        "v202609271", date(2026, 9, 27), 1
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_revisions_compare_as_numbers(reverse: bool) -> None:
    releases = [release("v2026112210"), release("v202611229")]
    if reverse:
        releases.reverse()
    assert pick_release(releases, date(2026, 11, 27)) == expected(
        "v2026112210", date(2026, 11, 22), 10
    )


def test_list_order_does_not_matter() -> None:
    assert pick_release(list(reversed(REAL)), date(2026, 11, 27)).tag == "v202611220"


def test_nothing_in_effect_yet_is_an_error() -> None:
    with pytest.raises(
        ValueError, match="no GTFS release in effect on 2026-07-01 among 12 releases"
    ):
        pick_release(REAL, date(2026, 7, 1))


def test_empty_list_is_an_error() -> None:
    with pytest.raises(ValueError, match="among 0 releases"):
        pick_release([], date(2026, 11, 27))


@pytest.mark.parametrize(
    "newer",
    [
        release("v202611250", draft=True),
        release("v202611250", prerelease=True),
        release("v202611250", asset="gtfs_public.tar.gz"),
        release("v20261125"),  # no revision
        release("v2026-11-250"),
        release("202611250"),
        release("v202611250-test"),
        release("v202611310"),  # Nov 31
        release("v\u0662\u0660\u0662\u0666\u0661\u0661\u0662\u06650"),  # Arabic-Indic
    ],
)
def test_releases_we_cannot_trust_are_skipped(newer: Release) -> None:
    assert pick_release([newer, *REAL], date(2026, 11, 27)).tag == "v202611220"


def test_a_release_without_assets_is_skipped() -> None:
    bare = Release(tag_name="v202611250", draft=False, prerelease=False, assets=())
    assert pick_release([bare, *REAL], date(2026, 11, 27)).tag == "v202611220"


def test_changed_api_shape_is_loud() -> None:
    changed = json.loads(FIXTURE.read_bytes())
    del changed[0]["assets"]
    with pytest.raises(pydantic.ValidationError):
        parse_releases(json.dumps(changed).encode())


def test_wrong_types_are_loud() -> None:
    changed = json.loads(FIXTURE.read_bytes())
    changed[0]["draft"] = "false"
    with pytest.raises(pydantic.ValidationError):
        parse_releases(json.dumps(changed).encode())


def test_unknown_fields_are_ignored() -> None:
    changed = json.loads(FIXTURE.read_bytes())
    changed[0]["body"] = "Release notes"
    assert parse_releases(json.dumps(changed).encode()) == REAL
