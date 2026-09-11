"""
Tree-sitter adapter for TraceKite.

Wraps the TreeSitterParser/Extractor so it satisfies the BaseParser interface and
produces ParseResult objects that the ingestion pipeline already understands.
"""

import logging
import os
import re
from typing import Optional

from tracekite.parsers.base import (
    BaseParser,
    ParseResult,
    ParsedEntity,
    ParsedImport,
    ParsedApiEndpoint,
    ParsedMethodCall,
)
from tracekite.parsers.tree_sitter.core.models import (
    LanguageType,
    SymbolInfo,
    get_language_by_extension,
)
from tracekite.parsers.tree_sitter.core.parser import TreeSitterParser
from tracekite.parsers.tree_sitter.core.extractor import TreeSitterExtractor

logger = logging.getLogger(__name__)

# Map TraceKite language strings to LanguageType for callers that
# already know the language.
_LANGUAGE_NAME_MAP = {
    "java": LanguageType.JAVA,
    "kotlin": LanguageType.KOTLIN,
    "python": LanguageType.PYTHON,
    "javascript": LanguageType.JAVASCRIPT,
    "typescript": LanguageType.TYPESCRIPT,
    "go": LanguageType.GO,
    "rust": LanguageType.RUST,
    "c": LanguageType.C,
    "c++": LanguageType.CPP,
    "c#": LanguageType.CSHARP,
    "ruby": LanguageType.RUBY,
    "php": LanguageType.PHP,
    "scala": LanguageType.SCALA,
}


class TreeSitterSourceParser(BaseParser):
    def __init__(self):
        self._parser = TreeSitterParser()
        self._extractor = TreeSitterExtractor()

    @property
    def supported_extensions(self) -> list[str]:
        return list(_get_all_source_extensions())

    def parse(self, file_path: str, content: str) -> ParseResult:
        try:
            language = _detect_language(file_path)
        except ValueError as e:
            logger.debug("Tree-sitter unsupported file: %s (%s)", file_path, e)
            return ParseResult(errors=[str(e)])

        ts_result = self._parser.parse_content(content, file_path, language)
        if not ts_result.success:
            return ParseResult(errors=[ts_result.error_message or "parse failed"])

        root_node = ts_result.metadata.get("ast_root")
        ts_language = self._parser._get_language(language, file_path)

        symbols: list[SymbolInfo] = []
        method_calls: list[ParsedMethodCall] = []
        symbol_refs: list[dict] = []

        if root_node is not None and ts_language is not None:
            try:
                symbols = self._extractor.extract_symbols(
                    root_node, ts_language, language, file_path
                )
                raw_calls = self._extractor.extract_method_calls(
                    root_node, ts_language, language, file_path, content
                )
                method_calls = [_convert_method_call(c) for c in raw_calls]
                symbol_refs = self._extractor.extract_symbol_references(
                    root_node, ts_language, language, file_path, symbols
                )
            except Exception as e:
                logger.warning("Tree-sitter extraction failed for %s: %s", file_path, e)

        entities = _entities_with_annotations(symbols)
        imports = _extract_imports(file_path, content, language)
        api_endpoints = _extract_api_endpoints(symbols, method_calls, language)

        return ParseResult(
            entities=entities,
            imports=imports,
            api_endpoints=api_endpoints,
            method_calls=method_calls,
            symbol_references=symbol_refs,
            errors=[],
        )


def _detect_language(file_path: str) -> LanguageType:
    ext = os.path.splitext(file_path)[1].lower()
    return get_language_by_extension(ext)


def _get_all_source_extensions() -> set[str]:
    from tracekite.parsers.tree_sitter.core.models import LANGUAGE_METADATA

    extensions: set[str] = set()
    for metadata in LANGUAGE_METADATA.values():
        if metadata.get("has_ast_parser"):
            extensions.update(metadata["extensions"])
    return extensions


def _is_code_symbol(symbol: SymbolInfo) -> bool:
    return symbol.symbol_type in {
        "class",
        "interface",
        "method",
        "function",
        "procedure",
        "object",
    }


