"""Tests for parse/hours.py: a detour's daily hours from its message.

Messages are real (verbatim from the 2026-11-25/26 snapshots) unless a
test says it's hand-built.
"""

from datetime import time

import pytest

from septa_detours.model import DailyHours
from septa_detours.parse.hours import EVERY_DAY, parse_daily_hours

WEEKDAYS = (0, 1, 2, 3, 4)


def hours(message: str) -> tuple[tuple[int, ...], str, str] | None:
    """The parsed hours as ``(days, "HH:MM", "HH:MM")``, for whole comparisons."""
    parsed = parse_daily_hours(message)
    if parsed is None:
        return None
    return (parsed.days, parsed.start.strftime("%H:%M"), parsed.end.strftime("%H:%M"))


def test_returns_daily_hours() -> None:
    message = (
        "7am - 4pm, Mon - Fri until 11/30/26, NB via Nedro, Right on 20th St, "
        "Left on Chelten Ave, Right on Wister, Reg Rt"
    )
    assert parse_daily_hours(message) == DailyHours(
        days=WEEKDAYS, start=time(7), end=time(16)
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # Hours, then days.
        (
            "6am - 6pm Mon - Fri, Until 6/30/27, NB via Malvern, Right on 64th, "
            "Left on Lebanon, Left on Wynnewood, Right on Malvern, Reg Rt",
            (WEEKDAYS, "06:00", "18:00"),
        ),
        # Days, then hours; half hours.
        (
            "Mon - Fri 8:30am - 3pm until, 11/27/26, SB via Tacony St, Right on "
            "Harbison Ave, Left on Bridge St, Reg Rt",
            (WEEKDAYS, "08:30", "15:00"),
        ),
        # "Friday" spelled out.
        (
            "Mon - Friday 7am - 4pm, Until 11/27/26, SB via Pine St, Left on W "
            "Brown St, Right on Powell St, Right on W Fornance St, Reg Rt",
            (WEEKDAYS, "07:00", "16:00"),
        ),
        # "thru", and the date after a comma (not a "Fri 12/26" label).
        (
            "Mon thru Fri 7am -5:30pm, 12/26/26, NB via Ridge Ave, Stay on Ridge "
            "Ave, Reg Rt",
            (WEEKDAYS, "07:00", "17:30"),
        ),
        # Days and no "until".
        (
            "7am - 4pm Mon thru Fri, 11/27/26, SB via 17th, Left on Washington, "
            "Right on Broad, Right on Passyunk, Left on 17th, Reg Rt",
            (WEEKDAYS, "07:00", "16:00"),
        ),
        (
            "7am - 3pm weekdays, until 11/30/26, EB via Graysferry, Reg Rt",
            (WEEKDAYS, "07:00", "15:00"),
        ),
        (
            "Weekdays 6am - 3pm Until, 1/1/27, WB via 41st St, Left on  Powelton "
            "Ave, Right on 42nd St, Left on Haverford Ave, Reg Rt",
            (WEEKDAYS, "06:00", "15:00"),
        ),
        # The range split by a comma.
        (
            "Weekdays only 7:40 am -, 6:00 pm, SB via Darby Road, Left on West "
            "Chester Pike, Left on Township Line, Regular Route",
            (WEEKDAYS, "07:40", "18:00"),
        ),
        # Two days listed.
        (
            "9am - 3pm, Mon & Tues until 11/25/26, NB via Mt Pleasant, Right on "
            "Creshem, Left on Sedgwick, Left on Chew, Right on Mt Pleasant, Reg Rt",
            ((0, 1), "09:00", "15:00"),
        ),
        # Overnight.
        (
            "Monday thru Wednesday, 7:00PM to 5:00AM, NB via JFK Blvd, Right on "
            "20th, Left on  Ben Franklinn Pkwy, Reg Rt",
            ((0, 1, 2), "19:00", "05:00"),
        ),
        # No days, "until" a date: every day. "330pm" is 3:30 pm.
        (
            "7am -330pm until 11/25/26, NB via Pratt, Right on Lorretto, Left on "
            "Oxford, Reg Rt",
            (EVERY_DAY, "07:00", "15:30"),
        ),
        (
            "7am - 4pm until 1/1/27, EB via Tabor Rd, Left on  Wagner Ave, Right "
            "on Olney Ave, Right on 5th St, Left on Tabor Rd, Reg Rt",
            (EVERY_DAY, "07:00", "16:00"),
        ),
    ],
)
def test_real_daily_hours(message: str, expected: tuple) -> None:
    assert hours(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        # 24/7, even with an end time.
        "24/7 until 4pm 12/30/26, (CTC Trips ), EB via Batrum Ave, Right on 89th "
        "St, Left on Tinicum Blvd, Reg Rt",
        "24/7 Mon - Sun, until 12/31/26 discontinued, bus stop NB Broad St &, Arch St",
        # A range on one date: start/end already cover it.
        "2am - 10pm on 11-26-26, WB via Broad, Right on Walnut, Right on "
        "Schuylkill Ave, Left on Market, Reg Rt",
        "7am - 3pm on 11/25/26, EB via Wyoming, Right on Whitaker, Left on Hunting "
        "Park, Left on G, Right on Wyoming, Reg Rt",
        "3pm - 2am 11/25/26, - 11/26/26, NB via 22nd, Right on Chestnut, Left on "
        "13th, Left on Vine, Right on 16th L-Spring Garden, Reg Rt",
        # Times that aren't a range.
        "3pm on 11/25/26 to 2am on, 11/26/26, EB via 30th St, Left on Chestnut "
        "Sts, Reg Rt",
        "Until 2am on Thurs 11/26/26, NB via 16th St, Right on Locust St, Reg Rt",
        "Until 23:59 on 12/31/26, Discontinued transit stops, @ 32nd & Grays "
        "Ferry, Eastbound",
        # No times at all.
        "Until Further Notice",
        "",
    ],
)
def test_no_daily_hours(message: str) -> None:
    assert parse_daily_hours(message) is None


