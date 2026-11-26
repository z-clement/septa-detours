"""Normalize street names so alert locations can be compared to OSM names.

Alerts write ``"17th & Washington"`` or ``"Broad St"``; OSM writes
``"South 17th Street"`` / ``"Washington Avenue"``. Both sides go through
the same functions here, so a rule can never apply to one side only by
accident.
"""

from typing import NamedTuple

import polars as pl

STREET_TYPES: dict[str, str] = {
    "street": "street",
    "st": "street",
    "avenue": "avenue",
    "ave": "avenue",
    "av": "avenue",
    "road": "road",
    "rd": "road",
    "boulevard": "boulevard",
    "blvd": "boulevard",
    "drive": "drive",
    "dr": "drive",
    "lane": "lane",
    "ln": "lane",
    "pike": "pike",
    "pk": "pike",
    "square": "square",
    "sq": "square",
}
"""Final word (casefolded, dots removed) -> canonical street type.

Only types the real data needs. Words that are often part of a name
(Park, Ferry, Ridge) are left out on purpose: with ``"park"`` here,
alert ``"Hunting Park"`` would split as base ``"hunting"``. Square is in:
alerts abbreviate it (``"S Penn Sq"``, ``"Rittenhouse Sq"``), and OSM's
streets around a square end in it (``"South Penn Square"``), so both
sides split the same way.
"""


WORD_ALIASES: dict[str, str] = {
    # Abbreviations.
    "jfk": "john f kennedy",  # alert "JFK Blvd"; OSM "JFK Drive"
    "mt": "mount",  # alert "Mt Pleasant"; OSM "Mt Pleasant Road"
    "prk": "park",  # alert "Hunting Prk"
    # Missing or missing spaces.
    "graysferry": "grays ferry",  # alert "Graysferry & Washington"
    "malvernave": "malvern ave",  # alert "MalvernAve btwn 64th & Wynnewood"
    # Typos, each seen in a real alert (or OSM: "Schuykill Parkway").
    "batrum": "bartram",  # "Tinicum Blvd & Batrum Ave"
    "creshem": "cresheim",  # "Mt Pleasant & Creshem"
    "farimount": "fairmount",  # "Farimount & Beach"
    "krestown": "krewstown",  # "Krestown Rd Btwn Algon & Bloomfield"
    "lorretto": "loretto",  # "Oxford & Lorretto"
    "riggold": "ringgold",  # "Morris St & Riggold St"
    "schuykill": "schuylkill",  # "Market & Schuykill"
    "graden": "garden",  # "Spring Graden & Pennsylvania"
    "sping": "spring",  # route 31 message "Sping Garden"
}
"""Whole word (casefolded, dots removed) -> its replacement word(s).

Applied to alert text and OSM names alike, once, before the type is split
off (so ``"MalvernAve"`` -> ``"malvern ave"`` -> type ``"avenue"``). No
replacement word is itself a key, so one pass is enough. Exact entries
only, no fuzzy matching: an unseen typo stays unmatched. Deliberately
absent: ``"garney"`` (route 54; probably Garnet Street, but unverified).
"""


class StreetName(NamedTuple):
    """A street name split into its base and its type, both normalized."""

    base: str
    """Casefolded words before the type, e.g. ``"spring garden"``."""
    street_type: str | None
    """Canonical type (a ``STREET_TYPES`` value), or ``None`` if not given."""


