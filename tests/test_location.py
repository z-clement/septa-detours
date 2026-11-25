import json

import pytest

from septa_detours.model import Intersection
from septa_detours.parse.location import PLURAL_TYPES, parse_location


@pytest.mark.parametrize(
    ("raw", "streets"),
    [
        # Real location text (fixtures and snapshots).
        ("17th & Washington", ("17th", "Washington")),
        ("Broad & Chestnut", ("Broad", "Chestnut")),
        ("16th St  & Locust St", ("16th St", "Locust St")),
        ("22nd  &  Chestnut", ("22nd", "Chestnut")),
        ("17th & Cecil B Moore", ("17th", "Cecil B Moore")),
        ("Darby Road & West Chester Pike", ("Darby Road", "West Chester Pike")),
        ("Market & 30th St", ("Market", "30th St")),
        # Names are kept as written: no case, typo or alias fixes here.
        ("15th & MArket", ("15th", "MArket")),
        ("Market & Schuykill", ("Market", "Schuykill")),
        ("West Chester Pike & Township line", ("West Chester Pike", "Township line")),
        # "and" as the separator.
        ("Ogontz and Roselyn", ("Ogontz", "Roselyn")),
        ("Garney and Lehigh", ("Garney", "Lehigh")),
        # A plural type after the second name goes onto both, singular.
        ("Arch & 15th Sts", ("Arch St", "15th St")),
        ("17th & Spring Garden Sts", ("17th St", "Spring Garden St")),
        ("Pennsylvania & Fairmount Aves", ("Pennsylvania Ave", "Fairmount Ave")),
    ],
)
def test_parse_location_intersection(raw: str, streets: tuple[str, str]) -> None:
    assert parse_location(raw) == Intersection(streets=streets)


@pytest.mark.parametrize(
    ("raw", "streets"),
    [
        # Hand-built: spacing and case around the separator.
        ("17th&Pine", ("17th", "Pine")),
        (" 17th &Pine ", ("17th", "Pine")),
        ("Ogontz AND Roselyn", ("Ogontz", "Roselyn")),
        ("Ogontz\tand Roselyn", ("Ogontz", "Roselyn")),
        # "and" only as a whole word.
        ("Anderson & Sandy", ("Anderson", "Sandy")),
        ("Rand & Andover", ("Rand", "Andover")),
        # Plurals: any case; "Streets" too; not when only part of a word.
        ("Arch & 15th STS", ("Arch St", "15th St")),
        ("JFK & 30th Streets", ("JFK Street", "30th Street")),
        ("Arch & Stsville", ("Arch", "Stsville")),
        # A plural only counts after the second name.
        ("Arch Sts & 15th", ("Arch Sts", "15th")),
        # Same name, different type: not the same street.
        ("Ridge Ave & Ridge Rd", ("Ridge Ave", "Ridge Rd")),
        # Words containing a form marker are fine: "Tower", "Station", "Atwood".
        ("Tower & Atwood", ("Tower", "Atwood")),
    ],
)
def test_parse_location_intersection_rules(raw: str, streets: tuple[str, str]) -> None:
    assert parse_location(raw) == Intersection(streets=streets)


@pytest.mark.parametrize("raw", ["", "   ", "\u00a0"])
def test_parse_location_rejects_blank(raw: str) -> None:
    with pytest.raises(ValueError, match=r"^blank location "):
        parse_location(raw)


@pytest.mark.parametrize(
    "raw",
    [
        # Real: one name, a missing name, other forms.
        "Dickinson",
        "PNC Center",
        "Broad &",
        "Chester Pk/Morton Ave & 9th St",
        "Frankford av & Hunting Prk to Torresdale",
        "University Ave at The VA Hospital",
        "Market St btwn 23rd & 19th Sts",
        "Schuylkill btw Walnut & Chestnut",
        "Devereaux Between Battersby & Harbison",
        "Henry Ave Btwn Fox St & Midvale",
        # Hand-built.
        "& Broad",
        "&",
        "Broad & Pine & 15th",
        "Broad and Pine & 15th",
        "and Broad",
        "Arch & Sts",
        "Arch AT 15th",
        # Each form marker alone, with an "&" that would otherwise split.
        "University Ave at VA & Woodland",
        "Frankford & Hunting Park to Torresdale",
        "Market btwn 23rd & 19th",
        "Market BTW 23rd & 19th",
        "Market between 23rd & 19th",
        "Spring Garden/Art Museum & Pennsylvania",
    ],
)
def test_parse_location_rejects_unrecognized(raw: str) -> None:
    with pytest.raises(ValueError, match=r"^unrecognized location "):
        parse_location(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "Ridge Ave & Ridge Ave",  # real
        "Ridge Ave & ridge ave",
        "Arch & Arch Sts",
    ],
)
def test_parse_location_rejects_same_street_twice(raw: str) -> None:
    with pytest.raises(ValueError, match=r"^same street twice in location "):
        parse_location(raw)


def test_parse_location_blank_error_quotes_raw_text() -> None:
    with pytest.raises(ValueError, match=r"^blank location '   '$"):
        parse_location("   ")


def test_parse_location_error_quotes_raw_text() -> None:
    # As sent, before cleaning, so the issue shows what SEPTA wrote.
    with pytest.raises(ValueError, match=r"^unrecognized location 'Broad  &'$"):
        parse_location("Broad  &")


def test_plural_types_keys_are_casefolded() -> None:
    for key in PLURAL_TYPES:
        assert key == key.casefold()


# Every fixture location that doesn't parse, with the reason. Adding a fixture
# breaks this on purpose: review its locations, then update the pin.
UNPARSED_FIXTURE_LOCATIONS = {
    "17th btwn Master & Jefferson": "unrecognized",
    "Bethayres Station": "unrecognized",
    "Broad &": "unrecognized",
    "Convention btw Health Science  & 33rd St": "unrecognized",
    "JFK Between  17th & 30th  Streets": "unrecognized",
    "JFK Blvd btwn 17th & 30th Sts": "unrecognized",
    "JFK btwn 20th & 15th/ Art Museum 16th": "unrecognized",
    "JFK/17th to 30th & Market 23rd to 19th": "unrecognized",
    "Market St btwn 23rd & 19th Sts": "unrecognized",
    "Market btwn 23rd & 19th": "unrecognized",
    "Old York Rd Btwn 65th Ave & 66th Ave": "unrecognized",
    "PNC Center": "unrecognized",
    "Ridge Ave & Ridge Ave": "same street twice",
    "Schuylkill btw Walnut & Chestnut": "unrecognized",
    "Summerdale Between Cheltenham & Alcott": "unrecognized",
    "University Ave at The VA Hospital": "unrecognized",
}


def test_fixture_locations_sweep(read_alert_fixture, alert_fixture_names) -> None:
    locations = {
        detour[field]
        for name in alert_fixture_names
        for detour in json.loads(read_alert_fixture(name))["detour"]
        for field in ("location_start", "location_end")
        if detour[field].strip()
    }
    unparsed = {}
    for raw in locations:
        try:
            parse_location(raw)
        except ValueError as error:
            unparsed[raw] = str(error).split(" location ")[0].removesuffix(" in")
    assert len(locations) == 67
    assert unparsed == UNPARSED_FIXTURE_LOCATIONS
