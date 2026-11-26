"""Shared data types passed between pipeline stages.

Two types cross a stage boundary, and every stage depends on them, so flag
any change here:

- ``DetourNotice``: what ``parse/`` learns from one API detour entry alone,
  with no GTFS knowledge. ``parse/`` produces it; ``match/`` consumes it.
- ``Detour``: a notice plus its GTFS match. ``match/`` produces it;
  ``export/`` consumes it.

Conventions:

- ``None`` on a parsed field means "could not determine", never "guessed".
  The reason goes in ``issues``.
- Raw API text is kept verbatim in ``SourceText`` so every parsed value can
  be traced back and re-parsed later.
- Only structure is validated here. Interpreting messy text belongs in
  small, pure functions in ``parse/``, not in Pydantic validators.
- Every model round-trips through JSON (``model_dump_json`` ->
  ``model_validate_json``), so ``data/processed/`` can be read back.
  ``dump_detours`` / ``read_detours`` are the file format for a list of
  ``Detour``s.

The raw API JSON shape is *not* defined here: it is ``parse/``'s private
input format.
"""

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from septa_detours.gtfs.load import Feed

type Direction = Literal["NB", "SB", "EB", "WB"]
"""Compass direction, normalized.

Real messages also write "Eastbound" and "W/B"; ``parse/`` maps those here.
No other forms (inbound, both directions) were seen on 2026-11-24. An
unrecognized form becomes ``None`` plus an issue, not a new value.
"""

type NoticeStatus = Literal["complete", "partial", "unknown"]

type CleanText = Annotated[str, Field(pattern=r"^\S(?:.*\S)?$")]
"""Non-empty text with no leading or trailing whitespace.

Parsed fields use ``CleanText | None``: blank input must become ``None``,
so ``""`` and ``"Construction "`` are rejected here as parser bugs.
"""

type DirectionId = Annotated[int, Field(ge=0, le=1)]
"""GTFS ``direction_id``. Not ``Literal[0, 1]``: that accepts ``True`` and
``1.0`` even in strict mode, while a strict ``int`` rejects both."""


