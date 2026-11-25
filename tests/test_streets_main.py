"""Tests for ``python -m septa_detours.streets`` (the street-cache build).

Each test runs in a fake repo under ``tmp_path``: tiny GTFS ``stops.txt``
files and three small ``.osm.pbf`` extracts converted from XML (the
finder requires real ``.osm.pbf`` names). Pennsylvania is the hand-written
``broad_washington.osm`` fixture; New Jersey and Delaware are one or two
ways each, and Delaware repeats Pennsylvania's border way 110.
"""

import subprocess
import sys
from pathlib import Path

import osmium
import polars as pl
import pytest

from septa_detours.gtfs.load import load_stops
from septa_detours.streets import __main__ as streets_main
from septa_detours.streets.cache import (
    DEFAULT_STREET_CACHE,
    FETCH_COMMAND,
    StreetCacheInfo,
    read_street_cache,
    read_street_cache_info,
    service_bbox,
    write_street_cache,
)
from septa_detours.streets.load import STREET_WAYS_SCHEMA

FIXTURE = Path(__file__).parent / "fixtures" / "osm" / "broad_washington.osm"

# Two bus stops near the fixture's Broad & Washington, one rail stop. With
# the 2 km margin the box covers the fixture's Philly ways but not its
# Pittsburgh way (109).
BUS_STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon\n"
    "1,Broad St & Washington Av,39.9386,-75.1677\n"
    "2,Broad St & Ellsworth St,39.9375,-75.1675\n"
)
RAIL_STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon\r\n90005,Lombard-South,39.9439,-75.1660\r\n"
)

NODES = (
    '<node id="5" version="1" lat="39.9388" lon="-75.1655"/>'
    '<node id="7" version="1" lat="40.4415" lon="-79.9959"/>'
    '<node id="30" version="1" lat="39.9400" lon="-75.1600"/>'
    '<node id="31" version="1" lat="39.9410" lon="-75.1610"/>'
)
NJ_XML = (
    NODES + '<way id="301" version="1"><nd ref="30"/><nd ref="31"/>'
    '<tag k="highway" v="residential"/><tag k="name" v="Jersey Street"/></way>'
)
TURNPIKE = (
    '<way id="110" version="1"><nd ref="5"/><nd ref="7"/>'
    '<tag k="highway" v="motorway"/><tag k="name" v="{name}"/></way>'
)
DE_XML = (
    NODES
    + TURNPIKE.format(name="Pennsylvania Turnpike")
    + '<way id="401" version="1"><nd ref="31"/><nd ref="30"/>'
    '<tag k="highway" v="tertiary"/><tag k="name" v="Delaware Avenue"/></way>'
)

SOURCES = (
    "pennsylvania-261124.osm.pbf",
    "new-jersey-261124.osm.pbf",
    "delaware-261124.osm.pbf",
)
# PA (minus Pittsburgh's 109), then NJ, then DE (its copy of 110 collapses).
EXPECTED_WAY_IDS = [101, 102, 107, 108, 110, 301, 401]

# Stands in for a cache built earlier, which a failed build must not touch.
OLD_CACHE_WAYS = pl.DataFrame(
    [(1, "Old Street", "residential", [1, 2], [[-75.1, 39.9], [-75.2, 39.9]])],
    schema=STREET_WAYS_SCHEMA,
    orient="row",
)


def write_pbf(osm_xml: str, path: Path) -> None:
    """Convert OSM XML (a full file's text) into an ``.osm.pbf`` at ``path``."""
    xml_path = path.with_name(path.name + ".src.osm")
    xml_path.write_text(osm_xml, encoding="utf-8")
    with osmium.SimpleWriter(str(path), overwrite=True) as writer:
        for obj in osmium.FileProcessor(str(xml_path)):
            writer.add(obj)
    xml_path.unlink()


