"""
Pytest unit tests for TreeSitterExtractor and QueryEngine.

These tests invoke the extractor and query engine directly with real
small code snippets for every supported language.  They are skipped when
Tree-sitter is not installed so the rest of the suite can still run.
"""

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from adduce.parsers.tree_sitter.core.extractor import (
    TREE_SITTER_AVAILABLE as EXTRACTOR_TS_AVAILABLE,
    TreeSitterExtractor,
)
from adduce.parsers.tree_sitter.core.models import LanguageType, SymbolInfo
from adduce.parsers.tree_sitter.core.parser import TreeSitterParser
from adduce.parsers.tree_sitter.core.queries.query_engine import (
    TREE_SITTER_AVAILABLE as ENGINE_TS_AVAILABLE,
    QueryEngine,
)

TS_AVAILABLE = EXTRACTOR_TS_AVAILABLE and ENGINE_TS_AVAILABLE


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _parse(language: LanguageType, code: str, path: str = None):
    """Parse *code* and return (root_node, tree_sitter_language)."""
    path = path or f"test.{language.value}"
    parser = TreeSitterParser()
    result = parser.parse_content(code, path, language)
    assert result.success, f"Failed to parse {language.value}: {result.error_message}"
    root = result.metadata["ast_root"]
    ts_language = parser._get_language(language, path)
    assert ts_language is not None
    return root, ts_language


# -----------------------------------------------------------------------------
# Symbol extraction
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not TS_AVAILABLE, reason="Tree-sitter not installed")
class TestTreeSitterExtractorSymbols:
    @pytest.mark.parametrize(
        "language,code,expected",
        [
            pytest.param(
                LanguageType.JAVA,
                """
@RestController
public class UserController {
    public static final int MAX = 100;
    @Query("SELECT * FROM users WHERE id = ?")
    public User getUser(Long id) { return repo.findById(id); }
}
interface UserRepo { List<User> findAll(); }
enum Status { ACTIVE, INACTIVE }
""",
                {
                    "annotation": {"RestController", "Query"},
                    "class": {"UserController"},
                    "interface": {"UserRepo"},
                    "method": {"getUser", "findAll"},
                    "variable": {"MAX", "ACTIVE", "INACTIVE"},
                },
                id="java",
            ),
            pytest.param(
                LanguageType.KOTLIN,
                """
@RestController
class UserController {
    @Query("SELECT * FROM users WHERE id = ?")
    fun getUser(id: Long): User { return repo.findById(id) }
}
interface UserRepo { fun findAll(): List<User> }
enum class Status { ACTIVE, INACTIVE }
""",
                {
                    "annotation": {"RestController", "Query"},
                    "class": {"UserController", "Status"},
                    "method": {"getUser", "findAll"},
                },
                id="kotlin",
            ),
            pytest.param(
                LanguageType.PYTHON,
                """
@staticmethod
class UserController:
    MAX = 100
    def get_user(self, id: int):
        return self.repo.find(id)
""",
                {
                    "annotation": {"staticmethod"},
                    "class": {"UserController"},
                    "method": {"get_user"},
                    "variable": {"MAX"},
                },
                id="python",
            ),
            pytest.param(
                LanguageType.JAVASCRIPT,
                """
class UserController {
    getUser(id) {
        const sql = "SELECT * FROM users WHERE id = ?";
        return obj.findUser(id);
    }
}
""",
                {
                    "class": {"UserController"},
                    "method": {"getUser"},
                    "variable": {"sql"},
                },
                id="javascript",
            ),
            pytest.param(
                LanguageType.TYPESCRIPT,
                """
interface UserRepo { findAll(): User[]; }
class UserController {
    getUser(id: number): User {
        const sql: string = "SELECT * FROM users WHERE id = ?";
        return obj.findUser(id);
    }
}
enum Status { ACTIVE, INACTIVE }
type Box = { x: number };
""",
                {
                    "interface": {"UserRepo", "Box"},
                    "class": {"UserController"},
                    "method": {"getUser"},
                    "variable": {"sql", "ACTIVE", "INACTIVE"},
                },
                id="typescript",
            ),
            pytest.param(
                LanguageType.GO,
                """
package main

type UserController struct{}

func GetUser(id int) (*User, error) {
    return obj.FindUser(id)
}
""",
                {
                    "method": {"GetUser"},
                },
                id="go",
            ),
            pytest.param(
                LanguageType.RUST,
                """
#[derive(Debug)]
struct UserController;

impl UserController {
    fn get_user(&self, id: i64) -> User {
        self.find_user(id)
    }
}
""",
                {
                    "annotation": {"derive"},
                    "class": {"UserController"},
                    "method": {"get_user"},
                },
                id="rust",
            ),
        ],
    )
    def test_extract_symbols(self, language: LanguageType, code: str, expected: Dict[str, Any]):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(language, code)
        symbols = extractor.extract_symbols(root, ts_language, language, "test.file")

        by_type: Dict[str, List[str]] = {}
        for symbol in symbols:
            by_type.setdefault(symbol.symbol_type, []).append(symbol.name)

        for symbol_type, names in expected.items():
            assert set(by_type.get(symbol_type, [])).issuperset(names), (
                f"{language.value}: missing {symbol_type} symbols; got {by_type}"
            )

        # Every symbol should carry sensible location / signature data.
        for symbol in symbols:
            assert symbol.file_path == "test.file"
            assert symbol.line_number > 0
            assert symbol.end_line >= symbol.line_number
            assert symbol.signature is not None

    def test_extract_symbols_empty_source(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "\n")
        symbols = extractor.extract_symbols(root, ts_language, LanguageType.PYTHON, "empty.py")
        assert symbols == []

    def test_extract_symbols_parent_class_association(self):
        extractor = TreeSitterExtractor()
        code = """
class UserController {
    getUser(id) { return obj.findUser(id); }
}
"""
        root, ts_language = _parse(LanguageType.JAVASCRIPT, code)
        symbols = extractor.extract_symbols(root, ts_language, LanguageType.JAVASCRIPT, "assoc.js")
        methods = [s for s in symbols if s.symbol_type == "method"]
        assert len(methods) == 1
        assert methods[0].name == "getUser"
        assert methods[0].parent_class == "UserController"

    def test_extract_symbols_exception_returns_empty(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "def f(): pass")
        with patch.object(extractor.query_engine, "find_annotations", side_effect=RuntimeError("boom")):
            symbols = extractor.extract_symbols(root, ts_language, LanguageType.PYTHON, "boom.py")
        assert symbols == []

    def test_extract_symbols_when_tree_sitter_unavailable(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "def f(): pass")
        with patch("adduce.parsers.tree_sitter.core.extractor.TREE_SITTER_AVAILABLE", False):
            symbols = extractor.extract_symbols(root, ts_language, LanguageType.PYTHON, "no_ts.py")
        assert symbols == []


