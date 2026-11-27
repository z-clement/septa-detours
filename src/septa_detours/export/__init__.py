"""Export stage: turn matched data into the web map's files.

``site`` builds the data contract (``contract``: JSON and GeoJSON in
``web/data/``) from the match output and GTFS; ``deploy`` builds the copy
of ``web/`` that is published. ``geojson``, ``simplify`` and ``write``
are their helpers.
"""
