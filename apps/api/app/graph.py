"""Deterministic, bounded graph primitives for infrastructure relationships.

The graph deliberately has no dependency on a graph database.  Relationships
are materialized in Postgres/SQLite and this module builds a sorted adjacency
index for one bounded API request.  Current derived edges are undirected, so
the engine never invents upstream/downstream semantics.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    name: str = ""
    asset_type: str = ""
    region: str | None = None
    source_key: str | None = None


@dataclass(frozen=True, slots=True)
class GraphEdge:
    id: str
    from_id: str
    to_id: str
    relationship_type: str
    directionality: str = "UNDIRECTED"
    relationship_source: str = "DERIVED"
    relationship_key: str = ""
    source_relationship_id: str | None = None
    derivation_method: str | None = None
    derivation_version: str | None = None
    confidence: float | None = None
    evidence: dict = field(default_factory=dict)
    distance_km: float | None = None
    tolerance_m: float | None = None


class GraphEngine:
    """An immutable adjacency index with reproducible traversal order."""

    def __init__(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]):
        self.nodes = {node.id: node for node in nodes}
        self.edges = {
            edge.id: edge
            for edge in sorted(edges, key=lambda item: (item.relationship_type, item.from_id, item.to_id, item.id))
            if edge.from_id in self.nodes and edge.to_id in self.nodes and edge.from_id != edge.to_id
        }
        self._adjacency: dict[str, list[tuple[str, GraphEdge]]] = defaultdict(list)
        for edge in self.edges.values():
            if edge.directionality == "DIRECTED":
                self._adjacency[edge.from_id].append((edge.to_id, edge))
            else:
                self._adjacency[edge.from_id].append((edge.to_id, edge))
                self._adjacency[edge.to_id].append((edge.from_id, edge))
        for node_id in self.nodes:
            self._adjacency[node_id].sort(key=lambda item: (item[0], item[1].relationship_type, item[1].id))
        # Metrics are expensive structural graph calculations. Keep the
        # memoization request-local (one engine is built per API request) so
        # list/metrics endpoints do not repeat Brandes/Tarjan work for every
        # returned node, without introducing stale process-wide cache state.
        self._metrics_cache: dict[tuple[str, ...], dict[str, dict]] = {}
        self._structural_metrics_cache: dict[tuple[str, ...], dict[str, dict]] = {}
        self._alternate_path_cache: dict[tuple[str, ...], dict[str, int]] = {}

    def _allowed(self, edge: GraphEdge, relationship_types: set[str] | None) -> bool:
        return not relationship_types or edge.relationship_type in relationship_types

    def _neighbors_for(self, node_id: str, *, direction: str = "both", relationship_types: set[str] | None = None):
        """Yield ``(neighbor_id, edge)`` in stable order.

        ``in`` is supported for directed edges.  For an undirected edge both
        endpoint orientations are equivalent and therefore returned for
        ``both`` only; callers can reject directional requests when their
        contract requires it.
        """
        for neighbor_id, edge in self._adjacency.get(node_id, []):
            if not self._allowed(edge, relationship_types):
                continue
            if edge.directionality != "DIRECTED" or direction == "both":
                yield neighbor_id, edge
            elif direction == "out" and edge.from_id == node_id:
                yield neighbor_id, edge
            elif direction == "in" and edge.to_id == node_id:
                yield neighbor_id, edge

    def neighbor_ids(
        self,
        node_id: str,
        *,
        depth: int = 1,
        limit: int = 100,
        direction: str = "both",
        relationship_types: set[str] | None = None,
    ) -> list[str]:
        if node_id not in self.nodes:
            return []
        if depth < 1 or limit < 1:
            return []
        visited = {node_id}
        queue = deque([(node_id, 0)])
        result: list[str] = []
        while queue and len(result) < limit:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for neighbor_id, _edge in self._neighbors_for(
                current, direction=direction, relationship_types=relationship_types
            ):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                result.append(neighbor_id)
                if len(result) >= limit:
                    break
                queue.append((neighbor_id, current_depth + 1))
        return result

    def neighbors(self, node_id: str, **kwargs) -> list[GraphNode]:
        return [self.nodes[item] for item in self.neighbor_ids(node_id, **kwargs)]

    def connected_components(self, relationship_types: set[str] | None = None) -> list[list[str]]:
        remaining = set(self.nodes)
        components: list[list[str]] = []
        for root in sorted(self.nodes):
            if root not in remaining:
                continue
            component = []
            queue = deque([root])
            remaining.remove(root)
            while queue:
                current = queue.popleft()
                component.append(current)
                for neighbor_id, _edge in self._neighbors_for(current, relationship_types=relationship_types):
                    if neighbor_id in remaining:
                        remaining.remove(neighbor_id)
                        queue.append(neighbor_id)
            components.append(sorted(component))
        return components

    def shortest_path(
        self,
        from_id: str,
        to_id: str,
        *,
        max_hops: int = 12,
        relationship_types: set[str] | None = None,
    ) -> list[str] | None:
        if from_id not in self.nodes or to_id not in self.nodes or max_hops < 0:
            return None
        if from_id == to_id:
            return [from_id]
        queue = deque([(from_id, 0)])
        predecessor: dict[str, str | None] = {from_id: None}
        while queue:
            current, hops = queue.popleft()
            if hops >= max_hops:
                continue
            for neighbor_id, _edge in self._neighbors_for(current, relationship_types=relationship_types):
                if neighbor_id in predecessor:
                    continue
                predecessor[neighbor_id] = current
                if neighbor_id == to_id:
                    path = [to_id]
                    while path[-1] != from_id:
                        path.append(predecessor[path[-1]] or from_id)
                    return list(reversed(path))
                queue.append((neighbor_id, hops + 1))
        return None

    def subgraph(
        self,
        root: str,
        *,
        depth: int = 2,
        max_nodes: int = 100,
        relationship_types: set[str] | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge], bool]:
        if root not in self.nodes or depth < 0 or max_nodes < 1:
            return [], [], False
        selected = [root]
        seen = {root}
        queue = deque([(root, 0)])
        truncated = False
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for neighbor_id, _edge in self._neighbors_for(current, relationship_types=relationship_types):
                if neighbor_id in seen:
                    continue
                if len(selected) >= max_nodes:
                    truncated = True
                    continue
                seen.add(neighbor_id)
                selected.append(neighbor_id)
                queue.append((neighbor_id, current_depth + 1))
        selected_set = set(selected)
        edges = [
            edge
            for edge in self.edges.values()
            if edge.from_id in selected_set
            and edge.to_id in selected_set
            and self._allowed(edge, relationship_types)
        ]
        return (
            [self.nodes[item] for item in selected],
            sorted(edges, key=lambda edge: (edge.relationship_type, edge.from_id, edge.to_id, edge.id)),
            truncated,
        )

    def degree(self, node_id: str, relationship_types: set[str] | None = None) -> int:
        return sum(1 for _ in self._neighbors_for(node_id, relationship_types=relationship_types))

    def articulation_points(self, relationship_types: set[str] | None = None) -> set[str]:
        """Tarjan articulation points for the selected undirected graph."""
        adjacency = {
            node_id: sorted(
                neighbor_id
                for neighbor_id, _edge in self._neighbors_for(node_id, relationship_types=relationship_types)
            )
            for node_id in self.nodes
        }
        discovery: dict[str, int] = {}
        low: dict[str, int] = {}
        parent: dict[str, str | None] = {}
        result: set[str] = set()
        clock = 0

        def visit(node_id: str) -> None:
            nonlocal clock
            discovery[node_id] = low[node_id] = clock
            clock += 1
            children = 0
            for neighbor_id in adjacency[node_id]:
                if neighbor_id not in discovery:
                    parent[neighbor_id] = node_id
                    children += 1
                    visit(neighbor_id)
                    low[node_id] = min(low[node_id], low[neighbor_id])
                    if parent.get(node_id) is None and children > 1:
                        result.add(node_id)
                    if parent.get(node_id) is not None and low[neighbor_id] >= discovery[node_id]:
                        result.add(node_id)
                elif neighbor_id != parent.get(node_id):
                    low[node_id] = min(low[node_id], discovery[neighbor_id])

        for root in sorted(self.nodes):
            if root not in discovery:
                parent[root] = None
                visit(root)
        return result

    def betweenness_centrality(self, relationship_types: set[str] | None = None) -> dict[str, float]:
        """Unweighted Brandes betweenness, normalized for an undirected graph."""
        scores = {node_id: 0.0 for node_id in self.nodes}
        for source in sorted(self.nodes):
            stack: list[str] = []
            predecessors: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
            sigma = {node_id: 0.0 for node_id in self.nodes}
            distance = {node_id: -1 for node_id in self.nodes}
            sigma[source] = 1.0
            distance[source] = 0
            queue = deque([source])
            while queue:
                current = queue.popleft()
                stack.append(current)
                for neighbor_id, _edge in self._neighbors_for(current, relationship_types=relationship_types):
                    if distance[neighbor_id] < 0:
                        queue.append(neighbor_id)
                        distance[neighbor_id] = distance[current] + 1
                    if distance[neighbor_id] == distance[current] + 1:
                        sigma[neighbor_id] += sigma[current]
                        predecessors[neighbor_id].append(current)
            dependency = {node_id: 0.0 for node_id in self.nodes}
            while stack:
                current = stack.pop()
                for predecessor in predecessors[current]:
                    if sigma[current]:
                        dependency[predecessor] += (
                            sigma[predecessor] / sigma[current]
                        ) * (1.0 + dependency[current])
                if current != source:
                    scores[current] += dependency[current]
        # Each undirected shortest path is encountered from both endpoints.
        scores = {node_id: value / 2.0 for node_id, value in scores.items()}
        n = len(self.nodes)
        if n > 2:
            scale = 2.0 / ((n - 1) * (n - 2))
            scores = {node_id: value * scale for node_id, value in scores.items()}
        return {node_id: round(value, 8) for node_id, value in sorted(scores.items())}

    def metrics(self, node_id: str, relationship_types: set[str] | None = None) -> dict:
        cache_key = tuple(sorted(relationship_types or ()))
        cached = self._metrics_cache.get(cache_key)
        if cached is None:
            cached = {}
            self._metrics_cache[cache_key] = cached
        if node_id in cached:
            return dict(cached[node_id])

        structural = self._structural_metrics_cache.get(cache_key)
        if structural is None:
            structural = self._compute_structural_metrics(relationship_types)
            self._structural_metrics_cache[cache_key] = structural
        item = dict(structural.get(node_id, {
            "degree": 0,
            "component_size": 0,
            "betweenness_centrality": 0.0,
            "is_articulation_point": False,
        }))
        alternate_cache = self._alternate_path_cache.setdefault(cache_key, {})
        if node_id not in alternate_cache:
            alternate_cache[node_id] = self._alternate_path_count(node_id, relationship_types)
        item["alternate_path_count"] = alternate_cache[node_id]
        cached[node_id] = item
        return dict(item)

    def _compute_structural_metrics(self, relationship_types: set[str] | None = None) -> dict[str, dict]:
        components = self.connected_components(relationship_types)
        articulation = self.articulation_points(relationship_types)
        centrality = self.betweenness_centrality(relationship_types)
        component_sizes = {
            node_id: len(component)
            for component in components
            for node_id in component
        }
        result: dict[str, dict] = {}
        for current_node_id in self.nodes:
            result[current_node_id] = {
                "degree": self.degree(current_node_id, relationship_types),
                "component_size": component_sizes.get(current_node_id, 0),
                "betweenness_centrality": centrality.get(current_node_id, 0.0),
                "is_articulation_point": current_node_id in articulation,
            }
        return result

    def _alternate_path_count(
        self, node_id: str, relationship_types: set[str] | None = None
    ) -> int:
        """Count alternate routes only for the requested node."""

        if node_id not in self.nodes:
            return 0
        alternate_paths = 0
        # For an undirected edge, an alternate path exists if its endpoints
        # remain connected after the direct edge is ignored. This remains
        # structural and is never called an operational score.
        for neighbor_id, edge in self._neighbors_for(node_id, relationship_types=relationship_types):
            visited = {node_id}
            queue = deque([node_id])
            while queue:
                current = queue.popleft()
                for candidate, candidate_edge in self._neighbors_for(
                    current, relationship_types=relationship_types
                ):
                    if candidate_edge.id == edge.id or candidate in visited:
                        continue
                    visited.add(candidate)
                    queue.append(candidate)
            if neighbor_id in visited:
                alternate_paths += 1
        return alternate_paths
