"""HTTP routes from Spring WebFlux functional DSL and Ktor.

The WebFlux RouterFunction DSL — not annotations — in Java and
Kotlin: ``RouterFunctions.route(GET("/x"), h)``, chained ``.andRoute(...)``,
the ``route().GET(...).build()`` builder, ``nest(path("/v1"), ...)`` prefixes,
and the Kotlin ``router { }`` / ``coRouter { }`` DSL with ``"/v1".nest { }``.
The Ktor slice: ``routing { get("/x") { } }`` with
``route("/v1") { }`` prefix nesting, including pathless verbs (``get { }``)
that inherit the enclosing route path.

Precision-first: only string-literal paths (no ``$templates``, no concat).
Prefix nesting is resolved by paren/brace-depth walks over a string-masked
view of the file, so braces inside path templates like ``"/pets/{id}"``
cannot corrupt span boundaries.
"""

import re
from dataclasses import dataclass, field

# Gate extraction on framework evidence so a bare `GET("/x")` helper in an
# unrelated file cannot masquerade as a route table.
_WF_MARKER = re.compile(
    r"RouterFunctions?|RequestPredicates|coRouter|web\.reactive\.function"
    r"|\brouter\s*\{")
_KTOR_MARKER = re.compile(r"io\.ktor|\brouting\s*\{|\bfun\s+Route\.")

# WebFlux predicates/builder verbs: GET("/x") bare, RequestPredicates.GET,
# or builder .GET — the lookahead requires the literal to be a whole argument,
# which is what skips "/a" + id concatenations.
_WF_VERB = re.compile(
    r'(?<![\w$])(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*"([^"]*)"'
    r"(?=\s*[,)])")
_WF_NEST = re.compile(r"\b(?:andNest|nest)\s*\(")
_WF_PATH_PRED = re.compile(r'\bpath\s*\(\s*"([^"]*)"')
_KT_NEST = re.compile(r'"([^"]*)"\s*\.\s*nest\s*\{')
_WF_HANDLER_INLINE = re.compile(r"\s*,\s*([\w:.]+)\s*\)")  # GET("/x", h::f)
_WF_HANDLER_AFTER = re.compile(r"\s*\)\s*,\s*([\w:.]+)")   # route(GET("/x"), h)

_KTOR_ROUTING = re.compile(r"(?<!\w)routing\s*\{")
_KTOR_ROUTE = re.compile(r'(?<!\w)route\s*\(\s*"([^"]*)"[^)]*\)\s*\{')
# `(?<![\w.])` keeps `client.get("https://...")` (Ktor HTTP client) and
# `map.get { }` out; server verbs are called bare inside routing blocks.
_KTOR_VERB_PATH = re.compile(
    r'(?<![\w.])(get|post|put|delete|patch|head|options)\s*\(\s*"([^"]*)"'
    r"[^)]*\)\s*\{")
_KTOR_VERB_BARE = re.compile(
    r"(?<![\w.])(get|post|put|delete|patch|head|options)\s*\{")

_OPT_PARAM = re.compile(r"\{(\w+)\?\}")   # Ktor {id?} -> {id}
_DYNAMIC = re.compile(r"[$%]")            # Kotlin templates / format markers


@dataclass
class JvmRoute:
    """One statically-declared HTTP route registration."""
    method: str          # uppercase verb; "ANY" reserved for unconstrained
    path: str            # brace-template path with nest/route prefix applied
    framework: str       # webflux-fn | ktor
    line: int
    handler_name: str = ""
    attrs: dict = field(default_factory=dict)


@dataclass
class _Span:
    """A nest(...) argument span or route("/x") { } body with its prefix."""
    start: int
    end: int
    prefix: str


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def _scan(content: str) -> tuple[str, str]:
    """Two views: `clean` blanks comments; `mask` also blanks string bodies.

    Handles Kotlin/Java escapes, char literals, and triple-quoted raw
    strings. Newlines survive in both views so positions keep line numbers.
    """
    clean, mask = list(content), list(content)
    i, n = 0, len(content)
    while i < n:
        char = content[i]
        if content.startswith('"""', i):
            j = content.find('"""', i + 3)
            end = n if j < 0 else j + 3
            for k in range(i + 3, j if j >= 0 else n):
                if content[k] != "\n":
                    mask[k] = " "
            i = end
        elif char in ('"', "'"):
            j = i + 1
            while j < n and content[j] != char:
                if content[j] == "\\":
                    j += 1
                j += 1
            for k in range(i + 1, min(j, n)):
                if content[k] != "\n":
                    mask[k] = " "
            i = j + 1
        elif char == "/" and content.startswith("//", i):
            j = content.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                clean[k] = mask[k] = " "
            i = j
        elif char == "/" and content.startswith("/*", i):
            j = content.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, min(j, n)):
                if content[k] != "\n":
                    clean[k] = mask[k] = " "
            i = j
        else:
            i += 1
    return "".join(clean), "".join(mask)


def _close_of(mask: str, open_pos: int) -> int:
    """Index of the delimiter closing the one at `open_pos` (mask view)."""
    open_char = mask[open_pos]
    close_char = {"(": ")", "{": "}"}[open_char]
    depth = 0
    for i in range(open_pos, len(mask)):
        if mask[i] == open_char:
            depth += 1
        elif mask[i] == close_char:
            depth -= 1
            if depth == 0:
                return i
    return len(mask)


