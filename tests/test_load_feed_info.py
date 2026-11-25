"""Tests for ``gtfs.load.load_feed_info`` over small files in ``tmp_path``.

The header and rows are copied from the real 2026-11-25 feeds, which both
have CRLF line endings. The versions differ here (the real ones are equal)
so a swapped feed shows.
"""

from pathlib import Path

import polars as pl
import pytest

from septa_detours.gtfs.load import load_feed_info

HEADER = (
    "feed_publisher_name,feed_publisher_url,feed_lang,"
    "feed_start_date,feed_end_date,feed_version\r\n"
)
BUS_FEED_INFO = HEADER + "SEPTA,https://septa.org/,en,20261122,20270220,v202611220\r\n"
RAIL_FEED_INFO = HEADER + "SEPTA,https://septa.org/,en,20261115,20270213,v202611150\r\n"

OUTPUT_SCHEMA = {
    "feed_version": pl.String,
    "feed_start_date": pl.String,
    "feed_end_date": pl.String,
    "feed": pl.String,
}


def write_feed(root: Path, feed: str, text: str) -> None:
    """Write ``text`` as ``root/<feed>/feed_info.txt`` (newlines kept)."""
    (root / feed).mkdir(parents=True, exist_ok=True)
    (root / feed / "feed_info.txt").write_bytes(text.encode("utf-8"))


@pytest.fixture
def gtfs_root(tmp_path: Path) -> Path:
    write_feed(tmp_path, "bus", BUS_FEED_INFO)
    write_feed(tmp_path, "rail", RAIL_FEED_INFO)
    return tmp_path


def test_loads_both_feeds_in_order(gtfs_root: Path) -> None:
    output = load_feed_info(root=gtfs_root)
    assert output.schema == OUTPUT_SCHEMA
    assert output.rows() == [
        ("v202611220", "20261122", "20270220", "bus"),
        ("v202611150", "20261115", "20270213", "rail"),
    ]


def test_loads_only_the_requested_feed(gtfs_root: Path) -> None:
    output = load_feed_info(["rail"], root=gtfs_root)
    assert output.rows() == [("v202611150", "20261115", "20270213", "rail")]


def test_crlf_leaves_no_carriage_return(gtfs_root: Path) -> None:
    # feed_version is the last column, right before each \r\n.
    versions = load_feed_info(root=gtfs_root)["feed_version"].to_list()
    assert versions == ["v202611220", "v202611150"]


def test_values_stay_strings(tmp_path: Path) -> None:
    write_feed(
        tmp_path,
        "bus",
        HEADER + "SEPTA,https://septa.org/,en,20261122,20270220,0042\r\n",
    )
    assert load_feed_info(["bus"], root=tmp_path)["feed_version"].to_list() == ["0042"]


def test_empty_version_is_null(tmp_path: Path) -> None:
    write_feed(
        tmp_path, "bus", HEADER + "SEPTA,https://septa.org/,en,20261122,20270220,\r\n"
    )
    assert load_feed_info(["bus"], root=tmp_path)["feed_version"].to_list() == [None]


def test_missing_file_raises(tmp_path: Path) -> None:
    write_feed(tmp_path, "bus", BUS_FEED_INFO)
    with pytest.raises(FileNotFoundError):
        load_feed_info(root=tmp_path)


def test_missing_column_raises(tmp_path: Path) -> None:
    write_feed(tmp_path, "bus", "feed_publisher_name,feed_version\r\nSEPTA,v1\r\n")
    with pytest.raises(ValueError, match=r"bus feed's feed_info\.txt is missing"):
        load_feed_info(["bus"], root=tmp_path)
