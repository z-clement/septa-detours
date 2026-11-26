"""Walk a detour along one named street at a time (tier C).

The message says which streets to take (``"Left on Washington, Right on
Broad"``); each leg follows one street's OSM ways from where the bus
turned onto it to where it turns off. So each leg's graph is that street
alone, a few dozen nodes: never a routing engine choosing its own streets.

Graphs are networkx ``Graph`` objects: nodes are OSM node IDs with
``lon``/``lat`` attributes, edges join consecutive nodes of a way and
carry their ``length_m``.
"""

import itertools
from collections.abc import Iterable, Sequence
from typing import Literal

import networkx as nx
import polars as pl

from septa_detours.geo import metres_between


def street_graph(ways: pl.DataFrame, selected: pl.DataFrame) -> nx.Graph:
    """Build the graph of the selected ways: one street, as the bus can walk it.

    Undirected: the cache has no one-way tags, and the message already says
    which streets the bus takes. A node shared by two ways (where one way
    ends and the next begins, or a crossing of two selected ways) is one
    graph node, which is what joins the ways into a street.

    Args:
        ways: The street cache (``streets.cache.read_street_cache``).
        selected: The street's ways (``way_id`` column, e.g. from
            ``streets.street_matches``).

    Returns:
        The graph; empty when no way is selected. A way's lone node (a
        one-node way) is a node with no edges.
    """
    graph = nx.Graph()
    rows = ways.join(selected.select("way_id"), on="way_id", how="semi")
    for node_ids, coordinates in rows.select("node_ids", "coordinates").iter_rows():
        for node_id, (lon, lat) in zip(node_ids, coordinates, strict=True):
            graph.add_node(node_id, lon=lon, lat=lat)
        for (a, a_point), (b, b_point) in zip(
            zip(node_ids, coordinates, strict=True),
            zip(node_ids[1:], coordinates[1:], strict=True),
            strict=False,
        ):
            graph.add_edge(a, b, length_m=metres_between(a_point, b_point))
    return graph


def walk_street(
    graph: nx.Graph, sources: Iterable[int], targets: Iterable[int]
) -> tuple[int, ...] | None:
    """The shortest walk along ``graph`` from any source to the nearest target.

    ``sources`` is where the bus is (the nodes of the crossing it turned
    onto this street at); ``targets`` is where it may turn off (the nodes
    of every crossing with the next street). The nearest target by
    ``length_m`` is the turn: "Left on Washington, Right on Broad" means
    the first Broad.

    Args:
        graph: One street, from ``street_graph``.
        sources: Node IDs; those not on the street are ignored.
        targets: Node IDs; those not on the street are ignored.

    Returns:
        The walk's node IDs, source first, target last. One node when a
        source is itself a target (the next turn is at the same corner).
        ``None`` when no source is on the street, no target can be reached
        from one, or two targets are exactly as near (never guessed).
    """
    starts = {node for node in sources if node in graph}
    if not starts:
        return None
    lengths, paths = nx.multi_source_dijkstra(graph, starts, weight="length_m")
    reached = sorted((lengths[node], node) for node in set(targets) if node in lengths)
    if not reached:
        return None
    if len(reached) > 1 and reached[0][0] == reached[1][0]:
        return None
    return tuple(paths[reached[0][1]])


TURN_LOOK_M = 100.0
"""How far along each walk a turn's directions are read.

Not just the segments at the corner: ``South Penn Square`` leaves 15th
St almost straight south for ~45 m before curving east, so the first
segments say "right" where the turn is "left". Real data (``121123Z``):
read 30, 100 or 200 m out, all 185 checkable turns agree with their
message.
"""


type Side = Literal["left", "right"]
"""Which way a turn goes (``model.Turn`` without ``"via"``)."""


def turn_side(
    incoming: Sequence[Sequence[float]], outgoing: Sequence[Sequence[float]]
) -> Side | None:
    """Which way the bus turns where ``incoming`` ends and ``outgoing`` starts.

    Directions are read over ``TURN_LOOK_M``: from the first point at
    least that far back along ``incoming`` to the corner, and from the
    corner to the first point at least that far along ``outgoing`` (a
    shorter walk: its far end). Left or right is the sign of their cross
    product (positive: left, as x is east and y north); scaling longitude
    to metres wouldn't change the sign.

    Args:
        incoming: ``[lon, lat]`` points in travel order, ending at the
            corner.
        outgoing: ``[lon, lat]`` points in travel order, starting at the
            corner (``outgoing[0]`` is the corner used).

    Returns:
        ``"left"``, ``"right"``, or ``None`` when either walk has fewer
        than two points (no direction) or the directions are exactly in
        line.
    """
    if len(incoming) < 2 or len(outgoing) < 2:
        return None
    corner = outgoing[0]
    back = _point_along(incoming[::-1])
    ahead = _point_along(outgoing)
    cross = (corner[0] - back[0]) * (ahead[1] - corner[1]) - (corner[1] - back[1]) * (
        ahead[0] - corner[0]
    )
    if cross == 0:
        return None
    return "left" if cross > 0 else "right"


def _point_along(points: Sequence[Sequence[float]]) -> Sequence[float]:
    """The first point at least ``TURN_LOOK_M`` along ``points``, else the last."""
    walked = 0.0
    for previous, point in itertools.pairwise(points):
        walked += metres_between(previous, point)
        if walked >= TURN_LOOK_M:
            return point
    return points[-1]
