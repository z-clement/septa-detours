"""Warn when a GTFS feed is about to run out (shared, not a stage).

SEPTA's feeds say how long they're valid (``feed_info.txt``,
``feed_end_date``, ``YYYYMMDD``). GTFS is downloaded by hand, so the
hosted job checks this and logs a warning for the maintainer; riders see
nothing. The check never fails the job: an old feed still beats no map.
"""

import re
from datetime import date

WARN_WITHIN_DAYS = 14
"""Warn this many days before ``feed_end_date`` (inclusive) and after it."""

_GTFS_DATE = re.compile(r"([0-9]{4})([0-9]{2})([0-9]{2})")
"""ASCII digits only: ``\\d`` would also accept e.g. Arabic-Indic digits."""


def end_date_warning(
    feed: str,
    feed_end_date: str | None,
    today: date,
    within_days: int = WARN_WITHIN_DAYS,
) -> str | None:
    """A warning line if ``feed``'s GTFS ends within ``within_days``, else None.

    ``feed_end_date`` is the last day of service (GTFS: inclusive), so on
    that day the feed "ends today" and the day after it "ended 1 day ago".
    Exactly ``within_days`` left still warns. A missing or unreadable date
    also gives a warning rather than an error: it's worth a look, and
    this check must never stop the job.
    """
    end = _parse_gtfs_date(feed_end_date)
    if end is None:
        return f"{feed} GTFS: can't read feed_end_date {feed_end_date!r}"
    days_left = (end - today).days
    if days_left > within_days:
        return None
    if days_left > 0:
        when = f"ends {end.isoformat()}, in {_days(days_left)}"
    elif days_left == 0:
        when = f"ends {end.isoformat()}, today"
    else:
        when = f"ended {end.isoformat()}, {_days(-days_left)} ago"
    return f"{feed} GTFS {when}: download a new feed"


def _parse_gtfs_date(text: str | None) -> date | None:
    """``YYYYMMDD`` as a date; None if missing, not 8 digits, or not a real day."""
    if text is None:
        return None
    match = _GTFS_DATE.fullmatch(text)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"