def _entities_with_annotations(symbols: list[SymbolInfo]) -> list[ParsedEntity]:
    """Attach annotation symbols (full text incl. arguments) to the code symbol
    they precede — @KafkaListener(topics=…) was parsed and thrown away before."""
    code = sorted((s for s in symbols if _is_code_symbol(s)), key=lambda s: s.line_number)
    attached: dict[int, list[str]] = {id(s): [] for s in code}
    for ann in (s for s in symbols if s.symbol_type == "annotation"):
        for sym in code:
            if ann.end_line <= sym.line_number and sym.line_number - ann.end_line <= 5:
                attached[id(sym)].append(ann.signature or f"@{ann.name}")
                break
    return [_convert_symbol(s, attached[id(s)]) for s in code]


def _convert_symbol(symbol: SymbolInfo, annotations: list[str] | None = None) -> ParsedEntity:
    entity_type = symbol.symbol_type
    if entity_type == "procedure":
        entity_type = "method"
    if entity_type == "object":
        entity_type = "class"

    metadata: dict = {
        "parent_class": symbol.parent_class,
        "visibility": symbol.visibility,
        "return_type": symbol.return_type,
        "parameters": symbol.parameters,
    }
    if symbol.documentation:
        metadata["documentation"] = symbol.documentation

    return ParsedEntity(
        name=symbol.name,
        type=entity_type,
        start_line=symbol.line_number,
        end_line=symbol.end_line,
        signature=symbol.signature or "",
        modifiers=[],
        annotations=list(annotations or []),
        docstring=symbol.documentation or "",
        is_public=symbol.visibility in (None, "public"),
        metadata=metadata,
    )


def _convert_method_call(call) -> ParsedMethodCall:
    return ParsedMethodCall(
        caller_name=call.caller_method or "",
        callee_name=call.called_method or "",
        file_path=call.file_path,
        line=call.line_number,
        call_type=call.call_type or "direct",
        context=call.context or "",
        confidence="high",
    )


def _extract_imports(file_path: str, content: str, language: LanguageType) -> list[ParsedImport]:
    imports: list[ParsedImport] = []
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if language in (LanguageType.JAVA, LanguageType.KOTLIN):
            for match in re.finditer(r"^import\s+([\w.]+(?:\.\*)?)", content, re.MULTILINE):
                imports.append(ParsedImport(module=match.group(1), line=_line_at(content, match.start())))

        elif language == LanguageType.PYTHON:
            # `import x, y` and `from x import y, z`
            for match in re.finditer(r"^import\s+(.+)$", content, re.MULTILINE):
                for name in _split_import_list(match.group(1)):
                    imports.append(ParsedImport(module=name, line=_line_at(content, match.start())))
            for match in re.finditer(r"^from\s+([\w.]+)\s+import\s+(.+)$", content, re.MULTILINE):
                module = match.group(1)
                is_wildcard = "*" in match.group(2)
                imports.append(ParsedImport(module=module, is_wildcard=is_wildcard, line=_line_at(content, match.start())))

        elif language in (LanguageType.JAVASCRIPT, LanguageType.TYPESCRIPT):
            # ES6 import / export from
            for match in re.finditer(
                r"import\s+(?:[\w*\s{},]*\s+from\s+)?['\"]([^'\"]+)['\"]",
                content,
            ):
                imports.append(ParsedImport(module=match.group(1), line=_line_at(content, match.start())))
            # CommonJS require
            for match in re.finditer(
                r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
                content,
            ):
                imports.append(ParsedImport(module=match.group(1), line=_line_at(content, match.start())))

        elif language == LanguageType.GO:
            for match in re.finditer(r'import\s+\(\s*([^)]+)\)', content, re.DOTALL):
                for line in match.group(1).splitlines():
                    m = re.search(r'["\']([^"\']+)["\']', line)
                    if m:
                        imports.append(ParsedImport(module=m.group(1), line=_line_at(content, match.start())))
            for match in re.finditer(r'import\s+["\']([^"\']+)["\']', content):
                imports.append(ParsedImport(module=match.group(1), line=_line_at(content, match.start())))

    except Exception as e:
        logger.debug("Import extraction failed for %s: %s", file_path, e)

    return imports