# -----------------------------------------------------------------------------
# Method call extraction
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not TS_AVAILABLE, reason="Tree-sitter not installed")
class TestTreeSitterExtractorMethodCalls:
    @pytest.mark.parametrize(
        "language,code,expected_calls",
        [
            pytest.param(
                LanguageType.JAVA,
                """
class UserController {
    public User getUser(Long id) {
        return repo.findById(id);
    }
}
""",
                {"findById"},
                id="java",
            ),
            pytest.param(
                LanguageType.KOTLIN,
                """
class UserController {
    fun getUser(id: Long): User {
        return repo.findById(id)
    }
}
""",
                {"findById"},
                id="kotlin",
            ),
            pytest.param(
                LanguageType.PYTHON,
                """
class UserController:
    def get_user(self, id: int):
        return repo.find_by_id(id)
""",
                {"find_by_id"},
                id="python",
            ),
            pytest.param(
                LanguageType.JAVASCRIPT,
                """
class UserController {
    getUser(id) {
        return obj.findUser(id);
    }
}
""",
                {"findUser"},
                id="javascript",
            ),
            pytest.param(
                LanguageType.TYPESCRIPT,
                """
class UserController {
    getUser(id: number): User {
        return obj.findUser(id);
    }
}
""",
                {"findUser"},
                id="typescript",
            ),
            pytest.param(
                LanguageType.GO,
                """
package main

func GetUser(id int) (*User, error) {
    return obj.FindUser(id)
}
""",
                {"FindUser"},
                id="go",
            ),
            pytest.param(
                LanguageType.RUST,
                """
struct UserController;
impl UserController {
    fn get_user(&self, id: i64) -> User {
        self.find_user(id)
    }
}
""",
                {"find_user"},
                id="rust",
            ),
        ],
    )
    def test_extract_method_calls(self, language: LanguageType, code: str, expected_calls):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(language, code)
        calls = extractor.extract_method_calls(root, ts_language, language, "test.file", code)
        found = {c.called_method for c in calls}
        assert expected_calls.issubset(found), f"{language.value}: expected {expected_calls}, got {found}"
        for call in calls:
            assert call.file_path == "test.file"
            assert call.line_number > 0
            assert call.context is not None
            assert call.call_type == "direct"

    def test_extract_method_calls_no_source_content(self):
        extractor = TreeSitterExtractor()
        code = """
class UserController {
    getUser(id) {
        return obj.findUser(id);
    }
}
"""
        root, ts_language = _parse(LanguageType.JAVASCRIPT, code)
        calls = extractor.extract_method_calls(root, ts_language, LanguageType.JAVASCRIPT, "test.js")
        assert any(c.called_method == "findUser" for c in calls)

    def test_extract_method_calls_empty_source(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "# nothing\n")
        calls = extractor.extract_method_calls(root, ts_language, LanguageType.PYTHON, "empty.py", "# nothing\n")
        assert calls == []

    def test_extract_method_calls_exception_returns_empty(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "obj.foo()\n")
        with patch.object(extractor.query_engine, "find_method_calls_grouped", side_effect=RuntimeError("boom")):
            calls = extractor.extract_method_calls(root, ts_language, LanguageType.PYTHON, "boom.py", "obj.foo()\n")
        assert calls == []

    def test_extract_method_calls_when_tree_sitter_unavailable(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "obj.foo()\n")
        with patch("adduce.parsers.tree_sitter.core.extractor.TREE_SITTER_AVAILABLE", False):
            calls = extractor.extract_method_calls(root, ts_language, LanguageType.PYTHON, "no_ts.py", "obj.foo()\n")
        assert calls == []


