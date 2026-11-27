"""Tests for export/deploy.py: the published site's versioned code URLs."""

from pathlib import Path

import pytest

from septa_detours.export.deploy import VERSION_LENGTH, asset_version, versioned_index

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
