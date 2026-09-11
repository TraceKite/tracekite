"""
Unit tests for the Tree-sitter core modules.

Modules covered:
- tracekite.parsers.tree_sitter.core.base_parser
- tracekite.parsers.tree_sitter.core.queries.query_loader
- tracekite.parsers.tree_sitter.core.parser

External dependencies (filesystem / tree-sitter / neo4j) are mocked so the
suite can run in any environment.
"""

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tracekite.parsers.tree_sitter.core.base_parser import BaseExtractor, BaseParser
from tracekite.parsers.tree_sitter.core.models import LanguageType, ParsingResult
from tracekite.parsers.tree_sitter.core.parser import TreeSitterParser
from tracekite.parsers.tree_sitter.core.queries.query_loader import QueryLoader


# ---------------------------------------------------------------------------
# Helpers / mocks
# ---------------------------------------------------------------------------


class MockNode:
    """Lightweight stand-in for tree_sitter.Node."""

    def __init__(
        self,
        node_type: str,
        start_byte: int,
        end_byte: int,
        start_point: tuple,
        end_point: tuple,
        children=None,
    ):
        self.type = node_type
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.start_point = start_point
        self.end_point = end_point
        self.children = children or []


class MockTree:
    def __init__(self, root_node):
        self.root_node = root_node


class FakeLanguage:
    """Replaces tree_sitter.Language in parser module during tests."""

    def __init__(self, ptr):
        self.abi_version = 14


class FakeLanguageVersionFallback:
    """Exercises the `version` fallback branch in _get_language."""

    def __init__(self, ptr):
        self.version = 13


class MockParserFactory:
    """Callable that returns a mock Parser when parser.Parser(ts_language) is used."""

    def __init__(self, root_node):
        self.root_node = root_node

    def __call__(self, language):
        parser = MagicMock()
        parser.parse = MagicMock(return_value=MockTree(self.root_node))
        return parser


class ConcreteParser(BaseParser):
    """Concrete parser used to test the abstract base class."""

    def __init__(self, supported=None):
        super().__init__()
        self.supported = set(supported or [])

    def parse_content(self, content: str, file_path: str, language: LanguageType) -> ParsingResult:
        return ParsingResult(file_path=file_path, language=language)

    def supports_language(self, language: LanguageType) -> bool:
        return language in self.supported


class ConcreteExtractor(BaseExtractor):
    def extract_symbols(self, content: str, file_path: str, language: LanguageType):
        return []


# ---------------------------------------------------------------------------
# BaseParser / BaseExtractor
# ---------------------------------------------------------------------------


class TestBaseParser:
    def test_base_parser_is_abstract(self):
        with pytest.raises(TypeError):
            BaseParser()

    def test_get_supported_languages(self):
        parser = ConcreteParser([LanguageType.PYTHON, LanguageType.JAVA])
        supported = parser.get_supported_languages()
        assert set(supported) == {LanguageType.PYTHON, LanguageType.JAVA}

    def test_get_supported_languages_empty(self):
        parser = ConcreteParser([])
        assert parser.get_supported_languages() == []


class TestBaseExtractor:
    def test_base_extractor_is_abstract(self):
        with pytest.raises(TypeError):
            BaseExtractor()

    def test_concrete_extractor_can_instantiate(self):
        extractor = ConcreteExtractor()
        assert extractor.extract_symbols("", "", LanguageType.PYTHON) == []


# ---------------------------------------------------------------------------
# QueryLoader
# ---------------------------------------------------------------------------


