"""HTTP server route declarations in Node/JS/TS frameworks.

Covers the frameworks the legacy JS extraction does not:

- NestJS: ``@Controller('owners')`` / ``@Controller({path, version})`` on
  classes joined with ``@Get``/``@Post``/... method decorators.
- Fastify (verb calls, ``route({...})`` objects, same-file ``register``
  with ``prefix``), Koa (``@koa/router`` with constructor and ``.prefix()``
  prefixes), Hapi (``server.route({...})``), AdonisJS (``Route.get`` / v6
  ``router.get`` plus ``Route.group(() => {...}).prefix('/api')``).
- Next.js route handlers: app-router ``**/route.ts`` verb exports and
  pages-router ``pages/api/**`` default exports; the path comes from the FILE
  path, not the content.
- Remix flat-file routes: ``loader`` export -> GET, ``action`` -> POST.
- Express router mounting: a router defined and mounted in the same file
  (``app.use('/v1', r)``) is emitted with the mount prefix applied and
  ``attrs={"mounted": True}`` so the orchestrator can dedupe against the
  unprefixed route the legacy parser already emits.

Plain Express verb calls (``app.get('/x', h)``, ``router.post(...)``) are
deliberately NOT emitted here: ``evigraph/parsers/javascript_parser.py`` and the
tree-sitter adapter already extract those, and re-emitting them would
double-count.

Precision-first: paths built from template literals containing ``${}`` or from
variables are skipped, never guessed. Path params normalize to brace
templates: ``:id`` -> ``{id}``, Next.js ``[id]`` -> ``{id}`` and ``[...slug]``
-> ``{slug}``, Remix ``$id`` -> ``{id}``, Hapi ``{id?}``/``{id*2}`` ->
``{id}``.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")

# Verb-call receiver methods -> HTTP method. `all`/`any` declare "any method"
# routes (Express `.all`, Adonis `Route.any`); `del` is the koa-router alias.
_HTTP_VERBS = {
    "get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE",
    "del": "DELETE", "patch": "PATCH", "head": "HEAD", "options": "OPTIONS",
    "all": "ANY", "any": "ANY",
}

# --- shared regexes --------------------------------------------------------

# recv.verb('<literal path>'  — the path must be a quoted literal; template
# literals are allowed only when interpolation-free (checked via "${" after).
_VERB_CALL = re.compile(
    r"\b(?P<recv>[A-Za-z_$][\w$]*)\s*\.\s*"
    r"(?P<verb>get|post|put|delete|del|patch|head|options|all|any)\s*\(\s*"
    r"(?P<q>['\"`])(?P<path>[^'\"`\n]*)(?P=q)")

# Handler argument right after the path: [Controller, 'method'] tuple (Adonis
# v6), 'Controller.method' magic string (Adonis v5), or a bare identifier.
_TUPLE_HANDLER = re.compile(
    r"\s*,\s*\[\s*([A-Za-z_$][\w$]*)\s*,\s*['\"]([\w$.]+)['\"]\s*\]")
_STRING_HANDLER = re.compile(r"\s*,\s*['\"]([\w$.#/]+)['\"]\s*[,)]")
_IDENT_HANDLER = re.compile(
    r"\s*,\s*([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*[,)]")

# Path-template normalization.
_COLON_PARAM = re.compile(r":([A-Za-z_$][\w$]*)(?:\([^)]*\))?\??")
_BRACE_MODIFIER = re.compile(r"\{([A-Za-z_$][\w$]*)[?*][^}]*\}")
_BRACKET_SEG = re.compile(
    r"\[\[\.\.\.([\w$-]+)\]\]|\[\.\.\.([\w$-]+)\]|\[([\w$-]+)\]")

# --- framework markers -----------------------------------------------------

_EXPRESS_IMPORT = re.compile(
    r"require\s*\(\s*['\"]express['\"]\s*\)|from\s+['\"]express['\"]")
_EXPRESS_ROUTER_VAR = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?!new\b)"
    r"(?:express\s*\.\s*)?Router\s*\(")
_MOUNT = re.compile(
    r"\b[A-Za-z_$][\w$]*\s*\.\s*use\s*\(\s*"
    r"(?P<q>['\"`])(?P<prefix>[^'\"`\n]*)(?P=q)\s*,\s*"
    r"(?P<target>[A-Za-z_$][\w$]*)\s*\)")

_FASTIFY_IMPORT = re.compile(
    r"require\s*\(\s*['\"]fastify['\"]\s*\)|from\s+['\"]fastify['\"]")
_FASTIFY_VAR = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?"
    r"(?:[Ff]astify\s*\(|require\s*\(\s*['\"]fastify['\"]\s*\)\s*\()")
_REGISTER = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\.\s*register\s*\(")
_PREFIX_KEY = re.compile(r"\bprefix\s*:\s*(['\"`])([^'\"`\n]*)\1")

_ROUTE_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\.\s*route\s*\(")
_OBJ_METHOD = re.compile(
    r"\bmethod\s*:\s*(?:['\"]([A-Za-z*]+)['\"]|\[([^\]]*)\])")
_OBJ_URL = re.compile(r"\b(?:url|path)\s*:\s*(['\"`])([^'\"`\n]*)\1")
_OBJ_PATH_KEY = re.compile(r"\bpath\s*:")
_OBJ_HANDLER = re.compile(r"\bhandler\s*:\s*([A-Za-z_$][\w$.]*)\s*[,}\r\n]")
_HAPI_IMPORT = re.compile(
    r"['\"]@hapi/hapi['\"]|require\s*\(\s*['\"]hapi['\"]\s*\)")

_KOA_ROUTER_IMPORT = re.compile(r"['\"](?:@koa/router|koa-router)['\"]")
_KOA_ROUTER_CLASS = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\s*\(\s*"
    r"['\"](?:@koa/router|koa-router)['\"]\s*\)"
    r"|import\s+([A-Za-z_$][\w$]*)\s+from\s+['\"](?:@koa/router|koa-router)['\"]")

_ADONIS_MARK = re.compile(
    r"@ioc:Adonis/Core/Route|@adonisjs/core/services/router"
    r"|use\s*\(\s*['\"]Route['\"]\s*\)")
_ADONIS_V6_IMPORT = re.compile(
    r"import\s+([A-Za-z_$][\w$]*)\s+from\s+"
    r"['\"]@adonisjs/core/services/router['\"]")
_ADONIS_V5_IMPORT = re.compile(
    r"import\s+([A-Za-z_$][\w$]*)\s+from\s+['\"]@ioc:Adonis/Core/Route['\"]"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*use\s*\(\s*['\"]Route['\"]\s*\)")
_CHAIN_CALL = re.compile(r"\s*\.\s*([A-Za-z_$][\w$]*)\s*\(")

_NEST_CONTROLLER = re.compile(r"@Controller\s*\(")
_NEST_CTRL_PATH = re.compile(r"\bpath\s*:\s*['\"]([^'\"]*)['\"]")
_NEST_CTRL_VERSION = re.compile(r"\bversion\s*:\s*['\"]?([\w.]+)['\"]?")
_NEST_VERB = re.compile(r"@(Get|Post|Put|Delete|Patch|Head|Options|All)\s*\(")
_QUOTED_ONLY = re.compile(r"^\s*(?:(['\"])([^'\"]*)\1\s*)?$")
_CLASS_KW = re.compile(r"\bclass\b")
_DECORATOR = re.compile(r"@[A-Za-z_$][\w$]*")
_TS_MODIFIER = re.compile(
    r"(?:public|private|protected|static|readonly|async|abstract|override)\b")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")

_NEXT_ROUTE_FILES = ("route.ts", "route.js", "route.tsx", "route.jsx")
_NEXT_APP_EXPORT = re.compile(
    r"export\s+(?:async\s+)?function\s+"
    r"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\("
    r"|export\s+const\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*=")
_DEFAULT_EXPORT = re.compile(r"export\s+default\b")
_PAGES_FN_NAME = re.compile(
    r"export\s+default\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")
_PAGES_ID_NAME = re.compile(
    r"(?m)^\s*export\s+default\s+([A-Za-z_$][\w$]*)\s*;?\s*$")

_REMIX_EXPORT = re.compile(
    r"export\s+(?:async\s+)?function\s+(loader|action)\b"
    r"|export\s+const\s+(loader|action)\s*[:=]")


@dataclass
class JsRoute:
    method: str          # GET/POST/... uppercase; "ANY" when indeterminate
    path: str            # normalized template starting with /
    framework: str       # fastify | koa-router | hapi | adonis | nestjs |
    #                      nextjs-app | nextjs-pages | remix | express
    line: int
    handler_name: str = ""
    attrs: dict = field(default_factory=dict)


# --- small helpers ---------------------------------------------------------


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


_PAIRS = {"(": ")", "{": "}", "[": "]"}


def _match_bracket(content: str, open_pos: int) -> int:
    """Index of the bracket matching ``content[open_pos]``; -1 if unbalanced.

    String- and comment-aware so quotes/braces inside literals or ``//``
    comments do not break the balance.
    """
    if open_pos < 0 or open_pos >= len(content):
        return -1
    open_ch = content[open_pos]
    close_ch = _PAIRS.get(open_ch)
    if close_ch is None:
        return -1
    depth = 0
    i = open_pos
    n = len(content)
    in_str: str | None = None
    while i < n:
        ch = content[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in ("'", '"', "`"):
            in_str = ch
        elif ch == "/" and i + 1 < n and content[i + 1] == "/":
            nl = content.find("\n", i)
            if nl == -1:
                return -1
            i = nl
        elif ch == "/" and i + 1 < n and content[i + 1] == "*":
            end = content.find("*/", i + 2)
            if end == -1:
                return -1
            i = end + 1
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _join_prefix(prefix: str, sub: str) -> str:
    parts = [p.strip("/") for p in ((prefix or "").strip(), (sub or "").strip())]
    return "/" + "/".join(p for p in parts if p)


def _normalize_path(raw: str | None) -> str | None:
    """Brace-template normalization; None means "decline, don't guess"."""
    if raw is None or "${" in raw:
        return None
    path = raw.strip() or "/"
    if not path.startswith("/"):
        path = "/" + path
    path = _COLON_PARAM.sub(r"{\1}", path)
    path = _BRACE_MODIFIER.sub(r"{\1}", path)
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _bracket_segment(seg: str) -> str:
    """Next.js dir segment: ``[id]``/``[...slug]``/``[[...slug]]`` -> braces."""
    m = _BRACKET_SEG.fullmatch(seg)
    if m:
        return "{" + (m.group(1) or m.group(2) or m.group(3)) + "}"
    return seg


def _inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _handler_after(content: str, pos: int) -> str:
    m = _TUPLE_HANDLER.match(content, pos)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    m = _STRING_HANDLER.match(content, pos)
    if m:
        return m.group(1)
    m = _IDENT_HANDLER.match(content, pos)
    if m:
        return m.group(1)
    return ""


def _emit(routes: list[JsRoute], method: str, prefix: str, raw_path: str,
          framework: str, line: int, handler: str = "",
          attrs: dict | None = None) -> None:
    path = _normalize_path(_join_prefix(prefix, raw_path))
    if path is None:
        return
    routes.append(JsRoute(method=method, path=path, framework=framework,
                          line=line, handler_name=handler, attrs=attrs or {}))


def _iter_verb_calls(content, start, end, receivers):
    """(match, raw_path) for literal-path verb calls on `receivers` in span."""
    for m in _VERB_CALL.finditer(content, start, end):
        if receivers is not None and m.group("recv") not in receivers:
            continue
        raw = m.group("path")
        if "${" in raw:
            continue
        yield m, raw


# --- NestJS ------------------------------------------------------------------


def _nest_handler_after(content: str, pos: int, end: int) -> str:
    """Method name below a route decorator, skipping decorators/modifiers."""
    while pos < end:
        while pos < end and content[pos] in " \t\r\n":
            pos += 1
        m = _DECORATOR.match(content, pos)
        if m:
            pos = m.end()
            while pos < end and content[pos] in " \t":
                pos += 1
            if pos < end and content[pos] == "(":
                close = _match_bracket(content, pos)
                if close == -1:
                    return ""
                pos = close + 1
            continue
        m = _TS_MODIFIER.match(content, pos)
        if m:
            pos = m.end()
            continue
        m = _IDENT.match(content, pos)
        return m.group(0) if m else ""
    return ""


def _extract_nestjs(content: str, routes: list[JsRoute]) -> None:
    controllers = list(_NEST_CONTROLLER.finditer(content))
    for i, cm in enumerate(controllers):
        args_open = cm.end() - 1
        args_close = _match_bracket(content, args_open)
        if args_close == -1:
            continue
        arg = content[args_open + 1:args_close].strip()
        attrs: dict = {}
        if not arg:
            prefix = ""
        elif arg.startswith("{"):
            pm = _NEST_CTRL_PATH.search(arg)
            prefix = pm.group(1) if pm else ""
            vm = _NEST_CTRL_VERSION.search(arg)
            if vm:
                attrs["version"] = vm.group(1)
        else:
            qm = _QUOTED_ONLY.match(arg)
            if qm is None or qm.group(2) is None:
                continue          # template literal / constant ref: decline
            prefix = qm.group(2)

        # Class body between this decorator and the next @Controller.
        scan_end = controllers[i + 1].start() if i + 1 < len(controllers) \
            else len(content)
        km = _CLASS_KW.search(content, args_close, scan_end)
        if km is None:
            continue
        body_open = content.find("{", km.end())
        if body_open == -1 or body_open >= scan_end:
            continue
        body_close = _match_bracket(content, body_open)
        if body_close == -1:
            body_close = scan_end

        for vm in _NEST_VERB.finditer(content, body_open, body_close):
            v_open = vm.end() - 1
            v_close = _match_bracket(content, v_open)
            if v_close == -1:
                continue
            v_arg = content[v_open + 1:v_close]
            qm = _QUOTED_ONLY.match(v_arg)
            if qm is None:
                continue          # non-literal decorator arg: decline
            sub = qm.group(2) or ""
            method = "ANY" if vm.group(1) == "All" else vm.group(1).upper()
            handler = _nest_handler_after(content, v_close + 1, body_close)
            _emit(routes, method, prefix, sub, "nestjs",
                  _line_of(content, vm.start()), handler, dict(attrs))


# --- Fastify -----------------------------------------------------------------


def _fastify_plugin_body(content: str, span_start: int, span_end: int):
    """(instance_param, body_open, body_close, fn_end) for an inline plugin."""
    span = content[span_start:span_end]
    fm = re.match(r"\s*(?:async\s+)?function\b[\w$\s]*\(", span)
    if fm:
        params_open = span_start + fm.end() - 1
        params_close = _match_bracket(content, params_open)
        if params_close == -1:
            return None
        param_m = _IDENT.search(content, params_open + 1, params_close)
        param = param_m.group(0) if param_m else None
        body_open = content.find("{", params_close)
    else:
        am = re.match(
            r"\s*(?:async\s*)?(?:\(\s*([A-Za-z_$][\w$]*)?[^)]*\)"
            r"|([A-Za-z_$][\w$]*))\s*=>", span)
        if am is None:
            return None
        param = am.group(1) or am.group(2)
        arrow_end = span_start + am.end()
        bm = re.match(r"\s*\{", content[arrow_end:span_end])
        if bm is None:
            return None                    # concise-body arrow: decline
        body_open = arrow_end + bm.end() - 1
    if body_open == -1 or body_open >= span_end:
        return None
    body_close = _match_bracket(content, body_open)
    if body_close == -1 or body_close > span_end:
        return None
    return param, body_open, body_close, body_close + 1


def _fastify_decl_body(content: str, name: str):
    """(param, body_open, body_close) for a same-file function declaration."""
    fm = re.search(rf"\bfunction\s+{re.escape(name)}\s*\(", content)
    if fm:
        params_open = fm.end() - 1
        params_close = _match_bracket(content, params_open)
        if params_close == -1:
            return None
        param_m = _IDENT.search(content, params_open + 1, params_close)
        body_open = content.find("{", params_close)
        if body_open == -1:
            return None
        body_close = _match_bracket(content, body_open)
        if body_close == -1:
            return None
        return (param_m.group(0) if param_m else None), body_open, body_close
    am = re.search(
        rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=\s*(?:async\s*)?"
        rf"(?:\(\s*([A-Za-z_$][\w$]*)?[^)]*\)|([A-Za-z_$][\w$]*))\s*=>", content)
    if am is None:
        return None
    bm = re.match(r"\s*\{", content[am.end():])
    if bm is None:
        return None
    body_open = am.end() + bm.end() - 1
    body_close = _match_bracket(content, body_open)
    if body_close == -1:
        return None
    return (am.group(1) or am.group(2)), body_open, body_close


def _scan_fastify_body(content, routes, body_open, body_close, param,
                       instances, prefix):
    receivers = {param} if param else set(instances)
    for m, raw in _iter_verb_calls(content, body_open + 1, body_close,
                                   receivers):
        verb = _HTTP_VERBS.get(m.group("verb"))
        if verb is None:
            continue
        _emit(routes, verb, prefix, raw, "fastify",
              _line_of(content, m.start()), _handler_after(content, m.end()))


def _extract_fastify(content: str, routes: list[JsRoute],
                     claimed: list[tuple[int, int]]) -> None:
    if not _FASTIFY_IMPORT.search(content):
        return
    instances = {m.group(1) for m in _FASTIFY_VAR.finditer(content)}
    instances.add("fastify")

    for rm in _REGISTER.finditer(content):
        if rm.group(1) not in instances:
            continue
        open_p = rm.end() - 1
        close_p = _match_bracket(content, open_p)
        if close_p == -1:
            continue
        claimed.append((rm.start(), close_p + 1))
        span = content[open_p + 1:close_p]
        if re.match(r"\s*require\s*\(", span):
            continue                       # cross-file plugin: decline
        id_m = re.match(r"\s*([A-Za-z_$][\w$]*)\s*(?=,|\))", span)
        if id_m:
            decl = _fastify_decl_body(content, id_m.group(1))
            if decl is None:
                continue                   # imported identifier: decline
            param, body_open, body_close = decl
            claimed.append((body_open, body_close + 1))
            fn_end = open_p + 1 + id_m.end()
        else:
            plugin = _fastify_plugin_body(content, open_p + 1, close_p)
            if plugin is None:
                continue
            param, body_open, body_close, fn_end = plugin
        pm = _PREFIX_KEY.search(content, fn_end, close_p)
        prefix = pm.group(2) if pm and "${" not in pm.group(2) else ""
        _scan_fastify_body(content, routes, body_open, body_close, param,
                           instances, prefix)

    # Top-level verb calls on fastify instances, outside register spans.
    for m, raw in _iter_verb_calls(content, 0, len(content), instances):
        if _inside(m.start(), claimed):
            continue
        verb = _HTTP_VERBS.get(m.group("verb"))
        if verb is None:
            continue
        _emit(routes, verb, "", raw, "fastify", _line_of(content, m.start()),
              _handler_after(content, m.end()))


# --- Fastify `.route({...})` object form + Hapi -------------------------------


def _extract_object_routes(content: str, routes: list[JsRoute],
                           claimed: list[tuple[int, int]]) -> None:
    is_fastify = bool(_FASTIFY_IMPORT.search(content))
    is_hapi = bool(_HAPI_IMPORT.search(content))
    for rm in _ROUTE_CALL.finditer(content):
        if _inside(rm.start(), claimed):
            continue
        open_p = rm.end() - 1
        close_p = _match_bracket(content, open_p)
        if close_p == -1:
            continue
        pos = open_p + 1
        while True:
            brace = content.find("{", pos, close_p)
            if brace == -1:
                break
            obj_end = _match_bracket(content, brace)
            if obj_end == -1 or obj_end > close_p:
                break
            obj = content[brace:obj_end + 1]
            pos = obj_end + 1
            mm = _OBJ_METHOD.search(obj)
            um = _OBJ_URL.search(obj)
            if mm is None or um is None:
                continue
            raw_path = um.group(2)
            if "${" in raw_path:
                continue
            if mm.group(1):
                methods = ["ANY" if mm.group(1) == "*" else mm.group(1).upper()]
            else:
                methods = [p.strip().strip("'\"").upper()
                           for p in mm.group(2).split(",") if p.strip()]
                methods = ["ANY" if m == "*" else m for m in methods]
            hm = _OBJ_HANDLER.search(obj)
            handler = hm.group(1) if hm else ""
            if is_fastify:
                framework = "fastify"
            elif is_hapi:
                framework = "hapi"
            else:
                framework = "hapi" if _OBJ_PATH_KEY.search(obj) else "fastify"
            line = _line_of(content, brace)
            for method in methods:
                if not re.fullmatch(r"[A-Z]+", method):
                    continue
                _emit(routes, method, "", raw_path, framework, line, handler)


# --- Koa -----------------------------------------------------------------


def _extract_koa(content: str, routes: list[JsRoute]) -> None:
    if not _KOA_ROUTER_IMPORT.search(content):
        return
    class_names = {g for m in _KOA_ROUTER_CLASS.finditer(content)
                   for g in m.groups() if g}
    if not class_names:
        class_names = {"Router"}
    alt = "|".join(re.escape(c) for c in sorted(class_names))
    var_re = re.compile(
        rf"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*new\s+(?:{alt})\s*\(")
    prefixes: dict[str, str] = {}
    for vm in var_re.finditer(content):
        args_open = vm.end() - 1
        args_close = _match_bracket(content, args_open)
        prefix = ""
        if args_close != -1:
            pm = _PREFIX_KEY.search(content, args_open, args_close)
            if pm and "${" not in pm.group(2):
                prefix = pm.group(2)
        prefixes[vm.group(1)] = prefix
    if not prefixes:
        return
    var_alt = "|".join(re.escape(v) for v in sorted(prefixes))
    for pm in re.finditer(
            rf"\b({var_alt})\s*\.\s*prefix\s*\(\s*(['\"`])([^'\"`\n]*)\2",
            content):
        if "${" not in pm.group(3):
            prefixes[pm.group(1)] = pm.group(3)
    for m, raw in _iter_verb_calls(content, 0, len(content), set(prefixes)):
        verb = _HTTP_VERBS.get(m.group("verb"))
        if verb is None:
            continue
        _emit(routes, verb, prefixes[m.group("recv")], raw, "koa-router",
              _line_of(content, m.start()), _handler_after(content, m.end()))


# --- AdonisJS --------------------------------------------------------------


def _extract_adonis(content: str, routes: list[JsRoute]) -> None:
    if not _ADONIS_MARK.search(content):
        return
    receivers: set[str] = set()
    for m in _ADONIS_V6_IMPORT.finditer(content):
        receivers.add(m.group(1))
    for m in _ADONIS_V5_IMPORT.finditer(content):
        receivers.add(m.group(1) or m.group(2))
    if re.search(r"@ioc:Adonis/Core/Route|use\s*\(\s*['\"]Route['\"]", content):
        receivers.add("Route")
    if "@adonisjs/core/services/router" in content and not receivers:
        receivers.add("router")
    receivers.discard("")

    alt = "|".join(re.escape(r) for r in sorted(receivers))
    group_re = re.compile(rf"\b(?:{alt})\s*\.\s*group\s*\(")
    group_spans: list[tuple[int, int, int, int, str]] = []  # span+body+prefix
    for gm in group_re.finditer(content):
        open_p = gm.end() - 1
        close_p = _match_bracket(content, open_p)
        if close_p == -1:
            continue
        if any(a <= gm.start() < b for a, b, _, _, _ in group_spans):
            continue                       # nested group: outer wins
        arrow = content.find("=>", open_p, close_p)
        if arrow == -1:
            continue
        body_open = content.find("{", arrow, close_p)
        if body_open == -1:
            continue
        body_close = _match_bracket(content, body_open)
        if body_close == -1 or body_close > close_p:
            continue
        # Walk the trailing chain (.prefix('/api').middleware(...)) for prefix.
        prefix = ""
        pos = close_p + 1
        while True:
            cm = _CHAIN_CALL.match(content, pos)
            if cm is None:
                break
            args_open = cm.end() - 1
            args_close = _match_bracket(content, args_open)
            if args_close == -1:
                break
            if cm.group(1) == "prefix":
                pm = re.search(r"['\"]([^'\"]+)['\"]",
                               content[args_open:args_close])
                if pm:
                    prefix = pm.group(1)
            pos = args_close + 1
        group_spans.append((gm.start(), pos, body_open, body_close, prefix))

    for _, _, body_open, body_close, prefix in group_spans:
        for m, raw in _iter_verb_calls(content, body_open + 1, body_close,
                                       receivers):
            verb = _HTTP_VERBS.get(m.group("verb"))
            if verb is None:
                continue
            _emit(routes, verb, prefix, raw, "adonis",
                  _line_of(content, m.start()),
                  _handler_after(content, m.end()))

    spans = [(a, b) for a, b, _, _, _ in group_spans]
    for m, raw in _iter_verb_calls(content, 0, len(content), receivers):
        if _inside(m.start(), spans):
            continue
        verb = _HTTP_VERBS.get(m.group("verb"))
        if verb is None:
            continue
        _emit(routes, verb, "", raw, "adonis", _line_of(content, m.start()),
              _handler_after(content, m.end()))


# --- Next.js -----------------------------------------------------------------


def _next_app_path(file_path: str) -> str | None:
    segments = [s for s in file_path.split("/") if s]
    if not segments or segments[-1] not in _NEXT_ROUTE_FILES:
        return None
    app_idx = max((i for i, s in enumerate(segments[:-1]) if s == "app"),
                  default=-1)
    if app_idx == -1:
        return None
    parts = []
    for seg in segments[app_idx + 1:-1]:
        if seg.startswith("(") and seg.endswith(")"):
            continue                       # route group
        if seg.startswith("@"):
            continue                       # parallel route slot
        parts.append(_bracket_segment(seg))
    return "/" + "/".join(parts)


def _extract_nextjs_app(file_path: str, content: str,
                        routes: list[JsRoute]) -> None:
    path = _next_app_path(file_path)
    if path is None:
        return
    norm = _normalize_path(path)
    if norm is None:
        return
    for m in _NEXT_APP_EXPORT.finditer(content):
        method = m.group(1) or m.group(2)
        routes.append(JsRoute(method=method, path=norm, framework="nextjs-app",
                              line=_line_of(content, m.start()),
                              handler_name=method))


def _next_pages_path(file_path: str) -> str | None:
    segments = [s for s in file_path.split("/") if s]
    if len(segments) < 3:
        return None
    idx = max((i for i, s in enumerate(segments[:-2])
               if s == "pages" and segments[i + 1] == "api"), default=-1)
    if idx == -1:
        return None
    rel = segments[idx + 1:]
    fname = rel[-1]
    base = re.sub(r"\.(tsx|ts|jsx|js|mjs|cjs)$", "", fname)
    if base == fname:
        return None
    parts = [_bracket_segment(s) for s in rel[:-1]]
    if base != "index":
        parts.append(_bracket_segment(base))
    return "/" + "/".join(parts)


def _extract_nextjs_pages(file_path: str, content: str,
                          routes: list[JsRoute]) -> None:
    path = _next_pages_path(file_path)
    if path is None:
        return
    dm = _DEFAULT_EXPORT.search(content)
    if dm is None:
        return
    norm = _normalize_path(path)
    if norm is None:
        return
    handler = ""
    fn = _PAGES_FN_NAME.search(content)
    if fn:
        handler = fn.group(1)
    else:
        idm = _PAGES_ID_NAME.search(content)
        if idm:
            handler = idm.group(1)
    routes.append(JsRoute(method="ANY", path=norm, framework="nextjs-pages",
                          line=_line_of(content, dm.start()),
                          handler_name=handler))


# --- Remix -----------------------------------------------------------------


def _remix_path(file_path: str) -> str | None:
    segments = [s for s in file_path.split("/") if s]
    idx = -1
    for i, s in enumerate(segments[:-1]):
        if s == "routes" and (i == 0 or segments[i - 1] == "app"):
            idx = i
    if idx == -1:
        return None
    rel = segments[idx + 1:]
    if len(rel) == 1:
        flat = re.sub(r"\.(tsx|ts|jsx|js)$", "", rel[0])
        if flat == rel[0]:
            return None
    elif len(rel) == 2 and rel[1] in ("route.ts", "route.tsx",
                                      "route.js", "route.jsx"):
        flat = rel[0]                      # v2 folder convention
    else:
        return None                        # deeper nesting: decline
    flat = flat.replace("[.]", "\x00")     # escaped literal dot
    parts: list[str] = []
    saw_index = False
    for seg in flat.split("."):
        seg = seg.replace("\x00", ".")
        if seg == "_index":
            saw_index = True
            continue
        if seg.startswith("_"):
            continue                       # pathless layout segment
        if seg == "$":
            parts.append("{splat}")
        elif seg.startswith("$"):
            parts.append("{" + seg[1:] + "}")
        elif seg:
            parts.append(seg)
    if not parts and not saw_index:
        return None                        # pathless layout only: decline
    return "/" + "/".join(parts)


def _extract_remix(file_path: str, content: str,
                   routes: list[JsRoute]) -> None:
    path = _remix_path(file_path)
    if path is None:
        return
    norm = _normalize_path(path)
    if norm is None:
        return
    for m in _REMIX_EXPORT.finditer(content):
        name = m.group(1) or m.group(2)
        method = "GET" if name == "loader" else "POST"
        attrs = {"remix": "action"} if name == "action" else {}
        routes.append(JsRoute(method=method, path=norm, framework="remix",
                              line=_line_of(content, m.start()),
                              handler_name=name, attrs=attrs))


# --- Express mounts ----------------------------------------------------------


def _extract_express_mounts(content: str, routes: list[JsRoute]) -> None:
    if not _EXPRESS_IMPORT.search(content):
        return
    router_vars = {m.group(1) for m in _EXPRESS_ROUTER_VAR.finditer(content)}
    if not router_vars:
        return
    per_var: dict[str, list[tuple[str, str, int, str]]] = {}
    for m, raw in _iter_verb_calls(content, 0, len(content), router_vars):
        verb = _HTTP_VERBS.get(m.group("verb"))
        if verb is None:
            continue
        per_var.setdefault(m.group("recv"), []).append(
            (verb, raw, _line_of(content, m.start()),
             _handler_after(content, m.end())))
    for mm in _MOUNT.finditer(content):
        target = mm.group("target")
        prefix = mm.group("prefix")
        if target not in per_var or "${" in prefix:
            continue                       # cross-file router: decline
        for verb, raw, line, handler in per_var[target]:
            _emit(routes, verb, prefix, raw, "express", line, handler,
                  {"mounted": True})


# --- entry point -----------------------------------------------------------


def extract_js_routes(file_path: str, content: str) -> list[JsRoute]:
    """All statically-declared HTTP server routes in one JS/TS file.

    ``file_path`` matters: Next.js and Remix derive the route path from the
    file location, not the content. Non-JS extensions return [].
    """
    if not file_path or not content:
        return []
    fp = file_path.replace("\\", "/")
    if not fp.lower().endswith(_JS_EXTS):
        return []

    routes: list[JsRoute] = []
    claimed: list[tuple[int, int]] = []
    extractors = (
        lambda: _extract_nextjs_app(fp, content, routes),
        lambda: _extract_nextjs_pages(fp, content, routes),
        lambda: _extract_remix(fp, content, routes),
        lambda: _extract_nestjs(content, routes),
        lambda: _extract_fastify(content, routes, claimed),
        lambda: _extract_object_routes(content, routes, claimed),
        lambda: _extract_koa(content, routes),
        lambda: _extract_adonis(content, routes),
        lambda: _extract_express_mounts(content, routes),
    )
    for run in extractors:
        try:
            run()
        except Exception as exc:           # malformed input must not raise
            logger.debug("js_route_extractor failed on %s: %s", file_path, exc)

    seen: set[tuple[str, str, str, int]] = set()
    unique: list[JsRoute] = []
    for r in routes:
        key = (r.framework, r.method, r.path, r.line)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique
