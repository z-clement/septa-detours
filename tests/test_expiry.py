"""Tests for ``gtfs.expiry.end_date_warning``.

``20270220`` is the real ``feed_end_date`` of both 2026-11-22 feeds
(``v202611220``). Each boundary is pinned on both sides by exact day.
"""

from datetime import date

import pytest

from septa_detours.gtfs.expiry import end_date_warning

REAL_END = "20270220"


def test_real_feed_today_is_quiet() -> None:
    assert end_date_warning("bus", REAL_END, date(2026, 11, 27)) is None


def test_fifteen_days_left_is_quiet() -> None:
    assert end_date_warning("bus", REAL_END, date(2027, 2, 5)) is None


def test_fourteen_days_left_warns() -> None:
    assert end_date_warning("bus", REAL_END, date(2027, 2, 6)) == (
        "bus GTFS ends 2027-02-20, in 14 days: download a new feed"
    )


def test_one_day_left_is_singular() -> None:
    assert end_date_warning("bus", REAL_END, date(2027, 2, 19)) == (
        "bus GTFS ends 2027-02-20, in 1 day: download a new feed"
    )


def test_end_date_itself_still_runs_today() -> None:
    assert end_date_warning("bus", REAL_END, date(2027, 2, 20)) == (
        "bus GTFS ends 2027-02-20, today: download a new feed"
    )


def test_day_after_end_has_ended() -> None:
    assert end_date_warning("bus", REAL_END, date(2027, 2, 21)) == (
        "bus GTFS ended 2027-02-20, 1 day ago: download a new feed"
    )


def test_long_past_end_counts_calendar_days() -> None:
    # February 2027 has 28 days: Feb 20 -> Mar 2 is 10 days.
    assert end_date_warning("rail", REAL_END, date(2027, 3, 2)) == (
        "rail GTFS ended 2027-02-20, 10 days ago: download a new feed"
    )


def test_counts_days_across_a_year_end() -> None:
    # As integers, 20270105 - 20261231 would be 8874, not 5.
    assert end_date_warning("bus", "20270105", date(2026, 12, 31)) == (
        "bus GTFS ends 2027-01-05, in 5 days: download a new feed"
    )


def test_within_days_moves_the_threshold() -> None:
    assert end_date_warning("rail", REAL_END, date(2027, 1, 21), within_days=30) == (
        "rail GTFS ends 2027-02-20, in 30 days: download a new feed"
    )
    assert end_date_warning("rail", REAL_END, date(2027, 1, 20), within_days=30) is None


@pytest.mark.parametrize(
    "end",
    [
        None,
        "",
        "2027220",
        "202702200",
        "2027-02-20",
        " 20270220",
        "20270230",
        "20271301",
        "\u0662\u0660\u0662\u0667\u0660\u0662\u0662\u0660",  # Arabic-Indic digits
    ],
)
def test_unreadable_end_date_warns_instead_of_failing(end: str | None) -> None:
    assert end_date_warning("bus", end, date(2026, 11, 27)) == (
        f"bus GTFS: can't read feed_end_date {end!r}"
    )
