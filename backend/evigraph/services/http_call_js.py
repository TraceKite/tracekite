"""JS/TS call-site patterns: fetch, axios, got/ky, SWR, RTK Query, MFE.

One language's block of `http_call_extractor`, moved out whole when that
file hit its size limit — the per-variant-module shape the parser registry
already uses. It contributes matches through the same `_add` pipeline, so
classification and template rules cannot drift between languages.
"""

import re

from evigraph.services.http_call_extractor import (
    HttpCallSite, _add, _is_concatenated, _window_end,
)

_FETCH = re.compile(r"\bfetch\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
_WEBSOCKET = re.compile(
    r"\bnew\s+WebSocket\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
_EVENTSOURCE = re.compile(
    r"\bnew\s+EventSource\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
_FETCH_METHOD = re.compile(r"method\s*:\s*['\"]([A-Za-z]+)['\"]")
_AXIOS_VERB = re.compile(r"\baxios\.(get|post|put|delete|patch|head)\s*\(\s*[`'\"]([^`'\"]+)")
_AXIOS_CONFIG = re.compile(r"\baxios\s*\(\s*\{[\s\S]{0,200}?url\s*:\s*[`'\"]([^`'\"]+)")
_NG_HTTP = re.compile(r"\$http\.(get|post|put|delete|patch|head)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")

# got/ky: bare call defaults to GET unless an options method: appears.
_GOT_KY = re.compile(
    r"\b(got|ky)(?:\.(get|post|put|delete|patch|head))?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
# superagent's default binding name is `request`, so both receivers are gated
# on the superagent import actually appearing in the file.
_SUPERAGENT_IMPORT = re.compile(
    r"require\s*\(\s*['\"]superagent['\"]\s*\)|from\s+['\"]superagent['\"]")
_SUPERAGENT_VERB = re.compile(
    r"\b(?:superagent|request)\s*\.\s*(get|post|put|delete|patch|head|del)"
    r"\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
_UNDICI_IMPORT = re.compile(
    r"require\s*\(\s*['\"]undici['\"]\s*\)|from\s+['\"]undici['\"]")
_UNDICI_REQUEST = re.compile(
    r"\bundici\s*\.\s*request\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
# Destructured `const { request } = require('undici')`; lookbehind keeps
# `.request(` member calls (axios.request etc.) out of this rule.
_BARE_REQUEST = re.compile(r"(?<![.\w])request\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")

# React data fetching. The SWR key doubles as the request URL only
# when it is URL-shaped, so bare cache keys never become call sites. RTK Query
# patterns are gated on the createApi/fetchBaseQuery marker because `url:` is
# far too common a property name on its own.
_SWR = re.compile(r"\buseSWR(?:Immutable|Infinite)?\s*\(\s*[`'\"]([^`'\"]+)")
_RTK_MARKER = re.compile(r"\bcreateApi\s*\(|\bfetchBaseQuery\s*\(")
_RTK_BASE = re.compile(
    r"fetchBaseQuery\s*\(\s*\{[^}]*?baseUrl\s*:\s*[`'\"]([^`'\"]+)")
_RTK_ENDPOINT = re.compile(
    r"\bquery\s*:\s*\(?[^)=\n]*\)?\s*=>\s*[`'\"](/[^`'\"]*)"
    r"|\burl\s*:\s*[`'\"](/[^`'\"]+)")

# Module federation: remotes: { shop: 'shop@https://x/remoteEntry.js' }
_MFE_REMOTE = re.compile(r"['\"]?(\w+)['\"]?\s*:\s*['\"](?:\w+@)?"
                         r"(https?://[^'\"]+remoteEntry\.js)['\"]")


def extract_js(content: str, sites: list[HttpCallSite]) -> None:
    # Channels first: a WebSocket or EventSource constructor is a consumer
    # of a long-lived contract, joined like any GET.
    for match in _WEBSOCKET.finditer(content):
        _add(sites, content, match.start(), "GET", match.group(1),
             "websocket", channel="websocket")
    for match in _EVENTSOURCE.finditer(content):
        _add(sites, content, match.start(), "GET", match.group(1),
             "eventsource", channel="sse")
    for match in _FETCH.finditer(content):
        window = content[match.end():match.end() + 240]
        method_match = _FETCH_METHOD.search(window)
        method = method_match.group(1).upper() if method_match else "GET"
        _add(sites, content, match.start(), method, match.group(1), "fetch",
             method_inferred=method_match is None)
    for match in _AXIOS_VERB.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(2), "axios")
    for match in _AXIOS_CONFIG.finditer(content):
        window = content[match.start():match.end() + 200]
        method_match = _FETCH_METHOD.search(window)
        method = method_match.group(1).upper() if method_match else "GET"
        _add(sites, content, match.start(), method, match.group(1), "axios",
             method_inferred=method_match is None)
    for match in _NG_HTTP.finditer(content):
        _add(sites, content, match.start(), match.group(1).upper(),
             match.group(2), "angular",
             concatenated=_is_concatenated(content, match.end()))
    for match in _GOT_KY.finditer(content):
        verb = match.group(2)
        if verb:
            method, inferred = verb.upper(), False
        else:
            method_match = _FETCH_METHOD.search(
                content, match.end(), _window_end(content, match.end(), 240, ";"))
            method = method_match.group(1).upper() if method_match else "GET"
            inferred = method_match is None
        _add(sites, content, match.start(), method, match.group(3),
             match.group(1), method_inferred=inferred)
    if _SUPERAGENT_IMPORT.search(content):
        for match in _SUPERAGENT_VERB.finditer(content):
            verb = match.group(1)
            _add(sites, content, match.start(),
                 "DELETE" if verb == "del" else verb.upper(),
                 match.group(2), "superagent")
    undici_calls = list(_UNDICI_REQUEST.finditer(content))
    if _UNDICI_IMPORT.search(content):
        undici_calls += list(_BARE_REQUEST.finditer(content))
    for match in undici_calls:
        method_match = _FETCH_METHOD.search(
            content, match.end(), _window_end(content, match.end(), 240, ";"))
        method = method_match.group(1).upper() if method_match else "GET"
        _add(sites, content, match.start(), method, match.group(1), "undici",
             method_inferred=method_match is None)

    # React data fetching: the SWR key IS the request URL, and RTK
    # Query endpoints are relative paths against a fetchBaseQuery base.
    for match in _SWR.finditer(content):
        url = match.group(1)
        if url.startswith(("/", "http")):
            _add(sites, content, match.start(), "GET", url, "swr")
    if _RTK_MARKER.search(content):
        for match in _RTK_BASE.finditer(content):
            _add(sites, content, match.start(), "GET", match.group(1),
                 "rtk-query", method_inferred=True)
        for match in _RTK_ENDPOINT.finditer(content):
            _add(sites, content, match.start(), "GET", match.group(1),
                 "rtk-query", method_inferred=True)

    # Module federation remotes: `shop@https://host/remoteEntry.js`
    # is a build-time dependency on another deployed frontend.
    if "ModuleFederationPlugin" in content or "federation(" in content:
        for match in _MFE_REMOTE.finditer(content):
            before = len(sites)
            _add(sites, content, match.start(), "GET", match.group(2),
                 "module-federation", method_inferred=True)
            for site in sites[before:]:
                site.service_hint = site.service_hint or match.group(1)
                if site.hint_source == "none":
                    site.hint_source = "config"
                site.attrs["module_federation"] = True
                site.attrs["remote"] = match.group(1)
