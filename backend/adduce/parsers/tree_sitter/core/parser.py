"""Tree-sitter parser implementation.

Adapted from an earlier internal parser.
Converted from async to synchronous methods for the synchronous ingestion pipeline.
"""

import logging
from typing import Any, Dict, List, Optional

from .base_parser import BaseParser
from .models import LanguageType, ParsingResult, get_tree_sitter_name, has_ast_parser

logger = logging.getLogger(__name__)

# Try to import Tree-Sitter, handle gracefully if not available
try:
    from tree_sitter import Language, Parser, Node

    TREE_SITTER_AVAILABLE = True
except ImportError as e:
    logger.warning(
        f"Tree-Sitter not available: {e}. Falling back to text-based parsing."
    )
    TREE_SITTER_AVAILABLE = False

    # Create dummy classes to prevent import errors
    class Language:
        pass

    class Parser:
        pass

    class Node:
        pass


class TreeSitterParser(BaseParser):
    """Synchronous Tree-sitter parser with per-language Parser/Language caching."""

    def __init__(self):
        # Cache can hold Language objects or raw language pointers (PyCapsules)
        self._language_cache: Dict[str, Any] = {}
        self._parser_cache: Dict[str, Parser] = {}

    def _serialize_node(
        self,
        node,
        content_bytes: bytes,
        max_text_length: int = 500,
        max_depth: int = 100,
        current_depth: int = 0,
    ) -> Dict[str, Any]:
        text = None
        if node.start_byte < len(content_bytes) and node.end_byte <= len(content_bytes):
            node_text = content_bytes[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )
            if len(node_text) <= max_text_length:
                text = node_text
            else:
                text = node_text[:max_text_length] + "..."

        children: List[Dict[str, Any]] = []
        if current_depth < max_depth:
            for child in node.children:
                children.append(
                    self._serialize_node(
                        child,
                        content_bytes,
                        max_text_length,
                        max_depth,
                        current_depth + 1,
                    )
                )

        return {
            "type": node.type,
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "start_point": {
                "row": node.start_point[0],
                "column": node.start_point[1],
            },
            "end_point": {
                "row": node.end_point[0],
                "column": node.end_point[1],
            },
            "text": text,
            "children": children,
        }

    def parse_content(
        self, content: str, file_path: str, language: LanguageType
    ) -> ParsingResult:
        try:
            if not TREE_SITTER_AVAILABLE:
                return ParsingResult(
                    file_path=file_path,
                    language=language,
                    success=False,
                    error_message="Tree-Sitter not available - install tree-sitter dependencies",
                )

            if not self.supports_language(language):
                return ParsingResult(
                    file_path=file_path,
                    language=language,
                    success=False,
                    error_message=f"Language {language.value} not supported by Tree-Sitter parser",
                )

            parser = self._get_parser(language, file_path)
            if not parser:
                # Special handling for SQL - it's expected to use text parser
                if language == LanguageType.SQL:
                    error_msg = "SQL_TEXT_PARSER_EXPECTED"
                else:
                    error_msg = f"Could not create parser for {language.value}"

                return ParsingResult(
                    file_path=file_path,
                    language=language,
                    success=False,
                    error_message=error_msg,
                )

            content_bytes = bytes(content, "utf8")
            tree = parser.parse(content_bytes)
            root_node = tree.root_node

            ast_json = self._serialize_node(root_node, content_bytes)

            result = ParsingResult(
                file_path=file_path,
                language=language,
                success=True,
                ast_json=ast_json,
            )

            result.metadata["ast_root"] = root_node
            result.metadata["content"] = content

            return result

        except Exception as e:
            logger.error(f"Tree-Sitter parsing failed for {file_path}: {e}")
            return ParsingResult(
                file_path=file_path,
                language=language,
                success=False,
                error_message=str(e),
            )

    def supports_language(self, language: LanguageType) -> bool:
        return TREE_SITTER_AVAILABLE and has_ast_parser(language)

    def parse_ast_root(self, content: str, language: LanguageType) -> Optional[Node]:
        try:
            if not TREE_SITTER_AVAILABLE or not self.supports_language(language):
                return None

            parser = self._get_parser(
                language, None
            )  # parse_ast_root doesn't have file_path
            if not parser:
                return None

            tree = parser.parse(bytes(content, "utf8"))
            return tree.root_node

        except Exception as e:
            logger.error(f"Failed to get AST root for {language.value}: {e}")
            return None

    def _get_parser(
        self, language: LanguageType, file_path: Optional[str] = None
    ) -> Optional[Parser]:
        """Get or create parser for language with caching.

        tree-sitter 0.25.x API: Parser(Language) - takes Language object directly.
        """
        try:
            if not TREE_SITTER_AVAILABLE:
                return None

            lang_name = get_tree_sitter_name(language)

            # For TypeScript, check if TSX file needs different parser
            cache_key = lang_name
            if lang_name == "typescript" and file_path and file_path.endswith(".tsx"):
                cache_key = "typescript_tsx"

            if cache_key in self._parser_cache:
                return self._parser_cache[cache_key]

            ts_language = self._get_language(language, file_path)
            if not ts_language:
                return None

            # Create parser with Language object (tree-sitter 0.25.x API)
            try:
                parser = Parser(ts_language)
                self._parser_cache[cache_key] = parser
                logger.debug(f"Created parser for {lang_name}")
                return parser

            except ValueError as ve:
                if "version" in str(ve).lower() or "incompatible" in str(ve).lower():
                    logger.warning(
                        f"Language version incompatibility for {lang_name}: {ve}"
                    )
                    return None
                raise
            except Exception as e:
                logger.error(f"Failed to create parser for {lang_name}: {e}")
                return None

        except Exception as e:
            logger.error(f"Failed to create parser for {language.value}: {e}")
            return None

    def _get_language(
        self, language: LanguageType, file_path: Optional[str] = None
    ) -> Optional[Language]:
        """Get or load Tree-Sitter language grammar with caching.

        Uses individual tree-sitter-* packages and wraps their language pointers
        in Language objects for compatibility with tree-sitter 0.25.x.

        API flow: ptr = ts_lang.language() -> Language(ptr) -> Parser(Language)
        """
        try:
            if not TREE_SITTER_AVAILABLE:
                return None

            lang_name = get_tree_sitter_name(language)

            # For TypeScript, check if TSX file needs different grammar
            cache_key = lang_name
            if lang_name == "typescript" and file_path and file_path.endswith(".tsx"):
                cache_key = "typescript_tsx"

            if cache_key in self._language_cache:
                return self._language_cache[cache_key]

            # Load language grammar from individual packages
            # These packages return raw language pointers (PyCapsule) that must be wrapped in Language()
            lang_ptr = None
            ts_language = None

            try:
                if lang_name == "java":
                    import tree_sitter_java as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "kotlin":
                    import tree_sitter_kotlin as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "python":
                    import tree_sitter_python as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "javascript":
                    import tree_sitter_javascript as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "typescript":
                    import tree_sitter_typescript as ts_lang

                    # Check if file is TSX (React TypeScript) - need different language
                    # TSX files have JSX syntax and need language_tsx() instead of language_typescript()
                    if file_path and file_path.endswith(".tsx"):
                        lang_ptr = ts_lang.language_tsx()
                        cache_key = "typescript_tsx"
                    else:
                        lang_ptr = ts_lang.language_typescript()
                        cache_key = "typescript"
                elif lang_name == "yaml":
                    import tree_sitter_yaml as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "json":
                    import tree_sitter_json as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "html":
                    try:
                        import tree_sitter_html as ts_lang

                        lang_ptr = ts_lang.language()
                    except ImportError:
                        logger.debug(
                            "tree-sitter-html not installed, HTML parsing unavailable"
                        )
                        return None
                elif lang_name == "css":
                    try:
                        import tree_sitter_css as ts_lang

                        lang_ptr = ts_lang.language()
                    except ImportError:
                        logger.debug(
                            "tree-sitter-css not installed, CSS parsing unavailable"
                        )
                        return None
                elif lang_name == "go":
                    import tree_sitter_go as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "rust":
                    import tree_sitter_rust as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "c":
                    import tree_sitter_c as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "cpp":
                    import tree_sitter_cpp as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name in {"c_sharp", "csharp"}:
                    import tree_sitter_c_sharp as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "ruby":
                    import tree_sitter_ruby as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "php":
                    import tree_sitter_php as ts_lang

                    lang_ptr = ts_lang.language_php()
                elif lang_name == "scala":
                    import tree_sitter_scala as ts_lang

                    lang_ptr = ts_lang.language()
                elif lang_name == "r":
                    logger.debug(
                        "R language: No tree-sitter parser available. Falling back to text chunking."
                    )
                    return None
                else:
                    logger.warning(f"No tree-sitter package available for {lang_name}")
                    return None

                # Wrap the raw language pointer in a Language object
                # tree-sitter 0.25.x: Language(ptr) - just needs the pointer
                if lang_ptr is not None:
                    ts_language = Language(lang_ptr)
                    if hasattr(ts_language, "abi_version"):
                        abi = ts_language.abi_version
                    else:
                        abi = ts_language.version
                    logger.debug(
                        f"Successfully loaded {lang_name} grammar (abi_version={abi})"
                    )
                else:
                    return None

            except ImportError as e:
                logger.warning(
                    f"Tree-Sitter grammar not installed for {language.value}: {e}"
                )
                return None
            except Exception as e:
                logger.warning(f"Failed to load grammar for {language.value}: {e}")
                return None

            # Cache and return
            if ts_language:
                self._language_cache[cache_key] = ts_language

            return ts_language

        except Exception as e:
            logger.error(
                f"Failed to load Tree-Sitter grammar for {language.value}: {e}"
            )
            return None

    def get_ast_root(self, parsing_result: ParsingResult) -> Optional[Node]:
        if not parsing_result.success:
            return None
        return parsing_result.metadata.get("ast_root")

    def clear_caches(self) -> None:
        self._language_cache.clear()
        self._parser_cache.clear()
        logger.info("Tree-Sitter caches cleared")
