"""HTTP server route declarations in Go source.

Covers the six routers that dominate Go services: net/http ServeMux
(including Go 1.22 ``"METHOD /path"`` patterns), echo, chi, fiber,
gorilla/mux, and gin. The downstream join key is (method, path template), so
extraction is precision-first: only string-literal paths are taken — a
variable, ``fmt.Sprintf``, or string concatenation is skipped, never guessed.

Framework identity comes from imports and constructor calls, because the call
shapes collide: echo and gin both write ``r.GET(...)``, chi and fiber both
write ``r.Get(...)``. Group/subrouter prefixes are tracked per variable
(``g := e.Group("/v1")``, ``s := r.PathPrefix("/v1").Subrouter()``), and
chi's closure-style ``Route("/v1", func(r chi.Router) {...})`` nesting is
resolved with a brace-depth walk over a string-masked view so braces inside
path templates cannot corrupt spans.

Param syntax is normalized to brace templates: ``:id`` (echo/gin/fiber) ->
``{id}``; chi/gorilla ``{id}`` stays and constrained ``{id:[0-9]+}`` ->
``{id}``; Go 1.22 ``{id}`` stays.
"""

import re
from dataclasses import dataclass, field

_GO122_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS",
                  "CONNECT", "TRACE"}

# Import path prefix -> framework.
_FRAMEWORK_IMPORTS = (
    ("github.com/labstack/echo", "echo"),
    ("github.com/gin-gonic/gin", "gin"),
    ("github.com/gofiber/fiber", "fiber"),
    ("github.com/go-chi/chi", "chi"),
    ("github.com/gorilla/mux", "gorilla"),
    ("net/http", "net/http"),
)
# Default package selectors, overridden by import aliases. Seeded even without
# imports so constructor calls in snippets still identify the framework.
_SELECTOR_DEFAULTS = {"echo": "echo", "gin": "gin", "fiber": "fiber",
                      "chi": "chi", "mux": "gorilla", "http": "net/http"}
# (framework, constructor func) pairs that yield a router variable.
_CTOR_FUNCS = {("echo", "New"), ("gin", "New"), ("gin", "Default"),
               ("fiber", "New"), ("chi", "NewRouter"), ("chi", "NewMux"),
               ("gorilla", "NewRouter"), ("net/http", "NewServeMux")}
# Typed-parameter/field package -> framework (`func routes(r chi.Router)`).
_TYPE_FRAMEWORKS = {"echo": "echo", "gin": "gin", "fiber": "fiber",
                    "chi": "chi", "mux": "gorilla", "http": "net/http"}

_IMPORT_BLOCK = re.compile(r"\bimport\s*\(([\s\S]*?)\)")
_IMPORT_SINGLE = re.compile(r'\bimport\s+(?:(\w+)\s+)?"([^"]+)"')
_IMPORT_SPEC = re.compile(r'^\s*(?:(\w+)\s+)?"([^"]+)"', re.MULTILINE)

_CONSTRUCTOR = re.compile(r"\b(\w+)\s*(?::=|=)\s*(\w+)\.(New\w*|Default)\s*\(")
_GROUP = re.compile(r'\b(\w+)\s*(?::=|=)\s*([\w.]+)\.Group\s*\(\s*"([^"]*)"')
_SUBROUTER = re.compile(
    r'\b(\w+)\s*(?::=|=)\s*([\w.]+)\.PathPrefix\s*\(\s*"([^"]*)"\s*\)'
    r"\s*\.\s*Subrouter\s*\(")
_TYPE_BINDING = re.compile(
    r"\b(\w+)\s+\*?(echo\.(?:Echo|Group)|gin\.(?:Engine|RouterGroup)"
    r"|fiber\.(?:App|Router)|chi\.(?:Router|Mux)|mux\.Router|http\.ServeMux)\b")

# Route calls. The trailing `",` requires a literal path immediately followed
# by the handler argument, which is what skips `fmt.Sprintf(...)`, variables,
# and `"/a" + suffix` concatenations without any extra logic.
_UPPER_VERB = re.compile(
    r'\b([\w.]+)\.(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|Any)'
    r'\s*\(\s*"([^"]*)"\s*,')
_CAP_VERB = re.compile(
    r'\b([\w.]+)\.(Get|Post|Put|Delete|Patch|Head|Options|All)'
    r'\s*\(\s*"(/[^"]*)"\s*,')
