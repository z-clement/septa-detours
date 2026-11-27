"""Tests for ``ingest/gtfs.py`` (choosing SEPTA's GTFS release).

``REAL`` is SEPTA's real release list (12 newest, 2026-11-27, trimmed;
``tests/fixtures/gtfs/``). It has both cases that matter: a release
published before its start date (``v202611220``: 11-18 for 11-22) and
same-date revisions (``v202609270`` / ``v202609271``).

Fetching runs against a fake GitHub behind ``httpx.MockTransport``: a
release list (one future release, the one in effect, an older one) and
downloads that redirect to another host, as GitHub's do.
"""

import hashlib
import json
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path

import httpx
import pydantic
import pytest

from septa_detours.ingest import __main__ as ingest_main
from septa_detours.ingest.gtfs import (
    RELEASES_URL,
    GtfsRelease,
    Release,
    fetch_gtfs,
    parse_releases,
    pick_release,
    raw_gtfs_path,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gtfs" / "releases-2026-11-27.json"
REAL = parse_releases(FIXTURE.read_bytes())
DOWNLOAD = "https://github.com/septadev/GTFS/releases/download"
# Each real tag's zip size and SHA-256 hex, straight from the fixture.
REAL_ASSETS = {
    r["tag_name"]: (r["assets"][0]["size"], r["assets"][0]["digest"][len("sha256:") :])
    for r in json.loads(FIXTURE.read_bytes())
}
SYNTHETIC_SIZE = 1234


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
        assets=(
            {
                "name": asset,
                "browser_download_url": f"{DOWNLOAD}/{tag}/{asset}",
                "size": SYNTHETIC_SIZE,
            },
        ),
    )


def expected(tag: str, start: date, revision: int) -> GtfsRelease:
    """The release ``pick_release`` should return (real or synthetic tag)."""
    size, sha256 = REAL_ASSETS.get(tag, (SYNTHETIC_SIZE, None))
    url = f"{DOWNLOAD}/{tag}/gtfs_public.zip"
    return GtfsRelease(tag, start, revision, url, size, sha256)


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


@pytest.mark.parametrize(
    "digest",
    [
        None,
        "sha256:" + "ab" * 32 + "0",  # one digit too many
        "sha512:" + "ab" * 64,
        "SHA256:" + "ab" * 32,
        "sha256:" + "AB" * 32,
    ],
)
def test_only_a_well_formed_sha256_digest_is_used(digest: str | None) -> None:
    unusual = Release(
        tag_name="v202611250",
        draft=False,
        prerelease=False,
        assets=(
            {
                "name": "gtfs_public.zip",
                "browser_download_url": f"{DOWNLOAD}/v202611250/gtfs_public.zip",
                "size": SYNTHETIC_SIZE,
                "digest": digest,
            },
        ),
    )
    picked = pick_release([unusual], date(2026, 11, 27))
    assert (picked.size, picked.sha256) == (SYNTHETIC_SIZE, None)


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


# A fake GitHub. The zip's bytes don't matter to ingest (saved untouched).
ZIP = b"PK\x03\x04" + b"google_bus.zip google_rail.zip" * 40
TODAY = date(2026, 11, 27)
OBJECTS = "https://objects.githubusercontent.com/github-production-release-asset"


def api_release(tag: str, content: bytes, *, digest: bool = True) -> dict:
    asset = {
        "name": "gtfs_public.zip",
        "browser_download_url": f"{DOWNLOAD}/{tag}/gtfs_public.zip",
        "size": len(content),
        "digest": f"sha256:{hashlib.sha256(content).hexdigest()}" if digest else None,
        "content_type": "application/zip",
    }
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": [asset]}


class FakeGitHub:
    """Serves the release list and redirected downloads; records requests.

    Lists a future release, ``v202611220`` (in effect on ``TODAY``) and
    ``v202611010``. Each download redirects to another host, which serves
    that release's bytes: ``served`` for ``v202611220`` (which may differ
    from what the list promises, ``ZIP``), else what was listed.
    """

    def __init__(
        self,
        served: bytes = ZIP,
        *,
        digest: bool = True,
        api_status: int = 200,
        download_status: int = 200,
    ) -> None:
        self.contents = {
            "v202612060": b"future feed",
            "v202611220": ZIP,
            "v202611010": b"older feed, " * 30,
        }
        self.releases = [
            api_release(tag, content, digest=digest or tag != "v202611220")
            for tag, content in self.contents.items()
        ]
        self.contents["v202611220"] = served
        self.api_status = api_status
        self.download_status = download_status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(RELEASES_URL):
            return httpx.Response(self.api_status, json=self.releases)
        for tag, content in self.contents.items():
            if url == f"{DOWNLOAD}/{tag}/gtfs_public.zip":
                return httpx.Response(302, headers={"Location": f"{OBJECTS}/{tag}"})
            if url == f"{OBJECTS}/{tag}":
                return httpx.Response(self.download_status, content=content)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handler), follow_redirects=True
        )

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def test_downloads_the_release_in_effect_untouched(tmp_path: Path) -> None:
    github = FakeGitHub()
    with github.client() as client:
        release, path, downloaded = fetch_gtfs(client, TODAY, tmp_path / "gtfs")
    assert (release.tag, downloaded) == ("v202611220", True)
    assert path == tmp_path / "gtfs" / "gtfs_public-v202611220.zip"
    assert path.read_bytes() == ZIP
    assert github.urls() == [
        f"{RELEASES_URL}?per_page=30",
        f"{DOWNLOAD}/v202611220/gtfs_public.zip",
        f"{OBJECTS}/v202611220",
    ]
    assert github.requests[0].headers["Accept"] == "application/vnd.github+json"


