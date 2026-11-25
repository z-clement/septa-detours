"""Split location text into street names.

``"A & B"`` -> ``Intersection``; ``"A btwn B & C"`` -> ``Segment``.

Names are kept as written (only cleaned); normalizing them for OSM is
``match/``'s job. Anything not in a recognized form raises, so the caller
records an issue instead of guessing.
"""

import re

from septa_detours.model import Intersection, Location, Segment
from septa_detours.parse.text import clean_text

PLURAL_TYPES: dict[str, str] = {"sts": "St", "aves": "Ave", "streets": "Street"}
"""Final word of ``"A & B Sts"`` (casefolded) -> the type each street gets.

Only the plurals seen in real locations (``Sts``, ``Aves``, ``Streets``).
"""

_PAIR_SEPARATOR = re.compile(r"\s*&\s*|\s+and\s+", re.IGNORECASE)
"""``&`` (spaces optional) or the word ``and``."""

_BETWEEN = re.compile(r"\s*\b(?:btwn|btw|between)\b\s*", re.IGNORECASE)
"""The segment marker, as a whole word (real: ``btwn``, ``Btwn``, ``btw``,
``Between``), with the spaces around it."""

_OTHER_FORM = re.compile(r"/|\b(?:to|at)\b", re.IGNORECASE)
"""Marks a form not handled yet: ``"Chester Pk/Morton Ave & 9th St"``,
``"Frankford av & Hunting Prk to Torresdale"``,
``"University Ave at The VA Hospital"``."""


def parse_location(raw: str) -> Location:
    """Parse location text into a structured ``Location``.

    Recognized:

    - An intersection, ``"A & B"`` or ``"A and B"``: ``"17th &
      Washington"`` -> ``Intersection(streets=("17th", "Washington"))``.
      A plural type after the second name applies to both: ``"Arch & 15th
      Sts"`` -> ``("Arch St", "15th St")``.
    - A segment, ``"A btwn B & C"`` (or ``btw``, ``between``): ``"Spruce
      btw 34th & 36th"`` -> ``Segment(street="Spruce", between=("34th",
      "36th"))``. A plural after ``C`` applies to ``B`` and ``C`` only:
      ``"JFK Blvd btwn 17th & 30th Sts"`` -> ``between=("17th St",
      "30th St")``.

    Args:
        raw: A raw ``location_start`` or ``location_end``.

    Raises:
        ValueError: ``raw`` is blank, isn't in a recognized form (no
            separator, a missing name as in ``"Broad &"``, three names, two
            ``btwn``, an ``&`` before ``btwn``, or a ``/``, ``to`` or ``at``
            form), or names the same street twice (``"Ridge Ave & Ridge
            Ave"``: every joint between two Ridge Avenue ways would look
            like the intersection; likewise a segment bounded by its own
            street). The message quotes ``raw`` so it can go straight into
            ``issues``.
    """
    text = clean_text(raw)
    if text is None:
        raise ValueError(f"blank location {raw!r}")
    if _OTHER_FORM.search(text):
        raise ValueError(f"unrecognized location {raw!r}")
    parts = _BETWEEN.split(text)
    if len(parts) == 1:
        return Intersection(streets=_split_pair(text, raw))
    if len(parts) != 2 or not parts[0] or _PAIR_SEPARATOR.search(parts[0]):
        raise ValueError(f"unrecognized location {raw!r}")
    street, bounds = parts
    between = _split_pair(bounds, raw)
    if street.casefold() in {bound.casefold() for bound in between}:
        raise ValueError(f"same street twice in location {raw!r}")
    return Segment(street=street, between=between)


def _split_pair(text: str, raw: str) -> tuple[str, str]:
    """Split cleaned ``"A & B"`` / ``"A & B Sts"`` into two street names.

    ``raw`` is only quoted in error messages.
    """
    pieces = _PAIR_SEPARATOR.split(text)
    if len(pieces) != 2 or not all(pieces):
        raise ValueError(f"unrecognized location {raw!r}")
    first, second = pieces
    *second_words, last = second.split(" ")
    singular = PLURAL_TYPES.get(last.casefold())
    if singular is not None:
        if not second_words:
            raise ValueError(f"unrecognized location {raw!r}")
        first = f"{first} {singular}"
        second = f"{' '.join(second_words)} {singular}"
    if first.casefold() == second.casefold():
        raise ValueError(f"same street twice in location {raw!r}")
    return first, second
