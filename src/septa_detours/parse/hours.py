"""Read a detour's daily hours from its message (UI plan U8).

``"7am - 4pm, Mon - Fri until 11/30/26, SB via Wister, ..."`` -> it runs
7:00 to 16:00 on weekdays, within its overall dates. Only the text
before the path (``via``) is read. A message with no daily hours gives
``None``; one whose hours can't be read without guessing raises, so the
caller can flag it.

Daily means a time range plus either days ("Mon - Fri", "Weekdays",
"Mon & Tues") or ``until`` a date (every day). A range on one date
("2am - 10pm on 11-26-26") isn't daily: parse's start and end already
cover it. Measured on the 2026-11-25/26 snapshots: 44 of 163 distinct
messages give daily hours (``docs/ui-plan.md``, U8 plan).
"""

import re
from datetime import time

from septa_detours.model import DailyHours

_VIA = re.compile(r"\bvia\b|\bvia(?=[A-Z])", re.IGNORECASE)
"""Where the path starts (as ``steps._VIA``: ``viaTasker`` too)."""

_TIME = r"(?:\d{1,2}(?::?\d{2})?\s*[ap]\.?\s*m\b\.?|\d{1,2}:\d{2})"
"""A time: with am/pm (``7am``, ``8:30am``, ``330pm``, ``7:00PM``,
``7:40 am``), or ``h:mm`` with none (``23:59``; ``11:59``: ambiguous)."""

_RANGE = re.compile(
    rf"(?P<start>{_TIME})\s*(?:-|to|thru)\s*(?P<end>{_TIME})", re.IGNORECASE
)
"""Two times joined by ``-``, ``to`` or ``thru`` (commas already spaces)."""

_PARTS = re.compile(
    r"(?P<hour>\d{1,2}?)(?::?(?P<minute>\d{2}))?\s*(?:(?P<half>[ap])\.?\s*m\.?)?$",
    re.IGNORECASE,
)
"""One time's hour, minute and am/pm (``330pm``: 3, 30, p)."""

_DAY_NAMES = (
    ("mon", "monday"),
    ("tue", "tues", "tuesday"),
    ("wed", "weds", "wednesday"),
    ("thu", "thur", "thurs", "thursday"),
    ("fri", "friday"),
    ("sat", "saturday"),
    ("sun", "sunday"),
)
_DAY_INDEX = {name: index for index, names in enumerate(_DAY_NAMES) for name in names}
_DAY = r"(?:" + "|".join(sorted(_DAY_INDEX, key=len, reverse=True)) + r")\.?"

_DATE_LABEL = re.compile(rf"\b{_DAY}\s+\d{{1,2}}[/-]\d{{1,2}}", re.IGNORECASE)
"""A day naming a date (``on Thurs 11/26/26``), not a recurrence: ignored.
Matched before commas become spaces: in ``Mon thru Fri, 12/26/26`` the
comma shows ``Fri`` ends the range."""

_DAY_RANGE = re.compile(
    rf"\b(?P<first>{_DAY})\s*(?:-|thru|through|to)\s*(?P<last>{_DAY})(?![a-z])",
    re.IGNORECASE,
)
_ONE_DAY = re.compile(rf"\b(?P<day>{_DAY})(?![a-z])", re.IGNORECASE)
_WEEKDAYS = re.compile(r"\bweekdays?\b", re.IGNORECASE)
_WEEKENDS = re.compile(r"\bweekends?\b", re.IGNORECASE)
_UNTIL = re.compile(r"\buntil\b", re.IGNORECASE)

EVERY_DAY = (0, 1, 2, 3, 4, 5, 6)


def parse_daily_hours(message: str) -> DailyHours | None:
    """When the detour runs each day, from the start of its message.

    Returns:
        The hours, or ``None`` when the message gives no daily hours: no
        time range (``24/7`` messages have none), or a range on one date
        (no days and no ``until``).

    Raises:
        ValueError: A daily range that can't be read without guessing: a
            time with no am/pm that could be either (``"9am -11:59"``), an
            impossible time, or a start equal to its end.
    """
    via = _VIA.search(message)
    head = message if via is None else message[: via.start()]
    # Date labels before commas go: "Fri, 12/26/26" ends a day range.
    head = _DATE_LABEL.sub(" ", head).replace(",", " ")
    found = _RANGE.search(head)
    if found is None:
        return None
    days = _days(head[: found.start()] + " " + head[found.end() :])
    if days is None and _UNTIL.search(head) is None:
        return None
    start = _time(found["start"], found[0])
    end = _time(found["end"], found[0])
    if start == end:
        raise ValueError(f"start and end are the same in {found[0]!r}")
    return DailyHours(days=days or EVERY_DAY, start=start, end=end)


def _days(text: str) -> tuple[int, ...] | None:
    """The weekdays named in ``text`` (ascending), or ``None`` if none.

    ``Mon - Fri`` / ``Mon thru Fri`` are ranges (inclusive; ``Fri - Mon``
    wraps; their end days are read again as single days, which adds
    nothing), ``Mon & Tues`` lists, ``Weekdays`` is Mon-Fri, ``Weekends``
    Sat-Sun. Date labels are already gone (``parse_daily_hours``).
    """
    days: set[int] = set()
    if _WEEKDAYS.search(text):
        days.update(range(5))
    if _WEEKENDS.search(text):
        days.update((5, 6))
    for found in _DAY_RANGE.finditer(text):
        first, last = _day(found["first"]), _day(found["last"])
        days.update((first + step) % 7 for step in range((last - first) % 7 + 1))
    days.update(_day(found["day"]) for found in _ONE_DAY.finditer(text))
    return tuple(sorted(days)) or None


def _day(name: str) -> int:
    return _DAY_INDEX[name.rstrip(".").casefold()]


def _time(text: str, context: str) -> time:
    """One time of a range (``context``: the whole range, for errors)."""
    parts = _PARTS.match(text.strip())
    if parts is None:
        raise ValueError(f"unreadable time {text!r} in {context!r}")
    hour = int(parts["hour"])
    minute = int(parts["minute"] or 0)
    half = parts["half"]
    if minute > 59:
        raise ValueError(f"impossible time {text!r} in {context!r}")
    if half is None:
        # h:mm with no am/pm: only a 24-hour reading is unambiguous.
        if hour > 23:
            raise ValueError(f"impossible time {text!r} in {context!r}")
        if hour == 0 or hour >= 13:
            return time(hour, minute)
        raise ValueError(f"no am/pm in {text!r} ({context!r}): morning or evening?")
    if not 1 <= hour <= 12:
        raise ValueError(f"impossible time {text!r} in {context!r}")
    return time(hour % 12 + (12 if half.casefold() == "p" else 0), minute)
