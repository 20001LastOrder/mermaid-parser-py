import pytest
from mermaid_parser.converters.flowchart import FlowChartConverter
from mermaid.flowchart import FlowChart
from mermaid.flowchart.node import NodeShape, NODE_SHAPES
from mermaid.flowchart.link import LINK_SHAPES


class TestFlowChartConverter:
    def test_convert_valid_flowchart(self):
        converter = FlowChartConverter()
        # Mock parsed data for a simple flowchart
        result = converter.convert("flowchart TD\nA[Start] --> |Process| B[End]")
        assert isinstance(result, FlowChart)
        assert len(result.nodes) == 2
        assert len(result.links) == 1
        assert result.nodes[0].id_ == "a"
        assert result.nodes[0].content == "Start"
        assert result.nodes[0].shape == NODE_SHAPES["normal"]
        assert result.nodes[1].id_ == "b"
        assert result.nodes[1].content == "End"
        assert result.nodes[1].shape == NODE_SHAPES["normal"]
        assert result.links[0].origin.id_ == "a"
        assert result.links[0].end.id_ == "b"
        assert result.links[0].shape == LINK_SHAPES["normal"]
        assert result.links[0].message == "|Process|"
        assert result.links[0].head_left == ""
        assert result.links[0].head_right == ">"

    def test_convert_empty_graph_data(
        self,
    ):
        converter = FlowChartConverter()
        result = converter.convert("flowchart TD")
        assert isinstance(result, FlowChart)
        assert len(result.nodes) == 0
        assert len(result.links) == 0

    @pytest.mark.parametrize(
        "node_type",
        [
            (NodeShape("[", "]")),
            (NodeShape("(", ")")),
            (NodeShape("([", "])")),
            (NodeShape("[[", "]]")),
            (NodeShape("[(", ")]")),
            (NodeShape("((", "))")),
            (NodeShape(">", "]")),
            (NodeShape("{", "}")),
            (NodeShape("{{", "}}")),
            (NodeShape("[/", "/]")),
            (NodeShape("[\\", "\\]")),
            (NodeShape("[/", "\\]")),
            (NodeShape("[\\", "/]")),
            (NodeShape("(((", ")))")),
        ],
    )
    def test_convert_node_shapes(self, node_type):
        converter = FlowChartConverter()
        graph_text = f"flowchart TD\nA{node_type.start}A{node_type.end}"
        result = converter.convert(graph_text)
        assert result.nodes[0].shape.start == node_type.start
        assert result.nodes[0].shape.end == node_type.end

    @pytest.mark.parametrize(
        "link_type,head_left,lead_right",
        [
            ("--", "", ">"),
            ("--", "<", ">"),
            ("-.-", "o", "o"),
            ("==", "x", "x"),
            ("~~~", "", ""),
        ],
    )
    def test_convert_link_types(self, link_type, head_left, lead_right):
        converter = FlowChartConverter()
        link = f"{head_left}{link_type}{lead_right}"

        result = converter.convert(f"flowchart TD\nA {link} B")
        
        link = result.links[0]
        assert link.head_left == head_left
        assert link.head_right == lead_right
        assert link.shape == link_type
