"""Tests for ``ingest/alerts.py`` and ``python -m septa_detours.ingest``.

No test touches the network: every client is built around an
``httpx.MockTransport`` whose handler plays the SEPTA server.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from septa_detours.ingest import __main__ as ingest_main
from septa_detours.ingest.alerts import (
    ALERTS_URL,
    DEFAULT_ALERTS_DIR,
    USER_AGENT,
    fetch_alerts,
    make_client,
    save_alerts_snapshot,
    snapshot_path,
)

# Shaped like the real API, with the real API's quirks kept: extra spaces
# in dates, a typo ("3pn"), and non-ASCII. Spacing is deliberately odd so a
# re-encode (json.loads + json.dumps) would change the bytes.
BODY = (
    '[{"route":"2","route_id":"bus_route_2","mode":"Bus","isdetour":"Y",'
    '"detour":[{"location_start":"17th & Spring Garden Sts",'
    '"location_end":"17th & JFK Blvd","start":"11/25/2026   3:00 PM",'
    '"end":"11/26/2026   2:00 AM","message":"3pn on 11/25/26 thru 2am, SB via '
    '17th St, Left on Spring Garden St, Reg Rt","reason":"Parade \u2013 Phase 2"}]}'
    "]   \n"
).encode()

JSON_HEADERS = {"content-type": "application/json"}
FIXED_TIME = datetime(2026, 11, 24, 15, 30, 0, tzinfo=UTC)


def mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def serve(
    content: bytes = BODY, status: int = 200, headers: dict | None = None
) -> httpx.Client:
    """A client whose every request gets the same canned response."""
    headers = JSON_HEADERS if headers is None else headers

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content, headers=headers)

    return mock_client(handler)


# --- fetch_alerts ---------------------------------------------------------


def test_fetch_returns_body_bytes_unchanged():
    assert fetch_alerts(serve()) == BODY


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        # Invalid UTF-8: decoding would replace \xff with U+FFFD.
        (b'[{"message":"caf\xff"}]\r\n', "application/json"),
        # Latin-1 "é" under a declared charset: decode+encode gives UTF-8.
        (b'[{"message":"caf\xe9"}]', "application/json; charset=iso-8859-1"),
    ],
    ids=["invalid-utf8", "latin1"],
)
def test_fetch_never_decodes_body(content, content_type):
    """Bytes that wouldn't survive a decode/encode round trip come back as-is."""
    assert fetch_alerts(serve(content, headers={"content-type": content_type})) == (
        content
    )


def test_fetch_requests_the_alerts_url_with_get():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=BODY, headers=JSON_HEADERS)

    fetch_alerts(mock_client(handler))
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert str(seen[0].url) == ALERTS_URL


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/json; charset=utf-8", "Application/JSON"],
)
def test_fetch_accepts_json_content_types(content_type):
    assert fetch_alerts(serve(headers={"content-type": content_type})) == BODY


@pytest.mark.parametrize("status", [404, 500, 503])
def test_fetch_raises_on_error_status(status):
    with pytest.raises(httpx.HTTPStatusError):
        fetch_alerts(serve(status=status))


@pytest.mark.parametrize(
    "headers", [{"content-type": "text/html; charset=iso-8859-1"}, {}]
)
def test_fetch_rejects_non_json_content_type(headers):
    """A 200 HTML maintenance page (or no header at all) is not data."""
    with pytest.raises(ValueError, match="expected JSON"):
        fetch_alerts(serve(content=b"<html>down</html>", headers=headers))


def test_fetch_rejects_lookalike_content_type():
    """Only the exact media type counts, not anything containing "json"."""
    with pytest.raises(ValueError, match="expected JSON"):
        fetch_alerts(serve(headers={"content-type": "application/jsonp"}))


def test_fetch_rejects_empty_body():
    with pytest.raises(ValueError, match="empty response"):
        fetch_alerts(serve(content=b""))


def test_fetch_does_not_validate_json_body():
    """Malformed JSON is still saved: judging the body is parse/'s job."""
    assert fetch_alerts(serve(content=b"[{not json")) == b"[{not json"


def unreachable(request: httpx.Request) -> httpx.Response:
    """Mock handler that fails like a dropped network connection."""
    raise httpx.ConnectError("simulated: no route to host", request=request)


def test_fetch_propagates_network_errors():
    with pytest.raises(httpx.ConnectError):
        fetch_alerts(mock_client(unreachable))


# --- make_client ----------------------------------------------------------


def test_make_client_settings():
    with make_client() as client:
        assert client.headers["User-Agent"] == USER_AGENT
        assert client.timeout.read == 30.0
        assert client.follow_redirects is True


# --- snapshot_path --------------------------------------------------------


def test_snapshot_path_format():
    assert snapshot_path(FIXED_TIME, Path("raw")) == Path("raw/2026-11-24T153000Z.json")


def test_snapshot_path_default_root():
    assert snapshot_path(FIXED_TIME).parent == DEFAULT_ALERTS_DIR
    assert Path("data/raw/alerts") == DEFAULT_ALERTS_DIR