def osm_file(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6">{body}</osm>'


@pytest.fixture
def fake_repo(tmp_path, monkeypatch) -> Path:
    for feed, text in (("bus", BUS_STOPS), ("rail", RAIL_STOPS)):
        (tmp_path / "data" / "gtfs" / feed).mkdir(parents=True)
        (tmp_path / "data" / "gtfs" / feed / "stops.txt").write_text(text)

    osm = tmp_path / "data" / "raw" / "osm"
    osm.mkdir(parents=True)
    write_pbf(FIXTURE.read_text(encoding="utf-8"), osm / SOURCES[0])
    write_pbf(osm_file(NJ_XML), osm / SOURCES[1])
    write_pbf(osm_file(DE_XML), osm / SOURCES[2])

    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_builds_cache_from_all_regions(fake_repo, capsys):
    assert streets_main.main([]) == 0

    cache = read_street_cache()
    assert cache["way_id"].to_list() == EXPECTED_WAY_IDS
    assert cache.schema == STREET_WAYS_SCHEMA
    assert read_street_cache_info() == StreetCacheInfo(
        sources=SOURCES, bbox=service_bbox(load_stops())
    )

    out, err = capsys.readouterr()
    assert out == (
        f"wrote {DEFAULT_STREET_CACHE} (7 ways from pennsylvania-261124.osm.pbf, "
        "new-jersey-261124.osm.pbf, delaware-261124.osm.pbf)\n"
    )
    osm = Path("data/raw/osm")
    assert err == "".join(f"reading {osm / name}\n" for name in SOURCES)


def test_uses_newest_extract_per_region(fake_repo):
    """An older Pennsylvania file (different content) is ignored."""
    old = fake_repo / "data" / "raw" / "osm" / "pennsylvania-261101.osm.pbf"
    write_pbf(osm_file(NODES + TURNPIKE.format(name="Old Turnpike Name")), old)
    assert streets_main.main([]) == 0
    assert read_street_cache_info().sources[0] == "pennsylvania-261124.osm.pbf"
    assert read_street_cache()["way_id"].to_list() == EXPECTED_WAY_IDS


def test_missing_extract_fails_before_reading_anything(fake_repo, capsys):
    """Delaware is missing. GTFS is deleted too: the extracts are checked first."""
    (fake_repo / "data" / "raw" / "osm" / "delaware-261124.osm.pbf").unlink()
    for feed in ("bus", "rail"):
        (fake_repo / "data" / "gtfs" / feed / "stops.txt").unlink()

    assert streets_main.main([]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: no delaware extract in data/raw/osm")
    assert FETCH_COMMAND in err
    assert not (fake_repo / DEFAULT_STREET_CACHE).exists()


def test_missing_stops_fails(fake_repo, capsys):
    (fake_repo / "data" / "gtfs" / "rail" / "stops.txt").unlink()
    assert streets_main.main([]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "reading" not in err  # failed before any extract was read
    assert not (fake_repo / DEFAULT_STREET_CACHE).exists()


def test_disagreeing_extracts_fail_and_keep_old_cache(fake_repo, capsys):
    """Delaware's copy of border way 110 differs (an edit between extract days)."""
    write_street_cache(
        OLD_CACHE_WAYS,
        StreetCacheInfo(sources=("older.osm.pbf",), bbox=(-76.0, 39.0, -74.0, 41.0)),
    )
    edited = osm_file(NODES + TURNPIKE.format(name="I-276"))
    write_pbf(edited, fake_repo / "data" / "raw" / "osm" / "delaware-261124.osm.pbf")

    assert streets_main.main([]) == 1
    _, err = capsys.readouterr()
    assert "error: 1 OSM ways differ between extracts (way 110)" in err
    assert read_street_cache_info().sources == ("older.osm.pbf",)


def test_corrupt_extract_keeps_its_traceback(fake_repo):
    """pyosmium's RuntimeError isn't an expected failure: no exit 1, a traceback."""
    (fake_repo / "data" / "raw" / "osm" / "new-jersey-261124.osm.pbf").write_bytes(
        b"not a pbf file"
    )
    with pytest.raises(RuntimeError):
        streets_main.main([])
    assert not (fake_repo / DEFAULT_STREET_CACHE).exists()


def test_rejects_arguments():
    with pytest.raises(SystemExit) as excinfo:
        streets_main.main(["--nope"])
    assert excinfo.value.code == 2


def test_runs_as_module(fake_repo):
    """``raise SystemExit(main())`` wiring, in a real subprocess."""
    result = subprocess.run(
        [sys.executable, "-m", "septa_detours.streets"],
        cwd=fake_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"wrote {DEFAULT_STREET_CACHE} (7 ways")