# -----------------------------------------------------------------------------
# SQL query extraction
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not TS_AVAILABLE, reason="Tree-sitter not installed")
class TestTreeSitterExtractorSQLQueries:
    @pytest.mark.parametrize(
        "language,code,expected_sql,should_find",
        [
            pytest.param(
                LanguageType.JAVA,
                """
class UserController {
    @Query("SELECT * FROM users WHERE id = ?")
    public User getUser(Long id) { return null; }
}
""",
                "SELECT * FROM users WHERE id = ?",
                True,
                id="java",
            ),
            pytest.param(
                LanguageType.PYTHON,
                """
class UserController:
    def get_user(self, id: int):
        sql = "SELECT * FROM users WHERE id = ?"
        return sql
""",
                "SELECT * FROM users WHERE id = ?",
                True,
                id="python",
            ),
            pytest.param(
                LanguageType.JAVASCRIPT,
                """
class UserController {
    getUser(id) {
        const sql = "SELECT * FROM users WHERE id = ?";
        return sql;
    }
}
""",
                "SELECT * FROM users WHERE id = ?",
                True,
                id="javascript",
            ),
            pytest.param(
                LanguageType.TYPESCRIPT,
                """
class UserController {
    getUser(id: number): User {
        const sql: string = "SELECT * FROM users WHERE id = ?";
        return sql;
    }
}
""",
                "SELECT * FROM users WHERE id = ?",
                True,
                id="typescript",
            ),
            pytest.param(
                LanguageType.KOTLIN,
                """
class UserController {
    @Query("SELECT * FROM users WHERE id = ?")
    fun getUser(id: Long): User { return User() }
}
""",
                "SELECT * FROM users WHERE id = ?",
                False,  # Current Kotlin query does not reach the string literal.
                id="kotlin",
            ),
            pytest.param(
                LanguageType.GO,
                """
package main
func GetUser(id int) { sql := "SELECT * FROM users" }
""",
                "",
                False,
                id="go",
            ),
            pytest.param(
                LanguageType.RUST,
                """
struct UserController;
impl UserController {
    fn get_user(&self, id: i64) { let sql = "SELECT * FROM users"; }
}
""",
                "",
                False,
                id="rust",
            ),
        ],
    )
    def test_extract_sql_queries(self, language: LanguageType, code: str, expected_sql: str, should_find: bool):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(language, code)
        symbols = extractor.extract_symbols(root, ts_language, language, "test.file")
        queries = extractor.extract_sql_queries(root, ts_language, language, "test.file", symbols)
        if should_find:
            assert any(expected_sql in q.sql_text for q in queries), (
                f"{language.value}: expected SQL not found in {queries}"
            )
            for q in queries:
                assert q.file_path == "test.file"
                assert q.line_number > 0
                assert q.annotation_type.value != ""
        else:
            # Either no query support or the query cannot match the snippet.
            assert all(expected_sql not in q.sql_text for q in queries)

    def test_extract_sql_queries_with_no_matching_method_symbol(self):
        extractor = TreeSitterExtractor()
        code = """
def get_users():
    return "SELECT * FROM users WHERE id = ?"
"""
        root, ts_language = _parse(LanguageType.PYTHON, code)
        # Method definition exists but we pass an empty symbol list, so the
        # extractor falls back to a placeholder symbol id.
        queries = extractor.extract_sql_queries(root, ts_language, LanguageType.PYTHON, "orphan.py", [])
        assert len(queries) == 1
        assert "SELECT * FROM users" in queries[0].sql_text
        assert "SYMBOL:get_users" in queries[0].method_symbol_id

    def test_extract_sql_queries_invalid_sql_filtered(self):
        extractor = TreeSitterExtractor()
        code = 'x = "hello world"\n'
        root, ts_language = _parse(LanguageType.PYTHON, code)
        queries = extractor.extract_sql_queries(root, ts_language, LanguageType.PYTHON, "no_sql.py", [])
        assert queries == []

    def test_extract_sql_queries_exception_returns_empty(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, 'sql = "SELECT * FROM users"\n')
        with patch.object(extractor.query_engine, "find_sql_annotations", side_effect=RuntimeError("boom")):
            queries = extractor.extract_sql_queries(root, ts_language, LanguageType.PYTHON, "boom.py", [])
        assert queries == []

    def test_extract_sql_queries_when_tree_sitter_unavailable(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, 'sql = "SELECT * FROM users"\n')
        with patch("adduce.parsers.tree_sitter.core.extractor.TREE_SITTER_AVAILABLE", False):
            queries = extractor.extract_sql_queries(root, ts_language, LanguageType.PYTHON, "no_ts.py", [])
        assert queries == []