def test_token_goes_to_the_api_only(tmp_path: Path) -> None:
    github = FakeGitHub()
    with github.client() as client:
        fetch_gtfs(client, TODAY, tmp_path, token="ghs_secret")
    auth = [r.headers.get("Authorization") for r in github.requests]
    assert auth == ["Bearer ghs_secret", None, None]


def test_no_token_no_authorization(tmp_path: Path) -> None:
    github = FakeGitHub()
    with github.client() as client:
        fetch_gtfs(client, TODAY, tmp_path)
    assert all("Authorization" not in r.headers for r in github.requests)


def test_a_saved_copy_that_checks_out_is_not_downloaded_again(tmp_path: Path) -> None:
    raw_gtfs_path("v202611220", tmp_path).write_bytes(ZIP)
    github = FakeGitHub()
    with github.client() as client:
        release, path, downloaded = fetch_gtfs(client, TODAY, tmp_path)
    assert (release.tag, downloaded) == ("v202611220", False)
    assert github.urls() == [f"{RELEASES_URL}?per_page=30"]
    assert path.read_bytes() == ZIP


@pytest.mark.parametrize(
    "saved", [ZIP[:-1], ZIP[:-1] + b"X"], ids=["truncated", "same-size-corrupt"]
)
def test_a_saved_copy_that_fails_the_check_is_replaced(
    tmp_path: Path, saved: bytes
) -> None:
    raw_gtfs_path("v202611220", tmp_path).write_bytes(saved)
    github = FakeGitHub()
    with github.client() as client:
        _, path, downloaded = fetch_gtfs(client, TODAY, tmp_path)
    assert downloaded is True
    assert path.read_bytes() == ZIP


@pytest.mark.parametrize(
    ("served", "message"),
    [
        (ZIP[:-1], f"v202611220: expected {len(ZIP)} bytes, got {len(ZIP) - 1}"),
        (ZIP[:-1] + b"X", "v202611220: SHA-256 mismatch: expected "),
    ],
    ids=["truncated", "same-size-corrupt"],
)
def test_a_bad_download_leaves_no_file(
    tmp_path: Path, served: bytes, message: str
) -> None:
    older = raw_gtfs_path("v202611010", tmp_path)
    older.write_bytes(b"older feed")
    github = FakeGitHub(served)
    with github.client() as client, pytest.raises(ValueError, match=message):
        fetch_gtfs(client, TODAY, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gtfs_public-v202611010.zip"]
    assert older.read_bytes() == b"older feed"


def test_without_a_digest_only_the_size_is_checked(tmp_path: Path) -> None:
    other = ZIP[:-1] + b"X"
    github = FakeGitHub(other, digest=False)
    with github.client() as client:
        _, path, _ = fetch_gtfs(client, TODAY, tmp_path)
    assert path.read_bytes() == other


def test_api_error_writes_nothing(tmp_path: Path) -> None:
    github = FakeGitHub(api_status=403)  # e.g. the rate limit
    with github.client() as client, pytest.raises(httpx.HTTPStatusError):
        fetch_gtfs(client, TODAY, tmp_path / "gtfs")
    assert not (tmp_path / "gtfs").exists()
    assert len(github.requests) == 1


def test_download_error_writes_nothing(tmp_path: Path) -> None:
    github = FakeGitHub(download_status=503)
    with github.client() as client, pytest.raises(httpx.HTTPStatusError):
        fetch_gtfs(client, TODAY, tmp_path / "gtfs")
    assert not (tmp_path / "gtfs").exists()


def test_main_gtfs_reports_wrote_then_have(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_from_env")
    monkeypatch.setattr(ingest_main, "_new_york_today", lambda: TODAY)
    github = FakeGitHub()
    monkeypatch.setattr(ingest_main, "make_client", github.client)
    assert ingest_main.main(["gtfs"]) == 0
    assert ingest_main.main(["gtfs"]) == 0
    assert capsys.readouterr().out == (
        "wrote data/raw/gtfs/gtfs_public-v202611220.zip "
        "(v202611220, in effect since 2026-11-22)\n"
        "have data/raw/gtfs/gtfs_public-v202611220.zip "
        "(v202611220, in effect since 2026-11-22)\n"
    )
    assert github.requests[0].headers["Authorization"] == "Bearer ghs_from_env"


def test_main_gtfs_uses_the_date_it_is_given(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The day before v202611220 starts: the older feed is in effect.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(ingest_main, "_new_york_today", lambda: date(2026, 11, 21))
    github = FakeGitHub()
    monkeypatch.setattr(ingest_main, "make_client", github.client)
    assert ingest_main.main(["gtfs"]) == 0
    assert capsys.readouterr().out == (
        "wrote data/raw/gtfs/gtfs_public-v202611010.zip "
        "(v202611010, in effect since 2026-11-01)\n"
    )
    assert "Authorization" not in github.requests[0].headers


def test_main_gtfs_error_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ingest_main, "_new_york_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(ingest_main, "make_client", FakeGitHub().client)
    assert ingest_main.main(["gtfs"]) == 1
    assert capsys.readouterr().err == (
        "error: no GTFS release in effect on 2026-07-01 among 3 releases\n"
    )


def test_new_york_today_is_new_yorks_date(monkeypatch: pytest.MonkeyPatch) -> None:
    # 02:00 UTC on Nov 22 is still Nov 21 in New York (UTC-5).
    class FixedNow(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return datetime(2026, 11, 22, 2, 0, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(ingest_main, "datetime", FixedNow)
    assert ingest_main._new_york_today() == date(2026, 11, 21)
