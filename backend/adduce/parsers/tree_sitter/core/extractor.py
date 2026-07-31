"""Tree-sitter symbol/call/SQL extractor.

Adapted from an earlier internal parser.
Converted from async to synchronous methods for the synchronous ingestion pipeline.
"""

import logging
from typing import Any, Dict, List, Optional

from .models import (
    AnnotationType,
    LanguageType,
    MethodCall,
    QueryType,
    SQLQuery,
    SymbolInfo,
)
from .parser import TreeSitterParser
from .queries.query_engine import QueryEngine
from .queries.query_loader import QueryLoader

logger = logging.getLogger(__name__)

try:
    from tree_sitter import Language, Node

    TREE_SITTER_AVAILABLE = True
except ImportError:

    class Node:
        ...

    class Language:
        ...

    TREE_SITTER_AVAILABLE = False


class TreeSitterExtractor:
    """Synchronous Tree-sitter extractor for symbols, calls, SQL and references."""

    def __init__(self):
        self.query_engine = QueryEngine()
        self.query_loader = QueryLoader()
        self.tree_sitter_parser = TreeSitterParser()

    def extract_symbols(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
        file_path: str,
    ) -> List[SymbolInfo]:
        if not TREE_SITTER_AVAILABLE:
            logger.warning("Tree-Sitter not available - cannot extract symbols")
            return []
        try:
            symbols: List[SymbolInfo] = []
            annotation_matches = self.query_engine.find_annotations(
                root_node, language, language_type
            )
            for match in annotation_matches:
                if match.get("capture_name") == "annotation_name":
                    node = match.get("node")
                    full_node = getattr(node, "parent", None) or node
                    # Climb to the full annotation/decorator/attribute node so that
                    # constructor-style annotations (e.g. Kotlin @GetMapping("/path"))
                    # and Rust attribute macros retain their arguments.
                    while full_node is not None:
                        node_type = getattr(full_node, "type", "")
                        if node_type in (
                            "annotation",
                            "decorator",
                            "attribute_item",
                            "attribute",
                        ):
                            break
                        full_node = getattr(full_node, "parent", None)
                    if full_node is None:
                        full_node = node
                    full_text = self._get_node_text(full_node) if full_node else f"@{match['text']}"
                    symbols.append(
                        SymbolInfo(
                            name=match["text"],
                            symbol_type="annotation",
                            file_path=file_path,
                            line_number=match["start_point"][0] + 1,
                            column=match["start_point"][1],
                            end_line=match["end_point"][0] + 1,
                            end_column=match["end_point"][1],
                            signature=full_text,
                        )
                    )
            proto_field_matches = self.query_engine.find_proto_fields(
                root_node, language, language_type
            )
            for match in proto_field_matches:
                if match.get("capture_name") == "field_name":
                    symbols.append(
                        SymbolInfo(
                            name=match["text"],
                            symbol_type="field",
                            file_path=file_path,
                            line_number=match["start_point"][0] + 1,
                            column=match["start_point"][1],
                            end_line=match["end_point"][0] + 1,
                            end_column=match["end_point"][1],
                            signature=f"field {match['text']}",
                        )
                    )
            constant_matches = self.query_engine.find_constants(
                root_node, language, language_type
            )
            for match in constant_matches:
                if match.get("capture_name") == "constant_name":
                    if language_type == LanguageType.PYTHON and not match[
                        "text"
                    ].isupper():
                        continue
                    symbols.append(
                        SymbolInfo(
                            name=match["text"],
                            symbol_type="variable",
                            file_path=file_path,
                            line_number=match["start_point"][0] + 1,
                            column=match["start_point"][1],
                            end_line=match["end_point"][0] + 1,
                            end_column=match["end_point"][1],
                            signature=f"const {match['text']}",
                        )
                    )
            type_matches = self.query_engine.find_type_aliases(
                root_node, language, language_type
            )
            for match in type_matches:
                if match.get("capture_name") == "type_name":
                    symbols.append(
                        SymbolInfo(
                            name=match["text"],
                            symbol_type="interface",
                            file_path=file_path,
                            line_number=match["start_point"][0] + 1,
                            column=match["start_point"][1],
                            end_line=match["end_point"][0] + 1,
                            end_column=match["end_point"][1],
                            signature=f"type {match['text']}",
                        )
                    )
            enum_constant_matches = self.query_engine.find_enum_constants(
                root_node, language, language_type
            )
            for match in enum_constant_matches:
                if match.get("capture_name") == "enum_constant":
                    symbols.append(
                        SymbolInfo(
                            name=match["text"],
                            symbol_type="variable",
                            file_path=file_path,
                            line_number=match["start_point"][0] + 1,
                            column=match["start_point"][1],
                            end_line=match["end_point"][0] + 1,
                            end_column=match["end_point"][1],
                            signature=f"enum constant {match['text']}",
                        )
                    )
            container_nodes: List[Tuple[SymbolInfo, Any]] = []

            interface_matches = self.query_engine.find_interfaces(
                root_node, language, language_type
            )
            for match in interface_matches:
                if match.get("capture_name") == "interface_name":
                    symbol = SymbolInfo(
                        name=match["text"],
                        symbol_type="interface",
                        file_path=file_path,
                        line_number=match["start_point"][0] + 1,
                        column=match["start_point"][1],
                        end_line=match["end_point"][0] + 1,
                        end_column=match["end_point"][1],
                        signature=f"interface {match['text']}",
                    )
                    symbols.append(symbol)
                    # The capture is the name node; the declaration node is its parent.
                    container_node = match.get("node")
                    if container_node is not None:
                        container_node = getattr(container_node, "parent", None) or container_node
                    container_nodes.append((symbol, container_node))

            class_matches = self.query_engine.find_classes(
                root_node, language, language_type
            )
            for match in class_matches:
                if match.get("capture_name") == "class_name":
                    symbol = SymbolInfo(
                        name=match["text"],
                        symbol_type="class",
                        file_path=file_path,
                        line_number=match["start_point"][0] + 1,
                        column=match["start_point"][1],
                        end_line=match["end_point"][0] + 1,
                        end_column=match["end_point"][1],
                        signature=f"class {match['text']}",
                    )
                    symbols.append(symbol)
                    container_node = match.get("node")
                    if container_node is not None:
                        container_node = getattr(container_node, "parent", None) or container_node
                    container_nodes.append((symbol, container_node))

            method_nodes: List[Tuple[SymbolInfo, Any]] = []
            method_matches = self.query_engine.find_method_definitions(
                root_node, language, language_type
            )
            for match in method_matches:
                if match.get("capture_name") == "method_name":
                    node = match.get("node")
                    # Use the full declaration node for span/containment so that
                    # call-site resolution can locate calls inside the method body.
                    decl_node = self._find_method_declaration(node, language_type) or node
                    sig = self._extract_method_signature(
                        node, language_type, match.get("text", "")
                    )
                    symbol = SymbolInfo(
                        name=match["text"],
                        symbol_type="method",
                        file_path=file_path,
                        line_number=match["start_point"][0] + 1,
                        column=match["start_point"][1],
                        end_line=decl_node.end_point[0] + 1,
                        end_column=decl_node.end_point[1],
                        signature=sig,
                    )
                    symbols.append(symbol)
                    method_nodes.append((symbol, decl_node))

            # Attach parent class/interface to methods by AST containment.
            for method_symbol, method_node in method_nodes:
                if method_node is None:
                    continue
                parent = None
                for container_symbol, container_node in container_nodes:
                    if container_node is None:
                        continue
                    if (
                        container_node.start_byte <= method_node.start_byte
                        and method_node.end_byte <= container_node.end_byte
                    ):
                        if parent is None or (
                            container_node.end_byte - container_node.start_byte
                            < parent.end_byte - parent.start_byte
                        ):
                            method_symbol.parent_class = container_symbol.name
                            parent = container_node

            logger.debug(f"Extracted {len(symbols)} symbols from {file_path}")
            return symbols
        except Exception as e:
            logger.error(f"Symbol extraction failed for {file_path}: {e}")
            return []

    def extract_method_calls(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
        file_path: str,
        source_content: Optional[str] = None,
    ) -> List[MethodCall]:
        if not TREE_SITTER_AVAILABLE:
            logger.warning("Tree-Sitter not available - cannot extract method calls")
            return []
        try:
            grouped = self.query_engine.find_method_calls_grouped(
                root_node, language, language_type
            )
            source_bytes = source_content.encode("utf-8") if source_content else None
            method_calls: List[MethodCall] = []
            for captures in grouped:
                full_call = captures.get("full_call")
                method_name_cap = captures.get("method_name")
                if not method_name_cap or not full_call:
                    continue
                method_name = method_name_cap.get("text", "")
                node = full_call.get("node")
                caller = self._enclosing_method_name(node, language_type, source_bytes)
                context = None
                if source_bytes is not None and node is not None:
                    context = self._slice_bytes(source_bytes, node)
                if not context:
                    context = self._build_context_from_captures(captures)
                method_calls.append(
                    MethodCall(
                        caller_method=caller,
                        called_method=method_name,
                        file_path=file_path,
                        line_number=method_name_cap["start_point"][0] + 1,
                        context=context,
                        call_type="direct",
                    )
                )
            logger.debug(f"Extracted {len(method_calls)} method calls from {file_path}")
            return method_calls
        except Exception as e:
            logger.error(f"Method call extraction failed for {file_path}: {e}")
            return []

    def extract_sql_queries(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
        file_path: str,
        symbols: List[SymbolInfo],
    ) -> List[SQLQuery]:
        if not TREE_SITTER_AVAILABLE:
            logger.warning("Tree-Sitter not available - cannot extract SQL queries")
            return []
        try:
            sql_queries: List[SQLQuery] = []
            sql_matches = self.query_engine.find_sql_annotations(
                root_node, language, language_type
            )
            methods_defs = self.query_engine.find_method_definitions(
                root_node, language, language_type
            )
            source_map: Dict[str, Dict[str, Any]] = {}
            for m in methods_defs:
                if m.get("capture_name") == "method_name":
                    method_name_node = m.get("node")
                    method_decl_node = (
                        method_name_node.parent if method_name_node else None
                    )
                    source_map.setdefault(
                        m["text"],
                        {"node": method_decl_node, "line": m["start_point"][0] + 1},
                    )
            ann_by_method: Dict[str, Dict[str, Any]] = {}
            for match in sql_matches:
                cap = match.get("capture_name")
                if cap == "method_name":
                    name = match["text"]
                    ann_by_method.setdefault(
                        name,
                        {"name": name, "annotations": [], "sqls": [], "line": match["start_point"][0] + 1},
                    )
                elif cap == "annotation_name":
                    name = match.get("method_name") or ""
                    if not name and "method_name" in match:
                        name = match["method_name"]
                    if name in ann_by_method:
                        ann_by_method[name]["annotations"].append(match["text"])
            method_nodes = [
                (k, v["node"]) for k, v in source_map.items() if v.get("node")
            ]
            sql_nodes_seen = set()
            for match in sql_matches:
                if match.get("capture_name") == "sql_query":
                    s_node = match.get("node")
                    node_id = (s_node.start_byte, s_node.end_byte) if s_node else None
                    if node_id and node_id in sql_nodes_seen:
                        continue
                    if node_id:
                        sql_nodes_seen.add(node_id)
                    sql_text = match.get("text", "")
                    if not self._is_valid_sql(sql_text):
                        continue
                    chosen = None
                    span = None
                    for name, mnode in method_nodes:
                        if mnode and self._node_contains(mnode, s_node):
                            cur_span = mnode.end_byte - mnode.start_byte
                            if span is None or cur_span < span:
                                chosen = name
                                span = cur_span
                    if chosen:
                        ann_by_method.setdefault(
                            chosen,
                            {
                                "name": chosen,
                                "annotations": [],
                                "sqls": [],
                                "line": source_map[chosen]["line"],
                            },
                        )
                        ann_by_method[chosen]["sqls"].append(match["text"])
            for name, data in ann_by_method.items():
                method_symbol = None
                for s in symbols:
                    if s.name == name and s.symbol_type == "method":
                        method_symbol = s
                        break
                mline = (
                    data.get("line")
                    or (source_map.get(name) or {}).get("line")
                    or 1
                )
                if method_symbol:
                    method_symbol_id = f"SYMBOL:{method_symbol.name}:{file_path}:{method_symbol.line_number}"
                else:
                    method_symbol_id = f"SYMBOL:{name}:{file_path}:{mline}"
                for sql_text in data.get("sqls", []):
                    clean_sql = sql_text.strip("\"'")
                    if not clean_sql:
                        continue
                    sql_query = SQLQuery(
                        method_symbol_id=method_symbol_id,
                        sql_text=clean_sql,
                        line_number=mline,
                        file_path=file_path,
                        annotation_type=AnnotationType.QUERY,
                        query_type=QueryType.UNKNOWN,
                    )
                    sql_queries.append(sql_query)
            logger.debug(f"Extracted {len(sql_queries)} SQL queries from {file_path}")
            return sql_queries
        except Exception as e:
            logger.error(f"SQL query extraction failed for {file_path}: {e}")
            return []

    def extract_symbol_references(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
        file_path: str,
        symbols: List[SymbolInfo],
    ) -> List[Dict[str, Any]]:
        if not TREE_SITTER_AVAILABLE:
            logger.warning("Tree-Sitter not available - cannot extract symbol references")
            return []
        try:
            symbol_references: List[Dict[str, Any]] = []
            identifier_matches = self.query_engine.find_identifiers(
                root_node, language, language_type
            )
            lookup = {s.name: s for s in symbols}
            for match in identifier_matches:
                name = match.get("text", "")
                if name in lookup:
                    symbol = lookup[name]
                    node = match.get("node")
                    ref_type = self._reference_type_from_ast(node)
                    symbol_id = f"SYMBOL:{symbol.name}:{symbol.file_path}:{symbol.line_number}"
                    symbol_references.append(
                        {
                            "symbol_id": symbol_id,
                            "reference_type": ref_type,
                            "file_path": file_path,
                            "line_number": match["start_point"][0] + 1,
                            "context": name,
                        }
                    )
            logger.debug(
                f"Extracted {len(symbol_references)} symbol references from {file_path}"
            )
            return symbol_references
        except Exception as e:
            logger.error(f"Symbol reference extraction failed for {file_path}: {e}")
            return []

    def _reference_type_from_ast(self, node: Optional[Node]) -> str:
        n = node
        while n:
            t = getattr(n, "type", "")
            if t in (
                "call_expression",
                "method_invocation",
                "function_call",
                "invocation_expression",
            ):
                return "call"
            if t in (
                "assignment",
                "variable_assignment",
                "augmented_assignment",
                "assignment_expression",
            ):
                return "write"
            if t in (
                "import_declaration",
                "import_statement",
                "import_directive",
            ):
                return "import"
            n = getattr(n, "parent", None)
        return "read"

    def _slice_bytes(self, source_bytes: bytes, node: Node) -> str:
        return source_bytes[node.start_byte : node.end_byte].decode(
            "utf-8", errors="replace"
        )

    def _enclosing_method_name(
        self,
        node: Optional[Node],
        language_type: LanguageType,
        source_bytes: Optional[bytes],
    ) -> str:
        n = node
        while n:
            if getattr(n, "type", "") in (
                "function_declaration",
                "method_declaration",
                "function_definition",
                "method_definition",
                "function_item",
            ):
                if source_bytes is not None:
                    return self._first_line(self._slice_bytes(source_bytes, n))
                return ""
            n = getattr(n, "parent", None)
        return ""

    def _first_line(self, s: str) -> str:
        return s.split("\n", 1)[0].strip()

    def _build_context_from_captures(self, captures: dict) -> Optional[str]:
        parts = []
        caller = captures.get("caller")
        if caller and caller.get("text"):
            parts.append(caller["text"])
            parts.append(".")
        if "method_name" in captures:
            parts.append(captures["method_name"]["text"])
        args = captures.get("arguments")
        if args and args.get("text"):
            txt = args["text"].strip()
            if txt and txt != "()":
                parts.append("(")
                parts.append("...")
                parts.append(")")
            else:
                parts.append("()")
        else:
            parts.append("()")
        if parts:
            return "".join(parts)
        return None

    def _node_contains(self, outer: Node, inner: Node) -> bool:
        return outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte

    def _is_valid_sql(self, sql_text: str) -> bool:
        if not sql_text or len(sql_text) < 10:
            return False

        text_upper = sql_text.strip().upper()
        text_stripped = sql_text.strip()

        sql_statement_starts = (
            "SELECT ",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "CREATE ",
            "ALTER ",
            "DROP ",
            "TRUNCATE ",
            "MERGE ",
            "WITH ",
            "CALL ",
            "EXEC ",
        )
        if text_upper.startswith(sql_statement_starts):
            return True

        false_positive_patterns = [
            "FAILED TO",
            "ERROR:",
            "EXCEPTION:",
            "LOG:",
            "DEBUG:",
            "UNABLE TO",
            "COULD NOT",
            "CANNOT ",
            "CAN'T ",
        ]
        for pattern in false_positive_patterns:
            if pattern in text_upper:
                return False

        sql_structure_patterns = [
            " FROM ",
            " WHERE ",
            " JOIN ",
            " SET ",
            " VALUES ",
            " INTO ",
            " TABLE ",
            " INDEX ",
            " VIEW ",
            " AS SELECT",
        ]
        keyword_count = sum(1 for p in sql_structure_patterns if p in text_upper)

        has_sql_keywords = any(
            kw in text_upper for kw in ["SELECT", "INSERT", "UPDATE", "DELETE", "FROM"]
        )

        if keyword_count >= 2 and has_sql_keywords:
            return True

        if (
            text_stripped.startswith("@")
            or text_stripped.startswith("//")
            or text_stripped.startswith("#")
        ):
            return False

        return False

    def _extract_method_signature(
        self,
        method_node: Optional[Node],
        language_type: LanguageType,
        fallback_name: str,
    ) -> str:
        if not method_node:
            return fallback_name
        try:
            decl_node = self._find_method_declaration(method_node, language_type)
            if decl_node:
                return self._build_signature_from_ast(decl_node, language_type)
            return fallback_name
        except Exception:
            return fallback_name

    def _find_method_declaration(
        self, node: Optional[Node], language_type: LanguageType
    ) -> Optional[Node]:
        if not node:
            return None
        method_types = {
            LanguageType.JAVA: ("method_declaration", "constructor_declaration"),
            LanguageType.KOTLIN: (
                "function_declaration",
                "primary_constructor",
                "secondary_constructor",
            ),
            LanguageType.TYPESCRIPT: ("method_definition", "function_declaration"),
            LanguageType.JAVASCRIPT: ("method_definition", "function_declaration"),
            LanguageType.PYTHON: ("decorated_definition",),
            LanguageType.GO: ("function_declaration",),
            LanguageType.RUST: ("function_item",),
        }
        target_types = method_types.get(language_type, ())
        n = node
        while n:
            node_type = getattr(n, "type", "")
            if node_type in target_types:
                return n
            if node_type == "function_definition" and language_type == LanguageType.PYTHON:
                parent = getattr(n, "parent", None)
                if parent and getattr(parent, "type", "") == "decorated_definition":
                    return parent
                return n
            n = getattr(n, "parent", None)
        return None

    def _build_signature_from_ast(
        self, decl_node: Node, language_type: LanguageType
    ) -> str:
        node_type = getattr(decl_node, "type", "")
        if language_type == LanguageType.PYTHON:
            return self._build_python_signature(decl_node)
        elif language_type in (LanguageType.JAVA, LanguageType.KOTLIN):
            return self._build_java_signature(decl_node)
        else:
            return self._build_generic_signature(decl_node)

    def _build_python_signature(self, decl_node: Node) -> str:
        parts = []
        node_type = getattr(decl_node, "type", "")
        if node_type == "decorated_definition":
            for child in decl_node.children:
                child_type = getattr(child, "type", "")
                if child_type == "decorator":
                    parts.append(self._get_node_text(child))
                elif child_type == "function_definition":
                    parts.append(self._build_function_def_signature(child))
        elif node_type == "function_definition":
            parts.append(self._build_function_def_signature(decl_node))
        return " ".join(parts)[:500]

    def _build_function_def_signature(self, func_node: Node) -> str:
        sig_parts = []
        for child in func_node.children:
            child_type = getattr(child, "type", "")
            if child_type == "block":
                break
            if child_type == ":":
                break
            sig_parts.append(self._get_node_text(child))
        return " ".join(sig_parts)

    def _build_java_signature(self, decl_node: Node) -> str:
        parts = []
        for child in decl_node.children:
            child_type = getattr(child, "type", "")
            if child_type == "block":
                break
            if child_type == "constructor_body":
                break
            parts.append(self._get_node_text(child))
        return " ".join(parts)[:500]

    def _build_generic_signature(self, decl_node: Node) -> str:
        parts = []
        for child in decl_node.children:
            child_type = getattr(child, "type", "")
            if child_type in ("block", "statement_block", "body"):
                break
            parts.append(self._get_node_text(child))
        return " ".join(parts)[:500]

    def _get_node_text(self, node: Node) -> str:
        text_prop = getattr(node, "text", None)
        if text_prop:
            return text_prop.decode("utf-8", errors="replace").strip()
        return ""
