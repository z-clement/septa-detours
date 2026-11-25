"""Tests for ``gtfs.load.load_stops`` over small files in ``tmp_path``.

Rows are copied from the real 2026-11-25 feeds (bus columns trimmed to a
realistic subset). The real rail file has CRLF line endings and fewer
columns (no ``location_type``); the bus file has LF.
"""

from pathlib import Path

import polars as pl
import pytest

from septa_detours.gtfs.load import load_stops

BUS_STOPS = (
    "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
    "4,4,Roosevelt Blvd & Broad St - FS,40.018128,-75.148887,0,\n"
    "5,5,Roosevelt Blvd & 5th St,40.023465,-75.133487,0,\n"
    "31033_boarding_track_1_boarding_area_south,,"
    "Track 1 Boarding - South Side,,,4,32158\n"
)
RAIL_STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon,stop_url,wheelchair_boarding\r\n"
    "90004,Gray 30th St Station,39.95667,-75.18166,,1\r\n"
)

OUTPUT_SCHEMA = {
    "stop_id": pl.String,
    "stop_name": pl.String,
    "stop_lat": pl.Float64,
    "stop_lon": pl.Float64,
    "feed": pl.String,
}


def write_feed(root: Path, feed: str, text: str) -> None:
    """Write ``text`` as ``root/<feed>/stops.txt`` (newlines kept)."""
    (root / feed).mkdir(parents=True, exist_ok=True)
    (root / feed / "stops.txt").write_bytes(text.encode("utf-8"))


@pytest.fixture
def gtfs_root(tmp_path: Path) -> Path:
    write_feed(tmp_path, "bus", BUS_STOPS)
    write_feed(tmp_path, "rail", RAIL_STOPS)
    return tmp_path


def test_loads_both_feeds_in_order(gtfs_root: Path):
    """Bus rows then rail rows, file order kept, each tagged with its feed."""
    expected = [
        ("4", "Roosevelt Blvd & Broad St - FS", 40.018128, -75.148887, "bus"),
        ("5", "Roosevelt Blvd & 5th St", 40.023465, -75.133487, "bus"),
        (
            "31033_boarding_track_1_boarding_area_south",
            "Track 1 Boarding - South Side",
            None,
            None,
            "bus",
        ),
        ("90004", "Gray 30th St Station", 39.95667, -75.18166, "rail"),
    ]
    assert expected == load_stops(root=gtfs_root).rows()


def test_output_schema(gtfs_root: Path):
    assert load_stops(root=gtfs_root).schema == OUTPUT_SCHEMA


def test_crlf_leaves_no_carriage_returns(gtfs_root: Path):
    """The real rail file is CRLF; the last kept column must still parse."""
    output = load_stops(["rail"], root=gtfs_root)
    assert output["stop_lon"].to_list() == [-75.18166]
    assert not output["stop_name"].str.contains("\r").any()


def test_single_feed(gtfs_root: Path):
    assert load_stops(["rail"], root=gtfs_root)["feed"].to_list() == ["rail"]


def test_stop_ids_stay_strings(tmp_path: Path):
    """Numeric-looking IDs keep their exact text (no ``007`` -> ``7``)."""
    write_feed(
        tmp_path, "bus", "stop_id,stop_name,stop_lat,stop_lon\n007,A & B,40.0,-75.1\n"
    )
    assert load_stops(["bus"], root=tmp_path)["stop_id"].to_list() == ["007"]


def test_empty_coordinates_are_null(tmp_path: Path):
    """Unquoted and quoted ``""`` both mean "no value"; the row is kept."""
    write_feed(
        tmp_path,
        "bus",
        'stop_id,stop_name,stop_lat,stop_lon\n1,Node,,\n2,Area,"",""\n',
    )
    output = load_stops(["bus"], root=tmp_path)
    assert output.select("stop_lat", "stop_lon").rows() == [(None, None), (None, None)]


def test_missing_column_raises(tmp_path: Path):
    write_feed(tmp_path, "bus", "stop_id,stop_name,stop_lat\n1,A & B,40.0\n")
    with pytest.raises(ValueError, match=r"bus feed's stops\.txt"):
        load_stops(["bus"], root=tmp_path)


def test_missing_file_raises(tmp_path: Path):
    write_feed(tmp_path, "bus", BUS_STOPS)
    with pytest.raises(FileNotFoundError):
        load_stops(root=tmp_path)  # no rail/stops.txt


def test_non_numeric_coordinate_raises(tmp_path: Path):
    write_feed(
        tmp_path, "bus", "stop_id,stop_name,stop_lat,stop_lon\n1,A & B,north,-75.1\n"
    )
    with pytest.raises(pl.exceptions.InvalidOperationError):
        load_stops(["bus"], root=tmp_path)
