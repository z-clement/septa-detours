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


class StreetName(NamedTuple):
    """A street name split into its base and its type, both normalized."""

    base: str
    """Casefolded words before the type, e.g. ``"spring garden"``."""
    street_type: str | None
    """Canonical type (a ``STREET_TYPES`` value), or ``None`` if not given."""


def split_street_type(name: str) -> StreetName:
    """Normalize ``name`` and split a known type off its last word.

    Normalizing: casefold, delete dots (``"J.F.K."`` -> ``"jfk"``,
    ``"John F. Kennedy"`` -> ``"john f kennedy"``), collapse whitespace.
    Then, if the last word is in ``STREET_TYPES``, it becomes the type:
    ``"Broad St"`` -> ``("broad", "street")``. Only the last word is
    checked, so a leading ``"St"`` (Saint) stays in the base.

    A name that is only a type word keeps it as the base
    (``"Street"`` -> ``("street", None)``), so the base is never empty.

    Raises:
        ValueError: ``name`` has no words (blank, or only dots).
    """
    words = name.replace(".", "").casefold().split()
    if not words:
        raise ValueError(f"blank street name {name!r}")
    *rest, last = words
    street_type = STREET_TYPES.get(last)
    if street_type is None or not rest:
        return StreetName(" ".join(words), None)
    return StreetName(" ".join(rest), street_type)
