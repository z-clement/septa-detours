"""Tests for ``septa_detours.ingest.osm`` (Geofabrik extracts)."""

import gzip
import hashlib
import re
from collections.abc import Callable, Iterator

import httpx
import pytest

from septa_detours.ingest import __main__ as ingest_main
from septa_detours.ingest.osm import (
    DEFAULT_OSM_DIR,
    GEOFABRIK_REGIONS,
    dated_extract_name,
    extract_url,
    fetch_extract,
    parse_md5_file,
)

# Real bodies of Geofabrik's .md5 files, fetched 2026-11-25. Same digest,
# different names: the -latest file and the dated file it redirects to.
DIGEST = "1ae124a257f93a0854f9efedfe7dd389"
DATED_NAME = "delaware-261124.osm.pbf"
DATED_MD5 = b"1ae124a257f93a0854f9efedfe7dd389  delaware-261124.osm.pbf\n"
LATEST_MD5 = b"1ae124a257f93a0854f9efedfe7dd389  delaware-latest.osm.pbf\n"


# --- extract_url -------------------------------------------------------------


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        (
            "delaware",
            "https://download.geofabrik.de/north-america/us/delaware-latest.osm.pbf",
        ),
        (
            "new-jersey",
            "https://download.geofabrik.de/north-america/us/new-jersey-latest.osm.pbf",
        ),
        # Not one of ours, but a valid name: the URL builder doesn't gatekeep.
        (
            "district-of-columbia",
            "https://download.geofabrik.de/north-america/us/district-of-columbia-latest.osm.pbf",
        ),
    ],
)
def test_extract_url(region, expected):
    assert extract_url(region) == expected


def test_extract_url_accepts_every_configured_region():
    urls = [extract_url(region) for region in GEOFABRIK_REGIONS]
    assert len(set(urls)) == len(GEOFABRIK_REGIONS)


@pytest.mark.parametrize(
    "region",
    [
        "",
        "Delaware",
        "new jersey",
        "new_jersey",
        "-delaware",
        "delaware-",
        "new--jersey",
        "../delaware",
        "us/delaware",
        "delaware?x=1",
        "delaware\n",
        "pennsylvania2",
    ],
)
def test_extract_url_rejects_invalid_region(region):
    with pytest.raises(ValueError, match="invalid Geofabrik region"):
        extract_url(region)


# --- dated_extract_name ------------------------------------------------------

US = "https://download.geofabrik.de/north-america/us"


@pytest.mark.parametrize(
    ("region", "final_url", "expected"),
    [
        # The real redirect targets seen on 2026-11-25.
        (
            "pennsylvania",
            f"{US}/pennsylvania/pennsylvania-261124.osm.pbf",
            "pennsylvania-261124.osm.pbf",
        ),
        (
            "new-jersey",
            f"{US}/new-jersey/new-jersey-261124.osm.pbf",
            "new-jersey-261124.osm.pbf",
        ),
        ("delaware", f"{US}/delaware/delaware-261124.osm.pbf", DATED_NAME),
        # Calendar edge cases that are real dates.
        (
            "delaware",
            f"{US}/delaware/delaware-280229.osm.pbf",
            "delaware-280229.osm.pbf",
        ),
        (
            "delaware",
            f"{US}/delaware/delaware-270101.osm.pbf",
            "delaware-270101.osm.pbf",
        ),
        (
            "delaware",
            f"{US}/delaware/delaware-261231.osm.pbf",
            "delaware-261231.osm.pbf",
        ),
    ],
)
def test_dated_extract_name(region, final_url, expected):
    assert dated_extract_name(region, final_url) == expected