def split_street_type(name: str) -> StreetName:
    """Normalize ``name`` and split a known type off its last word.

    Normalizing: casefold, delete dots (``"J.F.K."`` -> ``"jfk"``,
    ``"John F. Kennedy"`` -> ``"john f kennedy"``), collapse whitespace,
    replace whole words found in ``WORD_ALIASES`` (``"jfk"`` ->
    ``"john f kennedy"``).
    Then, if the last word is in ``STREET_TYPES``, it becomes the type:
    ``"Broad St"`` -> ``("broad", "street")``. Only the last word is
    checked, so a leading ``"St"`` (Saint) stays in the base.

    A name that is only a type word keeps it as the base
    (``"Street"`` -> ``("street", None)``), so the base is never empty.

    Raises:
        ValueError: ``name`` has no words (blank, or only dots).
    """
    words = [
        replacement
        for word in name.replace(".", "").casefold().split()
        for replacement in WORD_ALIASES.get(word, word).split()
    ]
    if not words:
        raise ValueError(f"blank street name {name!r}")
    *rest, last = words
    street_type = STREET_TYPES.get(last)
    if street_type is None or not rest:
        return StreetName(" ".join(words), None)
    return StreetName(" ".join(rest), street_type)


DIRECTION_PREFIXES = frozenset({"north", "south", "east", "west"})
"""Leading words dropped from OSM names (normalized form).

Full words only: in OSM, single letters are almost always letter
streets (``"E Street"``, ``"W Street"``), not abbreviated prefixes.
"""


def osm_street_keys(name: str) -> tuple[StreetName, ...]:
    """Return the keys an OSM street name can be looked up by.

    Always the full name first. If the base starts with a direction word
    and has more words after it, also the name without that word:
    ``"North Broad Street"`` -> ``("north broad", "street")``,
    ``("broad", "street")``. Alerts say ``"Broad"``; OSM spells out the
    Philly prefix.

    Not stripped when the direction word is the whole base:
    ``"South Street"`` is South Street, so only ``("south", "street")``.
    Stripping can add a wrong candidate (``"West Chester Pike"`` also
    gives ``("chester", "pike")``, a different real road); the caller
    must check candidates against the route. Alert text never goes
    through here: alert ``"South & 33rd"`` means South Street.

    Raises:
        ValueError: ``name`` has no words (see ``split_street_type``).
    """
    full = split_street_type(name)
    first, *rest = full.base.split(" ")
    if first not in DIRECTION_PREFIXES or not rest:
        return (full,)
    return (full, StreetName(" ".join(rest), full.street_type))


STREET_KEYS_SCHEMA = pl.Schema(
    {
        "way_id": pl.Int64,
        "base": pl.String,
        "street_type": pl.String,
        "prefix_dropped": pl.Boolean,
    }
)
"""Columns of ``street_key_table``. ``street_type`` null = no type;
``prefix_dropped`` = the key without the name's direction word (a looser
match than the full name)."""


def street_key_table(ways: pl.DataFrame) -> pl.DataFrame:
    """List the keys every OSM way can be looked up by.

    Args:
        ways: The street cache (``streets.cache.read_street_cache``); only
            ``way_id`` and ``name`` are read. Names are non-null there.

    Returns:
        A ``STREET_KEYS_SCHEMA`` frame, one row per ``osm_street_keys`` key
        of each way: in way order, the full key before the prefix-less
        one. Geometry stays in ``ways``; join back on ``way_id``.

    Raises:
        ValueError: A name has no words (only dots or whitespace), naming
            one way that has it. None in the 2026-11-24 cache; raising
            makes a changed extract loud instead of silently unmatched.

    ``osm_street_keys`` runs once per distinct name (40,003 for 146,871
    real ways), not once per way.
    """
    rows: list[tuple[str, str, str | None, bool]] = []
    for name in ways["name"].unique(maintain_order=True).to_list():
        try:
            keys = osm_street_keys(name)
        except ValueError as error:
            way_id = ways.filter(pl.col("name") == name)["way_id"].first()
            raise ValueError(f"way {way_id}: {error}") from None
        # osm_street_keys puts the full key first; any later one dropped a prefix.
        rows.extend(
            (name, key.base, key.street_type, index > 0)
            for index, key in enumerate(keys)
        )
    keys_by_name = pl.DataFrame(
        rows,
        schema={
            "name": pl.String,
            "base": pl.String,
            "street_type": pl.String,
            "prefix_dropped": pl.Boolean,
        },
        orient="row",
    )
    # "left_right": way order, then each name's keys in osm_street_keys order.
    return (
        ways.select("way_id", "name")
        .join(keys_by_name, on="name", how="inner", maintain_order="left_right")
        .select(STREET_KEYS_SCHEMA.names())
    )


