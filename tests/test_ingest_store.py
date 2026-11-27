"""Tests for ``ingest/store.py`` (snapshots kept on the ``snapshots`` branch).

``REAL_LS_TREE`` is real ``git ls-tree -z HEAD -- alerts/`` output (git
2.56) from a scratch repo holding two snapshots, a README and a
subdirectory; the ids are real. Other inputs are built in the same format.
"""

import pytest

from septa_detours.ingest.store import StoredSnapshot, newest_stored

OLD_BLOB = "78981922613b2afb6025042ff6bd878ac1994e85"
NEW_BLOB = "61780798228d17af2d34fce4cfbdf35556832472"
REAL_LS_TREE = (
    f"100644 blob {OLD_BLOB}\talerts/2026-11-25T025344Z.json\0"
    f"100644 blob {NEW_BLOB}\talerts/2026-11-27T134432Z.json\0"
    "100644 blob f2ad6c76f0115a6ba5b00456a849810e7ec0af20\talerts/README.md\0"
    "040000 tree acf1448d5d847bbfa21cd23a557f686390b64a4a\talerts/sub\0"
)
OTHER_BLOB = "0123456789abcdef0123456789abcdef01234567"


def entry(path: str, blob: str = OTHER_BLOB, kind: str = "blob") -> str:
    """One ``ls-tree -z`` entry (mode follows the kind, as git prints it)."""
    mode = "040000" if kind == "tree" else "100644"
    return f"{mode} {kind} {blob}\t{path}\0"


def test_real_output_gives_the_newest_snapshot_not_the_readme() -> None:
    assert newest_stored(REAL_LS_TREE) == StoredSnapshot(
        "2026-11-27T134432Z.json", NEW_BLOB
    )


def test_newest_by_name_whatever_the_listing_order() -> None:
    ls_tree = (
        entry("alerts/2026-11-26T141550Z.json", OLD_BLOB)
        + entry("alerts/2026-11-27T134432Z.json", NEW_BLOB)
        + entry("alerts/2026-11-25T121123Z.json", OTHER_BLOB)
    )
    assert newest_stored(ls_tree) == StoredSnapshot("2026-11-27T134432Z.json", NEW_BLOB)


def test_newest_within_a_day_by_time() -> None:
    ls_tree = entry("alerts/2026-11-26T145719Z.json", NEW_BLOB) + entry(
        "alerts/2026-11-26T141550Z.json", OLD_BLOB
    )
    assert newest_stored(ls_tree) == StoredSnapshot("2026-11-26T145719Z.json", NEW_BLOB)


def test_empty_listing_means_nothing_stored_yet() -> None:
    assert newest_stored("") is None


@pytest.mark.parametrize(
    "stray",
    [
        entry("alerts/2026-12-01T000000Z.json", kind="tree"),
        entry("alerts/2026-12-01T000000Z.json.tmp"),
        entry("alerts/2026-12-01T000000Z.JSON"),
        entry("alerts/2026-12-01T000000Zxjson"),
        entry("alerts/2026-12-01T00000Z.json"),
        entry("alerts/x2026-12-01T000000Z.json"),
        entry("alerts/sub/2026-12-01T000000Z.json"),
        entry("other/2026-12-01T000000Z.json"),
        entry("2026-12-01T000000Z.json"),
        entry("alerts/٢٠٢٦-12-01T000000Z.json"),  # Arabic-Indic digits
    ],
)
def test_strays_newer_than_every_snapshot_are_ignored(stray: str) -> None:
    assert newest_stored(REAL_LS_TREE + stray) == StoredSnapshot(
        "2026-11-27T134432Z.json", NEW_BLOB
    )


def test_only_strays_means_nothing_stored() -> None:
    ls_tree = entry("alerts/README.md") + entry("alerts/sub", kind="tree")
    assert newest_stored(ls_tree) is None