@pytest.mark.parametrize(
    "final_url",
    [
        # No redirect followed: the name would lose the data date.
        f"{US}/delaware-latest.osm.pbf",
        f"{US}/delaware/delaware-latest.osm.pbf",
        # Wrong region (in the folder, the name, or both).
        f"{US}/new-jersey/new-jersey-261124.osm.pbf",
        f"{US}/delaware/new-jersey-261124.osm.pbf",
        f"{US}/new-jersey/delaware-261124.osm.pbf",
        # Wrong place.
        "https://mirror.example.org/north-america/us/delaware/delaware-261124.osm.pbf",
        "http://download.geofabrik.de/north-america/us/delaware/delaware-261124.osm.pbf",
        f"{US}/delaware-261124.osm.pbf",
        f"{US}/extra/delaware/delaware-261124.osm.pbf",
        # Extras around a good URL.
        f"{US}/delaware/delaware-261124.osm.pbf?token=1",
        f"{US}/delaware/delaware-261124.osm.pbf#x",
        f"{US}/delaware/delaware-261124.osm.pbf.md5",
        f"{US}/delaware/delaware-261124.osm.pbf/",
        f" {US}/delaware/delaware-261124.osm.pbf",
        # Wrong date shape.
        f"{US}/delaware/delaware-26112.osm.pbf",
        f"{US}/delaware/delaware-2611240.osm.pbf",
        f"{US}/delaware/delaware-20261124.osm.pbf",
        f"{US}/delaware/delaware-26-11-24.osm.pbf",
        f"{US}/delaware/delaware-\u0662\u0666\u0661\u0661\u0662\u0664.osm.pbf",
        # Regex-escape check: "." must be a literal dot.
        f"{US}/delaware/delaware-261124xosmxpbf",
        "https://downloadxgeofabrikxde/north-america/us/delaware/delaware-261124.osm.pbf",
        # Wrong extension.
        f"{US}/delaware/delaware-261124.osm.bz2",
        f"{US}/delaware/delaware-261124.shp.zip",
    ],
)
def test_dated_extract_name_rejects_unexpected_url(final_url):
    with pytest.raises(ValueError, match="did not redirect to a dated extract"):
        dated_extract_name("delaware", final_url)


@pytest.mark.parametrize(
    "stamp",
    ["261340", "261100", "260230", "270229", "260431", "000000", "261132"],
)
def test_dated_extract_name_rejects_impossible_date(stamp):
    final_url = f"{US}/delaware/delaware-{stamp}.osm.pbf"
    with pytest.raises(ValueError, match=f"impossible date '{stamp}'"):
        dated_extract_name("delaware", final_url)


@pytest.mark.parametrize("region", ["", "Delaware", "../delaware", "us/delaware"])
def test_dated_extract_name_rejects_invalid_region(region):
    """Checked before the URL, with the same message as ``extract_url``."""
    final_url = f"{US}/{region}/{region}-261124.osm.pbf"
    with pytest.raises(ValueError, match="invalid Geofabrik region"):
        dated_extract_name(region, final_url)


# --- parse_md5_file ----------------------------------------------------------


def test_parse_md5_real_dated_file():
    assert parse_md5_file(DATED_MD5, DATED_NAME) == DIGEST


def test_parse_md5_real_latest_file():
    assert parse_md5_file(LATEST_MD5, "delaware-latest.osm.pbf") == DIGEST


def test_parse_md5_final_newline_optional():
    assert parse_md5_file(DATED_MD5.rstrip(b"\n"), DATED_NAME) == DIGEST


