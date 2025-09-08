from mermaid.flowchart import FlowChart, Node, Link
from mermaid_parser.parser import MermaidParser
import networkx as nx

NODE_SHAPE_MAP = {
    "square": "normal",
    "round": "round-edge",
    "stadium": "stadium-shape",
    "subroutine": "subroutine-shape",
    "cylinder": "cylindrical",
    "circle": "circle",
    "odd": "label-shape",
    "diamond": "rhombus",
    "hexagon": "hexagon",
    "lean_right": "parallelogram",
    "lean_left": "parallelogram-alt",
    "trapezoid": "trapezoid",
    "inv_trapezoid": "trapezoid-alt",
    "doublecircle": "double-circle",
}

EDGE_SHAPE_MAP = {
    "normal": "normal",
    "dotted": "dotted",
    "thick": "thick",
    "invisible": "hidden",
}

EDGE_TYPE_MAP = {
    "arrow_open": ("none", "none"),
    "arrow_point": ("none", "arrow"),
    "double_arrow_point": ("left-arrow", "arrow"),
    "arrow_circle": ("none", "bullet"),
    "double_arrow_circle": ("bullet", "bullet"),
    "arrow_cross": ("none", "cross"),
    "double_arrow_cross": ("cross", "cross"),
}


class FlowChartConverter:
    def __init__(self):
        self.parser = MermaidParser()

    def convert(self, mermaid_text: str) -> FlowChart:
        parsed_data = self.parser.parse(mermaid_text)
        graph_type = parsed_data.get("graph_type")
        if "flowchart" not in graph_type:
            raise ValueError(f"Unsupported graph type: {graph_type}")

        graph_data = parsed_data.get("graph_data", {})
        nodes = {
            node: self._convert_node(node_data)
            for node, node_data in graph_data.get("vertices").items()
        }
        links = [
            self._convert_link(link, nodes) for link in graph_data.get("edges", [])
        ]

        return FlowChart("FlowChart", nodes=list(nodes.values()), links=links)

    def _convert_node(self, node: dict) -> Node:
        return Node(
            id_=node["id"],
            content=node["text"],
            shape=NODE_SHAPE_MAP.get(node.get("type", "square")),
        )

    def _convert_link(self, link: dict, nodes: dict[str, Node]) -> Link:
        head_left, head_right = EDGE_TYPE_MAP.get(link["type"], ("none", "none"))
        edge_shape = EDGE_SHAPE_MAP.get(link.get("stroke", "normal"))
        return Link(
            origin=nodes[link["start"]],
            end=nodes[link["end"]],
            shape=edge_shape,
            message=link["text"],
            head_left=head_left,
            head_right=head_right,
        )

    def to_networkx(self, flowchart: FlowChart) -> nx.DiGraph:
        G = nx.DiGraph()
        for node in flowchart.nodes.values():
            G.add_node(node.id, content=node.content, shape=node.shape)
        for link in flowchart.links:
            G.add_edge(
                link.origin.id, link.end.id, shape=link.shape, message=link.message
            )
        return G
