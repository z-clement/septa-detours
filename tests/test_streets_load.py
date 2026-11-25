"""Tests for ``septa_detours.streets.load.read_street_ways``.

Most tests read the hand-written ``tests/fixtures/osm/broad_washington.osm``
(each way there is annotated with the rule it tests). Small one-off cases
are written as XML into ``tmp_path``.
"""

from pathlib import Path

import pytest

from septa_detours.streets.load import STREET_WAYS_SCHEMA, read_street_ways

FIXTURE = Path(__file__).parent / "fixtures" / "osm" / "broad_washington.osm"

# Node coordinates from the fixture, as [lon, lat].
N1 = [-75.1679, 39.9396]
N2 = [-75.1677, 39.9386]
N3 = [-75.1675, 39.9376]
N4 = [-75.1700, 39.9384]
N5 = [-75.1655, 39.9388]
N7 = [-79.9959, 40.4415]
N8 = [-79.9940, 40.4420]

# (way_id, name, highway, node_ids, coordinates), in file order.
ALL_ROWS = [
    (101, "South Broad Street", "primary", [1, 2, 3], [N1, N2, N3]),
    (102, "Washington Avenue", "secondary", [4, 2, 5], [N4, N2, N5]),
    (107, "Station Drive", "service", [5, 3], [N5, N3]),
    (108, "Broad Street Ramp", "primary_link", [4, 1], [N4, N1]),
    (109, "Liberty Avenue", "primary", [7, 8], [N7, N8]),
    (110, "Pennsylvania Turnpike", "motorway", [5, 7], [N5, N7]),
]

# Bounding boxes as BBox: west, south, east, north.
PHILLY = (-75.2, 39.9, -75.1, 40.0)
PITTSBURGH = (-80.1, 40.4, -79.9, 40.5)


def way_ids(frame) -> list[int]:
    return frame["way_id"].to_list()


def write_osm(tmp_path: Path, body: str) -> Path:
    """Write a minimal OSM XML file around ``body`` (nodes, ways)."""
    path = tmp_path / "test.osm"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<osm version="0.6" generator="test">\n{body}\n</osm>\n',
        encoding="utf-8",
    )
    return path


def road(way_id: int, refs: list[int], name: str = "Test Street") -> str:
    nds = "".join(f'<nd ref="{ref}"/>' for ref in refs)
    return (
        f'<way id="{way_id}" version="1">{nds}'
        f'<tag k="highway" v="residential"/><tag k="name" v="{name}"/></way>'
    )


def node(node_id: int, lon: float, lat: float) -> str:
    return f'<node id="{node_id}" version="1" lat="{lat}" lon="{lon}"/>'


# --- whole fixture -------------------------------------------------------------


def test_reads_named_roads_in_file_order():
    """Unnamed, footway, construction, non-highway ways, nodes and relations: gone."""
    frame = read_street_ways(FIXTURE)
    assert frame.rows() == ALL_ROWS


def test_schema():
    assert read_street_ways(FIXTURE).schema == STREET_WAYS_SCHEMA


def test_coordinates_are_lon_lat():
    """GeoJSON order; Philly's lon (~ -75) can't be mistaken for its lat (~ 40)."""
    broad = read_street_ways(FIXTURE).row(0, named=True)
    assert broad["coordinates"][0] == [-75.1679, 39.9396]


# --- bbox ----------------------------------------------------------------------


def test_bbox_none_keeps_everything():
    assert read_street_ways(FIXTURE, bbox=None).rows() == ALL_ROWS


def test_bbox_keeps_ways_with_any_node_inside():
    """Way 110 has one node in Philly and one in Pittsburgh: kept by both boxes."""
    assert way_ids(read_street_ways(FIXTURE, PHILLY)) == [101, 102, 107, 108, 110]
    assert way_ids(read_street_ways(FIXTURE, PITTSBURGH)) == [109, 110]


def test_bbox_keeps_whole_way():
    """A way partly outside the box keeps all its nodes, not just those inside."""
    turnpike = read_street_ways(FIXTURE, PHILLY).filter(way_id=110)
    assert turnpike["node_ids"].to_list() == [[5, 7]]
    assert turnpike["coordinates"].to_list() == [[N5, N7]]


