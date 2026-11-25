"""Find the affected travel direction in a detour message.

Two steps, kept separate so each can be tested alone:
    ``normalize_direction`` maps one token to a ``Direction``.
    ``find_directions`` lists every direction mentioned in a message.
Deciding what a list means (one, none, conflicting) is ``notice.py``'s job.
"""

import re

from septa_detours.model import Direction

_TOKEN_SEPARATOR = re.compile(r"[^\w/]+")
"""Runs of characters that separate tokens: anything but word characters
and ``/`` (kept so ``W/B`` survives as one token)."""

_SPELLINGS: dict[str, Direction] = {
    "nb": "NB",
    "sb": "SB",
    "eb": "EB",
    "wb": "WB",
    "n/b": "NB",
    "s/b": "SB",
    "e/b": "EB",
    "w/b": "WB",
    "northbound": "NB",
    "southbound": "SB",
    "eastbound": "EB",
    "westbound": "WB",
}
"""Accepted spellings, casefolded. Each pattern covers all four directions,
though real data (2026-11-25) only shows ``NB SB EB WB``, ``W/B``,
``Eastbound`` and ``Westbound``."""


def normalize_direction(token: str) -> Direction | None:
    """Map one direction spelling to its normalized form.

    Args:
        token: One whole token, already split from the message, e.g.
            ``"SB"``, ``"W/B"``, ``"Eastbound"``.

    Returns:
        ``"NB"``, ``"SB"``, ``"EB"`` or ``"WB"``, or ``None`` if ``token``
        isn't a direction spelling. Not an error: most words aren't.

    Case is ignored (``"nb"``, ``"EASTBOUND"`` match). Nothing else is
    forgiven: attached punctuation or whitespace (``"SB,"``, ``" NB"``) gives
    ``None``, since stripping it is the tokenizer's job, and so does a word
    that merely contains a spelling (``"Webster"``).
    """
    return _SPELLINGS.get(token.casefold())


def find_directions(message: str) -> tuple[Direction, ...]:
    """List the directions mentioned in a message, in order of appearance.

    Args:
        message: A raw API ``message``.

    Returns:
        Each distinct direction once, in first-appearance order; empty if
        none. Examples (from fixtures):

        - ``"..., SB via 17th St, ..."`` -> ``("SB",)``
        - ``"Until 11:59pm 10/31/27, W/B via JFK,, ..."`` -> ``("WB",)``
        - ``"... @ 32nd & Grays Ferry, Eastbound"`` -> ``("EB",)``
        - ``"NB Via Gloria Dei, ... Recover NB On ..."`` -> ``("NB",)``
        - ``"..., Via Huntingdon Pke, ..."`` -> ``()``

    Tokens are split on every character except letters, digits, ``_`` and
    ``/``, so ``"11:59pm SB,"`` yields ``SB``, ``"W/B"`` stays whole, and
    ``"Webster"`` is one token that isn't a direction. Known gap: a slash
    between two directions (``"NB/SB"``, not seen in real data) is one
    token and finds nothing.
    """
    tokens = _TOKEN_SEPARATOR.split(message)
    found = (normalize_direction(token) for token in tokens)
    return tuple(dict.fromkeys(d for d in found if d is not None))