def test_snapshot_path_converts_to_utc():
    """10:30 in UTC-5 (Philadelphia in winter) is 15:30Z."""
    eastern_winter = timezone(timedelta(hours=-5))
    local = datetime(2026, 11, 24, 10, 30, 0, tzinfo=eastern_winter)
    assert snapshot_path(local, Path()).name == "2026-11-24T153000Z.json"


def test_snapshot_path_drops_microseconds():
    assert (
        snapshot_path(FIXED_TIME.replace(microsecond=999_999), Path()).name
        == "2026-11-24T153000Z.json"
    )


def test_snapshot_path_rejects_naive_datetime():
    naive = datetime(2026, 11, 24, 15, 30, 0)  # noqa: DTZ001 - naive on purpose
    with pytest.raises(ValueError, match="timezone-aware"):
        snapshot_path(naive, Path())


def test_snapshot_names_sort_in_time_order():
    times = [
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC),
        datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC),
        datetime(2026, 11, 20, 0, 0, 0, tzinfo=UTC),
    ]
    names = [snapshot_path(t, Path()).name for t in reversed(times)]
    assert sorted(names) == [snapshot_path(t, Path()).name for t in times]


# --- save_alerts_snapshot -------------------------------------------------


def test_save_writes_exact_bytes_to_timestamped_file(tmp_path):
    path = save_alerts_snapshot(serve(), root=tmp_path, clock=lambda: FIXED_TIME)
    assert path == tmp_path / "2026-11-24T153000Z.json"
    assert path.read_bytes() == BODY
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_save_creates_root_directory(tmp_path):
    root = tmp_path / "data" / "raw" / "alerts"
    path = save_alerts_snapshot(serve(), root=root, clock=lambda: FIXED_TIME)
    assert path.parent == root
    assert path.read_bytes() == BODY


def test_save_reads_clock_after_fetch(tmp_path):
    """The timestamp records when the response arrived."""
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        events.append("fetch")
        return httpx.Response(200, content=BODY, headers=JSON_HEADERS)

    def clock() -> datetime:
        events.append("clock")
        return FIXED_TIME

    save_alerts_snapshot(mock_client(handler), root=tmp_path, clock=clock)
    assert events == ["fetch", "clock"]


def test_save_default_clock_is_utc_now(tmp_path):
    before = datetime.now(UTC).replace(microsecond=0)
    path = save_alerts_snapshot(serve(), root=tmp_path)
    after = datetime.now(UTC)
    stamp = datetime.strptime(path.stem, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=UTC)
    assert before <= stamp <= after


def test_save_successive_fetches_make_separate_files(tmp_path):
    t1, t2 = FIXED_TIME, FIXED_TIME + timedelta(minutes=10)
    p1 = save_alerts_snapshot(serve(b"[1]"), root=tmp_path, clock=lambda: t1)
    p2 = save_alerts_snapshot(serve(b"[2]"), root=tmp_path, clock=lambda: t2)
    assert p1 != p2
    assert (p1.read_bytes(), p2.read_bytes()) == (b"[1]", b"[2]")


@pytest.mark.parametrize(
    ("client", "error"),
    [
        (serve(status=503), httpx.HTTPStatusError),
        (serve(headers={"content-type": "text/html"}), ValueError),
        (serve(content=b""), ValueError),
    ],
)
def test_save_failed_fetch_writes_nothing(tmp_path, client, error):
    root = tmp_path / "alerts"
    with pytest.raises(error):
        save_alerts_snapshot(client, root=root, clock=lambda: FIXED_TIME)
    assert not root.exists()


# --- python -m septa_detours.ingest ---------------------------------------


@pytest.fixture
def in_tmp_repo(tmp_path, monkeypatch):
    """Run from an empty fake repo root, so default relative paths land here."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def patch_client(monkeypatch, client: httpx.Client) -> None:
    monkeypatch.setattr(ingest_main, "make_client", lambda: client)


def test_main_success_writes_snapshot(in_tmp_repo, monkeypatch, capsys):
    patch_client(monkeypatch, serve())
    assert ingest_main.main([]) == 0

    files = list((in_tmp_repo / DEFAULT_ALERTS_DIR).iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == BODY
    out, err = capsys.readouterr()
    assert out == f"wrote {DEFAULT_ALERTS_DIR / files[0].name}\n"
    assert err == ""


@pytest.mark.parametrize(
    "client",
    [
        serve(status=500),
        serve(headers={"content-type": "text/html"}),
        mock_client(unreachable),
    ],
    ids=["status", "content-type", "network"],
)
def test_main_expected_failures_exit_1(in_tmp_repo, monkeypatch, capsys, client):
    patch_client(monkeypatch, client)
    assert ingest_main.main([]) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert not (in_tmp_repo / "data").exists()


def test_main_unexpected_errors_propagate(in_tmp_repo, monkeypatch):
    """A bug (not a fetch failure) keeps its traceback instead of exit 1."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("bug")

    patch_client(monkeypatch, mock_client(handler))
    with pytest.raises(RuntimeError, match="bug"):
        ingest_main.main([])


def test_main_rejects_unknown_arguments():
    with pytest.raises(SystemExit) as excinfo:
        ingest_main.main(["--nope"])
    assert excinfo.value.code == 2