_HANDLE = re.compile(r'\b([\w.]+)\.(HandleFunc|Handle)\s*\(\s*"([^"]*)"\s*,')
_CHI_ROUTE = re.compile(
    r'\b([\w.]+)\.Route\s*\(\s*"([^"]*)"\s*,\s*'
    r"func\s*\(\s*(\w+)\s+chi\.Router\s*\)\s*\{")

_CHAIN_CALL = re.compile(r"\s*\.\s*(\w+)\s*\(([^()]*)\)")
_QUOTED = re.compile(r'"([^"]+)"')
_METHOD_CONST = re.compile(r"http\.Method(\w+)")
_HANDLER_AFTER = re.compile(r"\s*([A-Za-z_][\w.]*)\s*[,)]")

_COLON_PARAM = re.compile(r":(\w+)\??")           # echo/gin/fiber, fiber `:id?`
_BRACE_CONSTRAINT = re.compile(r"\{(\w+):[^{}]*\}")  # gorilla/chi {id:[0-9]+}
# A whole segment that is one constrained param; fullmatch tolerates nested
# braces in the regex part ({id:[0-9]{4}}) that the embedded form cannot.
_SEGMENT_CONSTRAINT = re.compile(r"\{(\w+):.*\}")


@dataclass
class GoRoute:
    """One statically-declared HTTP route registration."""
    method: str          # uppercase verb; "ANY" when unconstrained
    path: str            # brace-template path with group/subrouter prefix
    framework: str       # net/http | echo | chi | fiber | gorilla | gin
    line: int
    handler_name: str = ""
    attrs: dict = field(default_factory=dict)


@dataclass
class _ChiSpan:
    """One chi `Route("/v1", func(r chi.Router) {...})` closure body."""
    start: int
    end: int
    prefix: str          # composed across nested Route calls
    param: str           # the closure's router variable


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def _scan(content: str) -> tuple[str, str]:
    """Two views: `clean` blanks comments; `mask` also blanks string bodies.

    Regexes read paths from `clean`; brace/paren matching walks `mask` so a
    `{id}` inside a path literal cannot unbalance a span. Newlines survive in
    both so positions map to the same line numbers.
    """
    clean, mask = list(content), list(content)
    i, n = 0, len(content)
    while i < n:
        char = content[i]
        if char in ('"', "`", "'"):
            j = i + 1
            while j < n and content[j] != char:
                if content[j] == "\\" and char != "`":  # raw strings: no escapes
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


def _join(prefix: str, path: str) -> str:
    prefix, path = (prefix or "").strip(), (path or "").strip()
    combined = prefix.rstrip("/") + "/" + path.lstrip("/") if prefix else path
    if not combined.startswith("/"):
        combined = "/" + combined
    if len(combined) > 1 and combined.endswith("/"):
        combined = combined.rstrip("/")
    return combined or "/"


def _template(path: str, colon_style: bool) -> str:
    """Normalize params to brace templates (`:id` -> `{id}`)."""
    if colon_style:
        path = _COLON_PARAM.sub(r"{\1}", path)
    segments = []
    for segment in path.split("/"):
        whole = _SEGMENT_CONSTRAINT.fullmatch(segment)
        segments.append("{%s}" % whole.group(1) if whole
                        else _BRACE_CONSTRAINT.sub(r"{\1}", segment))
    return "/".join(segments)


def _handler_after(clean: str, pos: int) -> str:
    """Simple identifier/selector handler right after the path comma."""
    match = _HANDLER_AFTER.match(clean, pos)
    if match and match.group(1) != "func":
        return match.group(1)
    return ""


def _lookup(bindings: dict, name: str):
    return bindings.get(name) or bindings.get(name.split(".")[-1])


def _imports(clean: str) -> tuple[dict, set]:
    """Selector->framework map (alias-aware) and imported framework set."""
    selectors = dict(_SELECTOR_DEFAULTS)
    detected: set[str] = set()
    specs = []
    for block in _IMPORT_BLOCK.finditer(clean):
        specs += _IMPORT_SPEC.findall(block.group(1))
    specs += _IMPORT_SINGLE.findall(clean)
    for alias, import_path in specs:
        for prefix, framework in _FRAMEWORK_IMPORTS:
            if import_path == prefix or import_path.startswith(prefix + "/"):
                detected.add(framework)
                selectors[alias or _basename(import_path)] = framework
                break
    return selectors, detected


