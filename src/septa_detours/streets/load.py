"""Read named roads from an OSM extract into a Polars DataFrame.

Works on any file pyosmium can read: Geofabrik's ``.osm.pbf`` extracts in
real use, small hand-written ``.osm`` XML files in tests.
"""

from pathlib import Path

import osmium
import polars as pl

# OSM highway=* values a bus can drive on (and that alerts name). Left out:
# footway, path, cycleway, pedestrian, steps, track, bridleway, corridor
# (not for buses), and construction/proposed (not open yet).
ROAD_TYPES = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "service",
        "busway",
    }
)

# (west, south, east, north) in degrees, i.e. (min lon, min lat, max lon, max lat).
type BBox = tuple[float, float, float, float]

STREET_WAYS_SCHEMA = pl.Schema(
    {
        "way_id": pl.Int64,
        "name": pl.String,
        "highway": pl.String,
        "node_ids": pl.List(pl.Int64),
        # One [lon, lat] pair per node, in node order (GeoJSON order).
        "coordinates": pl.List(pl.List(pl.Float64)),
    }
)


def read_street_ways(path: Path, bbox: BBox | None = None) -> pl.DataFrame:
    """Return every named road way in an OSM file, one row per way.

    A way is kept when it has a ``name`` tag and its ``highway`` tag is in
    ``ROAD_TYPES``. Rows are in file order. Names are exactly as OSM has
    them (``"North Broad Street"``); normalizing them is ``match/``'s job.
    Only nodes and ways are read; relations are skipped.

    OSM way IDs are global, so there's no source column. The same way can
    be in two extracts (a road crossing a state border is in both);
    callers combining extracts must drop those duplicates.

    Args:
        path: An ``.osm.pbf`` (or ``.osm`` XML) file.
        bbox: ``(west, south, east, north)``. If given, keep only ways with
            at least one node inside the box (edges count as inside); the
            whole way is kept, so long roads crossing the edge stay intact.
            ``None`` keeps every way.

    Returns:
        A frame with ``STREET_WAYS_SCHEMA``.

    Raises:
        ValueError: If a kept way references a node with no location
            (missing from the file). Geofabrik extracts include every node
            of every way, so this means a broken file, not a normal edge.
        RuntimeError: From pyosmium, if the file can't be opened or read.
    """
    processor = (
        osmium.FileProcessor(str(path), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    )

    columns: dict[str, list] = {name: [] for name in STREET_WAYS_SCHEMA}
    for way in processor:
        highway = way.tags.get("highway")
        name = way.tags.get("name")
        if highway not in ROAD_TYPES or name is None:
            continue

        node_ids: list[int] = []
        coordinates: list[list[float]] = []
        for node in way.nodes:
            location = node.location
            if not location.valid():
                msg = (
                    f"way {way.id} ({name!r}) references node {node.ref}, "
                    f"which has no location in {path}"
                )
                raise ValueError(msg)
            node_ids.append(node.ref)
            coordinates.append([location.lon, location.lat])

        if bbox is not None and not any(_inside(point, bbox) for point in coordinates):
            continue

        columns["way_id"].append(way.id)
        columns["name"].append(name)
        columns["highway"].append(highway)
        columns["node_ids"].append(node_ids)
        columns["coordinates"].append(coordinates)

    return pl.DataFrame(columns, schema=STREET_WAYS_SCHEMA)


def _inside(point: list[float], bbox: BBox) -> bool:
    """Return whether ``[lon, lat]`` is inside ``bbox``, edges included."""
    west, south, east, north = bbox
    lon, lat = point
    return west <= lon <= east and south <= lat <= north
