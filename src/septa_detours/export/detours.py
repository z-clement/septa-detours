"""Build GeoJSON for matched detours (pure; no file I/O).

Reads ``Detour``s only (``model.py``); never reaches into ``parse/`` or
``match/``. Feature types and the generic builders live in ``geojson.py``.
"""

from datetime import datetime

from septa_detours.export.geojson import Properties
from septa_detours.model import Detour

ISSUE_SEPARATOR = "; "


def _iso(moment: datetime | None) -> str | None:
    """ISO 8601 with the offset kept (``2026-11-25T15:00:00-05:00``)."""
    return None if moment is None else moment.isoformat()


def detour_properties(detour: Detour) -> Properties:
    """Flatten one detour's own fields into feature properties.

    Route-level properties (``route_id``, colors, ...) aren't included: the
    caller merges ``route_properties`` in, since it needs the GTFS routes
    table. Neither is ``node_id``, which only the start point has.

    Every value is a string or ``None`` (MapLibre turns nested values into
    JSON strings, so nothing nested goes in):

    - ``start`` / ``end``: ISO 8601 with the UTC offset as parsed.
    - ``issues``: parse issues, then match issues, joined with ``"; "``;
      ``None`` if there are none. For reading, not for parsing back: the
      detours JSON keeps them as a list.
    - ``message``: the API text verbatim.
    - ``status``: the notice's ``status`` property.
    - Anything the notice couldn't determine is ``None``, never ``""``.
    """
    notice = detour.notice
    issues = (*notice.issues, *detour.issues)
    return {
        "source_key": notice.source_key,
        "status": notice.status,
        "direction": notice.direction,
        "location_start": notice.location_start,
        "location_end": notice.location_end,
        "start": _iso(notice.start),
        "end": _iso(notice.end),
        "reason": notice.reason,
        "message": notice.source.message,
        "issues": ISSUE_SEPARATOR.join(issues) if issues else None,
    }
