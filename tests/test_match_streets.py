import polars as pl
import pytest

from septa_detours.match import streets
from septa_detours.match.streets import (
    ALERT_DIRECTION_LETTERS,
    DIRECTION_PREFIXES,
    STREET_KEYS_SCHEMA,
    STREET_MATCH_SCHEMA,
    STREET_TYPES,
    WORD_ALIASES,
    StreetName,
    alert_street_name,
    osm_street_keys,
    split_shared_ways,
    split_street_type,
    street_key_table,
    street_matches,
)
from septa_detours.streets.load import STREET_WAYS_SCHEMA


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
        ("S Penn Sq", ("s penn", "square")),
        ("Rittenhouse Sq", ("rittenhouse", "square")),
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
        ("South Penn Square", ("south penn", "square")),
        ("West Rittenhouse Square", ("west rittenhouse", "square")),
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
        ("South Penn Square", [("south penn", "square"), ("penn", "square")]),
        # Hand-built, type not in STREET_TYPES: the prefix still comes off.
        ("East Hunting Park", [("east hunting park", None), ("hunting park", None)]),
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


def make_ways(rows: list[tuple[int, str]]) -> pl.DataFrame:
    """A street-cache frame from ``(way_id, name)``; geometry is filler."""
    full_rows = [
        (way_id, name, "residential", [1, 2], [[-75.16, 39.95], [-75.17, 39.95]])
        for way_id, name in rows
    ]
    return pl.DataFrame(full_rows, schema=STREET_WAYS_SCHEMA, orient="row")


def test_street_key_table_rows() -> None:
    ways = make_ways(
        [
            (101, "North Broad Street"),
            (102, "Washington Avenue"),
            (103, "South Street"),
            (104, "Spring Garden"),
        ]
    )
    assert street_key_table(ways).rows() == [
        (101, "north broad", "street", False),
        (101, "broad", "street", True),
        (102, "washington", "avenue", False),
        (103, "south", "street", False),
        (104, "spring garden", None, False),
    ]


def test_street_key_table_schema_is_exact() -> None:
    # Only the key columns: no name, highway or geometry leak through.
    table = street_key_table(make_ways([(101, "North Broad Street")]))
    assert table.schema == STREET_KEYS_SCHEMA


def test_street_key_table_keeps_way_order_for_repeated_names() -> None:
    # 103 shares 101's name but must still come after 102 (a plain polars
    # join doesn't keep order); its keys stay full-first.
    ways = make_ways(
        [
            (101, "North Broad Street"),
            (102, "Washington Avenue"),
            (103, "North Broad Street"),
        ]
    )
    assert street_key_table(ways)["way_id"].to_list() == [101, 101, 102, 103, 103]
    assert street_key_table(ways).filter(pl.col("way_id") == 103).rows() == [
        (103, "north broad", "street", False),
        (103, "broad", "street", True),
    ]


def test_street_key_table_applies_aliases() -> None:
    ways = make_ways([(7, "Schuykill Parkway"), (8, "JFK Drive")])
    assert street_key_table(ways).rows() == [
        (7, "schuylkill parkway", None, False),
        (8, "john f kennedy", "drive", False),
    ]


def test_street_key_table_empty_ways() -> None:
    table = street_key_table(make_ways([]))
    assert table.is_empty()
    assert table.schema == STREET_KEYS_SCHEMA


def test_street_key_table_blank_name_names_the_way() -> None:
    ways = make_ways([(101, "Broad Street"), (102, " . "), (103, " . ")])
    with pytest.raises(ValueError, match=r"^way 102: blank street name ' \. '$"):
        street_key_table(ways)


def test_street_key_table_normalizes_each_name_once(monkeypatch) -> None:
    calls: list[str] = []

    def counting_keys(name: str) -> tuple[StreetName, ...]:
        calls.append(name)
        return osm_street_keys(name)

    monkeypatch.setattr(streets, "osm_street_keys", counting_keys)
    ways = make_ways(
        [(101, "Broad Street"), (102, "Pine Street"), (103, "Broad Street")]
    )
    street_key_table(ways)
    assert calls == ["Broad Street", "Pine Street"]


BROAD_WAYS = [
    (1, "North Broad Street"),
    (2, "Broad Avenue"),
    (3, "Broad Street"),
    (4, "South Broad Street"),
    (5, "Broadway"),
    (6, "West Chester Pike"),
    (7, "Chester Pike"),
    (8, "John F. Kennedy Boulevard"),
]


@pytest.fixture
def broad_keys() -> pl.DataFrame:
    return street_key_table(make_ways(BROAD_WAYS))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # No type: any type; prefix-less match 0, full-name match 2.
        ("Broad", [(1, 0), (2, 2), (3, 2), (4, 0)]),
        # Type given: must equal; +1 for it.
        ("Broad St", [(1, 1), (3, 3), (4, 1)]),
        ("Broad Ave", [(2, 3)]),
        # The alert's own prefix matches the full key only.
        ("North Broad", [(1, 2)]),
        ("North Broad St", [(1, 3)]),
        # A prefix-less key can be a different real road.
        ("Chester Pk", [(6, 1), (7, 3)]),
        # Same normalization as OSM: dots, case, aliases.
        ("J.F.K. Blvd", [(8, 3)]),
        ("BROAD street", [(1, 1), (3, 3), (4, 1)]),
        # Whole base only: "Broad" is not "Broadway".
        ("Broadway", [(5, 2)]),
        # The alert's one-letter prefix is the full word (full-name match).
        ("S Broad St", [(4, 3)]),
        ("N. Broad", [(1, 2)]),
    ],
)
def test_street_matches(broad_keys, name: str, expected: list[tuple[int, int]]) -> None:
    assert street_matches(broad_keys, name).rows() == expected