def _split_import_list(text: str) -> list[str]:
    # Strip "as" aliases for Python imports.
    names: list[str] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        part = re.sub(r"\s+as\s+\w+", "", part)
        names.append(part)
    return names


def _line_at(content: str, pos: int) -> int:
    return content[:pos].count("\n") + 1


def _extract_api_endpoints(
    symbols: list[SymbolInfo],
    method_calls: list[ParsedMethodCall],
    language: LanguageType,
) -> list[ParsedApiEndpoint]:
    """Extract API endpoint definitions from annotations/decorators and route calls."""
    endpoints: list[ParsedApiEndpoint] = []

    # Collect annotation symbols and attach them to the nearest method below them.
    annotation_symbols = [s for s in symbols if s.symbol_type == "annotation"]
    annotation_symbols.sort(key=lambda s: s.line_number)

    # For Spring controllers, accumulate class-level @RequestMapping base paths.
    base_paths: dict[str, str] = {}
    if language in (LanguageType.JAVA, LanguageType.KOTLIN,
                    LanguageType.CSHARP, LanguageType.SCALA):
        for ann in annotation_symbols:
            if not ann.parent_class:
                path = _parse_controller_route(ann.signature or ann.name)
                if path:
                    # The annotation belongs to a class if the next symbol is a class.
                    next_sym = _find_next_symbol(symbols, ann.line_number)
                    if next_sym and next_sym.symbol_type == "class":
                        base_paths[next_sym.name] = path

    for ann in annotation_symbols:
        handler = _find_handler_below(symbols, ann.line_number)
        if handler is None:
            continue

        # Skip class-level annotations (e.g. Spring @RequestMapping on a class)
        # — except JSR-356, where the CLASS is the endpoint: @ServerEndpoint
        # has no method-level half to wait for.
        next_sym = _find_next_symbol(symbols, ann.line_number)
        if next_sym and next_sym.symbol_type in ("class", "interface"):
            endpoint = _parse_endpoint_annotation(
                ann.signature or ann.name, language)
            if endpoint and endpoint.get("framework") == "websocket":
                endpoints.append(ParsedApiEndpoint(
                    method=endpoint["method"], path=endpoint["path"],
                    handler_name=next_sym.name,
                    controller_name=next_sym.name,
                    line=next_sym.line_number, framework="websocket"))
            continue

        endpoint = _parse_endpoint_annotation(ann.signature or ann.name, language)
        if endpoint is None:
            continue

        path = endpoint["path"]
        if language in (LanguageType.JAVA, LanguageType.KOTLIN,
                        LanguageType.CSHARP, LanguageType.SCALA):
            base = base_paths.get(handler.parent_class or "", "")
            path = _join_paths(base, path)

        # An annotation that declared no path is only an endpoint if a
        # class-level mapping supplied one. Emitting a bare "/" whenever the
        # class mapping failed to resolve would put a phantom root endpoint in
        # every such repo, and `GET /` collides with everything.
        if not endpoint.get("path_declared", True) and not path:
            continue

        controller = handler.parent_class or ""
        endpoints.append(
            ParsedApiEndpoint(
                method=endpoint["method"],
                path=path,
                handler_name=handler.name,
                controller_name=controller,
                line=handler.line_number,
                # The annotation may know better than the language default:
                # @ServerEndpoint is a websocket wherever it appears.
                framework=endpoint.get(
                    "framework", _framework_for_language(language)),
            )
        )

    # TypeScript/Express and Python/Flask/FastAPI route calls are already in
    # method_calls. Convert obvious ones.
    endpoints.extend(_extract_route_calls(method_calls, language))

    return endpoints


def _find_handler_below(symbols: list[SymbolInfo], line: int) -> Optional[SymbolInfo]:
    candidates = [
        s
        for s in symbols
        if s.symbol_type in ("method", "function", "procedure") and s.line_number >= line
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda s: s.line_number)


