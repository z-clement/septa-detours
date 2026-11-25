"""Tests for ``septa_detours.ingest.osm`` (Geofabrik extracts)."""

import re

import pytest

from septa_detours.ingest.osm import (
    GEOFABRIK_REGIONS,
    dated_extract_name,
    extract_url,
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
