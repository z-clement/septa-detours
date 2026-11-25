"""Split location text into street names, e.g. ``"A & B"`` -> ``Intersection``.

Names are kept as written (only cleaned); normalizing them for OSM is
``match/``'s job. Anything not in a recognized form raises, so the caller
records an issue instead of guessing.
"""

import re

from septa_detours.model import Intersection, Location
from septa_detours.parse.text import clean_text

PLURAL_TYPES: dict[str, str] = {"sts": "St", "aves": "Ave", "streets": "Street"}
"""Final word of ``"A & B Sts"`` (casefolded) -> the type each street gets.

Only the plurals seen in real locations (``Sts``, ``Aves``, ``Streets``).
"""

_PAIR_SEPARATOR = re.compile(r"\s*&\s*|\s+and\s+", re.IGNORECASE)
"""``&`` (spaces optional) or the word ``and``."""

_OTHER_FORM = re.compile(r"/|\b(?:btwn|btw|between|to|at)\b", re.IGNORECASE)
"""Marks a form not handled yet: ``"Chester Pk/Morton Ave & 9th St"``,
``"Frankford av & Hunting Prk to Torresdale"``,
``"University Ave at The VA Hospital"``, ``"Market btwn 23rd & 19th"``."""


def parse_location(raw: str) -> Location:
    """Parse location text into a structured ``Location``.

    Recognized: an intersection, ``"A & B"`` or ``"A and B"``, e.g.
    ``"17th & Washington"`` -> ``Intersection(streets=("17th",
    "Washington"))``. A plural type after the second name applies to both:
    ``"Arch & 15th Sts"`` -> ``("Arch St", "15th St")``.

    Args:
        raw: A raw ``location_start`` or ``location_end``.

    Raises:
        ValueError: ``raw`` is blank, isn't in a recognized form (no
            separator, a missing name as in ``"Broad &"``, three names, or a
            ``/``, ``to``, ``at`` or ``btwn`` form), or names the same
            street twice (``"Ridge Ave & Ridge Ave"``: every joint between
            two Ridge Avenue ways would look like the intersection). The
            message quotes ``raw`` so it can go straight into ``issues``.
    """
    text = clean_text(raw)
    if text is None:
        raise ValueError(f"blank location {raw!r}")
    if _OTHER_FORM.search(text):
        raise ValueError(f"unrecognized location {raw!r}")
    return Intersection(streets=_split_pair(text, raw))


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
