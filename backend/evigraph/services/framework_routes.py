"""Which extractor reads a file's routes, and what it refused to read.

The dispatch moved here from `ingest_source` so the refusal could come with
it. Route extraction is precision-first everywhere: a path built at runtime
(`baseUrl+"/cart"`, an `fmt.Sprintf`, a constant) is skipped rather than
guessed, which is correct — a guessed path is an invented edge.

What was missing is that the skip was silent. On
GoogleCloudPlatform/microservices-demo the frontend registers thirteen
gorilla/mux routes against a `baseUrl` prefix, and the repository reported
`endpoints: 0` — indistinguishable from a service that serves no HTTP at
all. Invariant I5 is that a decline is data: the number a reader needs is
"thirteen routes declined because their paths are computed", not silence.

Go and C# computed paths are modelled because their literal extractors have
matching, verified registration shapes. An extractor that has not been
checked reports zero rather than a guess, which is the same discipline
applied to the counter itself.
"""

import re

# The call shapes `go_route_extractor._HANDLE` reads, with the first argument
# NOT a string literal. Kept adjacent to that regex on purpose: the two are
# complementary halves of one grammar, and a shape added to one belongs in
# the other.
_COMPUTED_HANDLE = re.compile(
    r"\b[\w.]+\.(?:HandleFunc|Handle)\s*\(\s*(?![\"'`)])[^,)]+,")


def computed_go_paths(content: str) -> int:
    """Router registrations whose path is not a literal.

    Counted only when the file actually builds a router, so a client calling
    `c.Handle(...)` on something unrelated is not read as a declined route.
    Comments are stripped first: a commented-out registration is not a
    decline, it is not a registration.
    """
    from evigraph.services.go_route_extractor import _scan, _imports

    clean, _mask = _scan(content)
    _bindings, detected = _imports(clean)
    if not detected:
        return 0
    return len(_COMPUTED_HANDLE.findall(clean))


def framework_routes(file_info, content: str) -> tuple[list, int]:
    """Routes a framework extractor can read, and the count it declined.

    Framework route extraction beyond the generic parsers: JS/TS frameworks,
    Go routers, WebFlux/Ktor.
    """
    language = (file_info.language or "").lower()
    path = file_info.path
    if language in ("javascript", "typescript") or path.endswith(
            (".ts", ".tsx", ".js", ".jsx", ".mjs")):
        from evigraph.services.js_route_extractor import extract_js_routes
        return extract_js_routes(path, content), 0
    if path.endswith(".pb.gw.go"):
        # Generated gateway code: the path lives in a compiled pattern, so
        # the generic Go extractor's quoted-path search finds nothing.
        from evigraph.services.grpc_gateway_routes import extract_gateway_routes
        return extract_gateway_routes(path, content), 0
    if language == "go" or path.endswith(".go"):
        from evigraph.services.go_route_extractor import extract_go_routes
        return extract_go_routes(path, content), computed_go_paths(content)
    if language in ("java", "kotlin", "scala"):
        from evigraph.services.jvm_route_extractor import extract_jvm_routes
        return extract_jvm_routes(path, content), 0
    if language == "ruby" or path.endswith(".rb"):
        from evigraph.services.rb_route_extractor import extract_rb_routes
        return extract_rb_routes(path, content), 0
    if language == "php" or path.endswith(".php"):
        from evigraph.services.php_route_extractor import extract_php_routes
        return extract_php_routes(path, content), 0
    if language in ("c#", "csharp") or path.endswith(".cs"):
        from evigraph.services.csharp_route_extractor import (
            extract_csharp_routes_with_declines,
        )
        return extract_csharp_routes_with_declines(path, content)
    return [], 0
