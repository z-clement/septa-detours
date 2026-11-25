"""Download OpenStreetMap extracts from Geofabrik and save them untouched.

Source: Geofabrik's daily state extracts (``.osm.pbf``), one per US state.
SEPTA's service area crosses three: Pennsylvania (almost everything), New
Jersey (bus stops reach Trenton Transit Center) and Delaware (bus stops
reach Claymont Transit Center). Together about 540 MB.

Why Geofabrik, not the Overpass API: Overpass's public server refused even
small test queries ("at capacity") and asks automated or bulk users to run
their own instance; Geofabrik's download server is built for bulk files.

Ingest rules (see CLAUDE.md): fetch only, save the bytes exactly as
received under ``data/raw/osm/``. Reading the ``.pbf`` (with pyosmium) is a
later stage's job.

Every extract has a published ``.md5`` file in ``md5sum`` format, used to
reject truncated or corrupted downloads before they replace a good file.
"""

import re

GEOFABRIK_US_URL = "https://download.geofabrik.de/north-america/us"

# States SEPTA's routes touch. Order is download order: biggest first, so a
# failure on the one that matters most shows up first.
GEOFABRIK_REGIONS = ("pennsylvania", "new-jersey", "delaware")

# Lowercase words joined by single hyphens, like Geofabrik's own names.
_REGION_PATTERN = re.compile(r"[a-z]+(?:-[a-z]+)*")

# md5sum text-mode output: 32 lowercase hex digits, two spaces, file name,
# optional final newline. Groups: digest, name. The name excludes "\r" too,
# so a CRLF file is reported as malformed, not as naming "<name>\r".
_MD5_LINE_PATTERN = re.compile(r"([0-9a-f]{32})  ([^\r\n]+)\n?")


def extract_url(region: str) -> str:
    """Return Geofabrik's "latest" download URL for a US state extract.

    ``extract_url("delaware")`` gives
    ``https://download.geofabrik.de/north-america/us/delaware-latest.osm.pbf``.
    That link redirects to a dated file (``.../delaware/delaware-261124.osm.pbf``);
    following the redirect is the fetcher's job.

    Pure: builds a string, touches no network.

    ``region`` becomes a URL path segment, so it must be lowercase words
    joined by single hyphens. Anything else is rejected rather than cleaned
    up: ``"../x"`` or ``"us/pennsylvania"`` would point at a different file.
    It is not limited to ``GEOFABRIK_REGIONS``.

    Args:
        region: Geofabrik's name for the state, e.g. ``"new-jersey"``.

    Raises:
        ValueError: If ``region`` isn't lowercase hyphenated words.
    """
    if not _REGION_PATTERN.fullmatch(region):
        msg = f"invalid Geofabrik region {region!r}: expected e.g. 'new-jersey'"
        raise ValueError(msg)
    return f"{GEOFABRIK_US_URL}/{region}-latest.osm.pbf"


def parse_md5_file(content: bytes, expected_name: str) -> str:
    r"""Return the MD5 hex digest from a Geofabrik ``.md5`` file.

    The file is one ``md5sum`` line, e.g.
    ``b"1ae124a257f93a0854f9efedfe7dd389  delaware-261124.osm.pbf\n"``.

    Strict on purpose: only that exact shape is accepted (the final newline
    is optional). Uppercase hex, the ``md5sum -b`` marker (``*name``), extra
    lines, or non-ASCII bytes all raise: a changed format should be noticed,
    not half-understood.

    The name in the file must equal ``expected_name``. Geofabrik's
    ``-latest`` and dated ``.md5`` files name different files, so a mismatch
    means the checksum belongs to some other download.

    Args:
        content: The raw ``.md5`` response body.
        expected_name: The file name the checksum must be for, e.g.
            ``"delaware-261124.osm.pbf"``.

    Returns:
        The 32-character lowercase hex digest.

    Raises:
        ValueError: If the content isn't one well-formed line, or names a
            different file.
    """
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError:
        msg = f"MD5 file for {expected_name!r} is not ASCII: {content[:80]!r}"
        raise ValueError(msg) from None

    match = _MD5_LINE_PATTERN.fullmatch(text)
    if match is None:
        msg = f"MD5 file for {expected_name!r} is not one md5sum line: {text[:80]!r}"
        raise ValueError(msg)

    digest, name = match.groups()
    if name != expected_name:
        msg = f"MD5 file is for {name!r}, expected {expected_name!r}"
        raise ValueError(msg)
    return digest