def test_parse_md5_latest_file_does_not_match_dated_name():
    """Both files are real; using the -latest checksum for a dated file is an error."""
    with pytest.raises(ValueError, match=re.escape("is for 'delaware-latest.osm.pbf'")):
        parse_md5_file(LATEST_MD5, DATED_NAME)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\n",
        DATED_MD5.upper(),
        DIGEST.upper().encode() + b"  " + DATED_NAME.encode() + b"\n",
        DIGEST[:-1].encode() + b"  " + DATED_NAME.encode() + b"\n",
        DIGEST.encode() + b"0  " + DATED_NAME.encode() + b"\n",
        DIGEST.encode() + b" " + DATED_NAME.encode() + b"\n",
        DIGEST.encode() + b"\t" + DATED_NAME.encode() + b"\n",
        DIGEST.encode() + b"  \n",
        DIGEST.encode() + b"\n",
        b" " + DATED_MD5,
        DATED_MD5 + b"\n",
        DATED_MD5 + DATED_MD5,
        DATED_MD5.replace(b"\n", b"\r\n"),
    ],
    ids=[
        "empty",
        "blank-line",
        "all-upper",
        "upper-hex",
        "short-digest",
        "long-digest",
        "one-space",
        "tab",
        "no-name",
        "digest-only",
        "leading-space",
        "extra-blank-line",
        "two-lines",
        "crlf",
    ],
)
def test_parse_md5_rejects_malformed(content):
    """Every shape problem (CRLF and extra lines included) is reported as such."""
    with pytest.raises(ValueError, match="not one md5sum line"):
        parse_md5_file(content, DATED_NAME)


def test_parse_md5_rejects_binary_mode_marker():
    """``md5sum -b`` writes ``<digest> *<name>``; never seen from Geofabrik.

    Both forms a binary marker could take are rejected: the real one (one
    space, then ``*``) fails the line shape; two spaces then ``*`` would
    parse but name ``*delaware-...``, which isn't the expected file.
    """
    real_b = DIGEST.encode() + b" *" + DATED_NAME.encode() + b"\n"
    with pytest.raises(ValueError, match="not one md5sum line"):
        parse_md5_file(real_b, DATED_NAME)

    two_spaces = DIGEST.encode() + b"  *" + DATED_NAME.encode() + b"\n"
    with pytest.raises(
        ValueError, match=re.escape("is for '*delaware-261124.osm.pbf'")
    ):
        parse_md5_file(two_spaces, DATED_NAME)


def test_parse_md5_rejects_non_ascii():
    content = DIGEST.encode() + b"  " + "delaware-261124.osm.pbfé".encode()
    with pytest.raises(ValueError, match="not ASCII"):
        parse_md5_file(content, DATED_NAME)


def test_parse_md5_rejects_html_error_page():
    """A 200 HTML page in place of the checksum must not parse."""
    content = b"<!DOCTYPE html><html><body>Not Found</body></html>\n"
    with pytest.raises(ValueError, match="not one md5sum line"):
        parse_md5_file(content, DATED_NAME)


# --- fetch_extract -----------------------------------------------------------
#
# A fake Geofabrik behind httpx.MockTransport. Every request URL is appended
# to a shared ``log``; the download body appends "body" when it is first
# read, so tests can see whether (and when) the big download was consumed.

LATEST = f"{US}/delaware-latest.osm.pbf"
LATEST_NESTED = f"{US}/delaware/delaware-latest.osm.pbf"
DATED = f"{US}/delaware/delaware-261124.osm.pbf"
DATED_MD5_URL = f"{DATED}.md5"

# Starts like a real .pbf header; includes bytes that aren't valid UTF-8.
BODY_CHUNKS = (b"\x00\x00\x00\x0e\n\tOSMHeader", b"\xff\xfe not utf-8", b" end")
BODY = b"".join(BODY_CHUNKS)
BODY_MD5 = hashlib.md5(BODY, usedforsecurity=False).hexdigest()

HAPPY_LOG = [LATEST, LATEST_NESTED, DATED, DATED_MD5_URL, "body"]


def md5_line(digest: str, name: str = DATED_NAME) -> bytes:
    return f"{digest}  {name}\n".encode()


class LoggedBody(httpx.SyncByteStream):
    """A response body that logs "body" when read, optionally failing at the end."""

    def __init__(
        self, chunks: tuple[bytes, ...], log: list[str], error: Exception | None
    ) -> None:
        self.chunks = chunks
        self.log = log
        self.error = error

    def __iter__(self) -> Iterator[bytes]:
        self.log.append("body")
        yield from self.chunks
        if self.error is not None:
            raise self.error


