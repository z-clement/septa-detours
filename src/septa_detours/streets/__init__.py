"""OpenStreetMap street reference data, read from Geofabrik extracts.

Shared by the pipeline stages; not a stage itself (like ``gtfs/``). Reads
the raw ``.osm.pbf`` files that ``ingest/osm.py`` saves and returns Polars
frames with plain ``[lon, lat]`` coordinate lists only: no shapely, no
projection, and no interpretation of street names (that's ``match/``).
"""
