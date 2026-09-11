import pytest
from tracekite.models.graph_models import GraphNode
from tracekite.parsers.base import ParsedMethodCall
from tracekite.services.call_graph_resolver import build_call_graph


def _make_method_node(repo_id: str, node_id: str, name: str, path: str, start: int, end: int):
    return GraphNode(
        id=node_id,
        repo_id=repo_id,
        type="Method",
        name=name,
        label=name,
        path=path,
        language="Java",
        start_line=start,
        end_line=end,
    )


class TestCallGraphResolver:
    def test_same_class_call(self):
        nodes = [
            _make_method_node("r", "r:Method:a", "a", "Foo.java", 1, 5),
            _make_method_node("r", "r:Method:b", "b", "Foo.java", 7, 12),
        ]
        edges = []
        parse_context = {
            "Foo.java": {
                "file_node_id": "r:File:foo",
                "entities": [
                    {"id": "r:Method:a", "repo_id": "r", "file_path": "Foo.java", "name": "a",
                     "qualified_name": "Foo.a", "parent_class": "Foo", "type": "method",
                     "start_line": 1, "end_line": 5},
                    {"id": "r:Method:b", "repo_id": "r", "file_path": "Foo.java", "name": "b",
                     "qualified_name": "Foo.b", "parent_class": "Foo", "type": "method",
                     "start_line": 7, "end_line": 12},
                ],
                "method_calls": [
                    ParsedMethodCall(caller_name="", callee_name="b", file_path="Foo.java", line=3),
                ],
            }
        }

        build_call_graph("r", parse_context, nodes, edges)

        assert len(edges) == 1
        assert edges[0].source_id == "r:Method:a"
        assert edges[0].target_id == "r:Method:b"
        assert edges[0].type == "CALLS"
        assert edges[0].confidence == 0.9
        assert edges[0].origin == "inferred"
        assert edges[0].evidence == ["Foo.java:3"]

    def test_same_file_function_call(self):
        nodes = [
            _make_method_node("r", "r:Method:f", "f", "util.py", 1, 4),
            _make_method_node("r", "r:Method:g", "g", "util.py", 6, 9),
        ]
        edges = []
        parse_context = {
            "util.py": {
                "file_node_id": "r:File:util",
                "entities": [
                    {"id": "r:Method:f", "repo_id": "r", "file_path": "util.py", "name": "f",
                     "qualified_name": "f", "parent_class": None, "type": "function",
                     "start_line": 1, "end_line": 4},
                    {"id": "r:Method:g", "repo_id": "r", "file_path": "util.py", "name": "g",
                     "qualified_name": "g", "parent_class": None, "type": "function",
                     "start_line": 6, "end_line": 9},
                ],
                "method_calls": [
                    ParsedMethodCall(caller_name="", callee_name="g", file_path="util.py", line=3),
                ],
            }
        }

        build_call_graph("r", parse_context, nodes, edges)

        assert len(edges) == 1
        assert edges[0].source_id == "r:Method:f"
        assert edges[0].target_id == "r:Method:g"
        assert edges[0].confidence == 0.9

    def test_ignored_library_call(self):
        nodes = [
            _make_method_node("r", "r:Method:f", "f", "util.py", 1, 4),
        ]
        edges = []
        parse_context = {
            "util.py": {
                "file_node_id": "r:File:util",
                "entities": [
                    {"id": "r:Method:f", "repo_id": "r", "file_path": "util.py", "name": "f",
                     "qualified_name": "f", "parent_class": None, "type": "function",
                     "start_line": 1, "end_line": 4},
                ],
                "method_calls": [
                    ParsedMethodCall(caller_name="", callee_name="print", file_path="util.py", line=2),
                ],
            }
        }

        build_call_graph("r", parse_context, nodes, edges)

        assert len(edges) == 0

    def test_cross_class_call(self):
        nodes = [
            _make_method_node("r", "r:Method:a", "a", "A.java", 1, 5),
            _make_method_node("r", "r:Method:b", "b", "B.java", 1, 5),
        ]
        edges = []
        parse_context = {
            "A.java": {
                "file_node_id": "r:File:a",
                "entities": [
                    {"id": "r:Method:a", "repo_id": "r", "file_path": "A.java", "name": "a",
                     "qualified_name": "A.a", "parent_class": "A", "type": "method",
                     "start_line": 1, "end_line": 5},
                ],
                "method_calls": [
                    ParsedMethodCall(caller_name="", callee_name="B.b", file_path="A.java", line=3),
                ],
            },
            "B.java": {
                "file_node_id": "r:File:b",
                "entities": [
                    {"id": "r:Method:b", "repo_id": "r", "file_path": "B.java", "name": "b",
                     "qualified_name": "B.b", "parent_class": "B", "type": "method",
                     "start_line": 1, "end_line": 5},
                ],
                "method_calls": [],
            },
        }

        build_call_graph("r", parse_context, nodes, edges)

        assert len(edges) == 1
        assert edges[0].source_id == "r:Method:a"
        assert edges[0].target_id == "r:Method:b"
        assert edges[0].confidence == 0.7
