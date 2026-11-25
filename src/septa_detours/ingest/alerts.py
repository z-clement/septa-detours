"""Fetch SEPTA's alerts API and save each response as a raw snapshot.

Source: ``https://www3.septa.org/api/Alerts/index.php``, a JSON list with
one entry per route (~185 entries, ~200 KB). Each entry has a ``detour``
list of ``{location_start, location_end, start, end, message, reason}``.

Ingest rules (see CLAUDE.md):
    - **Fetch only.** The body is saved byte-for-byte as received; it is
      never decoded, re-encoded, or pretty-printed. Parsing is ``parse/``'s
      job, and an untouched copy means a parser bug can always be fixed
      and re-run against the original data.
    - **One file per fetch.** Detours come and go, so snapshots over time
      are the raw material for ``tests/fixtures/``.

The checks in ``fetch_alerts`` look only at the HTTP envelope (status,
content type, empty body), never at the JSON itself.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from septa_detours.io import write_bytes_atomic

ALERTS_URL = "https://www3.septa.org/api/Alerts/index.php"

# The path assumes you run from the repo root (data/raw/ is gitignored).
DEFAULT_ALERTS_DIR = Path("data/raw/alerts")

# Generic client name: identifies the tool without personal details.
USER_AGENT = "septa-detours/0.1"

# Seconds. The API usually answers in well under a second; 30 s allows a
# slow day without letting a hung connection block forever (httpx's own
# default is 5 s, which is tight for a ~200 KB body over a bad link).
TIMEOUT_SECONDS = 30.0

# Filename timestamp: UTC, no colons (illegal on Windows, awkward in
# shells), sorts lexically in time order.
_SNAPSHOT_FORMAT = "%Y-%m-%dT%H%M%SZ"


def make_client() -> httpx.Client:
    """Return an ``httpx.Client`` configured for the SEPTA API.

    Callers should use it as a context manager so the connection pool is
    closed. Tests don't call this; they build a client around an
    ``httpx.MockTransport`` instead, so no test touches the network.
    """
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
    )


def fetch_alerts(client: httpx.Client) -> bytes:
    """GET the alerts API and return the response body, unmodified.

    Envelope checks, so an outage page is never saved as if it were data:
        - **Non-2xx status** -> ``httpx.HTTPStatusError`` (via
          ``raise_for_status``).
        - **Content type isn't JSON** (e.g. a 200 HTML maintenance page)
          -> ``ValueError``. Only the header is checked; a body that claims
          JSON but is malformed is still saved, and ``parse/`` deals with it.
        - **Empty body** -> ``ValueError``.

    Args:
        client: An open client, usually from ``make_client``.

    Returns:
        The raw response bytes.

    Raises:
        httpx.HTTPError: Network failure, timeout, or non-2xx status.
        ValueError: Non-JSON content type or empty body.
    """
    response = client.get(ALERTS_URL)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    # Media type only: drop parameters like "; charset=utf-8".
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        msg = f"expected JSON from {ALERTS_URL}, got content type {content_type!r}"
        raise ValueError(msg)

    if not response.content:
        msg = f"empty response body from {ALERTS_URL}"
        raise ValueError(msg)

    return response.content


def snapshot_path(fetched_at: datetime, root: Path = DEFAULT_ALERTS_DIR) -> Path:
    """Return the snapshot filename for a fetch time, e.g. ``2026-11-24T153000Z.json``.

    Pure: builds a path, touches nothing on disk.

    Decisions:
        - **UTC, always.** Local time is ambiguous for an hour every
          November (DST fall-back), so two snapshots could get the same
          name or sort out of order.
        - **Naive datetimes are rejected**, not assumed to be UTC or local:
          guessing the zone is exactly the bug this avoids.
        - **Second resolution.** Two fetches in the same second share a
          name and the later one replaces the earlier. They'd hold the
          same data, so that's acceptable.

    Args:
        fetched_at: When the response was received. Must be timezone-aware.
        root: Snapshot directory. Defaults to ``data/raw/alerts``.

    Raises:
        ValueError: If ``fetched_at`` has no timezone.
    """
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        msg = f"fetched_at must be timezone-aware, got naive {fetched_at!r}"
        raise ValueError(msg)
    stamp = fetched_at.astimezone(UTC).strftime(_SNAPSHOT_FORMAT)
    return root / f"{stamp}.json"


def _utc_now() -> datetime:
    """Return the current time in UTC (the default clock)."""
    return datetime.now(UTC)


def save_alerts_snapshot(
    client: httpx.Client,
    root: Path = DEFAULT_ALERTS_DIR,
    clock: Callable[[], datetime] = _utc_now,
) -> Path:
    """Fetch the alerts API once and save the body as a new snapshot.

    The timestamp is taken *after* the response arrives, so it records
    when the data was received, not when the request started. If the
    fetch fails, nothing is written (and the directory isn't created).

    Args:
        client: An open client, usually from ``make_client``.
        root: Snapshot directory. Defaults to ``data/raw/alerts``.
        clock: Returns the current time; tests pass a fixed one.

    Returns:
        The path the snapshot was written to.

    Raises:
        httpx.HTTPError: From ``fetch_alerts``.
        ValueError: From ``fetch_alerts`` or ``snapshot_path``.
        OSError: If the file can't be written.
    """
    content = fetch_alerts(client)
    path = snapshot_path(clock(), root)
    write_bytes_atomic(content, path)
    return path