class TestQueryLoader:
    def test_default_queries_dir(self):
        loader = QueryLoader()
        expected = Path(__file__).parent.parent / "tracekite" / "parsers" / "tree_sitter" / "core" / "queries" / "files"
        assert loader.queries_dir == expected

    def test_custom_queries_dir(self, tmp_path):
        loader = QueryLoader(tmp_path)
        assert loader.queries_dir == tmp_path

    def test_load_query_cache_hit(self):
        loader = QueryLoader()
        loader._query_cache["python:method_definitions"] = "cached query"
        assert loader.load_query(LanguageType.PYTHON, "method_definitions") == "cached query"

    def test_load_query_file_exists(self, tmp_path):
        lang_dir = tmp_path / "python"
        lang_dir.mkdir()
        (lang_dir / "method_definitions.scm").write_text("(method_definition) @method")
        loader = QueryLoader(tmp_path)
        result = loader.load_query(LanguageType.PYTHON, "method_definitions")
        assert result == "(method_definition) @method"
        assert loader._query_cache["python:method_definitions"] == result

    def test_load_query_file_not_found(self, tmp_path):
        loader = QueryLoader(tmp_path)
        assert loader.load_query(LanguageType.PYTHON, "missing") is None

    def test_load_query_read_error(self, tmp_path, monkeypatch):
        lang_dir = tmp_path / "python"
        lang_dir.mkdir()
        query_file = lang_dir / "method_definitions.scm"
        query_file.write_text("query")

        def raise_error(*args, **kwargs):
            raise IOError("read failed")

        monkeypatch.setattr(Path, "read_text", raise_error)
        loader = QueryLoader(tmp_path)
        assert loader.load_query(LanguageType.PYTHON, "method_definitions") is None

    def test_load_all_queries_no_directory(self, tmp_path):
        loader = QueryLoader(tmp_path)
        assert loader.load_all_queries(LanguageType.PYTHON) == {}

    def test_load_all_queries_with_files(self, tmp_path):
        lang_dir = tmp_path / "python"
        lang_dir.mkdir()
        (lang_dir / "method_definitions.scm").write_text("q1")
        (lang_dir / "classes.scm").write_text("q2")
        loader = QueryLoader(tmp_path)
        result = loader.load_all_queries(LanguageType.PYTHON)
        assert result == {"method_definitions": "q1", "classes": "q2"}
        assert loader._query_cache["python:method_definitions"] == "q1"
        assert loader._query_cache["python:classes"] == "q2"

    def test_load_all_queries_read_error(self, tmp_path, monkeypatch):
        lang_dir = tmp_path / "python"
        lang_dir.mkdir()
        (lang_dir / "method_definitions.scm").write_text("q1")

        def raise_error(*args, **kwargs):
            raise IOError("read failed")

        monkeypatch.setattr(Path, "read_text", raise_error)
        loader = QueryLoader(tmp_path)
        assert loader.load_all_queries(LanguageType.PYTHON) == {}

    def test_clear_cache(self):
        loader = QueryLoader()
        loader._query_cache["a:b"] = "c"
        loader.clear_cache()
        assert loader._query_cache == {}


# ---------------------------------------------------------------------------
# TreeSitterParser - import fallback and construction
# ---------------------------------------------------------------------------


