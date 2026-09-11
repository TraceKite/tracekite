"""HTTP consumer-lite extraction (impl §5).

Fixture-verified client set: RestTemplate/WebClient/RestClient, OkHttp, Apache
HttpClient, java.net.http, Retrofit annotations (Java/Kotlin/Scala);
fetch/axios/got/ky/superagent/undici (JS/TS); requests/httpx/aiohttp/urllib3/
session objects (Python); HttpClient/RestSharp/Refit (C#); net/http + resty
(Go); reqwest (Rust). URL literals and env-var references are recorded with
hint_source; anything non-literal stays visible as an unmatchable-or-hinted
claim rather than a guessed edge (decline-don't-guess).
"""

import re
from dataclasses import dataclass, field

from evigraph.services.http_call_url import classify_url
from evigraph.utils.canonical import canonicalize_path_template

_DYNAMIC = re.compile(r"\$\{[^}]*\}|\{[^}]+\}|%s|%d")

_JAVA_REST = re.compile(
    r"\.(getForObject|getForEntity|postForObject|postForEntity|postForLocation"
    r"|exchange|patchForObject)\s*\(\s*\"([^\"]+)\"")
_JAVA_PUT_DELETE = re.compile(
    r"\.(put|delete)\s*\(\s*\"((?:https?|lb)://[^\"]+|/[^\"]*)\"")
_WEBCLIENT_URI = re.compile(
    r"(?:\.(get|post|put|delete|patch|head)\s*\(\s*\)[\s\S]{0,160}?)?"
    r"\.uri\s*\(\s*\"([^\"]+)\"")
_WEBCLIENT_CREATE = re.compile(
    r"\b(WebClient|RestClient)\s*\.\s*create\s*\(\s*\"([^\"]+)\"")
_FEIGN = re.compile(r"@FeignClient\s*\(([^)]*)\)")

# OkHttp: verb comes from a builder method after .url(); default GET.
_OKHTTP_URL = re.compile(
    r"(?:new\s+)?\bRequest\.Builder\s*\(\s*\)[\s\S]{0,160}?"
    r"\.url\s*\(\s*\"([^\"]+)\"")
_OKHTTP_VERB = re.compile(
    r"\.(get|post|put|delete|patch|head)\s*\(|\.method\s*\(\s*\"([A-Z]+)\"")
_APACHE_NEW = re.compile(
    r"\b(?:new\s+)?Http(Get|Post|Put|Delete|Patch|Head)\s*\(\s*\"([^\"]+)\"")
# java.net.http: newBuilder().uri(URI.create(..)) and newBuilder(URI.create(..)).
_JAVA11_URI = re.compile(
    r"\bHttpRequest\s*\.\s*newBuilder\s*\([\s\S]{0,160}?"
    r"URI\s*\.\s*create\s*\(\s*\"([^\"]+)\"")
_JAVA11_VERB = re.compile(
    r"\.(GET|POST|PUT|DELETE|PATCH|HEAD)\s*\(|\.method\s*\(\s*\"([A-Z]+)\"")
# Retrofit route annotations carry a literal argument; JAX-RS @GET does not,
# so requiring the string keeps server-side annotations out. @Url dynamic
# methods have no literal and are skipped naturally.
_RETROFIT = re.compile(
    r"@(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*\"([^\"]+)\"")
_FEIGN_NAME = re.compile(r"(?:name|value)\s*=\s*\"([^\"]+)\"|^\s*\"([^\"]+)\"")

_PY_CALL = re.compile(
    r"\b(?:requests|httpx)\.(get|post|put|delete|patch|head)\s*\(\s*(f?)[\"']([^\"']+)")
# Base-URL variable followed by a literal path:
#     await self._http.get(f"{self._registry_url}/v1/callers")
#     url = f"{self._orchestrator_url}/v1/turns"
# This is the dominant shape in dependency-injected services: the host is
# injected from configuration at deploy time, so it is never a literal, but
# the PATH is — and the path is what identifies the contract. Requiring a
# literal host is what made these call sites invisible.
#
# The interpolation must be the FIRST thing in the string (a base URL) and the
# path must be a literal; `f"{base}{path_const}"` carries no template and is
# declined rather than guessed.
# The path must START with `/` (so `f"{base}{CONST}"` is declined) but may then
# contain further interpolations: `/v1/callers/{caller_id}` has to survive as
# `/v1/callers/{}` or it would match the COLLECTION contract instead of the
# item one — a wrong match, which is worse than no match.
_PY_FSTRING_BASE = re.compile(
    r"f[\"']\{\s*([A-Za-z_][\w.]*)\s*\}(/(?:[^\"'\s{}]|\{[^{}\"']*\})*)")
