"""Write GeoJSON to disk for the web map.

The only file I/O in ``export/``. Uses stdlib ``json``; no extra
dependency needed.
"""

from pathlib import Path

from septa_detours.export.geojson import FeatureCollection
from septa_detours.gtfs.load import Feed

# The path assumes you run from the repo root
DEFAULT_WEB_DATA_DIR = Path("web/data")


def route_geojson_path(
    feed: Feed, route_id: str, root: Path = DEFAULT_WEB_DATA_DIR
) -> Path:
    """Return where a route's GeoJSON file goes, e.g. ``web/data/bus-21.geojson``.

    Edge cases:
        - Include ``feed`` in the name: ``route_id`` is only unique within
          a feed.
        - ``route_id`` comes from data, not code. Could it ever contain a
          ``/`` or other character that's unsafe in a filename?
    """
    # TODO: build the path.
    raise NotImplementedError


def write_geojson(collection: FeatureCollection, path: Path) -> None:
    """Write ``collection`` to ``path`` as JSON.

    Edge cases:
        - Create the parent directory if it doesn't exist.
        - NaN/Infinity aren't valid JSON, but ``json.dump`` writes them by
          default. Look at its ``allow_nan`` parameter.
        - Pick an explicit encoding when opening the file.
    """
    # TODO: mkdir parents, open, json.dump.
    raise NotImplementedError
