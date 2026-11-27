"""Tests for ``ingest/store.py`` (snapshots kept on the ``snapshots`` branch).

``REAL_LS_TREE`` is real ``git ls-tree -z HEAD -- alerts/`` output (git
2.56) from a scratch repo holding two snapshots, a README and a
subdirectory; the ids are real. Other inputs are built in the same format.

``commit_snapshot`` runs real git in ``tmp_path`` with the user's global
and system config switched off. Snapshot bytes are real API route
entries from ``tests/fixtures/alerts/``.
"""

import os
import subprocess
from pathlib import Path

import pytest

from septa_detours.ingest import __main__ as ingest_main
from septa_detours.ingest import store
from septa_detours.ingest.store import (
    BOT_EMAIL,
    BOT_NAME,
    StoredSnapshot,
    commit_snapshot,
    newest_stored,
    store_snapshot,
)

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


FIXTURES = Path(__file__).parent / "fixtures" / "alerts"
ROUTE_2 = (FIXTURES / "2026-11-25T025344Z__bus_route_2.json").read_bytes().strip()
ROUTE_24 = (FIXTURES / "2026-11-25T025344Z__bus_route_24.json").read_bytes().strip()
FEED_A = b"[" + ROUTE_2 + b"]"
FEED_B = b"[" + ROUTE_2 + b"," + ROUTE_24 + b"]"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.removesuffix("\n")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo with one commit on ``main`` and a staged change (the checkout)."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Maintainer")
    git(repo, "config", "user.email", "maintainer@example.com")
    (repo / "README.md").write_text("SEPTA detours\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "main")
    (repo / "README.md").write_text("SEPTA detours, edited\n")
    git(repo, "add", "README.md")
    return repo


def write_snapshot(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def files_in(repo: Path, commit: str) -> dict[str, bytes]:
    """Every file in ``commit`` and its bytes."""
    names = git(repo, "ls-tree", "-r", "--name-only", commit).splitlines()
    return {
        name: subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{name}"],
            capture_output=True,
            check=True,
        ).stdout
        for name in names
    }


def test_first_snapshot_is_a_root_commit_by_the_bot(repo: Path, tmp_path: Path) -> None:
    snapshot = write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A)
    commit = commit_snapshot(snapshot, None, repo)
    assert commit is not None
    assert files_in(repo, commit) == {"alerts/2026-11-25T025344Z.json": FEED_A}
    blob = git(repo, "rev-parse", f"{commit}:alerts/2026-11-25T025344Z.json")
    assert git(repo, "ls-tree", "-r", commit) == (
        f"100644 blob {blob}\talerts/2026-11-25T025344Z.json"
    )
    assert git(repo, "log", "-1", "--format=%P|%an|%ae|%cn|%ce|%B", commit) == (
        f"|{BOT_NAME}|{BOT_EMAIL}|{BOT_NAME}|{BOT_EMAIL}|alerts: 2026-11-25T025344Z\n"
    )


def test_changed_snapshot_is_added_on_top_of_the_parent(
    repo: Path, tmp_path: Path
) -> None:
    first = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), None, repo
    )
    assert first is not None
    second = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_B), first, repo
    )
    assert second is not None
    assert git(repo, "log", "-1", "--format=%P", second) == first
    assert files_in(repo, second) == {
        "alerts/2026-11-25T025344Z.json": FEED_A,
        "alerts/2026-11-25T121123Z.json": FEED_B,
    }
    assert git(repo, "log", "-1", "--format=%B", second) == (
        "alerts: 2026-11-25T121123Z\n"
    )


def test_unchanged_snapshot_is_not_committed(repo: Path, tmp_path: Path) -> None:
    first = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), None, repo
    )
    assert first is not None
    again = write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_A)
    assert commit_snapshot(again, first, repo) is None