# Verb for the call the f-string belongs to. Scans back over the argument list
# to the nearest `.verb(`; without one the site is not a request and is
# skipped, never assumed to be a GET.
_PY_FSTRING_VERB = re.compile(
    r"\.\s*(get|post|put|patch|delete|head)\s*\($", re.IGNORECASE)
# `url = f"{base}/path"` — the assignment target, so the verb can be found at
# the point the variable is actually passed to a request.
_PY_ASSIGN_TARGET = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*$")

_PY_SESSION_ASSIGN = re.compile(r"\b(\w+)\s*=\s*requests\.Session\s*\(")
# Any *session* receiver (aiohttp ClientSession, requests.Session by
# convention). URL must start with http(s):// or / so dict-style
# session.get("user_id") lookups (e.g. Flask) are declined, not guessed.
_PY_SESSION_VERB = re.compile(
    r"\b(?=[A-Za-z_])\w*?(?i:session)\w*\s*\.\s*(get|post|put|delete|patch|head)"
    r"\s*\(\s*(f?)[\"']([^\"']+)")
# Method-first .request("GET", url) signature: urllib3 PoolManager (also the
# `)` receiver for urllib3.PoolManager().request), aiohttp.request,
# requests/httpx .request. Verb must be an uppercase literal.
_PY_REQUEST_FIRST = re.compile(
    r"([A-Za-z_]\w*|\))\s*\.\s*request\s*\(\s*[\"']([A-Z]+)[\"']\s*,\s*"
    r"(f?)[\"']([^\"']+)")

_CSHARP_LANGS = {"c#", "csharp"}
# Receiver must contain client/http (or be a call result, e.g.
# factory.CreateClient(..)) so IDistributedCache.GetStringAsync("key") and
# friends are declined. `$`/`@` prefixes mark interpolated/verbatim strings.
_CS_HTTP_VERB = re.compile(
    r"(?:\)|\b(?=[A-Za-z_])\w*?(?i:client|http)\w*)\s*\.\s*"
    r"(Get|Post|Put|Delete|Patch)(?:String|FromJson|AsJson|ByteArray|Stream)?Async"
    r"(?:<[^()]{0,80}>)?\s*\(\s*([$@]{0,2})\"([^\"]+)\"")
_CS_BASE_ADDRESS = re.compile(
    r"\.\s*BaseAddress\s*=\s*new\s+Uri\s*\(\s*\"([^\"]+)\"")
_CS_RESTSHARP_CLIENT = re.compile(r"\bnew\s+RestClient\s*\(\s*\"([^\"]+)\"")
_CS_RESTSHARP_REQUEST = re.compile(
    r"\bnew\s+RestRequest\s*\(\s*\"([^\"]+)\"\s*(?:,\s*Method\.([A-Za-z]+))?")
_CS_REFIT = re.compile(r"\[(Get|Post|Put|Delete|Patch|Head)\s*\(\s*\"([^\"]+)\"\s*\)\s*\]")

_GO_HTTP_HELPER = re.compile(r"\bhttp\.(Get|Post|PostForm|Head)\s*\(\s*\"([^\"]+)\"")
_GO_NEW_REQUEST = re.compile(
    r"\bhttp\.NewRequest\s*\(\s*(?:http\.Method([A-Za-z]+)|\"([A-Z]+)\")\s*,\s*"
    r"\"([^\"]+)\"")
_GO_NEW_REQUEST_CTX = re.compile(
    r"\bhttp\.NewRequestWithContext\s*\(\s*[^,]{1,80},\s*"
    r"(?:http\.Method([A-Za-z]+)|\"([A-Z]+)\")\s*,\s*\"([^\"]+)\"")
# resty: verb is paired with the nearest .R() chain; the tempered gap stops at
# the next .R( so one chain cannot borrow another chain's verb.
_GO_RESTY_CHAIN = re.compile(
    r"\.R\s*\(\s*\)(?:(?!\.R\s*\()[\s\S]){0,300}?"
    r"\.(Get|Post|Put|Delete|Patch|Head|Options)\s*\(\s*\"([^\"]+)\"")
_GO_RESTY_BASE = re.compile(r"\.SetBaseURL\s*\(\s*\"([^\"]+)\"")

