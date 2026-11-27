"""Tests for ``python -m septa_detours.gtfs check`` (the GTFS end-date check).

Feeds are small ``feed_info.txt`` files under ``tmp_path`` with the real
header and CRLF endings. Bus ends on the real ``20270220``; rail is given
an earlier end (and its own version) so a swapped feed shows.
"""

from datetime import date
from pathlib import Path

import pytest

from septa_detours.gtfs import __main__ as gtfs_main
from septa_detours.gtfs.__main__ import check_feeds

HEADER = (
    "feed_publisher_name,feed_publisher_url,feed_lang,"
    "feed_start_date,feed_end_date,feed_version\r\n"
)
BUS_ROW = "SEPTA,https://septa.org/,en,20261122,20270220,v202611220\r\n"
RAIL_ROW = "SEPTA,https://septa.org/,en,20261115,20270213,v202611150\r\n"


def write_feed(root: Path, feed: str, text: str) -> None:
    """Write ``text`` as ``root/<feed>/feed_info.txt`` (newlines kept)."""
    (root / feed).mkdir(parents=True, exist_ok=True)
    (root / feed / "feed_info.txt").write_bytes(text.encode("utf-8"))


@pytest.fixture
def gtfs_root(tmp_path: Path) -> Path:
    write_feed(tmp_path, "bus", HEADER + BUS_ROW)
    write_feed(tmp_path, "rail", HEADER + RAIL_ROW)
    return tmp_path


def test_fresh_feeds_say_when_they_end(gtfs_root: Path) -> None:
    assert check_feeds(date(2026, 11, 27), gtfs_root) == [
        "bus GTFS v202611220 ends 2027-02-20",
        "rail GTFS v202611150 ends 2027-02-13",
    ]


def test_only_the_feed_near_its_end_warns(gtfs_root: Path) -> None:
    # Rail has 14 days left, bus 21.
    assert check_feeds(date(2027, 1, 30), gtfs_root) == [
        "bus GTFS v202611220 ends 2027-02-20",
        "::warning::rail GTFS ends 2027-02-13, in 14 days: download a new feed",
    ]


def test_missing_feed_info_warns_and_the_other_feed_still_checks(
    gtfs_root: Path,
) -> None:
    (gtfs_root / "bus" / "feed_info.txt").unlink()
    lines = check_feeds(date(2026, 11, 27), gtfs_root)
    assert len(lines) == 2
    assert lines[0].startswith("::warning::bus GTFS: ")
    assert "feed_info.txt" in lines[0]
    assert lines[1] == "rail GTFS v202611150 ends 2027-02-13"


def test_missing_column_warns(gtfs_root: Path) -> None:
    write_feed(
        gtfs_root,
        "rail",
        "feed_publisher_name,feed_version\r\nSEPTA,v202611150\r\n",
    )
    assert check_feeds(date(2026, 11, 27), gtfs_root) == [
        "bus GTFS v202611220 ends 2027-02-20",
        "::warning::rail GTFS: "
        "rail feed's feed_info.txt is missing an expected column.",
    ]


def test_header_only_feed_info_warns(gtfs_root: Path) -> None:
    write_feed(gtfs_root, "bus", HEADER)
    assert check_feeds(date(2026, 11, 27), gtfs_root) == [
        "::warning::bus GTFS: feed_info.txt has no rows",
        "rail GTFS v202611150 ends 2027-02-13",
    ]


def test_blank_end_date_warns(gtfs_root: Path) -> None:
    write_feed(
        gtfs_root,
        "bus",
        HEADER + "SEPTA,https://septa.org/,en,20261122,,v202611220\r\n",
    )
    assert check_feeds(date(2026, 11, 27), gtfs_root) == [
        "::warning::bus GTFS: can't read feed_end_date None",
        "rail GTFS v202611150 ends 2027-02-13",
    ]


def test_every_row_is_checked(gtfs_root: Path) -> None:
    write_feed(gtfs_root, "rail", HEADER + RAIL_ROW + BUS_ROW)
    assert check_feeds(date(2027, 2, 21), gtfs_root) == [
        "::warning::bus GTFS ended 2027-02-20, 1 day ago: download a new feed",
        "::warning::rail GTFS ended 2027-02-13, 8 days ago: download a new feed",
        "::warning::rail GTFS ended 2027-02-20, 1 day ago: download a new feed",
    ]


def test_main_prints_lines_and_exits_zero_even_with_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # main reads the default relative path, data/gtfs, from the repo root.
    old = HEADER + "SEPTA,https://septa.org/,en,20200101,20200301,v202001010\r\n"
    write_feed(tmp_path / "data" / "gtfs", "bus", old)
    monkeypatch.chdir(tmp_path)
    assert gtfs_main.main(["check"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2
    assert out[0].startswith("::warning::bus GTFS ended 2020-03-01, ")
    assert out[1].startswith("::warning::rail GTFS: ")


def test_main_needs_a_command() -> None:
    with pytest.raises(SystemExit) as exc:
        gtfs_main.main([])
    assert exc.value.code == 2
