"""HTTP routes declared in PHP: Laravel, Slim, Symfony attributes.

The trap this file is built around: Slim routes are `$app->get('/x', ...)`
and Guzzle calls are `$client->get('/x')` — the identical shape with the
edge pointing the opposite way. Recording a client call as a provider
contract is worse than missing it, so route receivers are an allowlist
(`$app`, `$router`, `$group`, `$routes`) and everything else matches
nothing here; the client side keeps its own allowlist in
`http_call_extractor`. An unknown receiver is a decline on both sides,
never a guess on either.

Laravel `Route::resource`/`apiResource` expands to the routes Laravel's
router actually registers — the DSL's documented meaning, not an
inference. Laravel paths already use brace params; Symfony's do too.
"""

import re
from dataclasses import dataclass, field

_LARAVEL_VERB = re.compile(
    r"Route::(get|post|put|patch|delete|any)\s*\(\s*['\"]([^'\"]+)['\"]")
_LARAVEL_RESOURCE = re.compile(
    r"Route::(apiResource|resource)\s*\(\s*['\"]([\w./-]+)['\"]")
_SLIM_VERB = re.compile(
    r"\$(?:app|router|group|routes?)\s*->\s*"
    r"(get|post|put|patch|delete|any)\s*\(\s*['\"](/[^'\"]*)['\"]")
_SYMFONY_ATTR = re.compile(
    r"#\[\s*Route\s*\(\s*['\"]([^'\"]+)['\"]([^\]]*)\]")
_SYMFONY_METHODS = re.compile(
    r"['\"](GET|POST|PUT|PATCH|DELETE)['\"]", re.I)

# What `Route::apiResource` registers, per Laravel's router. The plain
# `resource` variant adds the two HTML form routes; both keep {id} as the
# param the docs use.
_API_RESOURCE = (
    ("index", "GET", ""), ("store", "POST", ""),
    ("show", "GET", "/{id}"), ("update", "PATCH", "/{id}"),
    ("destroy", "DELETE", "/{id}"),
)
_HTML_EXTRA = (("create", "GET", "/create"), ("edit", "GET", "/{id}/edit"))


@dataclass
class PhpRoute:
    """One statically-declared HTTP route registration."""
    method: str
    path: str
    framework: str        # laravel | slim | symfony
    line: int
    handler_name: str = ""
    attrs: dict = field(default_factory=dict)


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def extract_php_routes(file_path: str, content: str) -> list[PhpRoute]:
    """Every statically-declared route in one PHP file.

    Returns an empty list for files it does not recognise — an extractor
    never raises for unrecognised input.
    """
    routes: list[PhpRoute] = []

    for match in _LARAVEL_VERB.finditer(content):
        routes.append(PhpRoute(
            match.group(1).upper() if match.group(1) != "any" else "ANY",
            match.group(2) if match.group(2).startswith("/")
            else "/" + match.group(2),
            "laravel", _line_of(content, match.start())))

    for match in _LARAVEL_RESOURCE.finditer(content):
        base = "/" + match.group(2).strip("/")
        actions = _API_RESOURCE if match.group(1) == "apiResource" \
            else _API_RESOURCE + _HTML_EXTRA
        line = _line_of(content, match.start())
        for action, method, suffix in actions:
            routes.append(PhpRoute(
                method, base + suffix, "laravel", line,
                handler_name=f"{match.group(2)}.{action}"))

    for match in _SLIM_VERB.finditer(content):
        routes.append(PhpRoute(
            match.group(1).upper() if match.group(1) != "any" else "ANY",
            match.group(2), "slim", _line_of(content, match.start())))

    for match in _SYMFONY_ATTR.finditer(content):
        path = match.group(1)
        if not path.startswith("/"):
            # `#[Route('api_home', ...)]` names a route, not a path;
            # asserting it as one would join on a word.
            continue
        methods = [m.upper()
                   for m in _SYMFONY_METHODS.findall(match.group(2) or "")]
        line = _line_of(content, match.start())
        for method in (methods or ["ANY"]):
            routes.append(PhpRoute(method, path, "symfony", line))

    return routes
