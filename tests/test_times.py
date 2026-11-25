import json
import re
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone

import pytest

from septa_detours.parse.times import (
    SEPTA_ZONE,
    local_time_issue,
    parse_api_datetime,
)


def local(*args: int) -> datetime:
    """An aware datetime in SEPTA_ZONE, e.g. ``local(2026, 11, 25, 15, 0)``."""
    return datetime(*args, tzinfo=SEPTA_ZONE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Real values, spacing as the API sends it.
        ("11/25/2026   3:00 PM", local(2026, 11, 25, 15, 0)),
        ("11/27/2026   4:00 PM", local(2026, 11, 27, 16, 0)),
        ("12/1/2026  11:59 PM", local(2026, 12, 1, 23, 59)),
        ("11/11/2026   6:30 AM", local(2026, 11, 11, 6, 30)),
        # Leading zeros optional on month, day and hour.
        ("01/05/2027 09:05 AM", local(2027, 1, 5, 9, 5)),
        ("1/5/2027 9:05 AM", local(2027, 1, 5, 9, 5)),
        # Surrounding whitespace and odd inner spacing.
        ("  11/25/2026 3:00 PM ", local(2026, 11, 25, 15, 0)),
        ("11/25/2026\t3:00  PM", local(2026, 11, 25, 15, 0)),
        # Lowercase meridiem.
        ("11/25/2026 3:00 pm", local(2026, 11, 25, 15, 0)),
    ],
)
def test_parses_api_format(raw: str, expected: datetime) -> None:
    assert parse_api_datetime(raw) == expected


@pytest.mark.parametrize(
    ("raw", "hour"),
    [
        ("11/25/2026 12:00 AM", 0),  # midnight
        ("11/25/2026 12:59 AM", 0),  # real API end on route 49
        ("11/25/2026 12:00 PM", 12),  # noon
        ("11/25/2026 1:00 AM", 1),
        ("11/25/2026 1:00 PM", 13),
    ],
)
def test_twelve_hour_clock(raw: str, hour: int) -> None:
    assert parse_api_datetime(raw).hour == hour


def test_attaches_septa_zone_not_a_fixed_offset() -> None:
    """Same wall time, different UTC offsets across DST: a real zone, not -05:00."""
    winter = parse_api_datetime("1/15/2027 3:00 PM")
    summer = parse_api_datetime("7/15/2027 3:00 PM")
    assert winter.tzinfo is SEPTA_ZONE
    assert summer.tzinfo is SEPTA_ZONE
    assert winter.utcoffset() == timedelta(hours=-5)
    assert summer.utcoffset() == timedelta(hours=-4)


@pytest.fixture
def machine_in_utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the test with the process's local time zone set to UTC."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.usefixtures("machine_in_utc")
def test_ignores_the_machine_time_zone() -> None:
    """API times are New York wall times wherever this runs (e.g. a UTC server).

    Catches ``naive.astimezone(...)``, which reads a naive datetime as the
    machine's local time and so passes only on a machine set to Eastern.
    """
    parsed = parse_api_datetime("11/25/2026 3:00 PM")
    assert parsed == local(2026, 11, 25, 15, 0)
    assert parsed.hour == 15


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_blank_raises(raw: str) -> None:
    with pytest.raises(ValueError, match=re.escape(f"blank datetime {raw!r}")):
        parse_api_datetime(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "2026-11-25 15:00",  # ISO: a different format, not guessed at
        "11/25/26 3:00 PM",  # two-digit year
        "11/25/2026 15:00 PM",  # 24-hour hour with a meridiem
        "11/25/2026 15:00",  # 24-hour, no meridiem
        "11/25/2026 3:00",  # missing meridiem
        "11/25/2026",  # date only
        "3:00 PM",  # time only
        "13/25/2026 3:00 PM",  # month 13
        "2/30/2026 3:00 PM",  # no such day
        "11/25/2026 3:60 PM",  # minute 60
        "11/25/2026 3:00 PM EST",  # trailing text
        "11/25/2026 3:00:00 PM",  # seconds
        "11/25/2026 3pm",  # message-style shorthand
        "11/25/2026   3:00",  # API-style spacing: the error quotes it as sent
    ],
)
def test_other_formats_raise_quoting_raw(raw: str) -> None:
    with pytest.raises(ValueError, match=re.escape(f"unrecognized datetime {raw!r}")):
        parse_api_datetime(raw)


def test_error_hides_strptime_chain() -> None:
    """The issue text is ours; strptime's own error is noise, not a cause."""
    with pytest.raises(ValueError, match="unrecognized datetime") as excinfo:
        parse_api_datetime("nope")
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__


def test_every_fixture_start_and_end_parses(
    read_alert_fixture: Callable[[str], bytes],
    alert_fixture_names: list[str],
) -> None:
    """All real API timestamps parse to aware SEPTA_ZONE datetimes."""
    checked = 0
    for name in alert_fixture_names:
        route = json.loads(read_alert_fixture(name))
        for detour in route["detour"]:
            for field in ("start", "end"):
                parsed = parse_api_datetime(detour[field])
                assert parsed.tzinfo is SEPTA_ZONE, (name, field)
                checked += 1
    assert checked > 0


# --- local_time_issue ---------------------------------------------------------
# DST in America/New_York: 2026-03-08 and 2027-03-14 spring forward at 2:00 AM
# (2:00-2:59 never happens); 2026-11-01 and 2027-11-07 fall back at 2:00 AM
# (1:00-1:59 happens twice).


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            (2027, 3, 14, 2, 30),
            "nonexistent local time 2027-03-14 02:30 (DST gap); read as 03:30 EDT",
        ),
        (
            (2027, 3, 14, 2, 0),
            "nonexistent local time 2027-03-14 02:00 (DST gap); read as 03:00 EDT",
        ),
        (
            (2026, 3, 8, 2, 59),
            "nonexistent local time 2026-03-08 02:59 (DST gap); read as 03:59 EDT",
        ),
        (
            (2027, 11, 7, 1, 30),
            "ambiguous local time 2027-11-07 01:30 (DST overlap); read as EDT",
        ),
        (
            (2027, 11, 7, 1, 0),
            "ambiguous local time 2027-11-07 01:00 (DST overlap); read as EDT",
        ),
        (
            (2026, 11, 1, 1, 59),
            "ambiguous local time 2026-11-01 01:59 (DST overlap); read as EDT",
        ),
    ],
)
def test_flags_doubtful_wall_times(args: tuple[int, ...], expected: str) -> None:
    assert local_time_issue(local(*args)) == expected


@pytest.mark.parametrize(
    "args",
    [
        (2027, 3, 14, 1, 59),  # just before the gap
        (2027, 3, 14, 3, 0),  # first real time after the gap
        (2027, 11, 7, 0, 59),  # just before the overlap
        (2027, 11, 7, 2, 0),  # first time after the overlap
        (2026, 11, 25, 15, 0),  # an ordinary afternoon
        (2027, 7, 15, 1, 30),  # 1:30 AM on a day with no DST change
    ],
)
def test_ordinary_wall_times_have_no_issue(args: tuple[int, ...]) -> None:
    assert local_time_issue(local(*args)) is None


def test_ambiguous_reports_the_fold_it_was_read_with() -> None:
    second = datetime(2027, 11, 7, 1, 30, tzinfo=SEPTA_ZONE, fold=1)
    assert local_time_issue(second) == (
        "ambiguous local time 2027-11-07 01:30 (DST overlap); read as EST"
    )


def test_fixed_offset_never_has_an_issue() -> None:
    """A gap wall time in SEPTA_ZONE is fine in a zone without DST."""
    fixed = datetime(2027, 3, 14, 2, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert local_time_issue(fixed) is None


def test_naive_datetime_raises() -> None:
    naive = datetime(2027, 3, 14, 2, 30)  # noqa: DTZ001
    with pytest.raises(ValueError, match="naive datetime"):
        local_time_issue(naive)


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("3/14/2027 2:30 AM", "nonexistent"),
        ("11/7/2027 1:30 AM", "ambiguous"),
    ],
)
def test_parsed_api_datetimes_are_flagged(raw: str, kind: str) -> None:
    """End to end: parse_api_datetime keeps the value; the issue is separate."""
    issue = local_time_issue(parse_api_datetime(raw))
    assert issue is not None
    assert issue.startswith(kind)


def test_no_fixture_datetime_is_flagged(
    read_alert_fixture: Callable[[str], bytes],
    alert_fixture_names: list[str],
) -> None:
    """None of the real timestamps fall in a DST gap or overlap."""
    flagged = []
    for name in alert_fixture_names:
        route = json.loads(read_alert_fixture(name))
        for detour in route["detour"]:
            for field in ("start", "end"):
                issue = local_time_issue(parse_api_datetime(detour[field]))
                if issue is not None:
                    flagged.append((name, field, issue))
    assert flagged == []