_RUST_REQWEST_GET = re.compile(r"\breqwest::(?:blocking::)?get\s*\(\s*\"([^\"]+)\"")

# Ruby interpolation is normalised to a positional param BEFORE
# classification, so "#{base}/v1/x" and f"{base}/v1/x" land in the same
# template space — two spellings of one idiom must not mint two contracts.
_RB_INTERP = re.compile(r"#\{[^}]*\}")
_RB_NET_HTTP = re.compile(
    r"Net::HTTP\.(get|post_form|post|put|delete)\s*\(\s*(?:URI\.parse\(|URI\()?"
    r"\s*['\"]([^'\"]+)['\"]")
_RB_LIB_VERB = re.compile(
    r"\b(Faraday|HTTParty|RestClient)\.(get|post|put|patch|delete)"
    r"\s*\(?\s*['\"]([^'\"]+)['\"]")

_PHP_CLIENT_RECEIVERS = "client|http|guzzle|httpclient|api"
# Receiver-limited on purpose: Slim routes are `$app->get('/x', ...)` and
# Guzzle calls are `$client->get('/x')` — the same shape, opposite edge
# direction, told apart only by the variable's name (the adapter learned
# this with Python's dict.get). An unknown receiver matches neither.
_PHP_CLIENT_VERB = re.compile(
    r"\$(?:" + _PHP_CLIENT_RECEIVERS + r")\s*->\s*"
    r"(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
_PHP_REQUEST = re.compile(
    r"->\s*request\s*\(\s*['\"](GET|POST|PUT|PATCH|DELETE)['\"]\s*,\s*"
    r"['\"]([^'\"]+)['\"]", re.I)
_PHP_HTTP_FACADE = re.compile(
    r"\bHttp::(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]")
_PHP_CURL = re.compile(
    r"curl_setopt\s*\(\s*\$\w+\s*,\s*CURLOPT_URL\s*,\s*['\"]([^'\"]+)['\"]")
# Generic receiver .get("...") is only trusted with an absolute URL so
# HashMap::get("key") style lookups never become call sites.
_RUST_CLIENT_VERB = re.compile(
    r"\.(get|post|put|delete|patch|head)\s*\(\s*\"(https?://[^\"]+)\"")

_JAVA_METHOD_MAP = {
    "getForObject": "GET", "getForEntity": "GET",
    "postForObject": "POST", "postForEntity": "POST", "postForLocation": "POST",
    "patchForObject": "PATCH",
    "put": "PUT", "delete": "DELETE",
}

# exchange() is verb-generic — the verb is an HttpMethod argument, not the
# method name. Reading it off the call site beats defaulting to GET, which
# produced a GET-keyed claim for every POST/PUT/DELETE exchange.
_EXCHANGE_VERB = re.compile(r"HttpMethod\s*\.\s*([A-Z]+)")
_EXCHANGE_WINDOW = 200

_JAVA_LANGS = {"java", "kotlin", "scala"}
_JS_LANGS = {"javascript", "typescript"}
_VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


@dataclass
class HttpCallSite:
    method: str
    raw_url: str
    path_template: str
    host: str | None
    service_hint: str | None
    hint_source: str
    line: int
    client: str
    attrs: dict = field(default_factory=dict)


def extract_http_calls(file_path: str, content: str, language: str | None) -> list[HttpCallSite]:
    lang = (language or "").lower()
    sites: list[HttpCallSite] = []
    if lang in _JAVA_LANGS:
        _extract_java(content, sites)
    elif lang in _JS_LANGS:
        # Imported at call time: the JS module imports this one's `_add`,
        # and a module-level import back would be a cycle.
        from evigraph.services.http_call_js import extract_js
        extract_js(content, sites)
        _mark_ui_sites(file_path, sites)
    elif lang == "python":
        _extract_python(content, sites)
    elif lang in _CSHARP_LANGS:
        _extract_csharp(content, sites)
    elif lang == "go":
        _extract_go(content, sites)
    elif lang == "rust":
        _extract_rust(content, sites)
    elif lang == "ruby":
        _extract_ruby(content, sites)
    elif lang == "php":
        _extract_php(content, sites)
    return sites


# Clients that only exist in UI code: a data-fetching hook has no server
# analogue, so its presence identifies the caller as a component without
# guessing from directory names.
_UI_ONLY_CLIENTS = frozenset({"swr", "rtk-query"})
_COMPONENT_EXTENSIONS = (".tsx", ".jsx")


def _mark_ui_sites(file_path: str, sites: list) -> None:
    """Flag call sites made from UI components.

    Two signals, each sufficient and neither guessed: the client is a
    UI-only library, or the file is a component file by extension. A plain
    fetch() in ordinary .ts stays unmarked — a Node service uses the same
    call shape, and marking it would type the edge by folklore.
    """
    component_file = file_path.endswith(_COMPONENT_EXTENSIONS)
    for site in sites:
        if component_file or site.client in _UI_ONLY_CLIENTS:
            site.attrs["ui"] = True


# A callback kwarg only counts inside webhook-ish context: `url=` appears
# in every HTTP call ever written, and without the guard each one would
# become a phantom delivery contract.
_WEBHOOK_CONTEXT = re.compile(r"webhook|subscri|\bhooks?\b|callback",
                              re.IGNORECASE)
_WEBHOOK_KWARG = re.compile(
    r"(?:callback_url|webhook_url|notification_url|hub\.callback|"
    r"[\"']?url[\"']?)\s*[:=]\s*[\"'](https?://[^\"']+)[\"']")
_WEBHOOK_CHAIN = re.compile(r"(\w+)\s*\.[\w.]*\s*\($")


def extract_webhook_registrations(content: str) -> list[tuple[int, str, str]]:
    """(line, callback_url, deliverer_hint) for each registration.

    The deliverer hint is the call chain's leading identifier
    (`stripe.WebhookEndpoint.create(` -> `stripe`) and is a HINT: generic
    receivers decline downstream rather than naming a coin-flip.
    """
    found = []
    for match in _WEBHOOK_KWARG.finditer(content):
        window = content[max(0, match.start() - 160):match.start()]
        if not _WEBHOOK_CONTEXT.search(window):
            continue
        chain = _WEBHOOK_CHAIN.search(window.rstrip().rstrip("(").rstrip()
                                      + "(")
        found.append((_line_of(content, match.start()), match.group(1),
                      (chain.group(1).lower() if chain else "")))
    return found


def extract_feign_clients(content: str) -> list[tuple[str, int]]:
    clients = []
    for match in _FEIGN.finditer(content):
        name_match = _FEIGN_NAME.search(match.group(1))
        if name_match:
            name = name_match.group(1) or name_match.group(2)
            if name:
                clients.append((name, _line_of(content, match.start())))
    return clients


def _exchange_verb(content: str, end: int) -> tuple[str, bool]:
    """Verb from the HttpMethod argument that follows the URL, if present."""
    window = content[end:end + _EXCHANGE_WINDOW]
    match = _EXCHANGE_VERB.search(window)
    if match and match.group(1) in {"GET", "POST", "PUT", "DELETE", "PATCH",
                                    "HEAD", "OPTIONS"}:
        return match.group(1), False
    return "GET", True


def _extract_java(content: str, sites: list[HttpCallSite]) -> None:
    for match in _JAVA_REST.finditer(content):
        name = match.group(1)
        if name == "exchange":
            method, inferred = _exchange_verb(content, match.end())
        else:
            method, inferred = _JAVA_METHOD_MAP[name], False
        _add(sites, content, match.start(), method, match.group(2),
             "resttemplate", method_inferred=inferred,
             concatenated=_is_concatenated(content, match.end()))
    for match in _JAVA_PUT_DELETE.finditer(content):
        _add(sites, content, match.start(), _JAVA_METHOD_MAP[match.group(1)],
             match.group(2), "resttemplate",
             concatenated=_is_concatenated(content, match.end()))
    for match in _WEBCLIENT_URI.finditer(content):
        verb = match.group(1)
        _add(sites, content, match.start(2), (verb or "GET").upper(),
             match.group(2), "webclient", method_inferred=verb is None,
             concatenated=_is_concatenated(content, match.end()))
    for match in _WEBCLIENT_CREATE.finditer(content):
        client = "webclient" if match.group(1) == "WebClient" else "restclient"
        _add(sites, content, match.start(), "GET", match.group(2), client,
             base_url=True)
    for match in _OKHTTP_URL.finditer(content):
        endpos = _window_end(content, match.end(), 240, ";", "Request.Builder")
        method, inferred = _verb_after(content, match.end(), endpos, _OKHTTP_VERB)
        _add(sites, content, match.start(1), method, match.group(1), "okhttp",
             method_inferred=inferred,
             concatenated=_is_concatenated(content, match.end()))
    for match in _APACHE_NEW.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(2), "apache",
             concatenated=_is_concatenated(content, match.end()))
    for match in _JAVA11_URI.finditer(content):
        endpos = _window_end(content, match.end(), 240, ";", "HttpRequest")
        method, inferred = _verb_after(content, match.end(), endpos, _JAVA11_VERB)
        _add(sites, content, match.start(1), method, match.group(1), "java-http",
             method_inferred=inferred,
             concatenated=_is_concatenated(content, match.end()))
    for match in _RETROFIT.finditer(content):
        _add(sites, content, match.start(), match.group(1), match.group(2),
             "retrofit")


