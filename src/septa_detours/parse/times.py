"""Parse the API's ``start``/``end`` strings into aware datetimes."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from septa_detours.parse.text import clean_text

SEPTA_ZONE = ZoneInfo("America/New_York")
"""The API gives local times with no zone; SEPTA's local time is New York."""

API_DATETIME_FORMAT = "%m/%d/%Y %I:%M %p"
"""The API format after spacing is collapsed: ``"11/25/2026 3:00 PM"``.

``strptime`` accepts ``%m``/``%d``/``%I`` with or without a leading zero,
and ``%p`` in any case. Every fixture value (108) has this shape.
"""


def parse_api_datetime(raw: str) -> datetime:
    """Parse an API timestamp such as ``"11/25/2026   3:00 PM"``.

    The API pads with a varying number of spaces (``"12/1/2026  11:59 PM"``),
    and month/day may or may not have a leading zero.

    Args:
        raw: The raw ``start`` or ``end`` string.

    Returns:
        An aware datetime in ``SEPTA_ZONE``.

    Raises:
        ValueError: If ``raw`` is blank or doesn't match the format. The
            message quotes ``raw`` so it can go straight into ``issues``.

    DST edge cases are accepted, not raised: the value is at most an hour
    off, and losing the whole date would be worse. ``local_time_issue``
    flags them separately, and ``parse_detour`` records that in ``issues``.
    - Fall back: ``1:30 AM`` on the first Sunday of November happens
      twice. ``strptime`` gives ``fold=0``, so this reads it as the first
      (daylight time).
    - Spring forward: ``2:30 AM`` on the second Sunday of March never
      happens. It is kept with the pre-change offset, i.e. the instant
      ``3:30 AM`` daylight time.
    """
    # Only this API format is accepted; "whatever looks like a date" is how
    # guessing creeps in.
    text = clean_text(raw)
    if text is None:
        msg = f"blank datetime {raw!r}"
        raise ValueError(msg)
    try:
        naive = datetime.strptime(text, API_DATETIME_FORMAT)  # noqa: DTZ007
    except ValueError:
        msg = f"unrecognized datetime {raw!r}"
        raise ValueError(msg) from None
    return naive.replace(tzinfo=SEPTA_ZONE)


def local_time_issue(moment: datetime) -> str | None:
    """Describe why ``moment``'s wall time is doubtful, or ``None`` if it isn't.

    A wall time can be doubtful in two ways around a DST change in
    ``moment.tzinfo``:

    - Nonexistent (spring-forward gap): the wall time doesn't survive a
      round trip through UTC. ``2:30 AM`` comes back as ``3:30 AM``.
    - Ambiguous (fall-back overlap): flipping ``fold`` changes the UTC
      offset, because the wall time happens twice.

    The gap is checked first: in a gap, flipping ``fold`` also changes the
    offset (PEP 495), so the overlap test alone would misreport it.

    Args:
        moment: An aware datetime, normally from ``parse_api_datetime``.

    Returns:
        A short reason for ``issues`` (stating how the time was read), or
        ``None``. A fixed-offset zone never gives an issue.

    Raises:
        ValueError: If ``moment`` is naive. That is a caller bug, not messy
            input: there's no zone to check against.

    Examples (``SEPTA_ZONE``):
        ``2027-03-14 02:30`` -> ``"nonexistent local time 2027-03-14 02:30
        (DST gap); read as 03:30 EDT"``;
        ``2027-11-07 01:30`` (fold 0) -> ``"ambiguous local time
        2027-11-07 01:30 (DST overlap); read as EDT"``;
        ``2026-11-25 15:00`` -> ``None``.
    """
    if moment.utcoffset() is None:
        msg = f"naive datetime {moment!r}"
        raise ValueError(msg)
    resolved = moment.astimezone(UTC).astimezone(moment.tzinfo)
    if resolved.replace(tzinfo=None) != moment.replace(tzinfo=None):
        return (
            f"nonexistent local time {moment:%Y-%m-%d %H:%M} (DST gap); "
            f"read as {resolved:%H:%M %Z}"
        )
    if moment.replace(fold=1 - moment.fold).utcoffset() != moment.utcoffset():
        return (
            f"ambiguous local time {moment:%Y-%m-%d %H:%M} (DST overlap); "
            f"read as {moment:%Z}"
        )
    return None
