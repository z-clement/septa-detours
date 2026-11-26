"""Read a detour's path from its message (tier B/C of the geography plan).

``"SB via 17th, Left on Washington, Right on Broad, Reg Rt"`` -> the
streets the bus takes, in order, until it rejoins its regular route.
Names are kept as written (only cleaned); normalizing them for OSM is
``match/``'s job. Anything not in a recognized form raises, so the caller
can leave the path out instead of guessing.
"""

import re

from septa_detours.model import Step, Turn

_VIA = re.compile(r"\bvia\b|\bvia(?=[A-Z])", re.IGNORECASE)
"""Where the path starts: the word ``via`` (also glued on: ``viaTasker``)."""

_REJOIN = re.compile(r"\breg\.?\s*rte?\b", re.IGNORECASE)
"""Where it ends: ``Reg Rt`` / ``Reg Rte`` (back on the regular route)."""

_TURN = re.compile(
    r"\b(?P<word>left|right)\s+on\b|\b(?P<letter>[LR])\s*-+",
    re.IGNORECASE,
)
"""A turn: ``Left on`` / ``Right on``, or the short ``L -`` / ``R--`` form."""

_PARENTHESES = re.compile(r"\([^)]*\)")
"""An aside like ``(slow, operation)``, dropped."""

_STREET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .']*$")
"""What's left of a street after cleaning: words, digits, dots, apostrophes."""

MAX_STREET_WORDS = 4
"""Longest real street name: ``"Cecil B Moore Ave"``. Longer means two
steps ran together (``"W Rittenhouse Sq L S Rittenhouse Sq"``)."""

_NOT_A_STREET = frozenset({"on", "around"})
"""Words that mean the text isn't just a street name (casefolded). Real
turns are ``Left on``/``Right on``, so any other ``on`` is an instruction
not handled (``Stay on``, ``Layover on``); ``around`` is real (``Left on
Around 30th St``)."""


def parse_route_steps(message: str) -> tuple[Step, ...]:
    """The detour's path: the ``via`` street, then each turn, to ``Reg Rt``.

    Commas inside a step are dropped (``"Right on, 16th St"``, ``"Market,
    St"``), as are parenthesized asides and a leading dash (``"via -
    Rockwell Ave"``). ``L -``/``R-`` are turns like ``Left on``/``Right
    on``. Only the first ``via`` and the first ``Reg Rt`` after it count.

    Raises:
        ValueError: No ``via``, no ``Reg Rt`` after it, or a step whose
            street is empty, longer than ``MAX_STREET_WORDS`` words, or not
            plain words (e.g. ``"Vare Layover on Vare until 1900"``).
    """
    via = _VIA.search(message)
    if via is None:
        raise ValueError("no 'via' in message")
    rejoin = _REJOIN.search(message, via.end())
    if rejoin is None:
        raise ValueError("no 'Reg Rt' after 'via'")
    path = _PARENTHESES.sub(" ", message[via.end() : rejoin.start()])

    turns: list[Turn] = ["via"]
    pieces: list[str] = []
    position = 0
    for turn in _TURN.finditer(path):
        pieces.append(path[position : turn.start()])
        word = (turn["word"] or turn["letter"]).casefold()
        turns.append("left" if word.startswith("l") else "right")
        position = turn.end()
    pieces.append(path[position:])
    return tuple(
        Step(turn=turn, street=_clean_street(piece))
        for turn, piece in zip(turns, pieces, strict=True)
    )


def _clean_street(piece: str) -> str:
    """One step's street: commas and extra spaces out, a leading dash off.

    Raises:
        ValueError: Empty, too long, or not plain words.
    """
    street = " ".join(piece.replace(",", " ").split()).lstrip("- ")
    words = street.split()
    if (
        len(words) > MAX_STREET_WORDS
        or not _STREET.match(street)
        or any(word.casefold() in _NOT_A_STREET for word in words)
    ):
        raise ValueError(f"not a street: {piece.strip()!r}")
    return street
