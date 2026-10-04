"""Routes registered by calling a framework: `app.MapGet`, `r.GET`, `.route`.

The annotation half of endpoint extraction reads symbols; this half reads
method calls, one pattern per language, each anchored to the call that owns it
(see own_call.py) so a chain of registrations yields one endpoint per link.
"""

import re

from tracekite.parsers.base import ParsedApiEndpoint, ParsedMethodCall
from tracekite.parsers.tree_sitter.core.models import LanguageType
from tracekite.parsers.tree_sitter.own_call import own_match


def extract_route_calls(method_calls: list[ParsedMethodCall], language: LanguageType) -> list[ParsedApiEndpoint]:
    endpoints: list[ParsedApiEndpoint] = []
    framework = framework_for_language(language)

    for call in method_calls:
        context = call.context or ""
        if language == LanguageType.CSHARP:
            # Minimal APIs: app.MapGet("/owners", handler)
            m = own_match(
                r"\.Map(Get|Post|Put|Delete|Patch)\s*\(\s*['\"]([^'\"]+)['\"]",
                context, call.callee_name)
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
            m = own_match(
                r"(?:app|router|server)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
                context, call.callee_name,
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
            m = own_match(
                r"@(\w+)\.route\s*\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*methods\s*=\s*\[(.*?)\])?",
                context, call.callee_name,
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
            m = own_match(
                r"(\w+)\.websocket\s*\(\s*['\"](/[^'\"]*)['\"]", context,
                call.callee_name)
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
            m = own_match(
                r"(\w+)\.(get|post|put|delete|patch)\s*\(\s*['\"](/[^'\"]*)['\"]",
                context, call.callee_name,
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
            # net/http is go_route_extractor's alone: `HandleFunc` serves every
            # method and Go 1.22 puts one inside the pattern ("POST /orders"),
            # which this pattern recorded as GET of a path named "/POST /orders".
            # Gin/Echo/Fiber: r.GET("/path", handler). Same two gates the
            # Python branch above earned the hard way: the path MUST start
            # with "/" — `w.Header.Get("Content-Type")`,
            # `field.Tag.Get("protobuf")` and `url.Values.Get("key")` all
            # match the verb pattern and fabricated endpoints on the
            # reference corpus — and a trailing comma requires the handler
            # argument, which is what distinguishes a route registration
            # from a single-argument client call like `client.Get("/x")`.
            m = own_match(
                r"\.(GET|POST|PUT|DELETE|PATCH)\s*\(\s*['\"](/[^'\"]*)['\"]\s*,",
                context, call.callee_name,
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
            m = own_match(
                r"\.route\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(?:(\w+)::)?(get|post|put|delete|patch)\b",
                context, call.callee_name,
                re.IGNORECASE,
            )
            if m:
                endpoints.append(
                    ParsedApiEndpoint(
                        method=m.group(3).upper(),
                        path=m.group(1),
                        handler_name=call.caller_name or "",
                        line=call.line,
                        framework="actix" if m.group(2) == "web" else "axum",
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


def framework_for_language(language: LanguageType) -> str:
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