def test_only_the_text_before_the_path_counts() -> None:
    # Hand-built: a range after "via" (glued on too) is part of the path.
    assert (
        parse_daily_hours("until 7pm 11/25/26, WB viaTasker, 9am - 3pm Mon - Fri")
        is None
    )
    assert (
        parse_daily_hours("Until 12/1/26, SB via 17th, Layover 9am - 3pm Weekdays")
        is None
    )


def test_a_day_naming_a_date_is_not_a_recurrence() -> None:
    # Hand-built: "Thurs 11/26/26" labels the date; no days, no until.
    assert parse_daily_hours("7am - 4pm on Thurs 11/26/26, SB via 17th, Reg Rt") is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # Hand-built forms the days reading handles.
        ("Sat - Sun 8am - 6pm until 12/1/26, SB via 17th", ((5, 6), "08:00", "18:00")),
        ("Weekends 8am - 6pm until 12/1/26, SB via 17th", ((5, 6), "08:00", "18:00")),
        (
            "Fri - Mon 9am - 5pm until 12/1/26, SB via 17th",
            ((0, 4, 5, 6), "09:00", "17:00"),
        ),
        ("Weds. 9am - 5pm until 12/1/26", ((2,), "09:00", "17:00")),
        ("Tue & Thurs 9am - 5pm until 12/1/26", ((1, 3), "09:00", "17:00")),
        # 12 am/pm, a 24-hour end, dots in a.m.
        ("Mon - Fri 12am - 12pm until 12/1/26", (WEEKDAYS, "00:00", "12:00")),
        ("Mon - Fri 7am - 23:30 until 12/1/26", (WEEKDAYS, "07:00", "23:30")),
        # A 24-hour 00:30: overnight.
        ("Mon - Fri 19:00 - 00:30 until 12/1/26", (WEEKDAYS, "19:00", "00:30")),
        ("Mon - Fri 7 a.m. - 4 p.m. until 12/1/26", (WEEKDAYS, "07:00", "16:00")),
    ],
)
def test_hand_built_forms(message: str, expected: tuple) -> None:
    assert hours(message) == expected


@pytest.mark.parametrize(
    ("message", "error"),
    [
        # Real: is 11:59 morning or night?
        (
            "Mon - Tues 9am -11:59 until, 11/23/26, EB via Market St, Right on 2nd "
            "St, Reg Rt",
            "no am/pm in '11:59'",
        ),
        # Hand-built: 12:30 with no am/pm is either too.
        ("Mon - Fri 7am - 12:30 until 12/1/26", "no am/pm in '12:30'"),
        ("Mon - Fri 13pm - 4pm until 12/1/26", "impossible time '13pm'"),
        ("Mon - Fri 7:75am - 4pm until 12/1/26", "impossible time '7:75am'"),
        ("Mon - Fri 7:60am - 4pm until 12/1/26", "impossible time '7:60am'"),
        ("Mon - Fri 7am - 24:00 until 12/1/26", "impossible time '24:00'"),
        ("Mon - Fri 0am - 4pm until 12/1/26", "impossible time '0am'"),
        ("Mon - Fri 7am - 7am until 12/1/26", "start and end are the same"),
    ],
)
def test_unreadable_hours(message: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        parse_daily_hours(message)