Routes = dict[str, Callable[[], httpx.Response]]


def geofabrik_routes(
    log: list[str],
    *,
    chunks: tuple[bytes, ...] = BODY_CHUNKS,
    md5_body: bytes | None = None,
    error: Exception | None = None,
) -> Routes:
    """The real redirect chain seen on 2026-11-25: 301, 307, then the dated file."""
    md5_body = md5_line(BODY_MD5) if md5_body is None else md5_body
    return {
        LATEST: lambda: httpx.Response(301, headers={"location": LATEST_NESTED}),
        LATEST_NESTED: lambda: httpx.Response(307, headers={"location": DATED}),
        DATED: lambda: httpx.Response(200, stream=LoggedBody(chunks, log, error)),
        DATED_MD5_URL: lambda: httpx.Response(200, content=md5_body),
    }


def geofabrik_client(routes: Routes, log: list[str]) -> httpx.Client:
    """Serve ``routes``; anything else is a 404. Follows redirects like make_client."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        log.append(url)
        make = routes.get(url)
        return make() if make else httpx.Response(404, content=b"Not Found")

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_fetch_extract_saves_verified_body_under_dated_name(tmp_path):
    log: list[str] = []
    root = tmp_path / "data" / "raw" / "osm"
    with geofabrik_client(geofabrik_routes(log), log) as client:
        path = fetch_extract(client, "delaware", root)

    assert path == root / DATED_NAME
    assert path.read_bytes() == BODY
    assert [p.name for p in root.iterdir()] == [DATED_NAME]
    # The checksum is fetched before a single body byte is read.
    assert log == HAPPY_LOG


def test_fetch_extract_replaces_existing_file(tmp_path):
    (tmp_path / DATED_NAME).write_bytes(b"older copy of the same extract")
    log: list[str] = []
    with geofabrik_client(geofabrik_routes(log), log) as client:
        fetch_extract(client, "delaware", tmp_path)
    assert (tmp_path / DATED_NAME).read_bytes() == BODY
    assert [p.name for p in tmp_path.iterdir()] == [DATED_NAME]


def test_fetch_extract_saves_decoded_body_when_gzip_encoded(tmp_path):
    """Geofabrik's MD5 is of the .pbf file, so HTTP content-encoding is undone."""
    log: list[str] = []
    routes = geofabrik_routes(log)
    routes[DATED] = lambda: httpx.Response(
        200, content=gzip.compress(BODY), headers={"content-encoding": "gzip"}
    )
    with geofabrik_client(routes, log) as client:
        path = fetch_extract(client, "delaware", tmp_path)
    assert path.read_bytes() == BODY


class DiskCheckingBody(httpx.SyncByteStream):
    """Yields 1 MiB, then records how much of it is on disk before yielding more."""

    first = b"\x00" * 2**20

    def __init__(self, tmp_file, sizes: list[int]) -> None:
        self.tmp_file = tmp_file
        self.sizes = sizes

    def __iter__(self) -> Iterator[bytes]:
        yield self.first
        exists = self.tmp_file.exists()
        self.sizes.append(self.tmp_file.stat().st_size if exists else -1)
        yield b"rest"


def test_fetch_extract_streams_to_disk(tmp_path):
    """The first chunk is on disk before the second arrives: nothing buffers it all."""
    sizes: list[int] = []
    body = DiskCheckingBody(tmp_path / f"{DATED_NAME}.tmp", sizes)
    content = DiskCheckingBody.first + b"rest"
    digest = hashlib.md5(content, usedforsecurity=False).hexdigest()
    log: list[str] = []
    routes = geofabrik_routes(log, md5_body=md5_line(digest))
    routes[DATED] = lambda: httpx.Response(200, stream=body)
    with geofabrik_client(routes, log) as client:
        path = fetch_extract(client, "delaware", tmp_path)
    assert sizes == [len(DiskCheckingBody.first)]
    assert path.read_bytes() == content