def _base_var_name(expr: str) -> str:
    """`self._registry_url` -> `registry`. Used only to disambiguate later,
    never to name a service on its own."""
    name = expr.rsplit(".", 1)[-1].lstrip("_").lower()
    for suffix in ("_base_url", "_baseurl", "_endpoint", "_url", "_base", "_uri"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _enclosing_call_verb(content: str, start: int) -> str | None:
    """Verb of the call whose argument list contains this position.

    Walks back balancing parentheses, so `f(g(), h(f"{b}/p"))` attributes the
    string to `h`, not `f`. Returns None when the enclosing call is not an
    HTTP verb — a missing verb is never assumed to be GET.
    """
    depth = 0
    i = start - 1
    floor = max(0, start - 400)
    while i >= floor:
        ch = content[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                match = _PY_FSTRING_VERB.search(content[floor:i + 1])
                return match.group(1).upper() if match else None
            depth -= 1
        i -= 1
    return None


def _assigned_var_verb(content: str, start: int, var: str) -> str | None:
    """`url = f"{base}/v1/turns"` ... `await client.post(url)`.

    The f-string is not inside the call, so the verb is found by looking
    forward for the first request that passes this variable.
    """
    if not var:
        return None
    pattern = re.compile(
        r"\.\s*(get|post|put|patch|delete|head)\s*\(\s*" + re.escape(var) + r"\s*[,)]",
        re.IGNORECASE)
    match = pattern.search(content, start, min(len(content), start + 1200))
    return match.group(1).upper() if match else None


def _extract_python(content: str, sites: list[HttpCallSite]) -> None:
    for match in _PY_CALL.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(3), "requests", f_string=match.group(2) == "f")
    for match in _PY_FSTRING_BASE.finditer(content):
        verb = _enclosing_call_verb(content, match.start())
        if verb is None:
            assigned = _PY_ASSIGN_TARGET.search(content, max(0, match.start() - 120),
                                                match.start())
            verb = _assigned_var_verb(content, match.end(),
                                      assigned.group(1) if assigned else "")
        if verb is None:
            continue
        _add(sites, content, match.start(), verb, match.group(2),
             "httpx", f_string=True, base_var=_base_var_name(match.group(1)))
    seen: set[int] = set()
    for var in sorted({m.group(1) for m in _PY_SESSION_ASSIGN.finditer(content)}):
        verb_call = re.compile(
            rf"\b{re.escape(var)}\s*\.\s*(get|post|put|delete|patch|head)"
            r"\s*\(\s*(f?)[\"']([^\"']+)")
        for match in verb_call.finditer(content):
            seen.add(match.start())
            _add(sites, content, match.start(), match.group(1).upper(),
                 match.group(3), "requests", f_string=match.group(2) == "f")
    for match in _PY_SESSION_VERB.finditer(content):
        if match.start() in seen:
            continue
        if not match.group(3).startswith(("http://", "https://", "/")):
            continue
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(3), "session", f_string=match.group(2) == "f")
    for match in _PY_REQUEST_FIRST.finditer(content):
        if match.group(2) not in _VERBS:
            continue
        receiver = match.group(1).lower()
        client = ("aiohttp" if receiver == "aiohttp"
                  else "requests" if receiver in ("requests", "httpx")
                  else "urllib3")
        _add(sites, content, match.start(), match.group(2), match.group(4),
             client, f_string=match.group(3) == "f")


