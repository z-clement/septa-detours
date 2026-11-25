"""Tests for ``gtfs.load.load_directions`` over small files in ``tmp_path``.

Rows are copied from the real 2026-11-25 feeds. The real rail file has
CRLF line endings; the bus file has LF.
"""

from pathlib import Path

import polars as pl
import pytest

from septa_detours.gtfs.load import load_directions

BUS_DIRECTIONS = (
    "route_id,direction_id,direction,direction_destination\n"
    "55,0,Northbound,Willow Grove & Doylestown\n"
    "55,1,Southbound,Olney Transit Center\n"
    "310,0,Loop,Horsham Breeze Red\n"
    "L1_OWL,0,Eastbound,Frankford Transit Center\n"
    "L1_OWL,1,Westbound,69th Street Transit Center\n"
)
RAIL_DIRECTIONS = (
    "route_id,direction_id,direction,direction_destination\r\n"
    "AIR,0,Inbound,Center City Philadelphia\r\n"
    "AIR,1,Outbound,Philadelphia International Airport\r\n"
)

OUTPUT_SCHEMA = {
    "route_id": pl.String,
    "direction_id": pl.Int8,
    "direction": pl.String,
    "direction_destination": pl.String,
    "feed": pl.String,
}


def write_feed(root: Path, feed: str, text: str) -> None:
    """Write ``text`` as ``root/<feed>/directions.txt`` (newlines kept)."""
    (root / feed).mkdir(parents=True, exist_ok=True)
    (root / feed / "directions.txt").write_bytes(text.encode("utf-8"))


@pytest.fixture
def gtfs_root(tmp_path: Path) -> Path:
    write_feed(tmp_path, "bus", BUS_DIRECTIONS)
    write_feed(tmp_path, "rail", RAIL_DIRECTIONS)
    return tmp_path


def test_loads_both_feeds_in_order(gtfs_root: Path):
    """Bus rows then rail rows, file order kept, each tagged with its feed."""
    output = load_directions(root=gtfs_root)
    expected = [
        ("55", 0, "Northbound", "Willow Grove & Doylestown", "bus"),
        ("55", 1, "Southbound", "Olney Transit Center", "bus"),
        ("310", 0, "Loop", "Horsham Breeze Red", "bus"),
        ("L1_OWL", 0, "Eastbound", "Frankford Transit Center", "bus"),
        ("L1_OWL", 1, "Westbound", "69th Street Transit Center", "bus"),
        ("AIR", 0, "Inbound", "Center City Philadelphia", "rail"),
        ("AIR", 1, "Outbound", "Philadelphia International Airport", "rail"),
    ]
    assert expected == output.rows()


def test_output_schema(gtfs_root: Path):
    """``direction_id`` is Int8, matching ``load_trips`` so they join."""
    assert load_directions(root=gtfs_root).schema == OUTPUT_SCHEMA


def test_crlf_leaves_no_carriage_returns(gtfs_root: Path):
    """The real rail file is CRLF; no value may end in ``\\r``."""
    output = load_directions(["rail"], root=gtfs_root)
    assert not output["direction_destination"].str.contains("\r").any()


def test_single_feed(gtfs_root: Path):
    output = load_directions(["rail"], root=gtfs_root)
    assert output["feed"].to_list() == ["rail", "rail"]


def test_route_ids_stay_strings(tmp_path: Path):
    """Numeric-looking IDs keep their exact text (no ``007`` -> ``7``)."""
    write_feed(
        tmp_path,
        "bus",
        "route_id,direction_id,direction,direction_destination\n"
        "007,0,Northbound,Somewhere\n",
    )
    assert load_directions(["bus"], root=tmp_path)["route_id"].to_list() == ["007"]


def test_empty_destination_is_null(tmp_path: Path):
    """``""`` means "no value" in GTFS, quoted or not."""
    write_feed(
        tmp_path,
        "bus",
        "route_id,direction_id,direction,direction_destination\n"
        "1,0,Northbound,\n"
        '2,0,Southbound,""\n',
    )
    output = load_directions(["bus"], root=tmp_path)
    assert output["direction_destination"].to_list() == [None, None]


def test_extra_columns_are_dropped(tmp_path: Path):
    write_feed(
        tmp_path,
        "bus",
        "route_id,direction_id,direction,direction_destination,extra\n"
        "55,0,Northbound,Willow Grove,x\n",
    )
    assert list(OUTPUT_SCHEMA) == load_directions(["bus"], root=tmp_path).columns


def test_missing_column_raises(tmp_path: Path):
    write_feed(tmp_path, "bus", "route_id,direction_id,direction\n55,0,Northbound\n")
    with pytest.raises(ValueError, match=r"bus feed's directions\.txt"):
        load_directions(["bus"], root=tmp_path)


def test_missing_file_raises(tmp_path: Path):
    """If SEPTA drops the extension, loading fails loudly."""
    write_feed(tmp_path, "bus", BUS_DIRECTIONS)
    with pytest.raises(FileNotFoundError):
        load_directions(root=tmp_path)  # no rail/directions.txt


def test_non_integer_direction_id_raises(tmp_path: Path):
    write_feed(
        tmp_path,
        "bus",
        "route_id,direction_id,direction,direction_destination\n"
        "55,north,Northbound,Willow Grove\n",
    )
    with pytest.raises(pl.exceptions.InvalidOperationError):
        load_directions(["bus"], root=tmp_path)
