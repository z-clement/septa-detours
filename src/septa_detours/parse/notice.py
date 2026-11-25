"""Assemble ``DetourNotice`` objects from raw API entries.

The field parsers raise ``ValueError``; this module is the only place that
catches it, turning each failure into ``None`` plus an ``issues`` entry
prefixed with the field name, e.g. ``"start: unparseable '...'"``.
"""

from septa_detours.model import DetourNotice
from septa_detours.parse._api import ApiDetour, ApiRoute


def make_source_key(route_id: str, location_start: str, start: str) -> str:
    """Hash the fields that loosely identify a detour across snapshots.

    Args:
        route_id: Raw API route ID.
        location_start: Raw ``location_start``.
        start: Raw ``start``.

    Returns:
        A short hex digest. Inputs are normalized first (decide how: case,
        whitespace) so cosmetic edits between snapshots keep the same key.

    Not an identity (see ``DetourNotice.source_key``): route 68 #0/#1 are
    the same detour posted twice one minute apart and get different keys,
    and two genuinely different detours could share one.
    """
    # TODO: normalize, join with a separator that can't appear in the
    #   inputs (or can't be confused), hash with hashlib (stdlib).
    raise NotImplementedError


def parse_detour(route: ApiRoute, detour: ApiDetour, snapshot: str) -> DetourNotice:
    """Parse one API detour item into a ``DetourNotice``.

    Never raises for messy text: every problem becomes ``None`` plus an
    issue. (A bug, e.g. a ``CleanText`` violation, should still raise.)

    Args:
        route: The route entry the item belongs to (gives ``route_id``,
            ``mode``).
        detour: The detour item.
        snapshot: Snapshot file name, e.g. ``"2026-11-25T025344Z.json"``.

    Returns:
        The notice, with ``source`` holding the raw strings verbatim.

    Decisions this function owns (each needs a test):
        - Directions: exactly one found -> it; none -> ``None`` + issue;
          two or more different -> ``None`` + issue (never pick one).
        - ``end`` earlier than ``start`` -> keep both, add an issue.
        - Message text vs API fields (route 44 #3 says "until 11/23", API
          end is 11/24): API fields win. Whether to flag the mismatch is
          open; detecting it means parsing message dates, which is out of
          scope for now.
        - Recurring windows ("7am - 4pm Mon thru Fri"): not modelled; open
          whether this should add an issue (it would make most notices
          ``partial``).
        - Stop closures vs reroutes: the model has no ``kind`` field yet.
          Adding one changes ``model.py`` (flag it first).
    """
    # TODO: build SourceText, call each field parser, collect issues.
    raise NotImplementedError


def parse_snapshot(content: bytes, snapshot: str) -> list[DetourNotice]:
    """Parse every detour item in a raw snapshot.

    Args:
        content: The snapshot file's bytes, as ingest saved them.
        snapshot: The snapshot's file name (stored on each notice).

    Returns:
        One notice per detour item, in API order (route order, then list
        order). Routes with no detours contribute nothing.

    Raises:
        pydantic.ValidationError: If the snapshot's structure is wrong
            (see ``_api.read_snapshot``).
    """
    # TODO
    raise NotImplementedError