def _first_top_level_comma(mask: str, start: int, end: int) -> int:
    """Boundary of a call's first argument (predicate arg of nest)."""
    depth = 0
    for i in range(start, end):
        char = mask[i]
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        elif char == "," and depth == 0:
            return i
    return end


def _join(prefix: str, path: str) -> str:
    prefix, path = (prefix or "").strip(), (path or "").strip()
    combined = prefix.rstrip("/") + "/" + path.lstrip("/") if prefix else path
    if not combined.startswith("/"):
        combined = "/" + combined
    if len(combined) > 1 and combined.endswith("/"):
        combined = combined.rstrip("/")
    return combined or "/"


def _compose(raw: list[tuple[int, int, str]]) -> list[_Span]:
    """Full prefixes: each span inherits from its innermost enclosing span."""
    spans: list[_Span] = []
    for start, end, segment in sorted(raw):
        base = ""
        for span in spans:  # last enclosing span found is the innermost
            if span.start < start and span.end >= end:
                base = span.prefix
        spans.append(_Span(start, end, _join(base, segment)))
    return spans


def _innermost(spans: list[_Span], pos: int):
    best = None
    for span in spans:
        if span.start <= pos < span.end and (
                best is None or span.start > best.start):
            best = span
    return best


def _wf_handler(clean: str, pos: int) -> str:
    """Best-effort handler ref right after the path literal."""
    if match := _WF_HANDLER_INLINE.match(clean, pos):
        return match.group(1)
    if match := _WF_HANDLER_AFTER.match(clean, pos):
        return match.group(1)
    return ""


def extract_jvm_routes(file_path: str, content: str) -> list[JvmRoute]:
    """All statically-declared WebFlux-functional/Ktor routes in one file."""
    lower = file_path.lower()
    if not lower.endswith((".java", ".kt", ".kts")) or not content:
        return []
    clean, mask = _scan(content)
    routes: list[JvmRoute] = []
    if _WF_MARKER.search(clean):
        _emit_webflux(clean, mask, routes)
    if lower.endswith((".kt", ".kts")) and _KTOR_MARKER.search(clean):
        _emit_ktor(clean, mask, routes)
    routes.sort(key=lambda r: r.line)
    return routes


def _emit_webflux(clean: str, mask: str, routes: list[JvmRoute]) -> None:
    raw: list[tuple[int, int, str]] = []
    for match in _WF_NEST.finditer(clean):  # nest(path("/v1"), ...)
        open_paren = match.end() - 1
        end = _close_of(mask, open_paren)
        comma = _first_top_level_comma(mask, open_paren + 1, end)
        predicate = _WF_PATH_PRED.search(clean, open_paren, comma)
        raw.append((match.start(), end, predicate.group(1) if predicate else ""))
    for match in _KT_NEST.finditer(clean):  # "/v1".nest { ... }
        open_brace = match.end() - 1
        raw.append((match.start(), _close_of(mask, open_brace), match.group(1)))
    spans = _compose(raw)

    for match in _WF_VERB.finditer(clean):
        path = match.group(2)
        if not path.startswith("/") or _DYNAMIC.search(path):
            continue
        span = _innermost(spans, match.start())
        routes.append(JvmRoute(
            method=match.group(1),
            path=_join(span.prefix if span else "", path),
            framework="webflux-fn", line=_line_of(clean, match.start()),
            handler_name=_wf_handler(clean, match.end())))


def _emit_ktor(clean: str, mask: str, routes: list[JvmRoute]) -> None:
    raw: list[tuple[int, int, str]] = []
    for match in _KTOR_ROUTING.finditer(clean):
        open_brace = match.end() - 1
        raw.append((open_brace, _close_of(mask, open_brace), ""))
    for match in _KTOR_ROUTE.finditer(clean):
        open_brace = match.end() - 1
        raw.append((open_brace, _close_of(mask, open_brace), match.group(1)))
    spans = _compose(raw)

    for match in _KTOR_VERB_PATH.finditer(clean):
        path = match.group(2)
        if _DYNAMIC.search(path):
            continue
        if path and not path.startswith(("/", "{")):
            continue  # absolute-URL client calls, not server routes
        span = _innermost(spans, match.start())
        routes.append(JvmRoute(
            method=match.group(1).upper(),
            path=_OPT_PARAM.sub(r"{\1}",
                                _join(span.prefix if span else "", path)),
            framework="ktor", line=_line_of(clean, match.start())))

    for match in _KTOR_VERB_BARE.finditer(clean):
        span = _innermost(spans, match.start())
        if span is None:
            continue
        # Direct children only: a `get { }` nested in some other lambda
        # (authenticate { }, webSocket { }...) has an unknowable path shape,
        # so it is declined rather than guessed.
        depth = (mask.count("{", span.start + 1, match.start())
                 - mask.count("}", span.start + 1, match.start()))
        if depth != 0:
            continue
        routes.append(JvmRoute(
            method=match.group(1).upper(),
            path=_OPT_PARAM.sub(r"{\1}", span.prefix or "/"),
            framework="ktor", line=_line_of(clean, match.start())))
