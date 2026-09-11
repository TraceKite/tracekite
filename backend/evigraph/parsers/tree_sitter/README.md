# Tree-sitter parser package

This package contains a self-contained, synchronous Tree-sitter parser and
extractor adapted from an earlier internal parser.

## Adaptations

- Removed the shared-library dependencies; logging uses the standard library
  `logging` module.
- `TreeSitterParser.parse_content` and all `TreeSitterExtractor.extract_*`
  methods are synchronous so they can be used from the existing synchronous
  ingestion pipeline.
- Models (`LanguageType`, `SymbolInfo`, `MethodCall`, `EndpointMapping`,
  `CallGraph`, `CallGraphNode`, `ParsingResult`, `SQLQuery`, etc.) are combined
  in `core/models.py`.
- Tree-sitter 0.25.x API usage is preserved (`Parser(Language)`,
  `Query(language, query_text)`, `QueryCursor.matches(root_node)`).
- `Language` and `Parser` objects are cached per language for performance, but
  `TreeSitterParser` / `TreeSitterExtractor` are otherwise stateless enough to
  be instantiated per file if needed.

## Usage

```python
from evigraph.parsers.tree_sitter.core.models import LanguageType
from evigraph.parsers.tree_sitter.core.parser import TreeSitterParser
from evigraph.parsers.tree_sitter.core.extractor import TreeSitterExtractor

parser = TreeSitterParser()
result = parser.parse_content(content, file_path, LanguageType.JAVA)
root = result.metadata.get("ast_root")

extractor = TreeSitterExtractor()
symbols = extractor.extract_symbols(root, language_obj, LanguageType.JAVA, file_path)
calls = extractor.extract_method_calls(root, language_obj, LanguageType.JAVA, file_path, content)
```