class TestTreeSitterParserImportFallback:
    """Verify parser.py falls back to dummy classes when tree_sitter is missing.

    The fallback import is executed in a subprocess so it cannot corrupt the
    module state used by the rest of the suite.
    """

    def test_tree_sitter_import_fallback_creates_dummy_classes(self):
        code = """
import sys
from unittest.mock import patch
with patch.dict(sys.modules, {"tree_sitter": None}):
    import tracekite.parsers.tree_sitter.core.parser as fallback_parser

assert fallback_parser.TREE_SITTER_AVAILABLE is False
assert fallback_parser.Language is not None
assert fallback_parser.Parser is not None
assert fallback_parser.Node is not None
print("fallback_ok")
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
        assert "fallback_ok" in result.stdout


class TestTreeSitterParserConstruction:
    def test_init_creates_empty_caches(self):
        parser = TreeSitterParser()
        assert parser._language_cache == {}
        assert parser._parser_cache == {}


# ---------------------------------------------------------------------------
# TreeSitterParser - _serialize_node
# ---------------------------------------------------------------------------


class TestSerializeNode:
    def test_serialize_node_basic(self):
        parser = TreeSitterParser()
        content = b"def foo(): pass"
        child = MockNode(
            "function_definition", 0, 15, (0, 0), (1, 0), []
        )
        root = MockNode("module", 0, 15, (0, 0), (1, 0), [child])
        result = parser._serialize_node(root, content)
        assert result["type"] == "module"
        assert result["text"] == "def foo(): pass"
        assert len(result["children"]) == 1
        assert result["children"][0]["type"] == "function_definition"
        assert result["children"][0]["text"] == "def foo(): pass"

    def test_serialize_node_text_truncated(self):
        parser = TreeSitterParser()
        content = b"x" * 1000
        root = MockNode("module", 0, 1000, (0, 0), (1, 0), [])
        result = parser._serialize_node(root, content, max_text_length=10)
        assert result["text"] == "x" * 10 + "..."

    def test_serialize_node_respects_max_depth(self):
        parser = TreeSitterParser()
        content = b"abc"
        grandchild = MockNode("grandchild", 0, 3, (0, 0), (0, 3), [])
        child = MockNode("child", 0, 3, (0, 0), (0, 3), [grandchild])
        root = MockNode("root", 0, 3, (0, 0), (0, 3), [child])
        result = parser._serialize_node(root, content, max_depth=1)
        assert len(result["children"]) == 1
        assert result["children"][0]["children"] == []

    def test_serialize_node_invalid_byte_range(self):
        parser = TreeSitterParser()
        content = b"abc"
        root = MockNode("root", 0, 10, (0, 0), (0, 10), [])
        result = parser._serialize_node(root, content)
        assert result["text"] is None

    def test_serialize_node_start_byte_out_of_range(self):
        parser = TreeSitterParser()
        content = b"abc"
        root = MockNode("root", 5, 10, (0, 0), (0, 10), [])
        result = parser._serialize_node(root, content)
        assert result["text"] is None


# ---------------------------------------------------------------------------
# TreeSitterParser - parse_content
# ---------------------------------------------------------------------------


class TestParseContent:
    def test_parse_content_success(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        root = MockNode("module", 0, 15, (0, 0), (1, 0), [])
        monkeypatch.setattr(parser, "_get_parser", lambda lang, fp: MockParserFactory(root)(None))

        result = parser.parse_content("def foo(): pass", "test.py", LanguageType.PYTHON)
        assert result.success is True
        assert result.ast_json is not None
        assert result.metadata["ast_root"] is not None
        assert result.metadata["content"] == "def foo(): pass"

    def test_parse_content_tree_sitter_unavailable(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", False)
        parser = TreeSitterParser()
        result = parser.parse_content("x", "test.py", LanguageType.PYTHON)
        assert result.success is False
        assert "Tree-Sitter not available" in result.error_message

    def test_parse_content_unsupported_language(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        result = parser.parse_content("x", "test.proto", LanguageType.PROTO)
        assert result.success is False
        assert "not supported" in result.error_message

    def test_parse_content_parser_fail_sql(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        monkeypatch.setattr(parser, "_get_parser", lambda lang, fp: None)
        result = parser.parse_content("SELECT 1", "test.sql", LanguageType.SQL)
        assert result.success is False
        assert result.error_message == "SQL_TEXT_PARSER_EXPECTED"

    def test_parse_content_parser_fail_general(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        monkeypatch.setattr(parser, "_get_parser", lambda lang, fp: None)
        result = parser.parse_content("x", "test.py", LanguageType.PYTHON)
        assert result.success is False
        assert "Could not create parser" in result.error_message

    def test_parse_content_exception(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()

        def raise_error(*args, **kwargs):
            raise RuntimeError("parse exploded")

        monkeypatch.setattr(parser, "_get_parser", raise_error)
        result = parser.parse_content("x", "test.py", LanguageType.PYTHON)
        assert result.success is False
        assert "parse exploded" in result.error_message


# ---------------------------------------------------------------------------
# TreeSitterParser - supports_language
# ---------------------------------------------------------------------------


class TestSupportsLanguage:
    def test_supports_language_true(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        assert parser.supports_language(LanguageType.PYTHON) is True

    def test_supports_language_false_no_tree_sitter(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", False)
        parser = TreeSitterParser()
        assert parser.supports_language(LanguageType.PYTHON) is False

    def test_supports_language_false_no_ast_parser(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        assert parser.supports_language(LanguageType.PROTO) is False


# ---------------------------------------------------------------------------
# TreeSitterParser - parse_ast_root
# ---------------------------------------------------------------------------


class TestParseAstRoot:
    def test_parse_ast_root_success(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        root = MockNode("module", 0, 15, (0, 0), (1, 0), [])
        monkeypatch.setattr(parser, "_get_parser", lambda lang, fp: MockParserFactory(root)(None))
        assert parser.parse_ast_root("def foo(): pass", LanguageType.PYTHON) is root

    def test_parse_ast_root_tree_sitter_unavailable(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", False)
        parser = TreeSitterParser()
        assert parser.parse_ast_root("x", LanguageType.PYTHON) is None

    def test_parse_ast_root_unsupported_language(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        assert parser.parse_ast_root("x", LanguageType.PROTO) is None

    def test_parse_ast_root_parser_fail(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        monkeypatch.setattr(parser, "_get_parser", lambda lang, fp: None)
        assert parser.parse_ast_root("x", LanguageType.PYTHON) is None

    def test_parse_ast_root_exception(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()

        def raise_error(*args, **kwargs):
            raise RuntimeError("root failed")

        monkeypatch.setattr(parser, "_get_parser", raise_error)
        assert parser.parse_ast_root("x", LanguageType.PYTHON) is None


# ---------------------------------------------------------------------------
# TreeSitterParser - _get_parser
# ---------------------------------------------------------------------------


class TestGetParser:
    def test_get_parser_tree_sitter_unavailable(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", False)
        parser = TreeSitterParser()
        assert parser._get_parser(LanguageType.PYTHON, "test.py") is None

    def test_get_parser_cached(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        cached = MagicMock()
        parser._parser_cache["python"] = cached
        assert parser._get_parser(LanguageType.PYTHON, "test.py") is cached

    def test_get_parser_tsx_cached(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        cached = MagicMock()
        parser._parser_cache["typescript_tsx"] = cached
        assert parser._get_parser(LanguageType.TYPESCRIPT, "test.tsx") is cached

    def test_get_parser_create_new(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguage)
        parser = TreeSitterParser()
        root = MockNode("module", 0, 1, (0, 0), (0, 1), [])
        monkeypatch.setattr(parser, "_get_language", lambda lang, fp: FakeLanguage(object()))
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Parser", MockParserFactory(root))
        result = parser._get_parser(LanguageType.PYTHON, "test.py")
        assert result is not None
        assert "python" in parser._parser_cache

    def test_get_parser_no_language(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        monkeypatch.setattr(parser, "_get_language", lambda lang, fp: None)
        assert parser._get_parser(LanguageType.PYTHON, "test.py") is None

    def test_get_parser_version_incompatibility(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        monkeypatch.setattr(parser, "_get_language", lambda lang, fp: FakeLanguage(object()))

        def raise_incompatible(language):
            raise ValueError("incompatible language version")

        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Parser", raise_incompatible)
        assert parser._get_parser(LanguageType.PYTHON, "test.py") is None

    def test_get_parser_other_value_error_is_caught_outer(self, monkeypatch):
        # The inner except ValueError re-raises, but the outer except Exception
        # catches it and returns None. This test exercises that code path.
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        monkeypatch.setattr(parser, "_get_language", lambda lang, fp: FakeLanguage(object()))

        def raise_other(language):
            raise ValueError("something else")

        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Parser", raise_other)
        assert parser._get_parser(LanguageType.PYTHON, "test.py") is None

    def test_get_parser_create_exception(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        monkeypatch.setattr(parser, "_get_language", lambda lang, fp: FakeLanguage(object()))

        def raise_runtime(language):
            raise RuntimeError("parser creation failed")

        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Parser", raise_runtime)
        assert parser._get_parser(LanguageType.PYTHON, "test.py") is None

    def test_get_parser_outer_exception(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()

        def raise_outer(*args, **kwargs):
            raise RuntimeError("outer failure")

        monkeypatch.setattr(
            "tracekite.parsers.tree_sitter.core.parser.get_tree_sitter_name", raise_outer
        )
        assert parser._get_parser(LanguageType.PYTHON, "test.py") is None


# ---------------------------------------------------------------------------
# TreeSitterParser - _get_language
# ---------------------------------------------------------------------------


class TestGetLanguage:
    def test_get_language_tree_sitter_unavailable(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", False)
        parser = TreeSitterParser()
        assert parser._get_language(LanguageType.PYTHON, "test.py") is None

    def test_get_language_cached(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        parser._language_cache["python"] = "cached_lang"
        assert parser._get_language(LanguageType.PYTHON, "test.py") == "cached_lang"

    def test_get_language_tsx_cached(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        parser._language_cache["typescript_tsx"] = "cached_tsx"
        assert parser._get_language(LanguageType.TYPESCRIPT, "test.tsx") == "cached_tsx"

    @pytest.mark.parametrize(
        "language, module_name, lang_method",
        [
            (LanguageType.JAVA, "tree_sitter_java", "language"),
            (LanguageType.KOTLIN, "tree_sitter_kotlin", "language"),
            (LanguageType.PYTHON, "tree_sitter_python", "language"),
            (LanguageType.JAVASCRIPT, "tree_sitter_javascript", "language"),
            (LanguageType.GO, "tree_sitter_go", "language"),
            (LanguageType.RUST, "tree_sitter_rust", "language"),
            (LanguageType.C, "tree_sitter_c", "language"),
            (LanguageType.CPP, "tree_sitter_cpp", "language"),
            (LanguageType.CSHARP, "tree_sitter_c_sharp", "language"),
            (LanguageType.RUBY, "tree_sitter_ruby", "language"),
            (LanguageType.PHP, "tree_sitter_php", "language_php"),
            (LanguageType.SCALA, "tree_sitter_scala", "language"),
            (LanguageType.JSON, "tree_sitter_json", "language"),
            (LanguageType.YAML, "tree_sitter_yaml", "language"),
        ],
    )
    def test_get_language_supported(self, language, module_name, lang_method, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguage)
        parser = TreeSitterParser()
        fake_ptr = object()
        fake_module = types.ModuleType(module_name)
        setattr(fake_module, lang_method, lambda: fake_ptr)
        with patch.dict(sys.modules, {module_name: fake_module}):
            result = parser._get_language(language, "test.txt")
        assert isinstance(result, FakeLanguage)

    def test_get_language_typescript_regular(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguage)
        parser = TreeSitterParser()
        fake_ptr = object()
        fake_module = types.ModuleType("tree_sitter_typescript")
        fake_module.language_typescript = lambda: fake_ptr
        fake_module.language_tsx = lambda: object()
        with patch.dict(sys.modules, {"tree_sitter_typescript": fake_module}):
            result = parser._get_language(LanguageType.TYPESCRIPT, "test.ts")
        assert isinstance(result, FakeLanguage)
        assert "typescript" in parser._language_cache

    def test_get_language_typescript_tsx(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguage)
        parser = TreeSitterParser()
        fake_ptr = object()
        fake_module = types.ModuleType("tree_sitter_typescript")
        fake_module.language_tsx = lambda: fake_ptr
        fake_module.language_typescript = lambda: object()
        with patch.dict(sys.modules, {"tree_sitter_typescript": fake_module}):
            result = parser._get_language(LanguageType.TYPESCRIPT, "test.tsx")
        assert isinstance(result, FakeLanguage)
        assert "typescript_tsx" in parser._language_cache

    def test_get_language_html_installed(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguage)
        parser = TreeSitterParser()
        fake_ptr = object()
        fake_module = types.ModuleType("tree_sitter_html")
        fake_module.language = lambda: fake_ptr
        with patch.dict(sys.modules, {"tree_sitter_html": fake_module}):
            result = parser._get_language(LanguageType.HTML, "test.html")
        assert isinstance(result, FakeLanguage)

    def test_get_language_html_not_installed(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        with patch.dict(sys.modules, {"tree_sitter_html": None}):
            assert parser._get_language(LanguageType.HTML, "test.html") is None

    def test_get_language_css_installed(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguage)
        parser = TreeSitterParser()
        fake_ptr = object()
        fake_module = types.ModuleType("tree_sitter_css")
        fake_module.language = lambda: fake_ptr
        with patch.dict(sys.modules, {"tree_sitter_css": fake_module}):
            result = parser._get_language(LanguageType.CSS, "test.css")
        assert isinstance(result, FakeLanguage)

    def test_get_language_css_not_installed(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        with patch.dict(sys.modules, {"tree_sitter_css": None}):
            assert parser._get_language(LanguageType.CSS, "test.css") is None

    def test_get_language_r_unsupported(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        assert parser._get_language(LanguageType.R, "test.r") is None

    def test_get_language_sql_unsupported(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        assert parser._get_language(LanguageType.SQL, "test.sql") is None

    def test_get_language_import_error(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        with patch.dict(sys.modules, {"tree_sitter_java": None}):
            assert parser._get_language(LanguageType.JAVA, "test.java") is None

    def test_get_language_general_exception(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()
        fake_module = types.ModuleType("tree_sitter_java")
        fake_module.language = lambda: (_ for _ in ()).throw(RuntimeError("grammar failed"))
        with patch.dict(sys.modules, {"tree_sitter_java": fake_module}):
            assert parser._get_language(LanguageType.JAVA, "test.java") is None

    def test_get_language_lang_ptr_none(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguage)
        parser = TreeSitterParser()
        fake_module = types.ModuleType("tree_sitter_java")
        fake_module.language = lambda: None
        with patch.dict(sys.modules, {"tree_sitter_java": fake_module}):
            assert parser._get_language(LanguageType.JAVA, "test.java") is None

    def test_get_language_abi_version(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguage)
        parser = TreeSitterParser()
        fake_module = types.ModuleType("tree_sitter_java")
        fake_module.language = lambda: object()
        with patch.dict(sys.modules, {"tree_sitter_java": fake_module}):
            result = parser._get_language(LanguageType.JAVA, "test.java")
        assert isinstance(result, FakeLanguage)
        assert result.abi_version == 14

    def test_get_language_version_fallback(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        monkeypatch.setattr(
            "tracekite.parsers.tree_sitter.core.parser.Language", FakeLanguageVersionFallback
        )
        parser = TreeSitterParser()
        fake_module = types.ModuleType("tree_sitter_java")
        fake_module.language = lambda: object()
        with patch.dict(sys.modules, {"tree_sitter_java": fake_module}):
            result = parser._get_language(LanguageType.JAVA, "test.java")
        assert isinstance(result, FakeLanguageVersionFallback)
        assert result.version == 13

    def test_get_language_outer_exception(self, monkeypatch):
        monkeypatch.setattr("tracekite.parsers.tree_sitter.core.parser.TREE_SITTER_AVAILABLE", True)
        parser = TreeSitterParser()

        def raise_outer(*args, **kwargs):
            raise RuntimeError("outer failure")

        monkeypatch.setattr(
            "tracekite.parsers.tree_sitter.core.parser.get_tree_sitter_name", raise_outer
        )
        assert parser._get_language(LanguageType.PYTHON, "test.py") is None


# ---------------------------------------------------------------------------
# TreeSitterParser - get_ast_root / clear_caches
# ---------------------------------------------------------------------------


class TestGetAstRoot:
    def test_get_ast_root_success(self):
        parser = TreeSitterParser()
        root = MockNode("module", 0, 1, (0, 0), (0, 1), [])
        result = ParsingResult(
            file_path="test.py",
            language=LanguageType.PYTHON,
            success=True,
            metadata={"ast_root": root},
        )
        assert parser.get_ast_root(result) is root

    def test_get_ast_root_failure(self):
        parser = TreeSitterParser()
        result = ParsingResult(
            file_path="test.py",
            language=LanguageType.PYTHON,
            success=False,
        )
        assert parser.get_ast_root(result) is None

    def test_get_ast_root_no_ast_root(self):
        parser = TreeSitterParser()
        result = ParsingResult(
            file_path="test.py",
            language=LanguageType.PYTHON,
            success=True,
        )
        assert parser.get_ast_root(result) is None


class TestClearCaches:
    def test_clear_caches(self):
        parser = TreeSitterParser()
        parser._language_cache["x"] = "y"
        parser._parser_cache["a"] = "b"
        parser.clear_caches()
        assert parser._language_cache == {}
        assert parser._parser_cache == {}
