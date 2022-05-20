from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, cast

from karton.core.inspect import KartonState
from networkx import DiGraph, generate_gexf  # type: ignore
from networkx.readwrite.json_graph import (  # type: ignore
    adjacency_data,
    adjacency_graph,
)

NODE_SIZE: Callable[
    [DiGraph, str], float
] = lambda graph, identity: 65 + 3.5 * graph.in_degree(identity)
DEFAULT_OPTIONS = {"color": {"r": 51, "g": 153, "b": 243, "a": 0}, "size": NODE_SIZE}
EMPTY_METADATA = {"version": "none", "info": "none"}
OPTIONS = ["color", "size"]


class KartonNode:
    def __init__(
        self, identity: str, metadata: Dict[str, str], filters, outputs
    ) -> None:
        self.identity = identity
        self.metadata = metadata
        self.filters = filters
        self.outputs = outputs

    def filter_contained(self, filter: Dict[str, str], output: Dict[str, str]) -> bool:
        return all(item in output.items() for item in filter.items())

    def __contains__(self, other: KartonNode) -> bool:
        if self.filters and other.outputs:
            for filter in self.filters:
                if any(
                    self.filter_contained(filter, output) for output in other.outputs
                ):
                    return True
        return False


class KartonGraph:
    def __init__(self, state: KartonState) -> None:
        self.state: KartonState = state
        self.nodes: List[KartonNode] = []
        self.graph: Dict[str, Set[str]] = {}

    def style_nodes(
        self,
        graph: DiGraph,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Style the graph.

        :param graph: a graph object
        :type graph: networkx.DiGraph
        :param options: styling options, which consists of:
        \t`color`: a dictionary specifying RGBA
        \t`size`: a function that takes a DiGraph and a node identity as
        \t    an input and returns a size (`float`)
        :type: Optional[Dict[str, Any]]
        """
        if not options:
            options = DEFAULT_OPTIONS

        for option in OPTIONS:
            if not options.get(option):
                options[option] = DEFAULT_OPTIONS[option]

        for node in self.nodes:
            graph.nodes[node.identity]["viz"] = {
                "color": options["color"],
                "size": cast(Callable[[DiGraph, str], float], options["size"])(
                    graph, node.identity
                ),
            }

            graph.nodes[node.identity]["version"] = node.metadata["version"]
            graph.nodes[node.identity]["info"] = node.metadata["info"]

    def build_nodes(self) -> None:
        values = {}

        for bind in self.state.backend.get_binds():
            if bind.identity and bind.identity not in values:
                values[bind.identity] = {
                    "filters": None,
                    "outputs": None,
                    "metadata": EMPTY_METADATA,
                }
            values[bind.identity]["filters"] = bind.filters
            values[bind.identity]["metadata"] = {
                "version": bind.service_version if bind.service_version else "N/A",
                "info": bind.info if bind.info else "N/A",
            }

        for outputs_object in self.state.backend.get_outputs():
            if outputs_object.identity not in values:
                values[outputs_object.identity] = {
                    "filters": None,
                    "outputs": None,
                    "metadata": EMPTY_METADATA,
                }
            values[outputs_object.identity]["outputs"] = outputs_object.outputs

        for identity in values.keys():
            metadata = cast(Dict[str, str], values[identity]["metadata"])
            node = KartonNode(
                identity=identity,
                metadata=metadata,
                filters=values[identity]["filters"],
                outputs=values[identity]["outputs"],
            )

            self.nodes.append(node)

    def create_graph(self) -> None:
        for node in self.nodes:
            self.graph[node.identity] = set()

        for node in self.nodes:
            for other in self.nodes:
                if other in node:
                    self.graph[other.identity].add(node.identity)

    def generate_graph(self) -> str:
        self.build_nodes()
        self.create_graph()

        nx_graph = DiGraph(self.graph)
        self.style_nodes(nx_graph)

        adj_data = adjacency_data(nx_graph)
        adj_graph = adjacency_graph(adj_data)
        gexf_graph = ""
        for line in generate_gexf(adj_graph):
            gexf_graph += line

        return gexf_graph
