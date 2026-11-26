"""A detour's own path, from its message's steps (tier C).

``"SB via 17th, Left on Washington, Right on Broad, Right on Reed, Left on
17th, Reg Rt"``: from the start (17th & Washington), along Washington to
Broad, Broad to Reed, Reed to 17th, then 17th back onto the route. Each
leg follows one street's OSM ways (``walk.py``) to its nearest crossing
with the next street (``crossings.py``); every turn must agree with the
message. Any doubt: no path, never a guess.
"""

import itertools
from collections.abc import Iterable, Sequence
from typing import NamedTuple

import polars as pl

from septa_detours.match.crossings import find_crossings
from septa_detours.match.streets import split_shared_ways, street_matches
from septa_detours.match.walk import street_graph, turn_side, walk_street
from septa_detours.model import Step, Turn


class Leg(NamedTuple):
    """The part of a detour on one street.

    Attributes:
        street: The street as written in the message.
        nodes: OSM node IDs in travel order (one when the bus turns off at
            the corner it turned on at).
        points: Each node's ``(lon, lat)``.
    """

    street: str
    nodes: tuple[int, ...]
    points: tuple[tuple[float, float], ...]


def walk_turns(
    steps: Sequence[Step],
    sources: Iterable[int],
    ways: pl.DataFrame,
    keys: pl.DataFrame,
) -> tuple[tuple[Leg, ...], frozenset[int]] | None:
    """Walk the streets between the route and the last one: ``steps[1:-1]``.

    ``steps[0]`` is the route (``"via 17th"``) and the last step's street
    leads back onto it (walked by the caller, from the returned corner).
    Each street in between is walked from the corner the bus turned onto
    it at to its nearest crossing with the next street.

    Args:
        steps: The notice's ``route_steps``.
        sources: Where the walk starts: the start point's node(s).
        ways: The street cache.
        keys: ``street_key_table(ways)``.

    Returns:
        ``(legs, corner)``: one ``Leg`` per street in ``steps[1:-1]``, and
        the nodes of the crossing where the bus turns onto the last
        street (``sources`` itself when there are no legs, e.g. two
        steps). ``None`` when a street doesn't reach the next one along
        its ways (no crossing, or none reachable, or two equally near),
        or a turn between two legs disagrees with the message
        (``turn_side``; a turn it can't tell is accepted).
    """
    legs: list[Leg] = []
    corner = frozenset(sources)
    for step, following in itertools.pairwise(steps[1:]):
        street, next_street = split_shared_ways(
            street_matches(keys, step.street), street_matches(keys, following.street)
        )
        crossings = find_crossings(ways, street, next_street)
        graph = street_graph(ways, street)
        nodes = walk_street(
            graph,
            corner,
            (node for crossing in crossings for node in crossing.node_ids),
        )
        if nodes is None:
            return None
        leg = Leg(
            street=step.street,
            nodes=nodes,
            points=tuple((graph.nodes[n]["lon"], graph.nodes[n]["lat"]) for n in nodes),
        )
        if legs and not _turn_agrees(legs[-1], leg, step.turn):
            return None
        legs.append(leg)
        (crossing,) = (c for c in crossings if nodes[-1] in c.node_ids)
        corner = frozenset(crossing.node_ids)
    return tuple(legs), corner


def _turn_agrees(before: Leg, after: Leg, turn: Turn) -> bool:
    """Whether turning from ``before`` onto ``after`` is ``turn``.

    A turn ``turn_side`` can't tell (a one-node leg, or straight on)
    counts as agreeing.
    """
    side = turn_side(before.points, after.points)
    return side is None or side == turn