@pytest.mark.parametrize(
    "chunks",
    [
        BODY_CHUNKS[:-1],  # truncated download
        (*BODY_CHUNKS[:-1], b" enD"),  # one byte changed
        (*BODY_CHUNKS, b"x"),  # one byte too many
        (),  # empty body
    ],
    ids=["truncated", "corrupted", "extra-byte", "empty"],
)
def test_fetch_extract_md5_mismatch_keeps_existing_file(tmp_path, chunks):
    (tmp_path / DATED_NAME).write_bytes(b"good old copy")
    log: list[str] = []
    with (
        geofabrik_client(geofabrik_routes(log, chunks=chunks), log) as client,
        pytest.raises(ValueError, match=f"MD5 mismatch for {re.escape(DATED_NAME)}"),
    ):
        fetch_extract(client, "delaware", tmp_path)

    assert (tmp_path / DATED_NAME).read_bytes() == b"good old copy"
    assert [p.name for p in tmp_path.iterdir()] == [DATED_NAME]
    assert log == HAPPY_LOG


def test_fetch_extract_connection_drop_mid_body_writes_nothing(tmp_path):
    log: list[str] = []
    root = tmp_path / "osm"
    routes = geofabrik_routes(log, error=httpx.ReadError("connection dropped"))
    with (
        geofabrik_client(routes, log) as client,
        pytest.raises(httpx.ReadError),
    ):
        fetch_extract(client, "delaware", root)
    # The directory exists (writing had started), but holds no file or temp.
    assert list(root.iterdir()) == []


# Failures before the download: the body is never read, nothing is created.


def _assert_nothing_written(root, log):
    assert "body" not in log
    assert not root.exists()


def test_fetch_extract_missing_md5_fails_before_download(tmp_path):
    log: list[str] = []
    routes = geofabrik_routes(log)
    del routes[DATED_MD5_URL]
    root = tmp_path / "osm"
    with (
        geofabrik_client(routes, log) as client,
        pytest.raises(httpx.HTTPStatusError, match="404"),
    ):
        fetch_extract(client, "delaware", root)
    assert log == HAPPY_LOG[:-1]
    _assert_nothing_written(root, log)


@pytest.mark.parametrize(
    ("md5_body", "message"),
    [
        (b"<html><body>Not Found</body></html>", "not one md5sum line"),
        (md5_line(BODY_MD5, "delaware-latest.osm.pbf"), "is for 'delaware-latest"),
        (md5_line(BODY_MD5, "delaware-261123.osm.pbf"), "is for 'delaware-261123"),
    ],
    ids=["html", "latest-name", "other-date"],
)
def test_fetch_extract_bad_md5_fails_before_download(tmp_path, md5_body, message):
    log: list[str] = []
    root = tmp_path / "osm"
    with (
        geofabrik_client(geofabrik_routes(log, md5_body=md5_body), log) as client,
        pytest.raises(ValueError, match=message),
    ):
        fetch_extract(client, "delaware", root)
    assert log == HAPPY_LOG[:-1]
    _assert_nothing_written(root, log)


@pytest.mark.parametrize("status", [404, 500, 503])
def test_fetch_extract_http_error_on_extract_skips_md5(tmp_path, status):
    log: list[str] = []
    routes = geofabrik_routes(log)
    routes[DATED] = lambda: httpx.Response(status, content=b"error page")
    root = tmp_path / "osm"
    with (
        geofabrik_client(routes, log) as client,
        pytest.raises(httpx.HTTPStatusError, match=str(status)),
    ):
        fetch_extract(client, "delaware", root)
    assert log == [LATEST, LATEST_NESTED, DATED]
    _assert_nothing_written(root, log)


