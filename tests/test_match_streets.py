import pytest

from septa_detours.match.streets import (
    STREET_TYPES,
    WORD_ALIASES,
    StreetName,
    osm_street_keys,
    split_street_type,
)


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
        ("J.F.K. Blvd", ("john f kennedy", "boulevard")),
        ("JFK", ("john f kennedy", None)),
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
        ("Mt. Airy Dr.", ("mount airy", "drive")),
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


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Real OSM names with a Philly direction prefix: two keys, full first.
        (
            "North Broad Street",
            [("north broad", "street"), ("broad", "street")],
        ),
        ("South 17th Street", [("south 17th", "street"), ("17th", "street")]),
        (
            "East Hunting Park Avenue",
            [("east hunting park", "avenue"), ("hunting park", "avenue")],
        ),
        # A different real road comes out as a key too; the caller filters.
        ("West Chester Pike", [("west chester", "pike"), ("chester", "pike")]),
        # Type not in STREET_TYPES: the prefix still comes off the base.
        ("South Penn Square", [("south penn square", None), ("penn square", None)]),
        # Case and dots are normalized before the prefix check.
        ("NORTH Broad St.", [("north broad", "street"), ("broad", "street")]),
    ],
)
def test_osm_street_keys_strips_prefix(name: str, expected: list[tuple]) -> None:
    assert osm_street_keys(name) == tuple(StreetName(*key) for key in expected)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # No prefix.
        ("Washington Avenue", ("washington", "avenue")),
        # The direction word is the whole base: it is the street's name.
        ("South Street", ("south", "street")),
        ("West Avenue", ("west", "avenue")),
        ("North", ("north", None)),
        # Single letters are letter streets, not prefixes.
        ("W Street", ("w", "street")),
        ("E 3rd Avenue", ("e 3rd", "avenue")),
        # A word that only starts like a direction.
        ("Northwood Avenue", ("northwood", "avenue")),
        ("Westminster Avenue", ("westminster", "avenue")),
        # Trailing directions are left alone (decided: not stripped).
        ("Broad Street North", ("broad street north", None)),
    ],
)
def test_osm_street_keys_single_key(name: str, expected: tuple) -> None:
    assert osm_street_keys(name) == (StreetName(*expected),)


def test_osm_street_keys_strips_only_one_prefix() -> None:
    assert osm_street_keys("North East Avenue") == (
        StreetName("north east", "avenue"),
        StreetName("east", "avenue"),
    )


def test_osm_street_keys_rejects_blank() -> None:
    with pytest.raises(ValueError, match="blank street name"):
        osm_street_keys(" . ")


def alert_matches_osm(alert: str, osm: str) -> bool:
    """The tier A rule: same base; the alert's type, if given, must agree."""
    wanted = split_street_type(alert)
    return any(
        key.base == wanted.base and wanted.street_type in (None, key.street_type)
        for key in osm_street_keys(osm)
    )


# (alert piece, real OSM name it should match). Alert pieces are real
# location text (split by hand); "Sping Garden" is from route 31's message.
ALIAS_EVIDENCE = [
    ("JFK Blvd", "John F. Kennedy Boulevard"),
    ("J.F.K. Blvd", "John F Kennedy Boulevard"),
    ("Mt Pleasant", "East Mount Pleasant Avenue"),
    ("Hunting Prk", "West Hunting Park Avenue"),
    ("Graysferry", "Grays Ferry Avenue"),
    ("MalvernAve", "Malvern Avenue"),
    ("Batrum Ave", "Bartram Avenue"),
    ("Creshem", "Cresheim Road"),
    ("Farimount", "Fairmount Avenue"),
    ("Krestown Rd", "Krewstown Road"),
    ("Lorretto", "Loretto Avenue"),
    ("Riggold St", "North Ringgold Street"),
    ("Schuykill", "South Schuylkill Avenue"),
    ("Spring Graden", "Spring Garden Street"),
    ("Sping Garden", "North Spring Garden Street"),
]


@pytest.mark.parametrize(("alert", "osm"), ALIAS_EVIDENCE)
def test_aliased_alert_matches_osm(alert: str, osm: str) -> None:
    assert alert_matches_osm(alert, osm)


def test_every_alias_has_evidence() -> None:
    # A new alias must come with a real (alert, OSM) pair above.
    used = {
        word
        for alert, _ in ALIAS_EVIDENCE
        for word in alert.replace(".", "").casefold().split()
    }
    assert set(WORD_ALIASES) <= used


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Glued type: aliased first, then the type is split off.
        ("MalvernAve", ("malvern", "avenue")),
        # Only word is an alias.
        ("Mt", ("mount", None)),
        # Alias in the middle of a name.
        ("Old Graysferry Rd", ("old grays ferry", "road")),
        # Case and dots are normalized before the lookup.
        ("SCHUYKILL", ("schuylkill", None)),
        ("M.T. Pleasant", ("mount pleasant", None)),
        # Whole words only.
        ("Mtn Road", ("mtn", "road")),
        ("Prkway", ("prkway", None)),
        # OSM's own variants get the same treatment (decided: both sides).
        ("JFK Drive", ("john f kennedy", "drive")),
        ("Mt Pleasant Road", ("mount pleasant", "road")),
        ("Schuykill Parkway", ("schuylkill parkway", None)),
    ],
)
def test_split_street_type_aliases(name: str, expected: tuple) -> None:
    assert split_street_type(name) == StreetName(*expected)


def test_alias_reaches_osm_keys() -> None:
    assert osm_street_keys("North JFK Street") == (
        StreetName("north john f kennedy", "street"),
        StreetName("john f kennedy", "street"),
    )


def test_aliased_type_is_still_strict() -> None:
    # "JFK Blvd" must not match "JFK Drive" (decided: strict if given).
    assert not alert_matches_osm("JFK Blvd", "JFK Drive")
    assert alert_matches_osm("JFK", "JFK Drive")


def test_word_aliases_keys_are_normalized_single_words() -> None:
    for key in WORD_ALIASES:
        assert key == key.casefold().replace(".", "")
        assert key.split() == [key]


def test_word_aliases_values_are_normalized_and_final() -> None:
    # One pass is enough: no replacement word is itself an alias key.
    for value in WORD_ALIASES.values():
        assert value == " ".join(value.casefold().replace(".", "").split())
        assert not set(value.split()) & set(WORD_ALIASES)


def test_word_aliases_never_replace_a_type_word() -> None:
    assert not set(WORD_ALIASES) & set(STREET_TYPES)