def _extract_csharp(content: str, sites: list[HttpCallSite]) -> None:
    for match in _CS_HTTP_VERB.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(3), "httpclient",
             interpolated="$" in match.group(2),
             concatenated=_is_concatenated(content, match.end()))
    for match in _CS_BASE_ADDRESS.finditer(content):
        _add(sites, content, match.start(), "GET", match.group(1), "httpclient",
             base_url=True)
    for match in _CS_RESTSHARP_CLIENT.finditer(content):
        _add(sites, content, match.start(), "GET", match.group(1), "restsharp",
             base_url=True)
    for match in _CS_RESTSHARP_REQUEST.finditer(content):
        verb = (match.group(2) or "").upper()
        _add(sites, content, match.start(),
             verb if verb in _VERBS else "GET", match.group(1), "restsharp",
             method_inferred=verb not in _VERBS)
    for match in _CS_REFIT.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(2), "refit")


def _extract_go(content: str, sites: list[HttpCallSite]) -> None:
    for match in _GO_HTTP_HELPER.finditer(content):
        name = match.group(1)
        _add(sites, content, match.start(),
             "POST" if name == "PostForm" else name.upper(), match.group(2),
             "net/http", concatenated=_is_concatenated(content, match.end()))
    for pattern in (_GO_NEW_REQUEST, _GO_NEW_REQUEST_CTX):
        for match in pattern.finditer(content):
            verb = (match.group(1) or match.group(2) or "").upper()
            if verb not in _VERBS:
                continue
            _add(sites, content, match.start(), verb, match.group(3),
                 "net/http", concatenated=_is_concatenated(content, match.end()))
    for match in _GO_RESTY_CHAIN.finditer(content):
        _add(sites, content, match.start(2), match.group(1).upper(),
             match.group(2), "resty",
             concatenated=_is_concatenated(content, match.end()))
    for match in _GO_RESTY_BASE.finditer(content):
        _add(sites, content, match.start(), "GET", match.group(1), "resty",
             base_url=True)


