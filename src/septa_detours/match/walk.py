"""Walk a detour along one named street at a time (tier C).

The message says which streets to take (``"Left on Washington, Right on
Broad"``); each leg follows one street's OSM ways from where the bus
turned onto it to where it turns off. So each leg's graph is that street
alone, a few dozen nodes: never a routing engine choosing its own streets.

Graphs are networkx ``Graph`` objects: nodes are OSM node IDs with
``lon``/``lat`` attributes, edges join consecutive nodes of a way and
carry their ``length_m``.
"""

import math
from collections.abc import Iterable

import networkx as nx
import polars as pl

from septa_detours.geo import EARTH_RADIUS_M


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
            graph.add_edge(a, b, length_m=_metres_between(a_point, b_point))
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


def _metres_between(p: list[float], q: list[float]) -> float:
    """Approximate ground distance between ``[lon, lat]`` points, in metres.

    The same formula as ``crossings._metres_between`` (equirectangular,
    mean Earth radius).
    """
    mean_lat = math.radians((p[1] + q[1]) / 2)
    dx = math.radians(q[0] - p[0]) * math.cos(mean_lat)
    dy = math.radians(q[1] - p[1])
    return EARTH_RADIUS_M * math.hypot(dx, dy)
