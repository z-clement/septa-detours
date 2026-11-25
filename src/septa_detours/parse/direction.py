"""Find the affected travel direction in a detour message.

Two steps, kept separate so each can be tested alone:
    ``normalize_direction`` maps one token to a ``Direction``.
    ``find_directions`` lists every direction mentioned in a message.
Deciding what a list means (one, none, conflicting) is ``notice.py``'s job.
"""

from septa_detours.model import Direction

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

    Edge cases to test: a direction glued to punctuation
    (``"11:59pm SB,"``), and words that merely contain the letters
    (a street named ``"Webster"`` must not count as ``WB``).
    """
    # TODO: split into tokens (think about which characters separate
    #   tokens, given "W/B" must survive as one), then normalize each.
    raise NotImplementedError
