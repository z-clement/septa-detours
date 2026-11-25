"""Parse the API's ``start``/``end`` strings into aware datetimes."""

from datetime import datetime
from zoneinfo import ZoneInfo

SEPTA_ZONE = ZoneInfo("America/New_York")
"""The API gives local times with no zone; SEPTA's local time is New York."""


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

    DST edge cases (decide, then test):
        - Fall back: ``1:30 AM`` on the first Sunday of November happens
          twice. ``zoneinfo`` picks the first (``fold=0``) silently.
        - Spring forward: ``2:30 AM`` on the second Sunday of March never
          happens. ``zoneinfo`` accepts it anyway without complaint.
        Raise, or accept and note? The model only has ``issues`` per notice,
        so a function that both returns a value and warns needs a design.
    """
    # TODO: normalize the spacing, parse with a fixed format, attach
    #   SEPTA_ZONE. Parse only this API format; don't accept "whatever
    #   looks like a date" (that is how guessing creeps in).
    raise NotImplementedError
