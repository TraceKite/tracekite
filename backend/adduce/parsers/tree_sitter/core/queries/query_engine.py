"""Tree-Sitter query execution engine.

Adapted from an earlier internal parser.
Preserves the Tree-sitter 0.25.x API usage:
    Query(language, query_text)
    QueryCursor.matches(root_node)
"""

import logging
from typing import Any, Dict, List, Optional

from ..models import LanguageType

logger = logging.getLogger(__name__)

# Try to import Tree-Sitter, handle gracefully if not available
try:
    from tree_sitter import Language, Node, Query, QueryCursor

    TREE_SITTER_AVAILABLE = True
except ImportError:

    class Language:
        pass

    class Node:
        pass

    class Query:
        pass

    class QueryCursor:
        pass

    TREE_SITTER_AVAILABLE = False


class QueryEngine:
    def __init__(self):
        self._query_cache: Dict[str, Query] = {}

    def execute_query(
        self,
        query_text: str,
        root_node: Node,
        language: Language,
        capture_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not TREE_SITTER_AVAILABLE:
            logger.warning("Tree-Sitter not available - cannot execute queries")
            return []

        try:
            # Get or create query object
            # tree-sitter 0.25.x: Use Query(language, query_text) constructor
            query_key = f"{language}:{hash(query_text)}"
            if query_key not in self._query_cache:
                try:
                    query = Query(language, query_text)
                    self._query_cache[query_key] = query
                except Exception as query_parse_error:
                    logger.debug(
                        f"Query parsing failed for: {query_text[:100]}... Error: {query_parse_error}"
                    )
                    return []
            else:
                query = self._query_cache[query_key]

            # Execute query using QueryCursor
            # tree-sitter 0.25.x: Use QueryCursor.matches() to get captures
            cursor = QueryCursor(query)
            matches = cursor.matches(root_node)

            # Process matches into structured results
            # tree-sitter 0.25.x matches() returns: [(pattern_idx, {capture_name: [nodes]}), ...]
            results = []

            for pattern_idx, captures_dict in matches:
                for capture_name, nodes in captures_dict.items():
                    if capture_names and capture_name not in capture_names:
                        continue

                    for node in nodes:
                        try:
                            if not hasattr(node, "text") or not hasattr(
                                node, "start_point"
                            ):
                                logger.debug(f"Invalid node object: {type(node)}")
                                continue

                            result = {
                                "capture_name": capture_name,
                                "node": node,
                                "text": node.text.decode("utf-8") if node.text else "",
                                "start_point": node.start_point,
                                "end_point": node.end_point,
                                "start_byte": node.start_byte,
                                "end_byte": node.end_byte,
                                "type": node.type,
                            }
                            results.append(result)
                        except Exception as e:
                            logger.debug(f"Error processing node: {e}")
                            continue

            return results

        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            return []

    def execute_query_grouped(
        self,
        query_text: str,
        root_node: Node,
        language: Language,
        capture_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Dict[str, Any]]]:
        if not TREE_SITTER_AVAILABLE:
            return []
        try:
            query_key = f"{language}:{hash(query_text)}"
            if query_key not in self._query_cache:
                try:
                    query = Query(language, query_text)
                    self._query_cache[query_key] = query
                except Exception:
                    return []
            else:
                query = self._query_cache[query_key]

            cursor = QueryCursor(query)
            matches = cursor.matches(root_node)
            grouped: List[Dict[str, Dict[str, Any]]] = []

            for _pattern_idx, captures_dict in matches:
                group: Dict[str, Dict[str, Any]] = {}
                for capture_name, nodes in captures_dict.items():
                    if capture_names and capture_name not in capture_names:
                        continue
                    for node in nodes:
                        if not hasattr(node, "text") or not hasattr(
                            node, "start_point"
                        ):
                            continue
                        group[capture_name] = {
                            "capture_name": capture_name,
                            "node": node,
                            "text": node.text.decode("utf-8") if node.text else "",
                            "start_point": node.start_point,
                            "end_point": node.end_point,
                            "start_byte": node.start_byte,
                            "end_byte": node.end_byte,
                            "type": node.type,
                        }
                if group:
                    grouped.append(group)
            return grouped
        except Exception as e:
            logger.error(f"Grouped query execution failed: {e}")
            return []

    def find_method_calls_grouped(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Dict[str, Any]]]:
        query_text = self._get_method_call_query(language_type)
        if not query_text:
            return []
        return self.execute_query_grouped(
            query_text,
            root_node,
            language,
            capture_names=["caller", "method_name", "arguments", "full_call"],
        )

    def find_sql_annotations(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_sql_annotation_query(language_type)
        if not query_text:
            return []

        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["annotation_name", "sql_query", "method_name"],
        )

    def find_method_definitions(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_method_definition_query(language_type)
        if not query_text:
            return []

        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["method_name", "class_name", "return_type"],
        )

    def find_method_calls(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_method_call_query(language_type)
        if not query_text:
            return []

        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["caller", "method_name", "arguments", "full_call"],
        )

    def find_identifiers(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_identifier_query(language_type)
        if not query_text:
            return []

        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["identifier"],
        )

    def _get_sql_annotation_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            LanguageType.JAVA: """
                (annotation
                  name: (identifier) @annotation_name
                  arguments: (annotation_argument_list
                    (string_literal) @sql_query))

                (method_declaration
                  name: (identifier) @method_name)

                (string_literal) @sql_query
            """,
            LanguageType.KOTLIN: """
                (annotation
                  (user_type (type_identifier) @annotation_name)
                  (value_arguments
                    (value_argument (string_literal) @sql_query)))

                (function_declaration
                  (simple_identifier) @method_name)

                (string_literal) @sql_query
            """,
            LanguageType.TYPESCRIPT: "(string) @sql_query",
            LanguageType.JAVASCRIPT: "(string) @sql_query",
            LanguageType.PYTHON: "(string) @sql_query",
        }

        return queries.get(language_type)

    def _get_identifier_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            LanguageType.JAVA: "(identifier) @identifier",
            LanguageType.KOTLIN: "(identifier) @identifier",
            LanguageType.PYTHON: "(identifier) @identifier",
            LanguageType.TYPESCRIPT: "(identifier) @identifier",
            LanguageType.JAVASCRIPT: "(identifier) @identifier",
            LanguageType.GO: "(identifier) @identifier",
            LanguageType.RUST: "(identifier) @identifier",
            LanguageType.CSHARP: "(identifier) @identifier",
        }

        return queries.get(language_type)

    def _get_method_definition_query(self, language_type: LanguageType) -> Optional[str]:
        # Use simplified, single-pattern queries to avoid syntax errors
        queries = {
            LanguageType.JAVA: "(method_declaration name: (identifier) @method_name)",
            LanguageType.KOTLIN: "(function_declaration name: (identifier) @method_name)",
            LanguageType.TYPESCRIPT: "(method_definition name: (property_identifier) @method_name)",
            LanguageType.JAVASCRIPT: "(method_definition name: (property_identifier) @method_name)",
            LanguageType.PYTHON: "(function_definition name: (identifier) @method_name)",
            LanguageType.GO: "(function_declaration name: (identifier) @method_name)",
            LanguageType.RUST: "(function_item name: (identifier) @method_name)",
            # C#: methods plus expression-bodied properties that front handlers.
            LanguageType.CSHARP: """
                (method_declaration name: (identifier) @method_name)
                (local_function_statement name: (identifier) @method_name)
            """,
            # Scala: concrete defs and trait-declared ones. Absent until the
            # D1 coverage pin — see the class-query note.
            LanguageType.SCALA: """
                (function_definition name: (identifier) @method_name)
                (function_declaration name: (identifier) @method_name)
            """,
        }

        return queries.get(language_type)

    def _get_method_call_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            LanguageType.JAVA: """
                (method_invocation
                  object: (identifier)? @caller
                  name: (identifier) @method_name
                  arguments: (argument_list)? @arguments) @full_call

                (method_invocation
                  name: (identifier) @method_name
                  arguments: (argument_list)? @arguments) @full_call
            """,
            LanguageType.TYPESCRIPT: """
                (call_expression
                  function: (member_expression
                    object: (identifier) @caller
                    property: (property_identifier) @method_name)
                  arguments: (arguments)? @arguments) @full_call

                (call_expression
                  function: (identifier) @method_name
                  arguments: (arguments)? @arguments) @full_call
            """,
            LanguageType.JAVASCRIPT: """
                (call_expression
                  function: (member_expression
                    object: (identifier) @caller
                    property: (property_identifier) @method_name)
                  arguments: (arguments)? @arguments) @full_call

                (call_expression
                  function: (identifier) @method_name
                  arguments: (arguments)? @arguments) @full_call
            """,
            LanguageType.PYTHON: """
                (call
                  function: (attribute
                    object: (identifier) @caller
                    attribute: (identifier) @method_name)
                  arguments: (argument_list)? @arguments) @full_call

                (call
                  function: (identifier) @method_name
                  arguments: (argument_list)? @arguments) @full_call
            """,
            LanguageType.GO: """
                (call_expression
                  function: (selector_expression
                    operand: (identifier) @caller
                    field: (field_identifier) @method_name)
                  arguments: (argument_list)? @arguments) @full_call

                (call_expression
                  function: (identifier) @method_name
                  arguments: (argument_list)? @arguments) @full_call
            """,
            LanguageType.RUST: """
                (call_expression
                  function: (field_expression
                    value: (_) @caller
                    field: (field_identifier) @method_name)
                  arguments: (arguments)? @arguments) @full_call

                (call_expression
                  function: (scoped_identifier
                    path: (identifier) @caller
                    name: (identifier) @method_name)
                  arguments: (arguments)? @arguments) @full_call

                (call_expression
                  function: (identifier) @method_name
                  arguments: (arguments)? @arguments) @full_call
            """,
            LanguageType.KOTLIN: """
                (call_expression
                  (navigation_expression
                    [(this_expression) (identifier)] @caller
                    (identifier) @method_name)
                  (value_arguments)? @arguments) @full_call

                (call_expression
                  (identifier) @method_name
                  (value_arguments)? @arguments) @full_call
            """,
        }

        return queries.get(language_type)

    def _get_enum_constant_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            LanguageType.JAVA: "(enum_declaration body: (enum_body (enum_constant name: (identifier) @enum_constant)))",
            LanguageType.KOTLIN: "(enum_declaration (enum_entry (simple_identifier) @enum_constant))",
            # TypeScript: use enum_declaration instead of direct enum_body
            LanguageType.TYPESCRIPT: "(enum_declaration body: (enum_body (property_identifier) @enum_constant))",
            LanguageType.JAVASCRIPT: "(enum_declaration body: (enum_body (property_identifier) @enum_constant))",
            LanguageType.CSHARP: "(enum_member_declaration name: (identifier) @enum_constant)",
        }
        return queries.get(language_type)

    def _get_interface_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            LanguageType.JAVA: "(interface_declaration name: (identifier) @interface_name)",
            LanguageType.KOTLIN: '(class_declaration "interface" name: (type_identifier) @interface_name)',
            LanguageType.TYPESCRIPT: "(interface_declaration name: (type_identifier) @interface_name)",
            LanguageType.JAVASCRIPT: "(interface_declaration name: (type_identifier) @interface_name)",
            LanguageType.CSHARP: "(interface_declaration name: (identifier) @interface_name)",
        }
        return queries.get(language_type)

    def _get_type_alias_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            LanguageType.TYPESCRIPT: "(type_alias_declaration name: (type_identifier) @type_name)",
            LanguageType.JAVASCRIPT: "(type_alias_declaration name: (type_identifier) @type_name)",
        }
        return queries.get(language_type)

    def _get_constant_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            # Java: simplified - just get field declarations, filter in code if needed
            LanguageType.JAVA: "(field_declaration declarator: (variable_declarator name: (identifier) @constant_name))",
            # Kotlin: simplified to avoid modifier issues
            LanguageType.KOTLIN: "(property_declaration (variable_declaration (simple_identifier) @constant_name))",
            # TypeScript/JS: const declarations
            LanguageType.TYPESCRIPT: "(lexical_declaration (variable_declarator name: (identifier) @constant_name))",
            LanguageType.JAVASCRIPT: "(lexical_declaration (variable_declarator name: (identifier) @constant_name))",
            # Python: uppercase module-level variables (convention)
            LanguageType.PYTHON: "(assignment left: (identifier) @constant_name)",
        }
        return queries.get(language_type)

    def find_enum_constants(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_enum_constant_query(language_type)
        if not query_text:
            return []
        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["enum_constant"],
        )

    def find_interfaces(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_interface_query(language_type)
        if not query_text:
            return []
        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["interface_name"],
        )

    def find_type_aliases(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_type_alias_query(language_type)
        if not query_text:
            return []
        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["type_name"],
        )

    def find_constants(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_constant_query(language_type)
        if not query_text:
            return []
        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["constant_name"],
        )

    def _get_class_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            LanguageType.JAVA: "(class_declaration name: (identifier) @class_name)",
            LanguageType.KOTLIN: '(class_declaration "class" name: (identifier) @class_name)',
            LanguageType.TYPESCRIPT: "(class_declaration name: (type_identifier) @class_name)",
            LanguageType.JAVASCRIPT: "(class_declaration name: (identifier) @class_name)",
            LanguageType.PYTHON: "(class_definition name: (identifier) @class_name)",
            LanguageType.RUST: "(struct_item name: (type_identifier) @class_name)",
            # C#: classes, records and structs are all "class-like" declarations
            # for symbol purposes; gRPC service impls subclass a generated base.
            LanguageType.CSHARP: """
                (class_declaration name: (identifier) @class_name)
                (record_declaration name: (identifier) @class_name)
                (struct_declaration name: (identifier) @class_name)
            """,
            # Scala had no symbol queries at all: the parse succeeded, the
            # tier read "full", and no class or def ever became a symbol —
            # so nothing (Spring annotations included) could anchor to one.
            # Found by the D1 coverage pin.
            LanguageType.SCALA: """
                (class_definition name: (identifier) @class_name)
                (object_definition name: (identifier) @class_name)
                (trait_definition name: (identifier) @class_name)
            """,
        }
        return queries.get(language_type)

    def find_classes(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_class_query(language_type)
        if not query_text:
            return []
        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["class_name"],
        )

    def _get_annotation_query(self, language_type: LanguageType) -> Optional[str]:
        queries = {
            # Java: @RestController (marker), @GetMapping(...) (with args)
            LanguageType.JAVA: "[(marker_annotation name: (identifier) @annotation_name) (annotation name: (identifier) @annotation_name)]",
            # Kotlin: marker annotations and constructor-style annotations
            LanguageType.KOTLIN: """
                (annotation (user_type (identifier) @annotation_name))
                (annotation (constructor_invocation (user_type (identifier) @annotation_name)))
            """,
            # Python: @app.route, @login_required, etc.
            LanguageType.PYTHON: "(decorator (identifier) @annotation_name)",
            # TypeScript/JS: @Component, @Injectable (experimental decorators)
            LanguageType.TYPESCRIPT: "(decorator (identifier) @annotation_name)",
            LanguageType.JAVASCRIPT: "(decorator (identifier) @annotation_name)",
            # Rust: #[get("/path")], #[derive(...)]
            LanguageType.RUST: "(attribute_item (attribute (identifier) @annotation_name))",
            # C#: [ApiController], [HttpGet("{id}")], [Route("api/x")]
            LanguageType.CSHARP: "(attribute name: (identifier) @annotation_name)",
            # Scala: @RestController, @GetMapping(Array("/path")). Absent
            # until the coverage pin proved the whole language yielded
            # no annotation symbols — Spring-on-Scala extracted nothing.
            LanguageType.SCALA: "(annotation (type_identifier) @annotation_name)",
        }
        return queries.get(language_type)

    def _get_proto_field_query(self, language_type: LanguageType) -> Optional[str]:
        if language_type != LanguageType.PROTO:
            return None
        # Proto fields: string name = 1; int32 age = 2;
        return "(field name: (identifier) @field_name)"

    def find_annotations(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_annotation_query(language_type)
        if not query_text:
            return []
        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["annotation_name"],
        )

    def find_proto_fields(
        self,
        root_node: Node,
        language: Language,
        language_type: LanguageType,
    ) -> List[Dict[str, Any]]:
        query_text = self._get_proto_field_query(language_type)
        if not query_text:
            return []
        return self.execute_query(
            query_text,
            root_node,
            language,
            capture_names=["field_name"],
        )

    def clear_cache(self) -> None:
        self._query_cache.clear()
        logger.info("Query cache cleared")
