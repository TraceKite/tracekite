"""Combined data models for the Tree-sitter parser/extractor package.

Adapted from an earlier internal parser.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# language_types.py
# ---------------------------------------------------------------------------


class LanguageType(Enum):
    JAVA = "java"
    KOTLIN = "kotlin"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    PYTHON = "python"

    GO = "go"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    CSHARP = "csharp"
    RUBY = "ruby"
    PHP = "php"

    SQL = "sql"
    JSON = "json"
    YAML = "yaml"
    PROTO = "proto"

    HTML = "html"
    CSS = "css"

    SCALA = "scala"
    R = "r"


LANGUAGE_METADATA: Dict[LanguageType, Dict[str, Any]] = {
    LanguageType.JAVA: {
        "extensions": {".java"},
        "has_ast_parser": True,
        "tree_sitter_name": "java",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": True,
    },
    LanguageType.KOTLIN: {
        "extensions": {".kt", ".kts"},
        "has_ast_parser": True,
        "tree_sitter_name": "kotlin",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": True,
    },
    LanguageType.TYPESCRIPT: {
        "extensions": {".ts", ".tsx"},
        "has_ast_parser": True,
        "tree_sitter_name": "typescript",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": True,
    },
    LanguageType.JAVASCRIPT: {
        "extensions": {".js", ".jsx", ".mjs", ".cjs"},
        "has_ast_parser": True,
        "tree_sitter_name": "javascript",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": False,
    },
    LanguageType.PYTHON: {
        "extensions": {".py", ".pyx", ".pyi"},
        "has_ast_parser": True,
        "tree_sitter_name": "python",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": False,
    },
    LanguageType.GO: {
        "extensions": {".go"},
        "has_ast_parser": True,
        "tree_sitter_name": "go",
        "supports_classes": False,
        "supports_methods": True,
        "supports_interfaces": True,
    },
    LanguageType.RUST: {
        "extensions": {".rs"},
        "has_ast_parser": True,
        "tree_sitter_name": "rust",
        "supports_classes": False,
        "supports_methods": True,
        "supports_interfaces": True,
    },
    LanguageType.C: {
        "extensions": {".c", ".h"},
        "has_ast_parser": True,
        "tree_sitter_name": "c",
        "supports_classes": False,
        "supports_methods": True,
        "supports_interfaces": False,
    },
    LanguageType.CPP: {
        "extensions": {".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"},
        "has_ast_parser": True,
        "tree_sitter_name": "cpp",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": False,
    },
    LanguageType.CSHARP: {
        "extensions": {".cs"},
        "has_ast_parser": True,
        "tree_sitter_name": "c_sharp",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": True,
    },
    LanguageType.RUBY: {
        "extensions": {".rb"},
        "has_ast_parser": True,
        "tree_sitter_name": "ruby",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": False,
    },
    LanguageType.PHP: {
        "extensions": {".php"},
        "has_ast_parser": True,
        "tree_sitter_name": "php",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": True,
    },
    LanguageType.SQL: {
        "extensions": {".sql"},
        "has_ast_parser": True,
        "tree_sitter_name": "sql",
        "supports_classes": False,
        "supports_methods": False,
        "supports_interfaces": False,
    },
    LanguageType.JSON: {
        "extensions": {".json", ".jsonc"},
        "has_ast_parser": True,
        "tree_sitter_name": "json",
        "supports_classes": False,
        "supports_methods": False,
        "supports_interfaces": False,
    },
    LanguageType.YAML: {
        "extensions": {".yaml", ".yml"},
        "has_ast_parser": True,
        "tree_sitter_name": "yaml",
        "supports_classes": False,
        "supports_methods": False,
        "supports_interfaces": False,
    },
    LanguageType.PROTO: {
        "extensions": {".proto"},
        "has_ast_parser": False,
        "tree_sitter_name": None,
        "supports_classes": False,
        "supports_methods": False,
        "supports_interfaces": False,
    },
    LanguageType.HTML: {
        "extensions": {".html", ".htm"},
        "has_ast_parser": True,
        "tree_sitter_name": "html",
        "supports_classes": False,
        "supports_methods": False,
        "supports_interfaces": False,
    },
    LanguageType.CSS: {
        "extensions": {".css", ".scss", ".sass", ".less"},
        "has_ast_parser": True,
        "tree_sitter_name": "css",
        "supports_classes": False,
        "supports_methods": False,
        "supports_interfaces": False,
    },
    LanguageType.SCALA: {
        "extensions": {".scala"},
        "has_ast_parser": True,
        "tree_sitter_name": "scala",
        "supports_classes": True,
        "supports_methods": True,
        "supports_interfaces": True,
    },
    LanguageType.R: {
        "extensions": {".r", ".R"},
        "has_ast_parser": True,
        "tree_sitter_name": "r",
        "supports_classes": False,
        "supports_methods": True,
        "supports_interfaces": False,
    },
}


def get_language_by_extension(extension: str) -> LanguageType:
    extension = extension.lower()
    for lang_type, metadata in LANGUAGE_METADATA.items():
        if extension in metadata["extensions"]:
            return lang_type
    raise ValueError(f"Unsupported file extension: {extension}")


def has_ast_parser(language: LanguageType) -> bool:
    return LANGUAGE_METADATA[language]["has_ast_parser"]


def get_tree_sitter_name(language: LanguageType) -> str:
    name = LANGUAGE_METADATA[language]["tree_sitter_name"]
    if name is None:
        raise ValueError(f"Language {language.value} does not have Tree-Sitter support")
    return name


def get_all_extensions() -> Set[str]:
    extensions = set()
    for metadata in LANGUAGE_METADATA.values():
        extensions.update(metadata["extensions"])
    return extensions


# ---------------------------------------------------------------------------
# symbol_info.py
# ---------------------------------------------------------------------------


class SymbolType(Enum):
    METHOD = "method"
    FUNCTION = "function"
    CLASS = "class"
    INTERFACE = "interface"
    VARIABLE = "variable"
    FIELD = "field"
    PARAMETER = "parameter"
    TABLE = "table"
    VIEW = "view"
    PROCEDURE = "procedure"
    KEY = "key"  # JSON key
    OBJECT = "object"  # Scala object


@dataclass
class CodeLocation:
    file_path: str
    line_number: int
    column: int
    end_line: int
    end_column: int


@dataclass
class SymbolInfo:
    name: str
    symbol_type: str  # Keep as string for backward compatibility
    file_path: str
    line_number: int
    column: int
    end_line: int
    end_column: int
    signature: Optional[str] = None
    parent_class: Optional[str] = None
    visibility: Optional[str] = None  # public, private, protected
    return_type: Optional[str] = None
    parameters: Optional[str] = None
    documentation: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    @property
    def location(self) -> CodeLocation:
        return CodeLocation(
            file_path=self.file_path,
            line_number=self.line_number,
            column=self.column,
            end_line=self.end_line,
            end_column=self.end_column,
        )

    @property
    def qualified_name(self) -> str:
        if self.parent_class:
            return f"{self.parent_class}.{self.name}"
        return self.name

    def is_method(self) -> bool:
        return self.symbol_type in ["method", "function", "procedure"]

    def is_class_like(self) -> bool:
        return self.symbol_type in ["class", "interface", "object"]


@dataclass
class MethodCall:
    caller_method: str
    called_method: str
    file_path: str
    line_number: int
    call_type: Optional[str] = None  # direct, virtual, static, interface, dynamic
    context: Optional[str] = None  # Surrounding code context
    parameters: Optional[str] = None
    return_type: Optional[str] = None

    @property
    def is_external_call(self) -> bool:
        # Simple heuristic: external calls often have package prefixes
        return "." in self.called_method and not self.called_method.startswith("this.")

    def __str__(self) -> str:
        return f"{self.caller_method} -> {self.called_method} at {self.file_path}:{self.line_number}"


@dataclass
class EndpointMapping:
    endpoint_path: str
    http_method: str  # GET, POST, etc. or "gRPC" for gRPC calls
    handler_method: str
    handler_class: str
    file_path: str
    line_number: int
    parameters: List[str] = field(default_factory=list)

    @property
    def qualified_handler(self) -> str:
        return f"{self.handler_class}.{self.handler_method}"

    def matches_path(self, path: str) -> bool:
        # Simple exact match - could be enhanced with pattern matching
        return self.endpoint_path == path or path in self.endpoint_path


# ---------------------------------------------------------------------------
# call_graph.py
# ---------------------------------------------------------------------------


@dataclass
class CallGraphNode:
    method_name: str
    class_name: Optional[str] = None
    file_path: str = ""
    calls: List[MethodCall] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        if self.class_name:
            return f"{self.class_name}.{self.method_name}"
        return self.method_name

    def add_call(self, method_call: MethodCall) -> None:
        self.calls.append(method_call)

    def get_callees(self) -> List[str]:
        return [call.called_method for call in self.calls]

    def get_external_calls(self) -> List[MethodCall]:
        return [call for call in self.calls if call.is_external_call]


@dataclass
class CallGraph:
    """Complete call graph for a file or repository."""

    nodes: List[CallGraphNode] = field(default_factory=list)
    method_calls: List[MethodCall] = field(default_factory=list)

    def add_node(self, node: CallGraphNode) -> None:
        self.nodes.append(node)

    def add_method_call(self, method_call: MethodCall) -> None:
        self.method_calls.append(method_call)

    def get_node_by_method(
        self, method_name: str, class_name: Optional[str] = None
    ) -> Optional[CallGraphNode]:
        for node in self.nodes:
            if node.method_name == method_name and node.class_name == class_name:
                return node
        return None


# ---------------------------------------------------------------------------
# parsing_result.py
# ---------------------------------------------------------------------------


@dataclass
class ParsingResult:
    file_path: str
    language: LanguageType
    symbols: List[SymbolInfo] = field(default_factory=list)
    call_graph: Optional[CallGraph] = None
    success: bool = True
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    ast_json: Optional[Dict[str, Any]] = None

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)

    @property
    def call_count(self) -> int:
        return len(self.call_graph.method_calls) if self.call_graph else 0

    def get_symbols_by_type(self, symbol_type: str) -> List[SymbolInfo]:
        return [symbol for symbol in self.symbols if symbol.symbol_type == symbol_type]

    def has_errors(self) -> bool:
        return not self.success or self.error_message is not None


@dataclass
class RepositoryAnalysisResult:
    repo_name: str
    repo_path: str
    file_results: List[ParsingResult] = field(default_factory=list)
    statistics: Dict[str, int] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None

    @property
    def total_files(self) -> int:
        return len(self.file_results)

    @property
    def total_symbols(self) -> int:
        return sum(result.symbol_count for result in self.file_results)


# ---------------------------------------------------------------------------
# sql_query.py
# ---------------------------------------------------------------------------


class QueryType(Enum):
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CREATE = "CREATE"
    ALTER = "ALTER"
    DROP = "DROP"
    UNKNOWN = "UNKNOWN"


class AnnotationType(Enum):
    QUERY = "@Query"
    NAMED_QUERY = "@NamedQuery"
    MODIFYING = "@Modifying"
    SELECT = "@Select"
    INSERT = "@Insert"
    UPDATE = "@Update"
    DELETE = "@Delete"
    NATIVE_QUERY = "@NativeQuery"
    UNKNOWN = "@Unknown"


@dataclass
class SQLQuery:
    """Represents a SQL query extracted from code annotations."""

    method_symbol_id: Union[int, str]  # int for real DB ID, str for placeholder
    sql_text: str
    line_number: int

    query_type: QueryType = QueryType.UNKNOWN
    annotation_type: AnnotationType = AnnotationType.UNKNOWN
    tables: List[str] = field(default_factory=list)

    is_parameterized: bool = False
    parameter_count: int = 0
    complexity_score: int = 0

    file_path: str = ""
    method_name: str = ""

    def __post_init__(self):
        if self.query_type == QueryType.UNKNOWN:
            self.query_type = self._detect_query_type()

        if not self.tables:
            self.tables = self._extract_table_names()

        if self.parameter_count == 0:
            self.parameter_count = self._count_parameters()
            self.is_parameterized = self.parameter_count > 0

        if self.complexity_score == 0:
            self.complexity_score = self._calculate_complexity()

    def _detect_query_type(self) -> QueryType:
        sql_upper = self.sql_text.upper().strip()

        # Remove comments and normalize whitespace
        sql_clean = re.sub(r"--.*$", "", sql_upper, flags=re.MULTILINE)
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
        sql_clean = re.sub(r"\s+", " ", sql_clean).strip()

        if sql_clean.startswith("SELECT"):
            return QueryType.SELECT
        elif sql_clean.startswith("INSERT"):
            return QueryType.INSERT
        elif sql_clean.startswith("UPDATE"):
            return QueryType.UPDATE
        elif sql_clean.startswith("DELETE"):
            return QueryType.DELETE
        elif sql_clean.startswith("CREATE"):
            return QueryType.CREATE
        elif sql_clean.startswith("ALTER"):
            return QueryType.ALTER
        elif sql_clean.startswith("DROP"):
            return QueryType.DROP
        else:
            return QueryType.UNKNOWN

    def _extract_table_names(self) -> List[str]:
        tables = set()
        sql_upper = self.sql_text.upper()

        patterns = [
            r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
            r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
            r"\bINTO\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
            r"\bUPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
            r"\bDELETE\s+FROM\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, sql_upper)
            for match in matches:
                # Clean up table name (remove schema prefix if present)
                table_name = match.split(".")[-1].strip('`"[]')
                if table_name and not table_name.isdigit():
                    tables.add(table_name.lower())

        return sorted(list(tables))

    def _count_parameters(self) -> int:
        question_marks = len(re.findall(r"\?", self.sql_text))
        named_params = len(re.findall(r":[a-zA-Z_][a-zA-Z0-9_]*", self.sql_text))
        numbered_params = len(re.findall(r"\$\d+", self.sql_text))

        return question_marks + named_params + numbered_params

    def _calculate_complexity(self) -> int:
        score = 0
        sql_upper = self.sql_text.upper()

        score += 1

        score += len(re.findall(r"\bJOIN\b", sql_upper)) * 2

        # Subquery complexity
        score += len(re.findall(r"\bSELECT\b", sql_upper)) - 1  # Subtract main SELECT

        score += len(re.findall(r"\bWHERE\b", sql_upper))

        score += len(re.findall(r"\bGROUP\s+BY\b", sql_upper))

        score += len(re.findall(r"\bORDER\s+BY\b", sql_upper))

        score += len(re.findall(r"\bHAVING\b", sql_upper))

        score += len(re.findall(r"\bUNION\b", sql_upper)) * 2

        return max(score, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method_symbol_id": self.method_symbol_id,
            "sql_text": self.sql_text,
            "query_type": self.query_type.value,
            "tables": json.dumps(self.tables),
            "annotation_type": self.annotation_type.value,
            "line_number": self.line_number,
            "is_parameterized": self.is_parameterized,
            "parameter_count": self.parameter_count,
            "complexity_score": self.complexity_score,
            "file_path": self.file_path,
            "method_name": self.method_name,
        }

    @classmethod
    def from_annotation(
        cls,
        method_symbol_id: int,
        annotation_text: str,
        line_number: int,
        file_path: str = "",
        method_name: str = "",
    ) -> Optional["SQLQuery"]:
        sql_text = cls._extract_sql_from_annotation(annotation_text)
        if not sql_text:
            return None

        annotation_type = cls._detect_annotation_type(annotation_text)

        return cls(
            method_symbol_id=method_symbol_id,
            sql_text=sql_text,
            line_number=line_number,
            annotation_type=annotation_type,
            file_path=file_path,
            method_name=method_name,
        )

    @staticmethod
    def _extract_sql_from_annotation(annotation_text: str) -> Optional[str]:
        # Pattern for @Query("SQL") or @Query(value = "SQL")
        patterns = [
            r"@Query\s*\(\s*\"([^\"]+)\"\s*\)",
            r"@Query\s*\(\s*value\s*=\s*\"([^\"]+)\"\s*\)",
            r"@Query\s*\(\s*\"\"\"([^\"]+)\"\"\"\s*\)",
            r"@NamedQuery\s*\(\s*query\s*=\s*\"([^\"]+)\"\s*\)",
            r"@Select\s*\(\s*\"([^\"]+)\"\s*\)",
            r"@Insert\s*\(\s*\"([^\"]+)\"\s*\)",
            r"@Update\s*\(\s*\"([^\"]+)\"\s*\)",
            r"@Delete\s*\(\s*\"([^\"]+)\"\s*\)",
        ]

        for pattern in patterns:
            match = re.search(pattern, annotation_text, re.DOTALL | re.IGNORECASE)
            if match:
                sql = match.group(1).strip()
                sql = sql.replace('\\"', '"').replace("\\n", "\n")
                sql = re.sub(r"\s+", " ", sql).strip()
                return sql

        return None

    @staticmethod
    def _detect_annotation_type(annotation_text: str) -> AnnotationType:
        text_upper = annotation_text.upper()

        if "@QUERY" in text_upper:
            return AnnotationType.QUERY
        elif "@NAMEDQUERY" in text_upper:
            return AnnotationType.NAMED_QUERY
        elif "@MODIFYING" in text_upper:
            return AnnotationType.MODIFYING
        elif "@SELECT" in text_upper:
            return AnnotationType.SELECT
        elif "@INSERT" in text_upper:
            return AnnotationType.INSERT
        elif "@UPDATE" in text_upper:
            return AnnotationType.UPDATE
        elif "@DELETE" in text_upper:
            return AnnotationType.DELETE
        elif "@NATIVEQUERY" in text_upper:
            return AnnotationType.NATIVE_QUERY
        else:
            return AnnotationType.UNKNOWN

    def __str__(self) -> str:
        return f"SQLQuery({self.query_type.value}, {len(self.sql_text)} chars, {len(self.tables)} tables)"

    def __repr__(self) -> str:
        return (
            f"SQLQuery(method_id={self.method_symbol_id}, "
            f"type={self.query_type.value}, "
            f"annotation={self.annotation_type.value}, "
            f"tables={self.tables}, "
            f"params={self.parameter_count}, "
            f"complexity={self.complexity_score})"
        )