def _basename(import_path: str) -> str:
    parts = import_path.split("/")
    if len(parts) > 1 and re.fullmatch(r"v\d+", parts[-1]):
        return parts[-2]
    return parts[-1]


def _bind_types(clean: str, bindings: dict, detected: set) -> None:
    for match in _TYPE_BINDING.finditer(clean):
        framework = _TYPE_FRAMEWORKS[match.group(2).split(".")[0]]
        bindings[match.group(1)] = (framework, "")
        detected.add(framework)


def _bind_sequential(clean: str, selectors: dict, detected: set,
                     bindings: dict) -> None:
    """Constructors, groups, and subrouters, applied in file order.

    Order matters because `g2 := g.Group("/admin")` composes on the prefix
    `g` carries at that point; Go's declare-before-use makes one pass enough.
    """
    events = ([(m.start(), "ctor", m) for m in _CONSTRUCTOR.finditer(clean)]
              + [(m.start(), "group", m) for m in _GROUP.finditer(clean)]
              + [(m.start(), "sub", m) for m in _SUBROUTER.finditer(clean)])
    for _, kind, match in sorted(events, key=lambda e: e[0]):
        var, source, arg = match.group(1), match.group(2), match.group(3)
        if kind == "ctor":
            framework = selectors.get(source)
            if framework and (framework, arg) in _CTOR_FUNCS:
                bindings[var] = (framework, "")
                detected.add(framework)
        elif kind == "group":
            parent = _lookup(bindings, source)
            if parent and parent[0] in ("echo", "gin", "fiber"):
                bindings[var] = (parent[0], _join(parent[1], arg))
        else:  # gorilla PathPrefix().Subrouter()
            parent = _lookup(bindings, source)
            if parent and parent[0] == "gorilla":
                bindings[var] = ("gorilla", _join(parent[1], arg))
            elif parent is None and "gorilla" in detected:
                bindings[var] = ("gorilla", _join("", arg))


def _chi_spans(clean: str, mask: str, bindings: dict) -> list[_ChiSpan]:
    spans: list[_ChiSpan] = []
    for match in _CHI_ROUTE.finditer(clean):
        bound = _lookup(bindings, match.group(1))
        if bound and bound[0] != "chi":
            continue
        open_brace = match.end() - 1
        end = _close_of(mask, open_brace)
        base = ""
        for span in spans:  # last enclosing span found is the innermost
            if span.start < match.start() and span.end >= end:
                base = span.prefix
        spans.append(_ChiSpan(match.start(), end,
                              _join(base, match.group(2)), match.group(3)))
    return spans


def _resolve(receiver: str, pos: int, bindings: dict, spans: list,
             detected: set, family: tuple):
    """(framework, prefix) for a route call receiver, or None to skip."""
    innermost = None
    for span in spans:
        if span.start <= pos < span.end and (
                innermost is None or span.start > innermost.start):
            innermost = span
    if innermost and receiver == innermost.param and "chi" in family:
        return "chi", innermost.prefix
    bound = _lookup(bindings, receiver)
    if bound:
        return bound if bound[0] in family else None
    if innermost:
        return None  # unknown variable inside a chi closure: too ambiguous
    candidates = [f for f in family if f in detected]
    if len(candidates) == 1:
        return candidates[0], ""
    return None


def _parse_mux_pattern(pattern: str):
    """Split a ServeMux pattern into (method, path, host); None if malformed.

    Go 1.22 grammar is `[METHOD ][HOST]/[PATH]`: `"GET /pets/{id}"`,
    `"example.com/admin"`, plain `"/path"` (any method). A trailing `/{$}`
    is the exact-match marker, not a segment.
    """
    pattern = pattern.strip()
    if not pattern:
        return None
    method = "ANY"
    if " " in pattern:
        head, _, rest = pattern.partition(" ")
        rest = rest.strip()
        if head not in _GO122_METHODS or not rest:
            return None
        method, pattern = head, rest
    host = ""
    if not pattern.startswith("/"):
        host, slash, tail = pattern.partition("/")
        if not slash:
            return None
        pattern = "/" + tail
    if pattern.endswith("/{$}"):
        pattern = pattern[:-4] or "/"
    return method, pattern, host