class _Frozen(BaseModel):
    """Base for shared models: immutable, no unknown fields, no coercion."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class SourceText(_Frozen):
    """One API detour entry's text, verbatim (no stripping or normalizing).

    Attributes:
        snapshot: File name of the raw snapshot it came from, e.g.
            ``"2026-11-25T025344Z.json"``. A name, not a path, so processed
            data doesn't depend on where the repo lives.
        route_id: API route ID, e.g. ``"bus_route_21"``. Not a GTFS ID.
        mode: API mode, e.g. ``"Bus"``. Unreliable (trolley 15 says "Bus").
        location_start: Raw ``location_start``.
        location_end: Raw ``location_end``; may be ``""``.
        start: Raw ``start``, e.g. ``"11/25/2026   3:00 PM"``.
        end: Raw ``end``.
        message: Raw ``message`` (turn-by-turn shorthand).
        reason: Raw ``reason``; often has trailing spaces.
    """

    snapshot: str
    route_id: str
    mode: str
    location_start: str
    location_end: str
    start: str
    end: str
    message: str
    reason: str


class Intersection(_Frozen):
    """Two streets that meet, from location text like ``"17th & Washington"``.

    Attributes:
        streets: The two street names as written (cleaned, a plural type
            like ``"Sts"`` moved onto both), not normalized:
            ``("Arch St", "15th St")``. Matching names to OSM is
            ``match/``'s job.
    """

    kind: Literal["intersection"] = "intersection"
    streets: tuple[CleanText, CleanText]


class Segment(_Frozen):
    """A stretch of one street, from ``"Market St btwn 23rd & 19th Sts"``.

    Attributes:
        street: The street the stretch is on, as written.
        between: The two cross streets bounding it, as written, in text
            order (not necessarily travel order).
    """

    kind: Literal["segment"] = "segment"
    street: CleanText
    between: tuple[CleanText, CleanText]


type Location = Annotated[Intersection | Segment, Field(discriminator="kind")]
"""A structured location; ``kind`` says which, also in JSON."""


type Turn = Literal["via", "left", "right"]
"""How a detour step joins its street: ``"via"`` for the first street."""


class Step(_Frozen):
    """One leg of a detour's path, from its message: ``"Left on Washington"``.

    Attributes:
        turn: ``"via"`` for the street the detour leaves the route on
            (``"SB via 17th"``), else the turn onto ``street``.
        street: The street as written (cleaned), not normalized:
            ``"Washington"``, ``"S Penn Sq"``.
    """

    turn: Turn
    street: CleanText


class DetourNotice(_Frozen):
    """What can be learned from one API detour entry, without GTFS.

    Attributes:
        source: The verbatim entry this notice was parsed from.
        source_key: Hash of normalized ``(route_id, location_start, start)``.
            For matching detours across snapshots later. Not guaranteed
            unique or stable; nothing should rely on it as an identity.
        start: When the detour begins (America/New_York), or ``None``.
        end: When the detour ends, or ``None``.
        location_start: Cleaned start location, or ``None`` if blank.
        location_end: Cleaned end location, or ``None`` if blank.
        start_place: ``location_start`` split into street names, or
            ``None`` if it is blank (no issue) or not in a recognized form
            (with an issue).
        end_place: ``location_end`` split into street names, or ``None``
            if it is blank or not in a recognized form (no issue either
            way: the end can be inferred from the detour's path).
        reason: Stripped reason, or ``None`` if blank.
        direction: Affected direction from the message, or ``None``.
        route_steps: The detour's path from the message (``parse/steps.py``):
            the ``via`` street, then each turn, up to ``Reg Rt``. Empty
            when the message has no such path (a stop closure, a layover)
            or it isn't in a recognized form, with no issue: messages
            aren't modeled yet, and an issue would make it ``partial``.
        issues: Why fields are ``None`` or doubtful, one string each, e.g.
            ``"end: unparseable '12/1/2026  11:5 PM'"``.

    Note: ``start``/``end`` bound the detour, but the message may narrow it
    further (e.g. "7am - 4pm Mon thru Fri"). That schedule is not modeled
    yet; it stays in ``source.message``. Whether ``end`` is after ``start``
    is checked by ``parse/`` (as an issue), not rejected here.
    """

    source: SourceText
    source_key: CleanText
    start: AwareDatetime | None
    end: AwareDatetime | None
    location_start: CleanText | None
    location_end: CleanText | None
    start_place: Location | None
    end_place: Location | None
    reason: CleanText | None
    direction: Direction | None
    route_steps: tuple[Step, ...] = ()
    issues: tuple[CleanText, ...] = ()

    @property
    def status(self) -> NoticeStatus:
        """Overall parse quality, derived from the fields.

        A plain property, not a Pydantic ``computed_field``: a computed field
        is written to JSON, and ``extra="forbid"`` then refuses to read that
        JSON back.

        - ``"unknown"``: the map can't place it (no ``location_start``) or
          can't tell when it applies (neither ``start`` nor ``end``). Keep it
          off the map; list it at most.
        - ``"complete"``: ``start``, ``end``, ``location_start`` and
          ``direction`` are all known, and there are no issues.
          ``location_end`` and ``reason`` are not required: a blank
          ``location_end`` is normal (19 of 140 real entries), and the map
          doesn't need a reason.
        - ``"partial"``: anything in between, including a full set of fields
          with any issue recorded (an issue means doubt).
        """
        if self.location_start is None or (self.start is None and self.end is None):
            return "unknown"
        required = (self.start, self.end, self.location_start, self.direction)
        if self.issues or any(field is None for field in required):
            return "partial"
        return "complete"


class AffectedShape(_Frozen):
    """One GTFS shape a detour applies to.

    Attributes:
        shape_id: GTFS ``shape_id`` (a string: rail IDs have leading zeros).
        direction_id: GTFS ``direction_id`` (0 or 1), or ``None`` if the
            trips carry none. Kept because detours can affect one direction.
    """

    shape_id: CleanText
    direction_id: DirectionId | None


class StartPoint(_Frozen):
    """Where a detour leaves the regular route: one OSM street crossing.

    Attributes:
        node_id: The OSM node standing for the crossing (a real node, so a
            later path search can start from it). Positive: real OSM data
            has no negative IDs.
        lon: The node's longitude (WGS84 degrees).
        lat: The node's latitude (WGS84 degrees).

    The bounds also reject NaN and infinity, which JSON can't hold.
    """

    node_id: Annotated[int, Field(gt=0)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    lat: Annotated[float, Field(ge=-90, le=90)]


class RouteMatch(_Frozen):
    """A notice tied to the GTFS network.

    Attributes:
        feed: GTFS feed the route belongs to.
        route_id: GTFS ``route_id``, e.g. ``"21"``.
        shapes: Shapes the detour affects, in first-appearance order. Empty
            if the route matched but the affected shapes could not be
            determined.
        start_point: The crossing at the notice's start location near this
            route, or ``None`` if it could not be placed (the reason is in
            ``Detour.issues``, unless the notice has no start intersection
            at all). Required, so forgetting to look it up can't pass for
            "not found".

    The detoured path itself (coordinates or street segments) is not here
    yet; add it when ``match/`` can produce one.
    """

    feed: Feed
    route_id: CleanText
    shapes: tuple[AffectedShape, ...] = ()
    start_point: StartPoint | None


class Detour(_Frozen):
    """A parsed notice plus its GTFS match; what ``export/`` consumes.

    Attributes:
        notice: The parse result.
        match: The GTFS match, or ``None`` if matching failed. There is no
            "not attempted" state: a ``Detour`` only exists after matching.
        issues: Why matching failed or is doubtful (parse issues stay on
            ``notice.issues``).
    """

    notice: DetourNotice
    match: RouteMatch | None
    issues: tuple[CleanText, ...] = ()


# The file format between ``match/`` (writer) and ``export/`` (reader): a JSON
# list of ``Detour`` objects. Use the two functions below, not this adapter.
_DETOURS = TypeAdapter(list[Detour])


def dump_detours(detours: Sequence[Detour]) -> bytes:
    """Serialize detours as compact UTF-8 JSON with a trailing newline.

    Input order is kept. An empty sequence gives ``[]`` + newline: a snapshot
    with no detours is a real state, not an error. ``read_detours`` reads
    the output back to equal ``Detour``s.
    """
    return _DETOURS.dump_json(list(detours)) + b"\n"


def read_detours(content: bytes) -> list[Detour]:
    """Read a JSON list of ``Detour``s, as written by ``dump_detours``.

    ``[]`` is valid. Validation is the models' own (strict, unknown fields
    rejected), so a file written by an older model version fails loudly
    rather than loading with gaps.

    Raises:
        pydantic.ValidationError: On invalid JSON, a non-list top level, or
            any entry that isn't a valid ``Detour``.
    """
    return _DETOURS.validate_json(content)