@pytest.mark.parametrize(
    "bbox",
    [
        (N7[0], N7[1], N7[0], N7[1]),  # a box that is exactly node 7
        (N7[0], N7[1], -79.0, 41.0),  # node 7 on the west/south edges
        (-81.0, 40.0, N7[0], N7[1]),  # node 7 on the east/north edges
    ],
    ids=["point", "west-south-edge", "east-north-edge"],
)
def test_bbox_edges_count_as_inside(bbox):
    assert way_ids(read_street_ways(FIXTURE, bbox)) == [109, 110]


def test_bbox_with_nothing_inside_gives_empty_typed_frame():
    frame = read_street_ways(FIXTURE, (0.0, 0.0, 1.0, 1.0))
    assert frame.is_empty()
    assert frame.schema == STREET_WAYS_SCHEMA


def test_bbox_is_lon_lat_not_lat_lon():
    """A box written (south, west, north, east) by mistake finds nothing."""
    swapped = (PHILLY[1], PHILLY[0], PHILLY[3], PHILLY[2])
    assert read_street_ways(FIXTURE, swapped).is_empty()


# --- one-off files ---------------------------------------------------------------


def test_order_is_file_order_not_id_order(tmp_path):
    body = "\n".join(
        [
            node(1, -75.16, 39.95),
            node(2, -75.15, 39.95),
            road(30, [1, 2], "Thirty"),
            road(10, [1, 2], "Ten"),
            road(20, [1, 2], "Twenty"),
        ]
    )
    assert way_ids(read_street_ways(write_osm(tmp_path, body))) == [30, 10, 20]


def test_closed_way_keeps_repeated_node(tmp_path):
    """A loop (e.g. a roundabout) lists its first node again at the end."""
    body = "\n".join(
        [
            node(1, -75.16, 39.95),
            node(2, -75.15, 39.95),
            node(3, -75.15, 39.96),
            road(40, [1, 2, 3, 1], "Loop Road"),
        ]
    )
    frame = read_street_ways(write_osm(tmp_path, body))
    assert frame["node_ids"].to_list() == [[1, 2, 3, 1]]
    assert frame["coordinates"].to_list() == [
        [[-75.16, 39.95], [-75.15, 39.95], [-75.15, 39.96], [-75.16, 39.95]]
    ]


def test_name_kept_exactly(tmp_path):
    """No cleanup: spacing, case and punctuation are match/'s problem."""
    name = "  N. 17th  st "
    body = "\n".join(
        [node(1, -75.16, 39.95), node(2, -75.15, 39.95), road(50, [1, 2], name)]
    )
    assert read_street_ways(write_osm(tmp_path, body))["name"].to_list() == [name]


def test_no_ways_gives_empty_typed_frame(tmp_path):
    frame = read_street_ways(write_osm(tmp_path, node(1, -75.16, 39.95)))
    assert frame.is_empty()
    assert frame.schema == STREET_WAYS_SCHEMA


def test_missing_node_location_raises(tmp_path):
    """Node 99 is referenced but not in the file: a broken extract."""
    body = "\n".join([node(1, -75.16, 39.95), road(60, [1, 99], "Broken Street")])
    path = write_osm(tmp_path, body)
    with pytest.raises(
        ValueError, match="way 60 \\('Broken Street'\\) references node 99"
    ) as excinfo:
        read_street_ways(path)
    assert str(path) in str(excinfo.value)


def test_missing_node_on_dropped_way_is_ignored(tmp_path):
    """Only kept ways are checked: a broken footway doesn't fail the file."""
    body = "\n".join(
        [
            node(1, -75.16, 39.95),
            node(2, -75.15, 39.95),
            road(70, [1, 2]),
            '<way id="71" version="1"><nd ref="1"/><nd ref="99"/>'
            '<tag k="highway" v="footway"/><tag k="name" v="Path"/></way>',
        ]
    )
    assert way_ids(read_street_ways(write_osm(tmp_path, body))) == [70]


def test_missing_file_raises_runtime_error(tmp_path):
    with pytest.raises(RuntimeError, match="No such file"):
        read_street_ways(tmp_path / "missing.osm.pbf")
