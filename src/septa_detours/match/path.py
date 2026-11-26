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

import networkx as nx
import polars as pl

from septa_detours.geo import distance_to_line_m
from septa_detours.match.crossings import find_crossings
from septa_detours.match.place import REJOIN_RADIUS_M
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
        leg = _leg(graph, step.street, nodes)
        if legs and not _turn_agrees(legs[-1], leg, step.turn):
            return None
        legs.append(leg)
        (crossing,) = (c for c in crossings if nodes[-1] in c.node_ids)
        corner = frozenset(crossing.node_ids)
    return tuple(legs), corner


def _leg(graph: nx.Graph, street: str, nodes: tuple[int, ...]) -> Leg:
    """A ``Leg`` along ``nodes`` of ``graph``, with their points."""
    points = tuple((graph.nodes[n]["lon"], graph.nodes[n]["lat"]) for n in nodes)
    return Leg(street=street, nodes=nodes, points=points)


def _turn_agrees(before: Leg, after: Leg, turn: Turn) -> bool:
    """Whether turning from ``before`` onto ``after`` is ``turn``.

    A turn ``turn_side`` can't tell (a one-node leg, or straight on)
    counts as agreeing.
    """
    side = turn_side(before.points, after.points)
    return side is None or side == turn


def walk_to_route(
    steps: Sequence[Step],
    corner: Iterable[int],
    ways: pl.DataFrame,
    keys: pl.DataFrame,
    lines: Sequence[Sequence[Sequence[float]]],
    rejoin_node: int | None,
) -> Leg | None:
    """Walk the last street from ``corner`` back onto the route.

    With a known rejoin (tier B's: the last two streets' crossing, so
    usually ``corner`` itself), the walk must end on it. Without one, the
    last street isn't the route itself ("Right on Ridge, Left on Francis,
    Reg Rt"): the walk goes to its nearest node within
    ``REJOIN_RADIUS_M`` of ``lines``, and that node is the rejoin. But
    if ``corner`` is itself that near the route, where the bus gets back
    on can't be told (it would "rejoin" where it turned): no leg.

    Real data (``121123Z``): of 30 walks without a rejoin, the corner is
    89-462 m off the route in 23; within 30 m in 6, five of them
    two-street paths ("via Harbison ave, Right on Frankford", whose tier
    B rejoin is the start itself, so the caller drops it).

    Args:
        steps: The notice's ``route_steps``; at least two (the last
            street and the one before it, which ``corner`` is on).
        corner: Where the bus turns onto the last street (from
            ``walk_turns``).
        ways: The street cache.
        keys: ``street_key_table(ways)``.
        lines: The affected shapes, as ``[lon, lat]`` lists.
        rejoin_node: The known rejoin's node, or ``None``.

    Returns:
        The last leg (one node when the bus is back on the route at
        ``corner``), or ``None``: the rejoin or the route isn't reachable
        along the last street, two targets are equally near, or (no
        rejoin) ``corner`` is already near the route.
    """
    corner = frozenset(corner)
    _, last = split_shared_ways(
        street_matches(keys, steps[-2].street), street_matches(keys, steps[-1].street)
    )
    graph = street_graph(ways, last)
    if rejoin_node is not None:
        targets: set[int] = {rejoin_node}
    else:
        targets = {
            node
            for node, data in graph.nodes(data=True)
            if any(
                distance_to_line_m(data["lon"], data["lat"], line) <= REJOIN_RADIUS_M
                for line in lines
            )
        }
        if targets & corner:
            return None
    nodes = walk_street(graph, corner, targets)
    if nodes is None:
        return None
    return _leg(graph, steps[-1].street, nodes)
