"""Static GTFS reference data for SEPTA's bus and rail feeds.

Shared by the pipeline stages; not a stage itself. Returns Polars frames
and plain coordinate lists only, with no shapely or projected geometry
(that belongs in ``match/``).
"""
