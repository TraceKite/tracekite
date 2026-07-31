"""
Integration tests for the Tree-sitter adapter using local fixture files.

These tests are skipped when Tree-sitter is not installed (e.g. on the host
outside Docker) so that the suite can still be run for non-parser tests.
"""

from pathlib import Path
import pytest

from adduce.parsers.parser_registry import parse_file
from adduce.parsers.tree_sitter.core.parser import TREE_SITTER_AVAILABLE

FIXTURES = Path(__file__).parent / "fixtures" / "callgraph-sample"


@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="Tree-sitter not installed")
class TestTreeSitterIntegration:
    def test_java_controller_parsed(self):
        path = FIXTURES / "UserController.java"
        content = path.read_text(encoding="utf-8")
        result = parse_file(str(path.relative_to(FIXTURES)), content)

        source = result.get("source_result")
        assert source is not None

        names = {e.name for e in source.entities}
        assert "UserController" in names
        assert "getUser" in names
        assert "fetchUser" in names

        assert len(source.api_endpoints) >= 1
        endpoint = next(ep for ep in source.api_endpoints)
        assert endpoint.method == "GET"
        assert "/api/users/{id}" in endpoint.path or endpoint.path == "/{id}"

        calls = [c for c in source.method_calls if c.callee_name == "fetchUser"]
        assert len(calls) >= 1

    def test_python_handler_parsed(self):
        path = FIXTURES / "handlers.py"
        content = path.read_text(encoding="utf-8")
        result = parse_file(str(path.relative_to(FIXTURES)), content)

        source = result.get("source_result")
        assert source is not None

        names = {e.name for e in source.entities}
        assert "health" in names
        assert "build_response" in names

        assert any(ep.method == "GET" and "/health" in ep.path for ep in source.api_endpoints)

        calls = [c for c in source.method_calls if c.callee_name == "build_response"]
        assert len(calls) >= 1

    def test_typescript_express_routes_parsed(self):
        path = FIXTURES / "routes.ts"
        content = path.read_text(encoding="utf-8")
        result = parse_file(str(path.relative_to(FIXTURES)), content)

        source = result.get("source_result")
        assert source is not None

        assert any(ep.method == "GET" and "/users/:id" in ep.path for ep in source.api_endpoints)

        calls = [c for c in source.method_calls if c.callee_name == "getUser"]
        assert len(calls) >= 1

    def test_go_handler_parsed(self):
        path = FIXTURES / "main.go"
        content = path.read_text(encoding="utf-8")
        result = parse_file(str(path.relative_to(FIXTURES)), content)

        source = result.get("source_result")
        assert source is not None

        names = {e.name for e in source.entities}
        assert "getUser" in names
        assert "fetchUser" in names

        assert any(ep.method == "GET" and "/api/users/{id}" in ep.path for ep in source.api_endpoints)

        calls = [c for c in source.method_calls if c.callee_name == "fetchUser"]
        assert len(calls) >= 1

    def test_rust_handler_parsed(self):
        path = FIXTURES / "main.rs"
        content = path.read_text(encoding="utf-8")
        result = parse_file(str(path.relative_to(FIXTURES)), content)

        source = result.get("source_result")
        assert source is not None

        names = {e.name for e in source.entities}
        assert "get_user" in names
        assert "build_response" in names

        assert any(ep.method == "GET" and "/api/users/{id}" in ep.path for ep in source.api_endpoints)

        calls = [c for c in source.method_calls if c.callee_name == "build_response"]
        assert len(calls) >= 1

    def test_kotlin_controller_parsed(self):
        path = FIXTURES / "UserController.kt"
        content = path.read_text(encoding="utf-8")
        result = parse_file(str(path.relative_to(FIXTURES)), content)

        source = result.get("source_result")
        assert source is not None

        names = {e.name for e in source.entities}
        assert "UserController" in names
        assert "getUser" in names
        assert "fetchUser" in names

        assert any(ep.method == "GET" and "/api/users/{id}" in ep.path for ep in source.api_endpoints)

        calls = [c for c in source.method_calls if c.callee_name == "fetchUser"]
        assert len(calls) >= 1