ALERT_DIRECTION_LETTERS: dict[str, str] = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
}
"""An alert name's one-letter first word -> the direction OSM spells out."""


def alert_street_name(name: str) -> StreetName:
    """Normalize an alert's street name: ``split_street_type``, plus letters.

    Alerts abbreviate the Philly direction prefix (``"S Penn Sq"``, ``"W
    Rittenhouse Sq"``); OSM spells it out (``"South Penn Square"``). A
    first word in ``ALERT_DIRECTION_LETTERS`` becomes the full word when
    more words follow it: ``"S Broad St"`` -> ``("south broad",
    "street")``. Alert side only: in OSM a single letter is a letter
    street (``"E Street"``), and so is an alert's lone ``"E St"`` (base
    ``"e"``, nothing after it).

    Raises:
        ValueError: ``name`` has no words (see ``split_street_type``).
    """
    split = split_street_type(name)
    first, *rest = split.base.split(" ")
    if first not in ALERT_DIRECTION_LETTERS or not rest:
        return split
    return StreetName(
        " ".join([ALERT_DIRECTION_LETTERS[first], *rest]), split.street_type
    )


STREET_MATCH_SCHEMA = pl.Schema({"way_id": pl.Int64, "specificity": pl.Int8})
"""Columns of ``street_matches``."""


def street_matches(keys: pl.DataFrame, name: str) -> pl.DataFrame:
    """List the OSM ways one alert street name matches, and how closely.

    The rule: same base; a type in ``name`` must equal the way's type (no
    type in ``name`` accepts any). ``"Broad"`` matches ``North Broad
    Street`` (by its prefix-less key) and ``Broad Avenue``; ``"Broad St"``
    only the first.

    Args:
        keys: Output of ``street_key_table``.
        name: One street name as written in the alert, e.g. ``"Broad St"``.

    Returns:
        A ``STREET_MATCH_SCHEMA`` frame, one row per matching way, in
        ``keys`` order. ``specificity`` ranks the match for
        ``split_shared_ways``: 2 if it matched the way's full name (not the
        prefix-less key), plus 1 if ``name`` gave a type. So 0..3.

    ``name`` goes through ``alert_street_name``: ``"S Broad St"`` matches
    ``South Broad Street`` by its full name.

    Raises:
        ValueError: ``name`` is blank (see ``split_street_type``).
    """
    wanted = alert_street_name(name)
    condition = pl.col("base") == wanted.base
    if wanted.street_type is not None:
        condition &= pl.col("street_type") == wanted.street_type
    typed = int(wanted.street_type is not None)
    specificity = (~pl.col("prefix_dropped")).cast(pl.Int8) * 2 + typed
    return keys.filter(condition).select(
        "way_id", specificity.cast(pl.Int8).alias("specificity")
    )


def split_shared_ways(
    first: pl.DataFrame, second: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Give each way matched by both names of a pair to one side only.

    A way on both sides stays on the side with the higher ``specificity``
    (full-name match beats prefix-less; then a given type beats none). On
    a tie it stays with ``first``: both names then describe the same
    street, and leaving ``second`` without it means a street is never found
    crossing itself.

    Args:
        first: ``street_matches`` for the first-listed name (``"A"`` in
            ``"A & B"``).
        second: ``street_matches`` for the second.

    Returns:
        ``(first, second)`` with each shared way removed from the losing
        side; rows otherwise unchanged, order kept.
    """
    shared = first.join(second, on="way_id", how="inner", suffix="_second")
    second_wins = pl.col("specificity_second") > pl.col("specificity")
    to_second = shared.filter(second_wins).select("way_id")
    to_first = shared.filter(~second_wins).select("way_id")
    return (
        first.join(to_second, on="way_id", how="anti", maintain_order="left"),
        second.join(to_first, on="way_id", how="anti", maintain_order="left"),
    )