def _extract_ruby(content: str, sites: list[HttpCallSite]) -> None:
    for match in _RB_NET_HTTP.finditer(content):
        verb = "POST" if match.group(1) == "post_form" else match.group(1).upper()
        _add(sites, content, match.start(), verb,
             _RB_INTERP.sub("{}", match.group(2)), "net_http",
             interpolated="#{" in match.group(2))
    for match in _RB_LIB_VERB.finditer(content):
        _add(sites, content, match.start(), match.group(2).upper(),
             _RB_INTERP.sub("{}", match.group(3)), match.group(1).lower(),
             interpolated="#{" in match.group(3))


def _extract_php(content: str, sites: list[HttpCallSite]) -> None:
    for match in _PHP_CLIENT_VERB.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(2), "guzzle")
    for match in _PHP_REQUEST.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(2), "guzzle")
    for match in _PHP_HTTP_FACADE.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(2), "laravel_http")
    for match in _PHP_CURL.finditer(content):
        _add(sites, content, match.start(), "GET", match.group(1), "curl",
             method_inferred=True)


def _extract_rust(content: str, sites: list[HttpCallSite]) -> None:
    for match in _RUST_REQWEST_GET.finditer(content):
        _add(sites, content, match.start(), "GET", match.group(1), "reqwest")
    for match in _RUST_CLIENT_VERB.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(2), "reqwest")


def _add(sites: list[HttpCallSite], content: str, pos: int, method: str,
         raw_url: str, client: str, **attr_flags) -> None:
    parsed = classify_url(raw_url)
    if parsed is None:
        return
    host, hint, hint_source, path, attrs = parsed
    # Flags stay booleans; a value carrying information (base_var) is kept
    # as-is rather than collapsed to True.
    attrs.update({k: (True if v is True else v)
                  for k, v in attr_flags.items() if v})
    if attrs.get("concatenated") and path.endswith("/"):
        path += "{}"
    template = canonicalize_path_template(_DYNAMIC.sub("{}", path.split("?")[0]))
    sites.append(HttpCallSite(
        method=method, raw_url=raw_url, path_template=template, host=host,
        service_hint=hint, hint_source=hint_source,
        line=_line_of(content, pos), client=client, attrs=attrs,
    ))


def _window_end(content: str, start: int, cap: int, *stops: str) -> int:
    """End of a verb-lookahead window: capped, and cut at statement/next-chain
    markers so one builder chain cannot borrow the next chain's verb."""
    end = min(len(content), start + cap)
    for stop in stops:
        idx = content.find(stop, start, end)
        if idx != -1:
            end = idx
    return end


def _verb_after(content: str, start: int, endpos: int,
                pattern: re.Pattern) -> tuple[str, bool]:
    """First HTTP verb a builder chain sets after its URL, else GET (inferred)."""
    match = pattern.search(content, start, endpos)
    if match:
        verb = next((g for g in match.groups() if g), "").upper()
        if verb in _VERBS:
            return verb, False
    return "GET", True


def _is_concatenated(content: str, end: int) -> bool:
    return content[end:end + 8].lstrip().startswith("+")


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1