def test_return_to_an_older_state_is_stored(repo: Path, tmp_path: Path) -> None:
    first = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), None, repo
    )
    assert first is not None
    second = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_B), first, repo
    )
    assert second is not None
    third = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-26T141550Z.json", FEED_A), second, repo
    )
    assert third is not None
    assert files_in(repo, third)["alerts/2026-11-26T141550Z.json"] == FEED_A


def test_same_name_and_bytes_already_stored_is_not_committed(
    repo: Path, tmp_path: Path
) -> None:
    # The older snapshot sent again: not the newest, so only the tree
    # comparison catches it.
    older = write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A)
    first = commit_snapshot(older, None, repo)
    assert first is not None
    second = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_B), first, repo
    )
    assert second is not None
    assert commit_snapshot(older, second, repo) is None


def test_same_name_with_different_bytes_is_refused(repo: Path, tmp_path: Path) -> None:
    first = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), None, repo
    )
    assert first is not None
    clash = write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_B)
    second = commit_snapshot(clash, first, repo)
    assert second is not None
    clash.write_bytes(FEED_A + b"\n")
    with pytest.raises(
        ValueError, match=r"alerts/2026-11-25T121123Z\.json is already stored"
    ):
        commit_snapshot(clash, second, repo)


@pytest.mark.parametrize(
    "name", ["2026-11-25T025344Z.json.tmp", "latest.json", "2026-11-25T0253Z.json"]
)
def test_non_snapshot_name_is_refused(repo: Path, tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="not an alerts snapshot name"):
        commit_snapshot(write_snapshot(tmp_path, name, FEED_A), None, repo)


def test_checkout_index_and_branches_are_untouched(repo: Path, tmp_path: Path) -> None:
    before = (
        git(repo, "status", "--porcelain"),
        git(repo, "rev-parse", "HEAD"),
        git(repo, "for-each-ref"),
    )
    first = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), None, repo
    )
    commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_B), first, repo
    )
    after = (
        git(repo, "status", "--porcelain"),
        git(repo, "rev-parse", "HEAD"),
        git(repo, "for-each-ref"),
    )
    assert after == before
    assert before[0] == "M  README.md"


def test_signing_config_does_not_get_in_the_way(repo: Path, tmp_path: Path) -> None:
    git(repo, "config", "commit.gpgsign", "true")
    git(repo, "config", "gpg.program", "false")  # signing would fail
    snapshot = write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A)
    assert commit_snapshot(snapshot, None, repo) is not None


def test_partial_clone_commits_without_fetching_old_snapshots(
    repo: Path, tmp_path: Path
) -> None:
    # The job's view of the branch: its file list, none of the contents.
    first = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), None, repo
    )
    assert first is not None
    git(repo, "branch", "snapshots", first)
    git(repo, "config", "uploadpack.allowFilter", "true")
    clone = tmp_path / "clone"
    git(
        tmp_path,
        "clone",
        "-q",
        "--filter=blob:none",
        "--depth=1",
        "--no-checkout",
        "--branch=snapshots",
        f"file://{repo}",
        str(clone),
    )
    old_blob = git(
        clone, "rev-parse", "origin/snapshots:alerts/2026-11-25T025344Z.json"
    )

    def is_local(blob: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", str(clone), "cat-file", "-e", blob],
                env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )

    assert not is_local(old_blob)
    second = commit_snapshot(
        write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_B),
        "origin/snapshots",
        clone,
    )
    assert second is not None
    assert not is_local(old_blob)
    assert git(clone, "ls-tree", "-r", "--name-only", second).splitlines() == [
        "alerts/2026-11-25T025344Z.json",
        "alerts/2026-11-25T121123Z.json",
    ]
    assert git(clone, "log", "-1", "--format=%P", second) == first


