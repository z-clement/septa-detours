"""Find the affected travel direction in a detour message.

Two steps, kept separate so each can be tested alone:
    ``normalize_direction`` maps one token to a ``Direction``.
    ``find_directions`` lists every direction mentioned in a message.
Deciding what a list means (one, none, conflicting) is ``notice.py``'s job.
"""

from septa_detours.model import Direction


def normalize_direction(token: str) -> Direction | None:
    """Map one direction spelling to its normalized form.

    Args:
        token: A candidate word, e.g. ``"SB"``, ``"W/B"``, ``"Eastbound"``.

    Returns:
        ``"NB"``, ``"SB"``, ``"EB"`` or ``"WB"``, or ``None`` if ``token``
        isn't a direction spelling. Not an error: most words aren't.

    Spellings seen in real data: ``NB SB EB WB``, ``W/B``, ``Eastbound``,
    ``Westbound``. Decide on case: fixtures only show upper ``NB`` and title
    ``Eastbound``.
    """
    # TODO
    raise NotImplementedError


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
