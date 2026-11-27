"""Tests for export/deploy.py: the published site's versioned code URLs."""

from pathlib import Path

import pytest

from septa_detours.export.__main__ import main
from septa_detours.export.deploy import (
    VERSION_LENGTH,
    asset_version,
    build_site,
    versioned_index,
)

REAL_INDEX = (Path(__file__).parents[1] / "web" / "index.html").read_text()
"""The page's own ``index.html``: the file ``deploy`` really rewrites."""

CODE = {"js/main.js": b"import './data.js';\n", "css/app.css": b"body {}\n"}


# --- asset_version ------------------------------------------------------------


def test_version_is_short_hex() -> None:
    version = asset_version(CODE)
    assert len(version) == VERSION_LENGTH
    assert int(version, 16) >= 0


def test_version_is_stable_and_ignores_order() -> None:
    reordered = dict(reversed(CODE.items()))
    assert asset_version(reordered) == asset_version(CODE)


@pytest.mark.parametrize(
    "changed",
    [
        # One byte of code.
        {**CODE, "css/app.css": b"body {}\r\n"},
        # A new file.
        {**CODE, "js/data.js": b""},
        # A renamed file, same bytes.
        {"js/index.js": CODE["js/main.js"], "css/app.css": CODE["css/app.css"]},
        # A byte moved from one file's end to the next file's start: the
        # concatenation is the same, the code isn't.
        {"css/app.css": b"body {}", "js/main.js": b"\nimport './data.js';\n"},
    ],
)
def test_any_code_change_changes_the_version(changed: dict[str, bytes]) -> None:
    assert asset_version(changed) != asset_version(CODE)


def test_file_boundaries_are_part_of_the_version() -> None:
    # Hand-built: without lengths, both hash "js/a" "js/b" "x" in a row.
    one_file = {"js/a": b"js/bx"}
    two_files = {"js/a": b"", "js/b": b"x"}
    assert asset_version(one_file) != asset_version(two_files)


# --- versioned_index ----------------------------------------------------------


def test_real_index_points_at_the_versioned_folders() -> None:
    assert REAL_INDEX.count('src="js/main.js"') == 1
    assert REAL_INDEX.count('href="css/app.css"') == 1
    expected = REAL_INDEX.replace(
        'src="js/main.js"', 'src="js-0123456789/main.js"'
    ).replace('href="css/app.css"', 'href="css-0123456789/app.css"')
    assert versioned_index(REAL_INDEX, "0123456789") == expected


def test_cdn_urls_are_left_alone() -> None:
    # The real page loads MapLibre's own js and css from unpkg.
    result = versioned_index(REAL_INDEX, "0123456789")
    assert result.count("https://unpkg.com/maplibre-gl@") == 2
    assert "maplibre-gl@5.24.0/dist/maplibre-gl.js" in result


def test_dot_slash_references_and_every_reference() -> None:
    # Hand-built: "./" prefixes, and two files in one folder.
    html = (
        '<link rel="stylesheet" href="./css/app.css" />'
        '<link rel="stylesheet" href="css/print.css" />'
        '<script type="module" src="js/main.js"></script>'
    )
    assert versioned_index(html, "abc") == (
        '<link rel="stylesheet" href="css-abc/app.css" />'
        '<link rel="stylesheet" href="css-abc/print.css" />'
        '<script type="module" src="js-abc/main.js"></script>'
    )


def test_lookalike_attributes_are_left_alone() -> None:
    # Hand-built: data-src isn't a load, and "jsx/" isn't "js/".
    html = (
        '<img data-src="js/x.png" /><script src="jsx/a.js"></script>'
        '<script src="js/main.js"></script><link href="css/app.css" />'
    )
    assert versioned_index(html, "abc") == (
        '<img data-src="js/x.png" /><script src="jsx/a.js"></script>'
        '<script src="js-abc/main.js"></script><link href="css-abc/app.css" />'
    )


@pytest.mark.parametrize(
    ("html", "missing"),
    [
        ('<link href="css/app.css" />', "js/"),
        ('<script src="js/main.js"></script>', "css/"),
        ('<script src="/js/main.js"></script>', "js/, css/"),
    ],
)
def test_a_page_that_loads_its_code_differently_is_refused(
    html: str, missing: str
) -> None:
    with pytest.raises(ValueError, match=f"never references {missing};"):
        versioned_index(html, "abc")


# --- build_site ---------------------------------------------------------------

WEB = {
    "index.html": REAL_INDEX.encode(),
    "css/app.css": b"body {}\n",
    "js/main.js": b'import { loadSite } from "./data.js";\n',
    "js/data.js": b"export const SCHEMA_VERSION = 10;\r\n",
    "test/data.test.js": b"// node --test\n",
    "data/status.json": b'{"schema_version":10}\n',
    "data/routes/bus-21.json": b'{"key":"bus-21"}\n',
}


def make_web(root: Path, files: dict[str, bytes] = WEB) -> Path:
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    return root


def tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_build_site_writes_the_published_copy(tmp_path: Path) -> None:
    web = make_web(tmp_path / "web")
    version = build_site(web, tmp_path / "site")
    assert version == asset_version(
        {name: WEB[name] for name in ("css/app.css", "js/main.js", "js/data.js")}
    )
    assert tree(tmp_path / "site") == {
        "index.html": versioned_index(REAL_INDEX, version).encode(),
        f"css-{version}/app.css": WEB["css/app.css"],
        f"js-{version}/main.js": WEB["js/main.js"],
        f"js-{version}/data.js": WEB["js/data.js"],
        "data/status.json": WEB["data/status.json"],
        "data/routes/bus-21.json": WEB["data/routes/bus-21.json"],
    }
    # The source is untouched.
    assert tree(web) == {name: WEB[name] for name in sorted(WEB)}


def test_nested_code_is_copied_and_versioned(tmp_path: Path) -> None:
    # Hand-built: a module in a subfolder (none today) is part of the code.
    nested = {**WEB, "js/lib/util.js": b"export const x = 1;\n"}
    version = build_site(make_web(tmp_path / "web", nested), tmp_path / "site")
    assert version != build_site(make_web(tmp_path / "plain"), tmp_path / "site-2")
    util = tmp_path / "site" / f"js-{version}" / "lib" / "util.js"
    assert util.read_bytes() == nested["js/lib/util.js"]


def test_build_site_into_an_empty_folder(tmp_path: Path) -> None:
    web = make_web(tmp_path / "web")
    (tmp_path / "site").mkdir()
    version = build_site(web, tmp_path / "site")
    assert (tmp_path / "site" / f"js-{version}" / "main.js").is_file()


def test_data_changes_keep_the_code_version(tmp_path: Path) -> None:
    first = build_site(make_web(tmp_path / "a"), tmp_path / "site-a")
    newer = {**WEB, "data/status.json": b'{"schema_version":10,"new":1}\n'}
    second = build_site(make_web(tmp_path / "b", newer), tmp_path / "site-b")
    assert second == first


def test_index_newlines_are_kept_exactly(tmp_path: Path) -> None:
    crlf = REAL_INDEX.replace("\n", "\r\n")
    web = make_web(tmp_path / "web", {**WEB, "index.html": crlf.encode()})
    version = build_site(web, tmp_path / "site")
    expected = versioned_index(crlf, version).encode()
    assert (tmp_path / "site" / "index.html").read_bytes() == expected


@pytest.mark.parametrize("stale", ["old.txt", "js-0123456789/main.js"])
def test_build_site_refuses_a_folder_with_files(tmp_path: Path, stale: str) -> None:
    web = make_web(tmp_path / "web")
    make_web(tmp_path / "site", {stale: b"old"})
    with pytest.raises(FileExistsError, match="already exists and isn't empty"):
        build_site(web, tmp_path / "site")
    assert tree(tmp_path / "site") == {stale: b"old"}


def test_build_site_refuses_a_file_as_the_folder(tmp_path: Path) -> None:
    web = make_web(tmp_path / "web")
    (tmp_path / "site").write_bytes(b"")
    with pytest.raises(FileExistsError, match="already exists"):
        build_site(web, tmp_path / "site")


def test_build_site_without_data_names_the_export(tmp_path: Path) -> None:
    files = {name: data for name, data in WEB.items() if not name.startswith("data/")}
    web = make_web(tmp_path / "web", files)
    with pytest.raises(FileNotFoundError, match=r"status\.json; make the data first"):
        build_site(web, tmp_path / "site")
    assert not (tmp_path / "site").exists()


@pytest.mark.parametrize("folder", ["js", "css"])
def test_build_site_without_a_code_folder(tmp_path: Path, folder: str) -> None:
    files = {name: data for name, data in WEB.items() if not name.startswith(folder)}
    web = make_web(tmp_path / "web", files)
    with pytest.raises(FileNotFoundError, match=f"no .*{folder} folder"):
        build_site(web, tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_build_site_with_an_unversionable_index_writes_nothing(tmp_path: Path) -> None:
    web = make_web(tmp_path / "web", {**WEB, "index.html": b"<p>no code</p>"})
    with pytest.raises(ValueError, match="never references js/, css/"):
        build_site(web, tmp_path / "site")
    assert not (tmp_path / "site").exists()


# --- the deploy command ---------------------------------------------------------


def test_main_deploy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    web = make_web(tmp_path / "web")
    out = tmp_path / "site"
    assert main(["deploy", str(out), "--web", str(web)]) == 0
    version = next(path.name for path in out.iterdir() if path.name.startswith("js-"))
    assert capsys.readouterr().out == (
        f"wrote 6 files to {out} (code version {version.removeprefix('js-')})\n"
    )


def test_main_deploy_refuses_a_full_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    web = make_web(tmp_path / "web")
    make_web(tmp_path / "site", {"old.txt": b"old"})
    assert main(["deploy", str(tmp_path / "site"), "--web", str(web)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")
    assert "already exists and isn't empty" in captured.err