@pytest.fixture
def origin(repo: Path, tmp_path: Path) -> Path:
    """A bare repo standing in for GitHub, holding ``repo``'s ``main``."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(origin, "config", "uploadpack.allowFilter", "true")
    git(repo, "push", "-q", str(origin), "main")
    return origin


def clone_main(origin: Path, path: Path) -> Path:
    """A fresh checkout of ``main``, as ``actions/checkout`` makes one."""
    git(path.parent, "clone", "-q", "--depth=1", f"file://{origin}", str(path))
    return path


@pytest.fixture
def job(origin: Path, tmp_path: Path) -> Path:
    return clone_main(origin, tmp_path / "job")


def stored_tip(origin: Path) -> str:
    return git(origin, "rev-parse", "--verify", "refs/heads/snapshots")


def test_first_store_creates_the_branch(
    origin: Path, job: Path, tmp_path: Path
) -> None:
    snapshot = write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A)
    commit = store_snapshot(snapshot, job)
    assert commit is not None
    assert stored_tip(origin) == commit
    assert git(origin, "log", "--format=%P|%s", "snapshots") == (
        "|alerts: 2026-11-25T025344Z"
    )
    assert files_in(origin, "snapshots") == {"alerts/2026-11-25T025344Z.json": FEED_A}


def test_later_runs_add_on_top_without_fetching_old_snapshots(
    origin: Path, job: Path, tmp_path: Path
) -> None:
    first = store_snapshot(
        write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), job
    )
    assert first is not None
    # The next run is a fresh checkout, like every Actions run.
    later_job = clone_main(origin, tmp_path / "later-job")
    second = store_snapshot(
        write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_B), later_job
    )
    assert second is not None
    assert stored_tip(origin) == second
    assert git(origin, "log", "--format=%s", "snapshots").splitlines() == [
        "alerts: 2026-11-25T121123Z",
        "alerts: 2026-11-25T025344Z",
    ]
    assert files_in(origin, "snapshots") == {
        "alerts/2026-11-25T025344Z.json": FEED_A,
        "alerts/2026-11-25T121123Z.json": FEED_B,
    }
    old_blob = git(origin, "rev-parse", "snapshots:alerts/2026-11-25T025344Z.json")
    missing = subprocess.run(
        ["git", "-C", str(later_job), "cat-file", "-e", old_blob],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        capture_output=True,
        check=False,
    )
    assert missing.returncode != 0


def test_unchanged_snapshot_pushes_nothing(
    origin: Path, job: Path, tmp_path: Path
) -> None:
    first = store_snapshot(
        write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), job
    )
    later_job = clone_main(origin, tmp_path / "later-job")
    again = write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_A)
    assert store_snapshot(again, later_job) is None
    assert stored_tip(origin) == first


def test_a_run_that_lost_the_race_is_rejected_not_forced(
    origin: Path, job: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_snapshot(write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), job)
    other_job = clone_main(origin, tmp_path / "other-job")
    winner: list[str | None] = []

    def other_run_pushes_first(
        snapshot: Path, parent: str | None, repo: Path
    ) -> str | None:
        # After this run fetched, another run stores its snapshot first
        # (its own call lands here too, with ``winner`` set: no recursion).
        if not winner:
            winner.append(None)
            other = write_snapshot(
                tmp_path / "other", "2026-11-25T121123Z.json", FEED_B
            )
            winner[0] = store_snapshot(other, other_job)
        return commit_snapshot(snapshot, parent, repo)

    monkeypatch.setattr(store, "commit_snapshot", other_run_pushes_first)
    late_feed = b"[" + ROUTE_24 + b"]"  # differs from both stored feeds
    late = write_snapshot(tmp_path, "2026-11-25T121500Z.json", late_feed)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        store_snapshot(late, job)
    assert "! [rejected]" in exc.value.stderr
    assert winner[0] is not None
    assert stored_tip(origin) == winner[0]


def test_job_checkout_stays_as_it_was(origin: Path, job: Path, tmp_path: Path) -> None:
    before = (git(job, "rev-parse", "HEAD"), git(job, "status", "--porcelain"))
    store_snapshot(write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), job)
    after = (git(job, "rev-parse", "HEAD"), git(job, "status", "--porcelain"))
    assert after == before
    assert git(job, "branch", "--format=%(refname:short)") == "main"


def test_unknown_remote_raises(job: Path, tmp_path: Path) -> None:
    snapshot = write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A)
    with pytest.raises(subprocess.CalledProcessError):
        store_snapshot(snapshot, job, remote="nowhere")


def test_main_store_reports_stored_then_unchanged(
    origin: Path,
    job: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(job)  # the workflow runs from its checkout
    first = write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A)
    assert ingest_main.main(["store", str(first)]) == 0
    tip = stored_tip(origin)
    assert capsys.readouterr().out == (
        f"stored 2026-11-25T025344Z.json on snapshots ({tip[:12]})\n"
    )

    again = write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_A)
    assert ingest_main.main(["store", str(again)]) == 0
    assert capsys.readouterr().out == (
        "unchanged: nothing new in 2026-11-25T121123Z.json; nothing pushed\n"
    )
    assert stored_tip(origin) == tip


def test_main_store_bad_name_exits_one(
    job: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(job)
    snapshot = write_snapshot(tmp_path, "latest.json", FEED_A)
    assert ingest_main.main(["store", str(snapshot)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: not an alerts snapshot name: 'latest.json'\n"


def test_main_store_git_failure_prints_git_stderr_and_exits_one(
    job: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(job)
    git(job, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    snapshot = write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A)
    assert ingest_main.main(["store", str(snapshot)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    first_line, rest = captured.err.split("\n", 1)
    assert first_line == (
        "error: git ls-remote --heads origin refs/heads/snapshots failed:"
    )
    assert "gone.git" in rest


@pytest.mark.parametrize(
    "argv", [["store"], ["alerts", "x.json"], ["osm", "x.json"], ["x.json"]]
)
def test_main_snapshot_goes_with_store_only(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        ingest_main.main(argv)
    assert exc.value.code == 2


def test_each_run_fetches_only_the_tip_commit(
    origin: Path, job: Path, tmp_path: Path
) -> None:
    store_snapshot(write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), job)
    second_job = clone_main(origin, tmp_path / "second-job")
    store_snapshot(
        write_snapshot(tmp_path, "2026-11-25T121123Z.json", FEED_B), second_job
    )
    third_job = clone_main(origin, tmp_path / "third-job")
    third = store_snapshot(
        write_snapshot(tmp_path, "2026-11-26T141550Z.json", FEED_A), third_job
    )
    assert third is not None
    # Two commits were stored before this run; it fetched just the newest.
    assert git(third_job, "rev-list", "--count", "refs/remotes/origin/snapshots") == "1"
    assert git(origin, "rev-list", "--count", "snapshots") == "3"


def test_a_branch_rewritten_by_hand_is_followed(
    repo: Path, origin: Path, job: Path, tmp_path: Path
) -> None:
    store_snapshot(write_snapshot(tmp_path, "2026-11-25T025344Z.json", FEED_A), job)
    # A second run in the same checkout fetches, setting its tracking ref
    # (the first run had no branch to fetch).
    store_snapshot(write_snapshot(tmp_path, "2026-11-25T121500Z.json", FEED_B), job)
    assert git(job, "rev-parse", "refs/remotes/origin/snapshots") != ""
    # The maintainer replaces the branch with an unrelated history.
    other = write_snapshot(tmp_path / "other", "2026-11-25T121123Z.json", FEED_A)
    rewritten = commit_snapshot(other, None, repo)
    assert rewritten is not None
    git(repo, "push", "-q", "--force", str(origin), f"{rewritten}:refs/heads/snapshots")
    # Same checkout as before (its tracking ref still points at the old tip).
    late = write_snapshot(tmp_path, "2026-11-26T141550Z.json", FEED_B)
    commit = store_snapshot(late, job)
    assert commit is not None
    assert git(origin, "log", "-1", "--format=%P", "snapshots") == rewritten
