"""Assemble ``DetourNotice`` objects from raw API entries.

The field parsers raise ``ValueError``; this module is the only place that
catches it, turning each failure into ``None`` plus an ``issues`` entry
prefixed with the field name, e.g. ``"start: unparseable '...'"``.
"""

import hashlib
import json

from septa_detours.model import DetourNotice
from septa_detours.parse._api import ApiDetour, ApiRoute
from septa_detours.parse.text import clean_text

SOURCE_KEY_LENGTH = 16
"""Hex characters kept from the SHA-256 digest (64 bits)."""


def make_source_key(route_id: str, location_start: str, start: str) -> str:
    """Hash the fields that loosely identify a detour across snapshots.

    Each field is normalized with ``clean_text`` (whitespace runs collapse
    to one space, ends stripped; blank becomes ``""``) and then casefolded,
    so cosmetic edits between snapshots keep the same key. Nothing else is
    forgiven: ``"9:30"`` and ``"09:30"`` give different keys.

    The three fields are hashed as a JSON list, so text can't shift
    between fields and collide: ``("Broad &", "Walnut")`` and
    ``("Broad", "& Walnut")`` differ.

    Args:
        route_id: Raw API route ID.
        location_start: Raw ``location_start``.
        start: Raw ``start``.

    Returns:
        The first ``SOURCE_KEY_LENGTH`` hex characters of the SHA-256
        digest. Changing the normalization or hashing changes every key.

    Not an identity (see ``DetourNotice.source_key``): route 68 #0/#1 are
    the same detour posted twice one minute apart and get different keys,
    and two genuinely different detours could share one.
    """
    fields = [
        (clean_text(raw) or "").casefold() for raw in (route_id, location_start, start)
    ]
    payload = json.dumps(fields).encode()
    return hashlib.sha256(payload).hexdigest()[:SOURCE_KEY_LENGTH]


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