# -----------------------------------------------------------------------------
# Symbol reference extraction
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not TS_AVAILABLE, reason="Tree-sitter not installed")
class TestTreeSitterExtractorSymbolReferences:
    @pytest.mark.parametrize(
        "language,code,expected_refs",
        [
            pytest.param(
                LanguageType.JAVA,
                """
class UserController {
    User getUser(Long id) { return repo.findById(id); }
}
""",
                {"getUser"},
                id="java",
            ),
            pytest.param(
                LanguageType.PYTHON,
                """
class UserController:
    MAX = 100
    def get_user(self, id: int):
        return self.repo.find(id)
""",
                {"UserController", "MAX", "get_user"},
                id="python",
            ),
            pytest.param(
                LanguageType.JAVASCRIPT,
                """
class UserController {
    getUser(id) { return obj.findUser(id); }
}
""",
                {"UserController"},
                id="javascript",
            ),
            pytest.param(
                LanguageType.GO,
                """
package main
func GetUser(id int) { return FindUser(id) }
""",
                {"GetUser"},
                id="go",
            ),
            pytest.param(
                LanguageType.RUST,
                """
struct UserController;
impl UserController {
    fn get_user(&self, id: i64) { self.find_user(id); }
}
""",
                {"get_user"},
                id="rust",
            ),
        ],
    )
    def test_extract_symbol_references(self, language: LanguageType, code: str, expected_refs):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(language, code)
        symbols = extractor.extract_symbols(root, ts_language, language, "test.file")
        refs = extractor.extract_symbol_references(root, ts_language, language, "test.file", symbols)
        names = {r["context"] for r in refs}
        assert expected_refs.issubset(names), f"{language.value}: expected {expected_refs}, got {names}"
        for ref in refs:
            assert ref["file_path"] == "test.file"
            assert ref["line_number"] > 0
            assert ref["reference_type"] in {"call", "write", "read", "import"}
            assert ref["symbol_id"].startswith("SYMBOL:")

    def test_extract_symbol_references_empty_symbols(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "x = 1\n")
        refs = extractor.extract_symbol_references(root, ts_language, LanguageType.PYTHON, "empty.py", [])
        assert refs == []

    def test_extract_symbol_references_exception_returns_empty(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "x = 1\n")
        dummy = SymbolInfo(name="x", symbol_type="variable", file_path="dummy.py", line_number=1, column=0, end_line=1, end_column=1)
        with patch.object(extractor.query_engine, "find_identifiers", side_effect=RuntimeError("boom")):
            refs = extractor.extract_symbol_references(root, ts_language, LanguageType.PYTHON, "boom.py", [dummy])
        assert refs == []

    def test_extract_symbol_references_when_tree_sitter_unavailable(self):
        extractor = TreeSitterExtractor()
        root, ts_language = _parse(LanguageType.PYTHON, "x = 1\n")
        dummy = SymbolInfo(name="x", symbol_type="variable", file_path="dummy.py", line_number=1, column=0, end_line=1, end_column=1)
        with patch("adduce.parsers.tree_sitter.core.extractor.TREE_SITTER_AVAILABLE", False):
            refs = extractor.extract_symbol_references(root, ts_language, LanguageType.PYTHON, "no_ts.py", [dummy])
        assert refs == []


