"""Normalize street names so alert locations can be compared to OSM names.

Alerts write ``"17th & Washington"`` or ``"Broad St"``; OSM writes
``"South 17th Street"`` / ``"Washington Avenue"``. Both sides go through
the same functions here, so a rule can never apply to one side only by
accident.
"""

from typing import NamedTuple

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
}
"""Final word (casefolded, dots removed) -> canonical street type.

Only types the real data needs. Words that are often part of a name
(Park, Square, Ferry, Ridge) are left out on purpose: with ``"park"`` here,
alert ``"Hunting Park"`` would split as base ``"hunting"``.
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