@pytest.mark.parametrize("name", ["Broad Rd", "Walnut", "South Chester Pike"])
def test_street_matches_none(broad_keys, name: str) -> None:
    result = street_matches(broad_keys, name)
    assert result.is_empty()
    assert result.schema == STREET_MATCH_SCHEMA


def test_street_matches_schema_is_exact(broad_keys) -> None:
    assert street_matches(broad_keys, "Broad").schema == STREET_MATCH_SCHEMA


def test_street_matches_rejects_blank(broad_keys) -> None:
    with pytest.raises(ValueError, match="blank street name"):
        street_matches(broad_keys, " ")


def make_matches(rows: list[tuple[int, int]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=STREET_MATCH_SCHEMA, orient="row")


def test_split_shared_ways_no_overlap_is_unchanged() -> None:
    first = make_matches([(1, 2), (2, 0)])
    second = make_matches([(3, 3)])
    new_first, new_second = split_shared_ways(first, second)
    assert new_first.rows() == [(1, 2), (2, 0)]
    assert new_second.rows() == [(3, 3)]
    assert new_first.schema == new_second.schema == STREET_MATCH_SCHEMA


@pytest.mark.parametrize(
    ("first_spec", "second_spec", "winner"),
    [(3, 2, "first"), (0, 1, "second"), (2, 2, "first"), (0, 0, "first")],
)
def test_split_shared_ways_specificity_decides(
    first_spec: int, second_spec: int, winner: str
) -> None:
    first = make_matches([(10, 2), (1, first_spec), (11, 0)])
    second = make_matches([(20, 3), (1, second_spec), (21, 1)])
    new_first, new_second = split_shared_ways(first, second)
    if winner == "first":
        assert new_first.rows() == [(10, 2), (1, first_spec), (11, 0)]
        assert new_second.rows() == [(20, 3), (21, 1)]
    else:
        assert new_first.rows() == [(10, 2), (11, 0)]
        assert new_second.rows() == [(20, 3), (1, second_spec), (21, 1)]


def test_split_shared_ways_keeps_schema_and_order() -> None:
    first = make_matches([(5, 2), (1, 0), (4, 2), (2, 3)])
    second = make_matches([(1, 3), (3, 0), (2, 1)])
    new_first, new_second = split_shared_ways(first, second)
    assert new_first.rows() == [(5, 2), (4, 2), (2, 3)]
    assert new_second.rows() == [(1, 3), (3, 0)]
    assert new_first.schema == new_second.schema == STREET_MATCH_SCHEMA


def test_split_shared_ways_full_name_beats_prefix_less(broad_keys) -> None:
    # "North Broad & Broad": way 1 matches both; its full name is "North
    # Broad Street", so it stays with "North Broad".
    first, second = split_shared_ways(
        street_matches(broad_keys, "North Broad"), street_matches(broad_keys, "Broad")
    )
    assert first.rows() == [(1, 2)]
    assert second.rows() == [(2, 2), (3, 2), (4, 0)]


def test_split_shared_ways_given_type_beats_none(broad_keys) -> None:
    # Way 3 "Broad Street": full name both sides; the typed name wins.
    first, second = split_shared_ways(
        street_matches(broad_keys, "Broad"), street_matches(broad_keys, "Broad St")
    )
    assert first.rows() == [(2, 2)]
    assert second.rows() == [(1, 1), (3, 3), (4, 1)]


def test_split_shared_ways_same_street_leaves_second_empty(broad_keys) -> None:
    # Both names normalize alike (an alias): every way ties and stays first.
    first, second = split_shared_ways(
        street_matches(broad_keys, "JFK Blvd"),
        street_matches(broad_keys, "John F Kennedy Blvd"),
    )
    assert first.rows() == [(8, 3)]
    assert second.is_empty()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Real alert spellings (route 2, 17, 44... messages).
        ("S Penn Sq", ("south penn", "square")),
        ("S. Penn Sq", ("south penn", "square")),
        ("W Rittenhouse Sq", ("west rittenhouse", "square")),
        ("N 5th St", ("north 5th", "street")),
        ("e Passyunk", ("east passyunk", None)),
        # A lone letter is a letter street, with or without a type.
        ("E St", ("e", "street")),
        ("W", ("w", None)),
        # Only the first word, and only these four letters.
        ("Avenue S", ("avenue s", None)),
        ("X Penn Sq", ("x penn", "square")),
        # Already spelled out: unchanged.
        ("South Penn Square", ("south penn", "square")),
    ],
)
def test_alert_street_name(name: str, expected: tuple) -> None:
    assert alert_street_name(name) == StreetName(*expected)


def test_alert_street_name_rejects_blank() -> None:
    with pytest.raises(ValueError, match="blank street name"):
        alert_street_name(" . ")


def test_alert_direction_letters_are_osm_prefixes() -> None:
    assert set(ALERT_DIRECTION_LETTERS.values()) == DIRECTION_PREFIXES


def test_street_matches_typed_name_skips_typeless_way() -> None:
    # Strict if given: an OSM name with no type isn't a "St".
    keys = street_key_table(make_ways([(1, "Broad"), (2, "Broad Street")]))
    assert street_matches(keys, "Broad St").rows() == [(2, 3)]
    assert street_matches(keys, "Broad").rows() == [(1, 2), (2, 2)]