def test_fetch_extract_no_redirect_to_dated_file_skips_md5(tmp_path):
    """If -latest is served directly, the data date is unknown: refuse."""
    log: list[str] = []
    routes = geofabrik_routes(log)
    routes[LATEST] = lambda: httpx.Response(
        200, stream=LoggedBody(BODY_CHUNKS, log, None)
    )
    root = tmp_path / "osm"
    with (
        geofabrik_client(routes, log) as client,
        pytest.raises(ValueError, match="did not redirect to a dated extract"),
    ):
        fetch_extract(client, "delaware", root)
    assert log == [LATEST]
    _assert_nothing_written(root, log)


def test_fetch_extract_invalid_region_makes_no_request(tmp_path):
    log: list[str] = []
    root = tmp_path / "osm"
    with (
        geofabrik_client(geofabrik_routes(log), log) as client,
        pytest.raises(ValueError, match="invalid Geofabrik region"),
    ):
        fetch_extract(client, "../delaware", root)
    assert log == []
    _assert_nothing_written(root, log)


# --- python -m septa_detours.ingest osm --------------------------------------


def region_body(region: str) -> bytes:
    return f"fake {region} extract \xff".encode("latin-1")


def all_regions_client(
    log: list[str], broken: dict[str, Callable[[], httpx.Response]] | None = None
) -> httpx.Client:
    """Serve every configured region's redirect chain, .md5 and body.

    ``broken`` maps a region to a replacement response for its dated file.
    """
    broken = broken or {}
    routes: Routes = {}
    for region in GEOFABRIK_REGIONS:
        nested = f"{US}/{region}/{region}-latest.osm.pbf"
        dated = f"{US}/{region}/{region}-261124.osm.pbf"
        body = region_body(region)
        digest = hashlib.md5(body, usedforsecurity=False).hexdigest()
        md5_body = md5_line(digest, f"{region}-261124.osm.pbf")
        routes[f"{US}/{region}-latest.osm.pbf"] = lambda nested=nested: httpx.Response(
            301, headers={"location": nested}
        )
        routes[nested] = lambda dated=dated: httpx.Response(
            307, headers={"location": dated}
        )
        routes[dated] = broken.get(region) or (
            lambda body=body: httpx.Response(200, content=body)
        )
        routes[f"{dated}.md5"] = lambda md5_body=md5_body: httpx.Response(
            200, content=md5_body
        )
    return geofabrik_client(routes, log)


