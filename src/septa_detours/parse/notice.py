"""Assemble ``DetourNotice`` objects from raw API entries.

The field parsers raise ``ValueError``; this module is the only place that
catches it, turning each failure into ``None`` plus an ``issues`` entry
prefixed with the field name, e.g. ``"start: unparseable '...'"``.
"""

import hashlib
import json
from datetime import UTC, datetime

from septa_detours.model import DetourNotice, Direction, Location, SourceText
from septa_detours.parse._api import ApiDetour, ApiRoute, read_snapshot
from septa_detours.parse.direction import find_directions
from septa_detours.parse.hours import parse_daily_hours
from septa_detours.parse.location import parse_location
from septa_detours.parse.steps import parse_route_steps
from septa_detours.parse.text import clean_text
from septa_detours.parse.times import local_time_issue, parse_api_datetime

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

    Issues come in field order: start, end, the end-before-start check,
    location_start, then direction. Each is prefixed with its field name.

    Decisions this function owns (each needs a test):
        - Locations: ``parse_location`` result -> ``start_place`` /
          ``end_place``. Blank text -> ``None`` with no issue. Start text
          in an unrecognized form -> ``None`` + issue, e.g.
          ``"location_start: unrecognized location 'Dickinson'"``, so the
          notice is ``partial``. End text in an unrecognized form ->
          ``None`` with no issue: the end can be inferred by walking the
          detour, so it shouldn't cost ``complete`` (42 of 166 real
          notices would otherwise be ``partial`` for this alone).
        - Directions: exactly one found -> it; none -> ``None`` + issue;
          two or more different -> ``None`` + issue (never pick one).
        - ``end`` earlier than ``start`` (as real instants) -> keep both,
          add an issue. Equal times are not flagged.
        - Blank ``location_start``/``location_end``/``reason`` -> ``None``
          with no issue: a ``None`` location_start already makes the
          status ``unknown``, and blank LE/reason are normal.
        - Message text vs API fields (route 44 #3 says "until 11/23", API
          end is 11/24): API fields win. Whether to flag the mismatch is
          open; detecting it means parsing message dates, which is out of
          scope for now.
        - Daily hours ("7am - 4pm Mon thru Fri", ``parse_daily_hours``):
          ``daily_hours``, or ``None`` with no issue when the message gives
          none; hours it can't read without guessing add an ``hours:``
          issue (decided 2026-11-26: unclear beats wrong).
        - Stop closures vs reroutes: the model has no ``kind`` field yet.
          Adding one changes ``model.py`` (flag it first).
        - Route steps (``parse_route_steps``): the message's path, or
          ``()`` with no issue when it has none or it isn't recognized
          (tier B uses it when present; a missing path costs nothing).
    """
    source = SourceText(
        snapshot=snapshot,
        route_id=route.route_id,
        mode=route.mode,
        location_start=detour.location_start,
        location_end=detour.location_end,
        start=detour.start,
        end=detour.end,
        message=detour.message,
        reason=detour.reason,
    )
    start, start_issues = _parse_time("start", detour.start)
    end, end_issues = _parse_time("end", detour.end)
    issues = [*start_issues, *end_issues]
    if start is not None and end is not None and _is_before(end, start):
        issues.append("end: before start")
    start_place, start_place_issues = _parse_place(
        "location_start", detour.location_start
    )
    issues.extend(start_place_issues)
    # Unrecognized end text is not an issue (decided): the end can be
    # inferred by walking the detour, so it shouldn't cost ``complete``.
    end_place, _ = _parse_place("location_end", detour.location_end)
    direction, direction_issues = _pick_direction(detour.message)
    issues.extend(direction_issues)
    try:
        route_steps = parse_route_steps(detour.message)
    except ValueError:
        route_steps = ()
    try:
        daily_hours = parse_daily_hours(detour.message)
    except ValueError as err:
        daily_hours = None
        issues.append(f"hours: {err}")
    return DetourNotice(
        source=source,
        source_key=make_source_key(route.route_id, detour.location_start, detour.start),
        start=start,
        end=end,
        location_start=clean_text(detour.location_start),
        location_end=clean_text(detour.location_end),
        start_place=start_place,
        end_place=end_place,
        reason=clean_text(detour.reason),
        direction=direction,
        route_steps=route_steps,
        daily_hours=daily_hours,
        issues=tuple(issues),
    )


def _parse_time(field: str, raw: str) -> tuple[datetime | None, tuple[str, ...]]:
    """Parse one API time, turning problems into field-prefixed issues.

    An unparseable value gives ``None`` and one issue, e.g.
    ``"start: unrecognized datetime '...'"``. A parsed value that falls in
    a DST gap or overlap is kept, with ``local_time_issue``'s reason.
    """
    try:
        moment = parse_api_datetime(raw)
    except ValueError as error:
        return None, (f"{field}: {error}",)
    issue = local_time_issue(moment)
    return moment, () if issue is None else (f"{field}: {issue}",)


def _parse_place(field: str, raw: str) -> tuple[Location | None, tuple[str, ...]]:
    """Parse one location's text, turning problems into field-prefixed issues.

    Blank text -> ``None`` and no issue (a blank location is "not given",
    not a problem). Unrecognized text -> ``None`` and one issue, e.g.
    ``"location_start: unrecognized location 'Broad &'"``; the caller
    decides whether to keep it (``parse_detour`` drops it for the end).
    """
    if clean_text(raw) is None:
        return None, ()
    try:
        return parse_location(raw), ()
    except ValueError as error:
        return None, (f"{field}: {error}",)


def _pick_direction(message: str) -> tuple[Direction | None, tuple[str, ...]]:
    """Decide the detour's direction from the directions in its message.

    Exactly one distinct direction -> it (repeats like route 24 #0's
    "NB Via ... Recover NB On" count once). None found, or two or more
    different ones -> ``None`` plus an issue; never pick one. Conflicting
    directions are listed in message order.
    """
    directions = find_directions(message)
    if len(directions) == 1:
        return directions[0], ()
    if not directions:
        return None, ("direction: none found in message",)
    return None, (f"direction: conflicting {', '.join(directions)} in message",)


def _is_before(later: datetime, earlier: datetime) -> bool:
    """Whether ``later`` is strictly before ``earlier``, as real instants.

    Compared in UTC on purpose: same-zone aware datetimes compare by wall
    clock, which gets a DST gap wrong (``2:30 AM`` is read as 07:30 UTC,
    after a ``3:10 AM`` end at 07:10 UTC). Equal times are not "before".
    """
    return later.astimezone(UTC) < earlier.astimezone(UTC)


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
            (see ``_api.read_snapshot``). Messy text never raises: it
            becomes issues on the notice (see ``parse_detour``).
    """
    return [
        parse_detour(route, detour, snapshot)
        for route in read_snapshot(content)
        for detour in route.detour
    ]