def extract_go_routes(file_path: str, content: str) -> list[GoRoute]:
    """All statically-declared HTTP routes in one Go file."""
    if not file_path.endswith(".go") or not content:
        return []
    clean, mask = _scan(content)
    selectors, detected = _imports(clean)
    bindings: dict[str, tuple[str, str]] = {}
    _bind_types(clean, bindings, detected)
    _bind_sequential(clean, selectors, detected, bindings)
    spans = _chi_spans(clean, mask, bindings)

    routes: list[GoRoute] = []
    _emit_member_verbs(clean, bindings, spans, detected, routes)
    _emit_handle(clean, mask, selectors, bindings, detected, routes)
    routes.sort(key=lambda r: r.line)
    return routes


def _emit_member_verbs(clean: str, bindings: dict, spans: list,
                       detected: set, routes: list[GoRoute]) -> None:
    for match in _UPPER_VERB.finditer(clean):  # echo / gin
        resolved = _resolve(match.group(1), match.start(), bindings, [],
                            detected, ("echo", "gin"))
        if not resolved:
            continue
        framework, prefix = resolved
        verb = match.group(2)
        routes.append(GoRoute(
            method="ANY" if verb == "Any" else verb,
            path=_template(_join(prefix, match.group(3)), colon_style=True),
            framework=framework, line=_line_of(clean, match.start()),
            handler_name=_handler_after(clean, match.end())))
    for match in _CAP_VERB.finditer(clean):  # chi / fiber
        resolved = _resolve(match.group(1), match.start(), bindings, spans,
                            detected, ("chi", "fiber"))
        if not resolved:
            continue
        framework, prefix = resolved
        verb = match.group(2)
        routes.append(GoRoute(
            method="ANY" if verb == "All" else verb.upper(),
            path=_template(_join(prefix, match.group(3)),
                           colon_style=framework == "fiber"),
            framework=framework, line=_line_of(clean, match.start()),
            handler_name=_handler_after(clean, match.end())))


def _emit_handle(clean: str, mask: str, selectors: dict, bindings: dict,
                 detected: set, routes: list[GoRoute]) -> None:
    """HandleFunc/Handle: gorilla routers vs net/http ServeMux."""
    for match in _HANDLE.finditer(clean):
        receiver = match.group(1)
        bound = _lookup(bindings, receiver)
        if bound and bound[0] == "gorilla":
            _emit_gorilla(clean, mask, match, bound[1], routes)
        elif bound and bound[0] == "net/http":
            _emit_servemux(clean, match, routes)
        elif bound:
            continue  # a chi/echo/... variable: not a form this row covers
        elif selectors.get(receiver) == "net/http":
            _emit_servemux(clean, match, routes)  # http.HandleFunc(...)
        elif "gorilla" in detected:
            _emit_gorilla(clean, mask, match, "", routes)
        elif "net/http" in detected:
            _emit_servemux(clean, match, routes)


def _emit_servemux(clean: str, match: re.Match, routes: list[GoRoute]) -> None:
    parsed = _parse_mux_pattern(match.group(3))
    if not parsed:
        return
    method, path, host = parsed
    routes.append(GoRoute(
        method=method, path=_template(path, colon_style=False),
        framework="net/http", line=_line_of(clean, match.start()),
        handler_name=_handler_after(clean, match.end()),
        attrs={"host": host} if host else {}))


def _emit_gorilla(clean: str, mask: str, match: re.Match, prefix: str,
                  routes: list[GoRoute]) -> None:
    """One route per `.Methods(...)` verb; no chain means ANY."""
    methods: list[str] = []
    attrs: dict = {}
    open_paren = clean.index("(", match.end(2))
    pos = _close_of(mask, open_paren) + 1
    while chained := _CHAIN_CALL.match(clean, pos):
        name, args = chained.group(1), chained.group(2)
        if name == "Methods":
            methods += [q.upper() for q in _QUOTED.findall(args)]
            methods += [c.upper() for c in _METHOD_CONST.findall(args)]
        elif name == "Host" and (host := _QUOTED.search(args)):
            attrs["host"] = host.group(1)
        pos = chained.end()
    path = _template(_join(prefix, match.group(3)), colon_style=False)
    line = _line_of(clean, match.start())
    handler = _handler_after(clean, match.end())
    for method in methods or ["ANY"]:
        routes.append(GoRoute(method=method, path=path, framework="gorilla",
                              line=line, handler_name=handler,
                              attrs=dict(attrs)))