@pytest.fixture
def in_tmp_repo(tmp_path, monkeypatch):
    """Run from an empty fake repo root, so default relative paths land here."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def patch_client(monkeypatch, client: httpx.Client) -> None:
    monkeypatch.setattr(ingest_main, "make_client", lambda: client)


def fetching_line(region: str) -> str:
    return f"fetching {region} ({US}/{region}-latest.osm.pbf)\n"


def wrote_line(region: str) -> str:
    return f"wrote {DEFAULT_OSM_DIR / f'{region}-261124.osm.pbf'}\n"


def test_main_osm_writes_every_region(in_tmp_repo, monkeypatch, capsys):
    log: list[str] = []
    patch_client(monkeypatch, all_regions_client(log))
    assert ingest_main.main(["osm"]) == 0

    out, err = capsys.readouterr()
    assert out == "".join(wrote_line(r) for r in GEOFABRIK_REGIONS)
    assert err == "".join(fetching_line(r) for r in GEOFABRIK_REGIONS)
    root = in_tmp_repo / DEFAULT_OSM_DIR
    assert sorted(p.name for p in root.iterdir()) == sorted(
        f"{r}-261124.osm.pbf" for r in GEOFABRIK_REGIONS
    )
    for region in GEOFABRIK_REGIONS:
        assert (root / f"{region}-261124.osm.pbf").read_bytes() == region_body(region)


@pytest.mark.parametrize(
    "broken_response",
    [
        lambda: httpx.Response(503, content=b"busy"),
        lambda: httpx.Response(200, content=b"not the real extract"),
    ],
    ids=["http-503", "md5-mismatch"],
)
def test_main_osm_failed_region_does_not_stop_the_others(
    in_tmp_repo, monkeypatch, capsys, broken_response
):
    """New Jersey (the middle region) fails; Pennsylvania and Delaware still land."""
    assert GEOFABRIK_REGIONS == ("pennsylvania", "new-jersey", "delaware")
    log: list[str] = []
    patch_client(
        monkeypatch, all_regions_client(log, broken={"new-jersey": broken_response})
    )
    assert ingest_main.main(["osm"]) == 1

    out, err = capsys.readouterr()
    assert out == wrote_line("pennsylvania") + wrote_line("delaware")
    # httpx's status errors span two lines, so check order, not line numbers.
    assert err.startswith(fetching_line("pennsylvania") + fetching_line("new-jersey"))
    error_at = err.index("error: new-jersey: ")
    assert err.index(fetching_line("delaware")) > error_at
    assert err.endswith(
        fetching_line("delaware") + "error: 1 of 3 regions failed: new-jersey\n"
    )

    root = in_tmp_repo / DEFAULT_OSM_DIR
    assert sorted(p.name for p in root.iterdir()) == [
        "delaware-261124.osm.pbf",
        "pennsylvania-261124.osm.pbf",
    ]


def test_main_osm_all_regions_fail(in_tmp_repo, monkeypatch, capsys):
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    patch_client(monkeypatch, httpx.Client(transport=httpx.MockTransport(unreachable)))
    assert ingest_main.main(["osm"]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("no route to host") == len(GEOFABRIK_REGIONS)
    assert err.endswith(
        "error: 3 of 3 regions failed: pennsylvania, new-jersey, delaware\n"
    )
    assert not (in_tmp_repo / "data").exists()


def test_main_osm_unexpected_errors_propagate(in_tmp_repo, monkeypatch):
    """A bug (not a fetch failure) keeps its traceback and stops the run."""
    calls: list[str] = []

    def buggy(client, region):
        calls.append(region)
        raise RuntimeError("bug")

    patch_client(monkeypatch, httpx.Client())
    monkeypatch.setattr(ingest_main, "fetch_extract", buggy)
    with pytest.raises(RuntimeError, match="bug"):
        ingest_main.main(["osm"])
    assert calls == ["pennsylvania"]


def test_main_osm_ctrl_c_stops_every_region(in_tmp_repo, monkeypatch):
    calls: list[str] = []

    def interrupted(client, region):
        calls.append(region)
        raise KeyboardInterrupt

    patch_client(monkeypatch, httpx.Client())
    monkeypatch.setattr(ingest_main, "fetch_extract", interrupted)
    with pytest.raises(KeyboardInterrupt):
        ingest_main.main(["osm"])
    assert calls == ["pennsylvania"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [([], "alerts"), (["alerts"], "alerts"), (["osm"], "osm")],
    ids=["default", "alerts", "osm"],
)
def test_main_source_picks_the_fetcher(in_tmp_repo, monkeypatch, argv, expected):
    called: list[str] = []

    def fake_alerts(client):
        called.append("alerts")
        return DEFAULT_OSM_DIR / "unused"

    def fake_osm(client, region):
        called.append("osm")
        return DEFAULT_OSM_DIR / "unused"

    patch_client(monkeypatch, httpx.Client())
    monkeypatch.setattr(ingest_main, "save_alerts_snapshot", fake_alerts)
    monkeypatch.setattr(ingest_main, "fetch_extract", fake_osm)
    assert ingest_main.main(argv) == 0
    assert set(called) == {expected}


@pytest.mark.parametrize("argv", [["rail"], ["OSM"], ["osm", "alerts"]])
def test_main_rejects_unknown_source(argv):
    with pytest.raises(SystemExit) as excinfo:
        ingest_main.main(argv)
    assert excinfo.value.code == 2
