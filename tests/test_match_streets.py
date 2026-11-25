import pytest

from septa_detours.match.streets import STREET_TYPES, StreetName, split_street_type


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Real alert spellings.
        ("Broad", ("broad", None)),
        ("17th", ("17th", None)),
        ("16th St", ("16th", "street")),
        ("Malvern Ave", ("malvern", "avenue")),
        ("Frankford av", ("frankford", "avenue")),
        ("Old York Rd", ("old york", "road")),
        ("Tinicum Blvd", ("tinicum", "boulevard")),
        ("Station Dr", ("station", "drive")),
        ("Queen Ln", ("queen", "lane")),
        ("Huntingdon Pk", ("huntingdon", "pike")),
        ("Spring Garden", ("spring garden", None)),
        ("MArket", ("market", None)),
        ("J.F.K. Blvd", ("jfk", "boulevard")),
        ("JFK", ("jfk", None)),
        # Real OSM spellings.
        ("North Broad Street", ("north broad", "street")),
        ("Washington Avenue", ("washington", "avenue")),
        ("John F. Kennedy Boulevard", ("john f kennedy", "boulevard")),
        ("John F Kennedy Boulevard", ("john f kennedy", "boulevard")),
        ("West Chester Pike", ("west chester", "pike")),
        ("Krewstown Road", ("krewstown", "road")),
        ("Health Sciences Drive", ("health sciences", "drive")),
        ("Loretto Avenue", ("loretto", "avenue")),
    ],
)
def test_split_street_type_real_names(name: str, expected: tuple) -> None:
    assert split_street_type(name) == StreetName(*expected)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Leading "St" is Saint: only the last word can be a type.
        ("St Elizabeth Drive", ("st elizabeth", "drive")),
        ("St. Georges Place", ("st georges place", None)),
        # A type word that isn't last stays in the base.
        ("Avenue of the States", ("avenue of the states", None)),
        # Name-like words are not types (see STREET_TYPES docstring).
        ("Hunting Park", ("hunting park", None)),
        ("Penn Square", ("penn square", None)),
        ("Grays Ferry", ("grays ferry", None)),
        ("Ridge", ("ridge", None)),
        # Only a type word: it stays the base, never an empty base.
        ("Street", ("street", None)),
        ("St.", ("st", None)),
        # Type spelled with a dot.
        ("Mt. Airy Dr.", ("mt airy", "drive")),
        # Whitespace runs and padding collapse.
        ("  Spring   Garden\tSt ", ("spring garden", "street")),
        # Case of the type word doesn't matter.
        ("Washington AVE", ("washington", "avenue")),
    ],
)
def test_split_street_type_rules(name: str, expected: tuple) -> None:
    assert split_street_type(name) == StreetName(*expected)


@pytest.mark.parametrize("name", ["", "   ", ".", " . . "])
def test_split_street_type_rejects_blank(name: str) -> None:
    with pytest.raises(ValueError, match="blank street name"):
        split_street_type(name)


def test_blank_error_quotes_input() -> None:
    with pytest.raises(ValueError, match=r"' \. '"):
        split_street_type(" . ")


def test_street_types_are_closed_under_canonical_form() -> None:
    # Every canonical type is itself a key mapping to itself, so a type
    # spelled out in full is recognized and an output type is stable.
    for canonical in STREET_TYPES.values():
        assert STREET_TYPES[canonical] == canonical


def test_street_types_keys_are_normalized() -> None:
    # Keys are compared to casefolded, dot-free words.
    for key in STREET_TYPES:
        assert key == key.casefold().replace(".", "").strip()
        assert " " not in key