def _find_next_symbol(symbols: list[SymbolInfo], line: int) -> Optional[SymbolInfo]:
    candidates = [s for s in symbols if s.line_number >= line and s.symbol_type != "annotation"]
    if not candidates:
        return None
    return min(candidates, key=lambda s: s.line_number)


def _parse_controller_route(text: str) -> Optional[str]:
    """Class-level base path: Spring @RequestMapping or ASP.NET [Route]."""
    m = re.search(
        r"@?(?:RequestMapping|Route)\s*\(\s*(?:value\s*=\s*|template\s*[:=]\s*)?"
        r"['\"]([^'\"]+)['\"]", text)
    if not m:
        return None
    path = m.group(1)
    # [Route("api/[controller]")] is resolved by ASP.NET at runtime from the
    # class name; leaving the token in would produce an unjoinable template.
    return None if "[controller]" in path.lower() else path


def _parse_request_mapping_path(text: str) -> Optional[str]:
    """Extract path from @RequestMapping(...) used on a class."""
    m = re.search(r"@RequestMapping\s*\(\s*(?:value\s*=\s*)?['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else None


def _join_paths(base: str, sub: str) -> str:
    if not base:
        return sub
    if not sub:
        return base
    if sub.startswith("http") or sub.startswith("www"):
        return sub
    return re.sub(r"/+", "/", base.rstrip("/") + "/" + sub.lstrip("/"))


def _parse_endpoint_annotation(text: str, language: LanguageType) -> Optional[dict]:
    text = text.strip()

    if language in (LanguageType.JAVA, LanguageType.KOTLIN,
                    LanguageType.SCALA):
        m = re.search(
            r"@ServerEndpoint\s*\(\s*(?:value\s*=\s*)?['\"]([^'\"]+)['\"]",
            text)
        if m:
            return {"method": "GET", "path": m.group(1),
                    "framework": "websocket"}
        # @GetMapping("/path") or @RequestMapping(value="/path", method=GET)
        mapping = {
            "GetMapping": "GET",
            "PostMapping": "POST",
            "PutMapping": "PUT",
            "DeleteMapping": "DELETE",
            "PatchMapping": "PATCH",
            "RequestMapping": "GET",
        }
        for ann, method in mapping.items():
            # The annotation may carry no path at all — `@PostMapping` on a
            # class already mapped to `/owners` is the idiomatic way to write
            # `POST /owners`. Requiring a quoted path lost every such endpoint,
            # so the path is matched separately and defaults to "" (which
            # _join_paths resolves against the class-level base).
            #
            # The `@` is optional because the extractor hands over bare names
            # ("PostMapping") for argument-less annotations and decorated text
            # ('@GetMapping("/x")') for the rest.
            if not re.search(rf"@?\b{ann}\b", text):
                continue
            # Scala Spring wraps annotation arrays: @GetMapping(Array("/x")).
            # Same annotation, same meaning; without this the whole language
            # silently extracted nothing — caught by the coverage pin.
            path_match = re.search(
                rf"@?{ann}\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?"
                rf"(?:Array\s*\(\s*)?"
                rf"\{{?\s*['\"]([^'\"]+)['\"]", text)
            path = path_match.group(1) if path_match else ""
            if ann == "RequestMapping":
                method_match = re.search(
                    r"method\s*=\s*\{?\s*(?:RequestMethod\.)?(\w+)", text)
                if method_match:
                    method = method_match.group(1).upper()
            return {"method": method, "path": path,
                    "path_declared": bool(path_match)}

    elif language == LanguageType.CSHARP:
        # ASP.NET Core: [HttpGet("{id}")], [HttpPost], [HttpDelete("{id}")].
        # The extractor hands over attribute text without the brackets.
        m = re.search(r"@?\b(?:Http)(Get|Post|Put|Delete|Patch|Head|Options)\b",
                      text, re.IGNORECASE)
        if m:
            path_match = re.search(
                r"\(\s*(?:template\s*[:=]\s*)?['\"]([^'\"]+)['\"]", text)
            return {"method": m.group(1).upper(),
                    "path": path_match.group(1) if path_match else "",
                    "path_declared": bool(path_match)}

    elif language == LanguageType.PYTHON:
        m = re.search(r"@(\w+)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", text)
        if m:
            return {"method": m.group(2).upper(), "path": m.group(3)}
        # A websocket route upgrades over GET; the channel rides the
        # framework field so the claim downstream can say so.
        m = re.search(r"@(\w+)\.websocket\s*\(\s*['\"]([^'\"]+)['\"]", text)
        if m:
            return {"method": "GET", "path": m.group(2),
                    "framework": "websocket"}
        # Router decorator with no literal path, e.g. @app.post()
        m = re.search(r"@(\w+)\.(get|post|put|delete|patch)\s*\(", text)
        if m:
            return {"method": m.group(2).upper(), "path": "",
                    "path_declared": False}

    elif language in (LanguageType.JAVASCRIPT, LanguageType.TYPESCRIPT):
        m = re.search(r"@(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
        if m:
            return {"method": m.group(1).upper(), "path": m.group(2)}
        # NestJS `@Get()` inherits the controller's `@Controller('owners')`.
        m = re.search(r"@(get|post|put|delete|patch)\s*\(\s*\)", text, re.IGNORECASE)
        if m:
            return {"method": m.group(1).upper(), "path": "",
                    "path_declared": False}

    elif language == LanguageType.RUST:
        # Actix/Rocket attribute macros: #[get("/path")]
        m = re.search(
            r"#\s*\[\s*(?:\w+::)?(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
            text,
            re.IGNORECASE,
        )
        if m:
            return {"method": m.group(1).upper(), "path": m.group(2)}
        # Extractor stores only the inner attribute text, e.g. get("/path")
        m = re.search(
            r"^(?:\w+::)?(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
            text,
            re.IGNORECASE,
        )
        if m:
            return {"method": m.group(1).upper(), "path": m.group(2)}

    return None


def _extract_route_calls(method_calls: list[ParsedMethodCall], language: LanguageType) -> list[ParsedApiEndpoint]:
    endpoints: list[ParsedApiEndpoint] = []
    framework = _framework_for_language(language)

    for call in method_calls:
        context = call.context or ""
        if language == LanguageType.CSHARP:
            # Minimal APIs: app.MapGet("/owners", handler)
            m = re.search(
                r"\.Map(Get|Post|Put|Delete|Patch)\s*\(\s*['\"]([^'\"]+)['\"]",
                context)
            if m:
                endpoints.append(
                    ParsedApiEndpoint(
                        method=m.group(1).upper(),
                        path=m.group(2),
                        handler_name=call.caller_name or "",
                        line=call.line,
                        framework=framework,
                    )
                )
        if language in (LanguageType.JAVASCRIPT, LanguageType.TYPESCRIPT):
            # app.get('/path', ...) or router.post('/path', ...)
            m = re.search(
                r"(?:app|router|server)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
                context,
                re.IGNORECASE,
            )
            if m:
                endpoints.append(
                    ParsedApiEndpoint(
                        method=m.group(1).upper(),
                        path=m.group(2),
                        handler_name=call.caller_name or "",
                        line=call.line,
                        framework=framework,
                    )
                )
        elif language == LanguageType.PYTHON:
            # Flask: @app.route('/path', methods=['GET'])
            m = re.search(
                r"@(\w+)\.route\s*\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*methods\s*=\s*\[(.*?)\])?",
                context,
            )
            if m:
                methods = m.group(3) or "GET"
                method = re.search(r"['\"](\w+)['\"]", methods)
                method_str = method.group(1).upper() if method else "GET"
                endpoints.append(
                    ParsedApiEndpoint(
                        method=method_str,
                        path=m.group(2),
                        handler_name=call.caller_name or "",
                        line=call.line,
                        framework=framework,
                    )
                )
                continue
            m = re.search(
                r"(\w+)\.websocket\s*\(\s*['\"](/[^'\"]*)['\"]", context)
            if m and m.group(1).lower() not in _PY_HTTP_CLIENTS:
                endpoints.append(ParsedApiEndpoint(
                    method="GET", path=m.group(2),
                    handler_name=call.caller_name or "", line=call.line,
                    framework="websocket"))
                continue
            # FastAPI: @app.get('/path')
            #
            # The path MUST start with "/". Matching any quoted first argument
            # made `dict.get("task_id")` -- the most common call in Python --
            # a GET endpoint, and manufactured 361 contracts like
            # `GET /caller_id` on the demo corpus.
            #
            # The `@` cannot be required here even though the decorator is how
            # routes are really registered: `context` is the call node's own
            # text, so the decorator sits in a parent node and is never
            # visible. The leading slash is the discriminator that IS present.
            m = re.search(
                r"(\w+)\.(get|post|put|delete|patch)\s*\(\s*['\"](/[^'\"]*)['\"]",
                context,
            )
            # A slash-leading path is still a client call when the receiver is
            # an HTTP client, and recording that as a PROVIDER contract points
            # the edge the wrong way -- worse than dropping it.
            if m and m.group(1).lower() in _PY_HTTP_CLIENTS:
                m = None
            if m:
                endpoints.append(
                    ParsedApiEndpoint(
                        method=m.group(2).upper(),
                        path=m.group(3),
                        handler_name=call.caller_name or "",
                        line=call.line,
                        framework=framework,
                    )
                )

        elif language == LanguageType.GO:
            # Standard net/http: http.HandleFunc("/path", handler)
            m = re.search(
                r"(?:http|mux)\s*\.\s*Handle(?:Func)?\s*\(\s*['\"]([^'\"]+)['\"]",
                context,
                re.IGNORECASE,
            )
            if m:
                endpoints.append(
                    ParsedApiEndpoint(
                        method="GET",
                        path=m.group(1),
                        handler_name=call.caller_name or "",
                        line=call.line,
                        framework=framework,
                    )
                )
                continue
            # Gin/Echo/Fiber: r.GET("/path", handler). Same two gates the
            # Python branch above earned the hard way: the path MUST start
            # with "/" — `w.Header.Get("Content-Type")`,
            # `field.Tag.Get("protobuf")` and `url.Values.Get("key")` all
            # match the verb pattern and fabricated endpoints on the
            # reference corpus — and a trailing comma requires the handler
            # argument, which is what distinguishes a route registration
            # from a single-argument client call like `client.Get("/x")`.
            m = re.search(
                r"\.(GET|POST|PUT|DELETE|PATCH)\s*\(\s*['\"](/[^'\"]*)['\"]\s*,",
                context,
                re.IGNORECASE,
            )
            if m:
                endpoints.append(
                    ParsedApiEndpoint(
                        method=m.group(1).upper(),
                        path=m.group(2),
                        handler_name=call.caller_name or "",
                        line=call.line,
                        framework=framework,
                    )
                )

        elif language == LanguageType.RUST:
            # Axum: .route("/path", routing::get(handler)) or .route("/path", get(handler))
            m = re.search(
                r"\.route\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(?:\w+::)?(get|post|put|delete|patch)\b",
                context,
                re.IGNORECASE,
            )
            if m:
                endpoints.append(
                    ParsedApiEndpoint(
                        method=m.group(2).upper(),
                        path=m.group(1),
                        handler_name=call.caller_name or "",
                        line=call.line,
                        framework=framework,
                    )
                )

    return endpoints


# Receivers whose `.get("/path")` is an outbound HTTP call, not a route
# registration. Recording one as a provider contract inverts the direction of
# the edge, which is worse than missing it.
_PY_HTTP_CLIENTS = frozenset({
    "requests", "session", "s", "client", "http", "httpx", "aiohttp",
    "urllib3", "conn", "connection", "api", "rest",
})


def _framework_for_language(language: LanguageType) -> str:
    return {
        LanguageType.JAVA: "spring",
        LanguageType.KOTLIN: "spring",
        LanguageType.PYTHON: "fastapi",
        LanguageType.JAVASCRIPT: "express",
        LanguageType.TYPESCRIPT: "express",
        LanguageType.GO: "gin",
        LanguageType.RUST: "actix",
        LanguageType.CSHARP: "aspnetcore",
    }.get(language, "unknown")