# -----------------------------------------------------------------------------
# QueryEngine
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not TS_AVAILABLE, reason="Tree-sitter not installed")
class TestQueryEngine:
    def test_execute_query_basic(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.PYTHON, "def foo(): pass\n")
        results = engine.execute_query("(function_definition name: (identifier) @method_name)", root, ts_language)
        assert len(results) == 1
        assert results[0]["text"] == "foo"
        assert results[0]["capture_name"] == "method_name"

    def test_execute_query_with_capture_filter(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.PYTHON, "def foo(): pass\n")
        results = engine.execute_query(
            "(function_definition name: (identifier) @method_name)",
            root,
            ts_language,
            capture_names=["method_name"],
        )
        assert len(results) == 1

    def test_execute_query_invalid_query_returns_empty(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.PYTHON, "def foo(): pass\n")
        results = engine.execute_query("this is not a valid query", root, ts_language)
        assert results == []

    def test_execute_query_grouped(self):
        engine = QueryEngine()
        code = """
class UserController {
    getUser(id) { return obj.findUser(id); }
}
"""
        root, ts_language = _parse(LanguageType.JAVASCRIPT, code)
        grouped = engine.find_method_calls_grouped(root, ts_language, LanguageType.JAVASCRIPT)
        assert len(grouped) >= 1
        group = grouped[0]
        assert "method_name" in group
        assert "full_call" in group

    def test_execute_query_grouped_invalid_query_returns_empty(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.PYTHON, "obj.foo()\n")
        grouped = engine.execute_query_grouped("invalid !!!", root, ts_language)
        assert grouped == []

    def test_find_method_definitions_for_all_languages(self):
        engine = QueryEngine()
        snippets = {
            LanguageType.JAVA: "class C { void m() {} }",
            LanguageType.KOTLIN: "class C { fun m() {} }",
            LanguageType.PYTHON: "def m(): pass",
            LanguageType.JAVASCRIPT: "class C { m() {} }",
            LanguageType.TYPESCRIPT: "class C { m() {} }",
            LanguageType.GO: "package main\nfunc m() {}",
            LanguageType.RUST: "fn m() {}",
        }
        for language, code in snippets.items():
            root, ts_language = _parse(language, code)
            defs = engine.find_method_definitions(root, ts_language, language)
            names = {d["text"] for d in defs}
            assert "m" in names, f"{language.value}: method definition not found; got {names}"

    def test_find_classes_for_all_languages(self):
        engine = QueryEngine()
        snippets = {
            LanguageType.JAVA: "class UserController {}",
            LanguageType.KOTLIN: "class UserController {}",
            LanguageType.PYTHON: "class UserController: pass",
            LanguageType.JAVASCRIPT: "class UserController {}",
            LanguageType.TYPESCRIPT: "class UserController {}",
            # Go class query expects type_declaration/type_spec which is not matched.
            LanguageType.RUST: "struct UserController;",
        }
        for language, code in snippets.items():
            root, ts_language = _parse(language, code)
            classes = engine.find_classes(root, ts_language, language)
            names = {c["text"] for c in classes}
            if language == LanguageType.GO:
                # Document current limitation: Go class query is empty for this AST.
                assert "UserController" not in names
            else:
                assert "UserController" in names, f"{language.value}: class not found; got {names}"

    def test_find_annotations(self):
        engine = QueryEngine()
        snippets = {
            LanguageType.JAVA: "@RestController class C {}",
            LanguageType.KOTLIN: "@RestController class C {}",
            LanguageType.PYTHON: "@staticmethod\ndef f(): pass",
            LanguageType.TYPESCRIPT: "@Component class C {}",
            LanguageType.JAVASCRIPT: "@Component class C {}",
            LanguageType.RUST: "#[derive(Debug)] struct S;",
        }
        for language, code in snippets.items():
            root, ts_language = _parse(language, code)
            annotations = engine.find_annotations(root, ts_language, language)
            assert len(annotations) >= 1, f"{language.value}: no annotations found"

    def test_find_interfaces(self):
        engine = QueryEngine()
        snippets = {
            LanguageType.JAVA: "interface I {}",
            LanguageType.TYPESCRIPT: "interface I {}",
        }
        for language, code in snippets.items():
            root, ts_language = _parse(language, code)
            interfaces = engine.find_interfaces(root, ts_language, language)
            assert any(i["text"] == "I" for i in interfaces), f"{language.value}: interface not found"

        # JavaScript and Kotlin interface queries do not match their grammars;
        # document the empty results rather than changing production code.
        root, ts_language = _parse(LanguageType.JAVASCRIPT, "interface I {}")
        assert engine.find_interfaces(root, ts_language, LanguageType.JAVASCRIPT) == []
        root, ts_language = _parse(LanguageType.KOTLIN, "interface I {}")
        assert engine.find_interfaces(root, ts_language, LanguageType.KOTLIN) == []

    def test_find_enum_constants(self):
        engine = QueryEngine()
        snippets = {
            LanguageType.JAVA: "enum Status { ACTIVE, INACTIVE }",
            LanguageType.TYPESCRIPT: "enum Status { ACTIVE, INACTIVE }",
        }
        for language, code in snippets.items():
            root, ts_language = _parse(language, code)
            enums = engine.find_enum_constants(root, ts_language, language)
            names = {e["text"] for e in enums}
            assert "ACTIVE" in names, f"{language.value}: enum constants not found; got {names}"

        # JavaScript enums and the Kotlin enum query do not match their grammars.
        root, ts_language = _parse(LanguageType.JAVASCRIPT, "enum Status { ACTIVE, INACTIVE }")
        assert engine.find_enum_constants(root, ts_language, LanguageType.JAVASCRIPT) == []
        root, ts_language = _parse(LanguageType.KOTLIN, "enum class Status { ACTIVE, INACTIVE }")
        assert engine.find_enum_constants(root, ts_language, LanguageType.KOTLIN) == []

    def test_find_type_aliases(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.TYPESCRIPT, "type Box = { x: number };\n")
        aliases = engine.find_type_aliases(root, ts_language, LanguageType.TYPESCRIPT)
        assert any(a["text"] == "Box" for a in aliases)

    def test_find_constants(self):
        engine = QueryEngine()
        code = """
public class C {
    public static final int MAX = 100;
}
"""
        root, ts_language = _parse(LanguageType.JAVA, code)
        constants = engine.find_constants(root, ts_language, LanguageType.JAVA)
        assert any(c["text"] == "MAX" for c in constants)

    def test_find_proto_fields_not_proto(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.JAVA, "class C {}")
        fields = engine.find_proto_fields(root, ts_language, LanguageType.JAVA)
        assert fields == []

    def test_find_sql_annotations_unsupported_language(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.GO, "package main\n")
        assert engine.find_sql_annotations(root, ts_language, LanguageType.GO) == []

    def test_find_method_calls_unsupported_language(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.PYTHON, "def f(): pass\n")
        # C has no method-call query defined.
        assert engine.find_method_calls(root, ts_language, LanguageType.C) == []

    def test_clear_cache(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.PYTHON, "def foo(): pass\n")
        engine.execute_query("(function_definition name: (identifier) @x)", root, ts_language)
        assert len(engine._query_cache) > 0
        engine.clear_cache()
        assert len(engine._query_cache) == 0

    def test_query_engine_when_tree_sitter_unavailable(self):
        engine = QueryEngine()
        root, ts_language = _parse(LanguageType.PYTHON, "def foo(): pass\n")
        with patch("adduce.parsers.tree_sitter.core.queries.query_engine.TREE_SITTER_AVAILABLE", False):
            assert engine.execute_query("(identifier) @x", root, ts_language) == []
            assert engine.execute_query_grouped("(identifier) @x", root, ts_language) == []
            assert engine.find_method_calls_grouped(root, ts_language, LanguageType.PYTHON) == []


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not TS_AVAILABLE, reason="Tree-sitter not installed")
class TestExtractorHelpers:
    def test_is_valid_sql(self):
        extractor = TreeSitterExtractor()
        assert extractor._is_valid_sql("SELECT * FROM users")
        assert extractor._is_valid_sql("INSERT INTO users VALUES (?)")
        assert extractor._is_valid_sql("UPDATE users SET name = 'x' WHERE id = 1")
        assert not extractor._is_valid_sql("hello world")
        assert not extractor._is_valid_sql("FAILED TO connect")
        assert not extractor._is_valid_sql("// comment")
        assert not extractor._is_valid_sql("")

    def test_build_context_from_captures(self):
        extractor = TreeSitterExtractor()
        # Empty capture still produces a bare "()" because the helper defaults to
        # argument parentheses.
        assert extractor._build_context_from_captures({}) == "()"
        caps = {
            "caller": {"text": "obj"},
            "method_name": {"text": "foo"},
            "arguments": {"text": "(a, b)"},
        }
        assert extractor._build_context_from_captures(caps) == "obj.foo(...)"
        caps2 = {
            "method_name": {"text": "bar"},
            "arguments": {"text": "()"},
        }
        assert extractor._build_context_from_captures(caps2) == "bar()"

    def test_node_contains(self):
        extractor = TreeSitterExtractor()
        root, _ = _parse(LanguageType.PYTHON, "def foo(): pass\n")
        func = root.child(0)
        name = func.child(1)
        assert extractor._node_contains(func, name)
        assert not extractor._node_contains(name, func)

    def test_get_node_text(self):
        extractor = TreeSitterExtractor()
        root, _ = _parse(LanguageType.PYTHON, "def foo(): pass\n")
        name = root.child(0).child(1)
        assert extractor._get_node_text(name) == "foo"
        assert extractor._get_node_text(None) == ""
        assert extractor._get_node_text(object()) == ""

    def test_slice_bytes(self):
        extractor = TreeSitterExtractor()
        root, _ = _parse(LanguageType.PYTHON, "def foo(): pass\n")
        func = root.child(0)
        assert extractor._slice_bytes(b"def foo(): pass\n", func) == "def foo(): pass"

    def test_first_line(self):
        extractor = TreeSitterExtractor()
        assert extractor._first_line("line1\nline2") == "line1"
        assert extractor._first_line("single") == "single"

    def test_enclosing_method_name(self):
        extractor = TreeSitterExtractor()
        code = "def outer():\n    x = 1\n"
        root, _ = _parse(LanguageType.PYTHON, code)
        func = root.child(0)
        assignment = func.child(2)
        name = extractor._enclosing_method_name(assignment, LanguageType.PYTHON, code.encode())
        assert "def outer" in name
        assert extractor._enclosing_method_name(None, LanguageType.PYTHON, None) == ""

    def test_reference_type_from_ast(self):
        extractor = TreeSitterExtractor()
        code = """
def f():
    x = 1
    print(x)
"""
        root, _ = _parse(LanguageType.PYTHON, code)
        func = root.child(0)
        block = func.child(4)
        assign = block.child(0).child(0)
        lhs = assign.child(0)
        ref = block.child(1).child(0).child(1).child(1)
        assert extractor._reference_type_from_ast(lhs) == "write"
        assert extractor._reference_type_from_ast(ref) == "read"

    def test_extract_method_signature(self):
        extractor = TreeSitterExtractor()
        code = "def foo(a, b): pass\n"
        root, _ = _parse(LanguageType.PYTHON, code)
        name = root.child(0).child(1)
        sig = extractor._extract_method_signature(name, LanguageType.PYTHON, "foo")
        assert "def foo" in sig
        assert extractor._extract_method_signature(None, LanguageType.PYTHON, "foo") == "foo"

    def test_find_method_declaration_unsupported_language(self):
        extractor = TreeSitterExtractor()
        root, _ = _parse(LanguageType.PYTHON, "def f(): pass\n")
        name = root.child(0).child(1)
        # SQL has no method-definition mapping; helper returns the fallback.
        assert extractor._find_method_declaration(name, LanguageType.SQL) is None
