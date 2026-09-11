"""API-gateway / proxy route-table parsing.

Every gateway config format here reduces to one claim shape: "requests
matching PATH (and optionally HOST) forward to TARGET, with these rewrite
semantics". That uniform shape is what the R4 gateway resolver consumes
(generalized rewrite semantics), so a single GatewayRouteRule
covers NGINX conf, Envoy route_config, Kong declarative,
Traefik file provider + docker labels, Next.js
rewrites/redirects/basePath and http-proxy-middleware / Vite /
webpack devServer proxies.

Precision-first: a dynamic target (nginx variables, ``${BACKEND_URL}``
templates, ``process.env.X``) keeps its rule — the route exists and is
graph-worthy — but ``target`` stays ``""`` with ``attrs["dynamic"] = True``
(plus ``attrs["env_ref"]`` when the variable names an env key), so the
resolver declines instead of guessing. Malformed input never raises.

Targets are normalized to a bare host / service name (scheme and port
stripped, port kept in ``attrs["port"]``) because that is the join key the
linker matches against compose service names and k8s Services.
"""

import json
import logging
import re
from dataclasses import dataclass, field

import yaml
from tracekite.parsers.yaml_shapes import as_list as _as_list, as_str as _str

logger = logging.getLogger(__name__)


@dataclass
class GatewayRouteRule:
    """One "PATH (+HOST) forwards to TARGET" claim, format-agnostic."""
    gateway_kind: str    # nginx | envoy | kong | traefik | next-rewrite | next-redirect | js-proxy
    match_path: str      # path or prefix as written, normalized to lead with /
    target: str          # upstream service name or host ("" when dynamic)
    match_host: str = ""
    strip_prefix: bool = False   # matched prefix removed before forwarding
    rewrite_to: str = ""         # explicit rewrite template / regex replacement
    weight: int | None = None
    line: int = 0
    attrs: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

_ENV_TEMPLATE = re.compile(r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}")
_PROCESS_ENV = re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)")
_URL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.IGNORECASE)


def _norm_path(path: str) -> str:
    path = (path or "").strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def _dynamic_attrs(raw: str) -> dict | None:
    """Attrs for a dynamic target, or None when the target is concrete."""
    if match := _ENV_TEMPLATE.search(raw):
        return {"dynamic": True, "env_ref": match.group(1)}
    if match := _PROCESS_ENV.search(raw):
        return {"dynamic": True, "env_ref": match.group(1)}
    if "$" in raw:
        return {"dynamic": True}
    return None


def _split_url(raw: str) -> tuple[str, int | None, str]:
    """(host, port, path) from a URL-ish string; host "" when unparseable."""
    rest = raw.strip()
    if _URL.match(rest):
        rest = rest.split("//", 1)[1]
    elif rest.startswith("//"):
        rest = rest[2:]
    host_port, _, path = rest.partition("/")
    host_port = host_port.rsplit("@", 1)[-1]          # drop userinfo
    host, _, port_text = host_port.partition(":")
    port = int(port_text) if port_text.isdigit() else None
    return host, port, ("/" + path if path else "")


def _target_from_url(raw: str, attrs: dict) -> str:
    """Resolve a URL-ish target to a bare host, flagging dynamic ones."""
    if dyn := _dynamic_attrs(raw):
        attrs.update(dyn)
        return ""
    host, port, _ = _split_url(raw)
    if port is not None:
        attrs["port"] = port
    return host

def _line_of(content: str, needle: str, start: int = 0) -> int:
    idx = content.find(needle, start) if needle else -1
    return content.count("\n", 0, idx) + 1 if idx >= 0 else 0




def _safe_yaml(content: str, require: str = ""):
    """The YAML document the caller wants, from a possibly multi-document file.

    Anything deployed as Kubernetes manifests routinely ships several
    documents in one file -- a ConfigMap, then the config it carries, then a
    Service, `---` between each. `yaml.safe_load` RAISES on the second
    document, so reading a route table that way discarded the entire file and
    reported no routes at all rather than failing loudly.

    `require` names the top-level key that identifies the interesting document
    (`http` for Traefik, `services` for Kong). Falling back to the first
    mapping keeps single-document files behaving exactly as before.
    """
    try:
        docs = [d for d in yaml.safe_load_all(content) if isinstance(d, dict)]
    except yaml.YAMLError:
        return None
    if require:
        for doc in docs:
            if require in doc:
                return doc
    return docs[0] if docs else None


def _balanced(content: str, open_idx: int) -> int:
    """Index just past the bracket that closes content[open_idx].

    Tracks ' " ` strings and // line comments so braces inside them do not
    count. Returns len(content) when never closed (caller gets the tail —
    for our per-rule extraction an over-long span degrades, not corrupts).
    """
    pairs = {"{": "}", "(": ")", "[": "]"}
    close = pairs.get(content[open_idx])
    if close is None:
        return open_idx + 1
    depth, index, quote = 0, open_idx, ""
    while index < len(content):
        char = content[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif char == "/" and content[index:index + 2] == "//":
            index = content.find("\n", index)
            if index < 0:
                return len(content)
        elif char in pairs:
            depth += 1
        elif char in pairs.values():
            if char == close:
                depth -= 1
                if depth == 0:
                    return index + 1
            # mismatched closer inside: ignore, JS regexes make these noisy
        index += 1
    return len(content)


# --------------------------------------------------------------------------
# NGINX
# --------------------------------------------------------------------------

_NGINX_COMMENT = re.compile(r"#[^\n]*")
_NGINX_BLOCK = re.compile(
    r"(?m)^[ \t]*(upstream[ \t]+(?P<upstream>[^\s{]+)"
    r"|server"
    r"|location[ \t]+(?:(?P<mod>=|\^~|~\*|~)[ \t]+)?(?P<path>[^\s{]+)"
    r")[ \t]*\{")
_NGINX_SERVER_NAME = re.compile(r"(?m)^\s*server_name\s+([^;]+);")
_NGINX_PROXY_PASS = re.compile(r"(?m)^\s*proxy_pass\s+([^;\s]+)\s*;")
_NGINX_REWRITE = re.compile(
    r"(?m)^\s*rewrite\s+(\S+)\s+(\S+)(?:\s+(last|break|redirect|permanent))?\s*;")
_NGINX_UPSTREAM_SERVER = re.compile(r"(?m)^\s*server\s+([^;\s]+)([^;]*);")


def _nginx_blocks(content: str, start: int, end: int):
    """Yield (match, body_start, body_end) for blocks in content[start:end]."""
    index = start
    while index < end:
        match = _NGINX_BLOCK.search(content, index, end)
        if not match:
            return
        open_idx = content.index("{", match.end() - 1)
        close_idx = _balanced(content, open_idx)
        yield match, open_idx + 1, min(close_idx - 1, end)
        index = close_idx


def _nginx_upstreams(content: str) -> dict[str, str]:
    """upstream name -> first non-backup/down server host (port stripped)."""
    upstreams: dict[str, str] = {}
    for match, body_start, body_end in _nginx_blocks(content, 0, len(content)):
        name = match.group("upstream")
        if not name:
            continue
        body = content[body_start:body_end]
        for server in _NGINX_UPSTREAM_SERVER.finditer(body):
            address, flags = server.group(1), server.group(2)
            if "backup" in flags or "down" in flags:
                continue
            if address.startswith("unix:"):
                continue
            host, _, _ = _split_url("//" + address)
            if host:
                upstreams[name] = host
                break
    return upstreams


def _nginx_location_rules(content: str, start: int, end: int, host: str,
                          upstreams: dict[str, str]) -> list[GatewayRouteRule]:
    rules: list[GatewayRouteRule] = []
    for match, body_start, body_end in _nginx_blocks(content, start, end):
        raw_path = match.group("path")
        if raw_path is None:
            continue                       # nested plain `server` never occurs
        modifier = match.group("mod") or ""
        body = content[body_start:body_end]

        # Nested locations first — their rules stand on their own. Their
        # spans are then blanked out of this location's body so a nested
        # proxy_pass is not double-counted by the enclosing location.
        for nested, _, nested_end in _nginx_blocks(content, body_start,
                                                   body_end):
            span_start = nested.start() - body_start
            span_end = nested_end + 1 - body_start
            body = (body[:span_start] + " " * (span_end - span_start)
                    + body[span_end:])
        rules += _nginx_location_rules(content, body_start, body_end, host,
                                       upstreams)

        proxy = _NGINX_PROXY_PASS.search(body)
        if not proxy:
            continue                       # return/redirect-only: skip

        attrs: dict = {}
        path = raw_path
        if modifier in ("~", "~*"):
            attrs["regex"] = True
            attrs["pattern"] = raw_path
            path = raw_path.lstrip("^").rstrip("$")
            if modifier == "~*":
                attrs["case_insensitive"] = True
        elif modifier == "=":
            attrs["exact"] = True

        rule = GatewayRouteRule(
            gateway_kind="nginx", match_path=_norm_path(path), target="",
            match_host=host, attrs=attrs,
            line=content.count("\n", 0, match.start()) + 1)

        raw_target = proxy.group(1)
        if dyn := _dynamic_attrs(raw_target):
            attrs.update(dyn)
        else:
            host_part, port, uri = _split_url(raw_target)
            if host_part in upstreams:
                rule.target = upstreams[host_part]
                attrs["upstream"] = host_part
            else:
                rule.target = host_part
                if port is not None:
                    attrs["port"] = port
            # CRITICAL nginx semantic: a proxy_pass WITH a URI part (even a
            # bare trailing /) replaces the matched location prefix; without
            # one the full original path is forwarded unchanged.
            if uri or raw_target.rstrip().endswith("/"):
                rule.strip_prefix = True
                if uri and uri != "/":
                    rule.rewrite_to = uri

        for rewrite in _NGINX_REWRITE.finditer(body):
            pattern, replacement, flag = rewrite.groups()
            if flag in ("redirect", "permanent"):
                continue                   # ignore redirect rewrites
            rule.rewrite_to = replacement
            rule.strip_prefix = True       # replacement defines the new path
            attrs["rewrite_pattern"] = pattern
            break
        rules.append(rule)
    return rules


def parse_nginx_conf(file_path: str, content: str) -> list[GatewayRouteRule]:
    """NGINX server/location/proxy_pass route table."""
    try:
        content = _NGINX_COMMENT.sub("", content)
        upstreams = _nginx_upstreams(content)
        rules: list[GatewayRouteRule] = []
        for match, body_start, body_end in _nginx_blocks(content, 0,
                                                         len(content)):
            if match.group("upstream"):
                continue
            if match.group("path") is not None:
                # Bare location outside a server block: an included snippet.
                rules += _nginx_location_rules(content, match.start(),
                                               body_end + 1, "", upstreams)
                continue
            body = content[body_start:body_end]
            host = ""
            if names := _NGINX_SERVER_NAME.search(body):
                candidates = [n for n in names.group(1).split()
                              if n and n not in ("_", "localhost")]
                host = candidates[0] if candidates else ""
            rules += _nginx_location_rules(content, body_start, body_end,
                                           host, upstreams)
        return rules
    except Exception as exc:               # never raise on malformed input
        logger.debug("nginx parse failed for %s: %s", file_path, exc)
        return []


# --------------------------------------------------------------------------
# Envoy
# --------------------------------------------------------------------------

def _envoy_clusters(data) -> dict[str, str]:
    """cluster name -> first endpoint address (fallback handled by caller)."""
    clusters: dict[str, str] = {}
    static = data.get("static_resources") if isinstance(data, dict) else None
    for cluster in _as_list((static or data).get("clusters")
                            if isinstance(static or data, dict) else None):
        if not isinstance(cluster, dict) or not cluster.get("name"):
            continue
        name, address = _str(cluster["name"]), ""
        assignment = cluster.get("load_assignment") or {}
        for endpoint_group in _as_list(assignment.get("endpoints")):
            if not isinstance(endpoint_group, dict):
                continue
            for lb in _as_list(endpoint_group.get("lb_endpoints")):
                socket = (((lb or {}).get("endpoint") or {})
                          .get("address") or {}).get("socket_address") or {}
                if socket.get("address"):
                    address = _str(socket["address"])
                    break
            if address:
                break
        clusters[name] = address
    return clusters


def _walk_virtual_hosts(node):
    """Yield every virtual_hosts list anywhere in the config tree.

    Deep-walking beats hardcoding listeners[].filter_chains[].filters[]
    paths: typed_config vs config vs a standalone route-config file all
    carry virtual_hosts, and a missed nesting level would silently drop
    every route.
    """
    if isinstance(node, dict):
        hosts = node.get("virtual_hosts")
        if isinstance(hosts, list):
            yield hosts
        for value in node.values():
            yield from _walk_virtual_hosts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_virtual_hosts(value)


def _envoy_route_rules(route: dict, host: str, clusters: dict[str, str],
                       content: str) -> list[GatewayRouteRule]:
    match = route.get("match") or {}
    action = route.get("route") or {}
    if not isinstance(match, dict) or not isinstance(action, dict):
        return []

    attrs: dict = {}
    if "prefix" in match:
        path, needle = _str(match["prefix"]), _str(match["prefix"])
    elif "path" in match:
        path, needle = _str(match["path"]), _str(match["path"])
        attrs["exact"] = True
    elif isinstance(match.get("safe_regex"), dict):
        path = needle = _str(match["safe_regex"].get("regex"))
        attrs["regex"] = True
        attrs["pattern"] = path
        path = path.lstrip("^").rstrip("$")
    else:
        return []

    rewrite_to, strip = "", False
    if action.get("prefix_rewrite") is not None:
        rewrite_to, strip = _str(action["prefix_rewrite"]), True
    elif isinstance(action.get("regex_rewrite"), dict):
        rewrite_to = _str(action["regex_rewrite"].get("substitution"))
        attrs["regex"] = True

    def build(target_name: str, weight: int | None) -> GatewayRouteRule:
        rule_attrs = dict(attrs)
        target = ""
        if target_name:
            rule_attrs["cluster"] = target_name
            target = clusters.get(target_name) or target_name
        else:
            rule_attrs["dynamic"] = True   # cluster_header etc.
        return GatewayRouteRule(
            gateway_kind="envoy", match_path=_norm_path(path), target=target,
            match_host=host, strip_prefix=strip, rewrite_to=rewrite_to,
            weight=weight, attrs=rule_attrs, line=_line_of(content, needle))

    weighted = action.get("weighted_clusters") or {}
    if isinstance(weighted, dict) and isinstance(weighted.get("clusters"), list):
        return [build(_str(c.get("name")), c.get("weight")
                      if isinstance(c.get("weight"), int) else None)
                for c in weighted["clusters"] if isinstance(c, dict)]
    if action.get("cluster"):
        return [build(_str(action["cluster"]), None)]
    if action.get("cluster_header"):
        return [build("", None)]
    return []


def parse_envoy_config(file_path: str, content: str) -> list[GatewayRouteRule]:
    """Envoy static route_config -> cluster routes."""
    data = _safe_yaml(content, "static_resources")
    if not isinstance(data, dict):
        return []
    try:
        clusters = _envoy_clusters(data)
        rules: list[GatewayRouteRule] = []
        for virtual_hosts in _walk_virtual_hosts(data):
            for vhost in virtual_hosts:
                if not isinstance(vhost, dict):
                    continue
                domains = [_str(d) for d in _as_list(vhost.get("domains"))]
                host = next((d for d in domains if d and "*" not in d), "")
                for route in _as_list(vhost.get("routes")):
                    if isinstance(route, dict):
                        rules += _envoy_route_rules(route, host, clusters,
                                                    content)
        return rules
    except Exception as exc:
        logger.debug("envoy parse failed for %s: %s", file_path, exc)
        return []


# --------------------------------------------------------------------------
# Kong declarative
# --------------------------------------------------------------------------

def parse_kong_config(file_path: str, content: str) -> list[GatewayRouteRule]:
    """Kong declarative config (kong.yml).

    Kong's strip_path DEFAULTS TO TRUE — an absent key must become
    strip_prefix=True or every Kong route's path math is wrong downstream.
    """
    data = _safe_yaml(content, "services")
    if not isinstance(data, dict) or not isinstance(data.get("services"), list):
        return []
    try:
        rules: list[GatewayRouteRule] = []
        for service in data["services"]:
            if not isinstance(service, dict):
                continue
            service_attrs: dict = {}
            if service.get("url"):
                target = _target_from_url(_str(service["url"]), service_attrs)
                _, _, service_path = _split_url(_str(service["url"]))
            else:
                target = _str(service.get("host"))
                if dyn := _dynamic_attrs(target):
                    service_attrs.update(dyn)
                    target = ""
                if isinstance(service.get("port"), int):
                    service_attrs["port"] = service["port"]
                service_path = _str(service.get("path"))
            if service_path and service_path != "/":
                service_attrs["service_path"] = service_path

            for route in _as_list(service.get("routes")):
                if not isinstance(route, dict):
                    continue
                attrs = dict(service_attrs)
                if service.get("name"):
                    attrs["service"] = _str(service["name"])
                if route.get("name"):
                    attrs["route"] = _str(route["name"])
                methods = [_str(m) for m in _as_list(route.get("methods"))]
                if methods:
                    attrs["methods"] = methods
                hosts = [_str(h) for h in _as_list(route.get("hosts"))]
                strip = route.get("strip_path")
                strip = True if strip is None else bool(strip)

                paths = [_str(p) for p in _as_list(route.get("paths"))] or ["/"]
                for raw_path in paths:
                    path_attrs = dict(attrs)
                    if raw_path.startswith("~"):   # Kong 3.x regex marker
                        raw_path = raw_path[1:]
                        path_attrs["regex"] = True
                    rules.append(GatewayRouteRule(
                        gateway_kind="kong", match_path=_norm_path(raw_path),
                        target=target, match_host=hosts[0] if hosts else "",
                        strip_prefix=strip, attrs=path_attrs,
                        line=_line_of(content, raw_path)))
        return rules
    except Exception as exc:
        logger.debug("kong parse failed for %s: %s", file_path, exc)
        return []


# --------------------------------------------------------------------------
# Traefik: file provider YAML + docker labels
# --------------------------------------------------------------------------

_TRAEFIK_MATCHER = re.compile(
    r"(Host|PathPrefix|PathRegexp|Path)\s*\(([^)]*)\)")
_TRAEFIK_QUOTED = re.compile(r"[`'\"]([^`'\"]+)[`'\"]")
_TRAEFIK_ROUTER_LABEL = re.compile(
    r"^traefik\.http\.routers\.([^.]+)\.(rule|middlewares|service)$",
    re.IGNORECASE)
_TRAEFIK_STRIP_LABEL = re.compile(
    r"^traefik\.http\.middlewares\.([^.]+)\.stripprefix\.prefixes$",
    re.IGNORECASE)


def _traefik_rule_parts(rule: str) -> tuple[list[str], list[str], bool]:
    """(hosts, paths, regex) parsed from a Traefik rule expression."""
    hosts, paths, regex = [], [], False
    for matcher, args in _TRAEFIK_MATCHER.findall(rule or ""):
        values = _TRAEFIK_QUOTED.findall(args)
        if matcher == "Host":
            hosts += values
        else:
            paths += values
            if matcher == "PathRegexp":
                regex = True
    return hosts, paths, regex


def _traefik_emit(kind_attrs: dict, rule_expr: str, target: str, strip: bool,
                  line: int) -> list[GatewayRouteRule]:
    hosts, paths, regex = _traefik_rule_parts(rule_expr)
    attrs = dict(kind_attrs)
    if regex:
        attrs["regex"] = True
    host = hosts[0] if hosts else ""
    rules = []
    for path in paths or ["/"]:
        rules.append(GatewayRouteRule(
            gateway_kind="traefik", match_path=_norm_path(path),
            target=target, match_host=host, strip_prefix=strip,
            attrs=dict(attrs), line=line))
    return rules


def parse_traefik_file(file_path: str, content: str) -> list[GatewayRouteRule]:
    """Traefik file-provider YAML: http.routers/services/middlewares."""
    data = _safe_yaml(content, "http")
    if not isinstance(data, dict) or not isinstance(data.get("http"), dict):
        return []
    try:
        http = data["http"]
        services, strip_middlewares = {}, set()
        for name, service in (http.get("services") or {}).items():
            balancer = (service or {}).get("loadBalancer") or {}
            for server in _as_list(balancer.get("servers")):
                url = _str((server or {}).get("url")
                           or (server or {}).get("address"))
                if url:
                    services[_str(name)] = url
                    break
        for name, middleware in (http.get("middlewares") or {}).items():
            if isinstance(middleware, dict) and isinstance(
                    middleware.get("stripPrefix"), dict):
                strip_middlewares.add(_str(name))

        rules: list[GatewayRouteRule] = []
        for name, router in (http.get("routers") or {}).items():
            if not isinstance(router, dict):
                continue
            attrs: dict = {"router": _str(name)}
            service_ref = _str(router.get("service")).split("@")[0]
            if service_ref in services:
                target = _target_from_url(services[service_ref], attrs)
            else:
                target = service_ref
            middlewares = [_str(m).split("@")[0]
                           for m in _as_list(router.get("middlewares"))]
            strip = any(m in strip_middlewares for m in middlewares)
            rule_expr = _str(router.get("rule"))
            rules += _traefik_emit(attrs, rule_expr, target, strip,
                                   _line_of(content, "rule:",
                                            content.find(_str(name))))
        return rules
    except Exception as exc:
        logger.debug("traefik parse failed for %s: %s", file_path, exc)
        return []


def parse_traefik_labels(labels: list[str] | dict) -> list[GatewayRouteRule]:
    """Traefik docker labels on a compose service.

    The router name maps to the compose service the labels sit ON, so
    target stays "": the ingestion orchestrator binds it to the owning
    compose service. attrs["router"] carries the router name for that join.
    """
    try:
        if isinstance(labels, dict):
            items = [(str(k), _str(v)) for k, v in labels.items()]
        else:
            items = []
            for label in labels or []:
                key, _, value = str(label).partition("=")
                items.append((key.strip(), value.strip()))

        routers: dict[str, dict] = {}
        strip_middlewares: set[str] = set()
        for key, value in items:
            if router := _TRAEFIK_ROUTER_LABEL.match(key):
                routers.setdefault(router.group(1), {})[
                    router.group(2).lower()] = value
            elif strip := _TRAEFIK_STRIP_LABEL.match(key):
                strip_middlewares.add(strip.group(1))

        rules: list[GatewayRouteRule] = []
        for name, entries in routers.items():
            middlewares = [m.strip().split("@")[0]
                           for m in entries.get("middlewares", "").split(",")
                           if m.strip()]
            strip = any(m in strip_middlewares for m in middlewares)
            rules += _traefik_emit({"router": name}, entries.get("rule", ""),
                                   "", strip, 0)
        return rules
    except Exception as exc:
        logger.debug("traefik label parse failed: %s", exc)
        return []


# --------------------------------------------------------------------------
# Next.js next.config.(js|mjs|ts)
# --------------------------------------------------------------------------

_NEXT_SECTION = re.compile(r"\b(rewrites|redirects)\b")
_NEXT_ENTRY = re.compile(
    r"\{[^{}]*?\bsource\s*:\s*['\"`]([^'\"`]+)['\"`]"
    r"[^{}]*?\bdestination\s*:\s*['\"`]([^'\"`]+)['\"`][^{}]*?\}", re.DOTALL)
_NEXT_PERMANENT = re.compile(r"\bpermanent\s*:\s*(true|false)")
_NEXT_BASE_PATH = re.compile(r"\bbasePath\s*:\s*['\"`](/[^'\"`]*)['\"`]")
_NEXT_PARAM = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)(\*?)")


def _next_path(source: str) -> tuple[str, bool]:
    """Convert :param -> {param}; returns (path, had_wildcard)."""
    wildcard = False

    def replace(match: re.Match) -> str:
        nonlocal wildcard
        if match.group(2):
            wildcard = True
        return "{" + match.group(1) + "}"

    return _NEXT_PARAM.sub(replace, source), wildcard


def parse_next_config(file_path: str, content: str) -> list[GatewayRouteRule]:
    """Next.js rewrites/redirects/basePath.

    Object-literal scan, tolerant of TS and of async-function vs property
    style: each {source, destination} literal is classified by the nearest
    preceding ``rewrites``/``redirects`` keyword. Literals containing a
    nested ``has:`` array are a known gap (see module docstring).
    """
    try:
        sections = [(m.start(), m.group(1))
                    for m in _NEXT_SECTION.finditer(content)]
        rules: list[GatewayRouteRule] = []

        for entry in _NEXT_ENTRY.finditer(content):
            preceding = [kind for pos, kind in sections
                         if pos < entry.start()]
            if not preceding:
                continue                   # precision: unknown section
            kind = ("next-redirect" if preceding[-1] == "redirects"
                    else "next-rewrite")
            source, destination = entry.group(1), entry.group(2)

            attrs: dict = {}
            match_path, wildcard = _next_path(source)
            if wildcard:
                attrs["wildcard"] = True

            target, rewrite_to = "", ""
            if dyn := _dynamic_attrs(destination):
                attrs.update(dyn)
            elif _URL.match(destination):
                host, port, dest_path = _split_url(destination)
                target = host
                if port is not None:
                    attrs["port"] = port
                rewrite_to = _next_path(dest_path)[0] if dest_path else ""
            else:
                attrs["internal"] = True
                rewrite_to = _next_path(destination)[0]

            if kind == "next-redirect":
                if permanent := _NEXT_PERMANENT.search(entry.group(0)):
                    attrs["permanent"] = permanent.group(1) == "true"

            rules.append(GatewayRouteRule(
                gateway_kind=kind, match_path=_norm_path(match_path),
                target=target, rewrite_to=rewrite_to, attrs=attrs,
                line=content.count("\n", 0, entry.start()) + 1))

        if base := _NEXT_BASE_PATH.search(content):
            rules.append(GatewayRouteRule(
                gateway_kind="next-rewrite",
                match_path=_norm_path(base.group(1)), target="",
                attrs={"base_path": True},
                line=content.count("\n", 0, base.start()) + 1))
        return rules
    except Exception as exc:
        logger.debug("next config parse failed for %s: %s", file_path, exc)
        return []


# --------------------------------------------------------------------------
# JS proxies: http-proxy-middleware + Vite/webpack devServer
# --------------------------------------------------------------------------

_HPM_CALL = re.compile(r"createProxyMiddleware\s*\(")
_APP_USE = re.compile(r"(?:app|router)\s*\.\s*use\s*\(\s*['\"`]([^'\"`]+)['\"`]"
                      r"\s*,\s*$")
_JS_TARGET = re.compile(r"\btarget\s*:\s*(['\"`])([^'\"`]*)\1")
_JS_TARGET_DYNAMIC = re.compile(r"\btarget\s*:\s*([^,}\n]+)")
_PATH_REWRITE_ENTRY = re.compile(
    r"['\"`]\^?([^'\"`]+)['\"`]\s*:\s*['\"`]([^'\"`]*)['\"`]")
_JS_REWRITE_FN = re.compile(
    r"\brewrite\s*:.*?\.replace\s*\(\s*/(\^?)((?:\\.|[^/\\])*)/\s*,\s*"
    r"(['\"`])([^'\"`]*)\3", re.DOTALL)
_PROXY_OBJECT = re.compile(r"\bproxy\s*:\s*[{\[]")
_PROXY_KEY = re.compile(r"['\"`]([^'\"`]+)['\"`]\s*:")
_CONTEXT_LIST = re.compile(r"\bcontext\s*:\s*\[([^\]]*)\]")
_QUOTED_STR = re.compile(r"['\"`]([^'\"`]+)['\"`]")


def _js_target(options: str, attrs: dict) -> str:
    if literal := _JS_TARGET.search(options):
        return _target_from_url(literal.group(2), attrs)
    if raw := _JS_TARGET_DYNAMIC.search(options):
        attrs.update(_dynamic_attrs(raw.group(1)) or {"dynamic": True})
    return ""


def _js_rewrite(options: str, context: str, rule: GatewayRouteRule) -> None:
    """pathRewrite maps and rewrite() arrows -> strip/rewrite semantics."""
    if "pathRewrite" in options:
        tail = options[options.index("pathRewrite"):]
        brace = tail.find("{")
        if brace >= 0:
            body = tail[brace:_balanced(tail, brace)]
            for pattern, replacement in _PATH_REWRITE_ENTRY.findall(body):
                clean = pattern.replace("\\/", "/")
                if replacement == "" and context.startswith(_norm_path(clean)):
                    rule.strip_prefix = True
                else:
                    rule.rewrite_to = replacement
                    rule.attrs["rewrite_pattern"] = clean
                break
    elif fn := _JS_REWRITE_FN.search(options):
        anchored, pattern, _, replacement = fn.groups()
        clean = pattern.replace("\\/", "/")
        if replacement == "" and anchored:
            rule.strip_prefix = True
        else:
            rule.rewrite_to = replacement
            rule.attrs["rewrite_pattern"] = clean


def _hpm_rules(content: str) -> list[GatewayRouteRule]:
    rules = []
    for call in _HPM_CALL.finditer(content):
        open_idx = content.index("(", call.start())
        args = content[open_idx + 1:_balanced(content, open_idx) - 1]

        context = ""
        if first := re.match(r"\s*['\"`]([^'\"`]+)['\"`]", args):
            context = first.group(1)
        else:                              # app.use('/api', createProxy...)
            lead = content[max(0, call.start() - 120):call.start()]
            if use := _APP_USE.search(lead):
                context = use.group(1)

        rule = GatewayRouteRule(
            gateway_kind="js-proxy", match_path=_norm_path(context),
            target="", line=content.count("\n", 0, call.start()) + 1)
        rule.target = _js_target(args, rule.attrs)
        _js_rewrite(args, _norm_path(context), rule)
        rules.append(rule)
    return rules


def _proxy_map_rules(content: str) -> list[GatewayRouteRule]:
    """Vite server.proxy / webpack devServer.proxy objects (attrs dev)."""
    rules = []
    for proxy in _PROXY_OBJECT.finditer(content):
        open_idx = proxy.end() - 1
        body = content[open_idx:_balanced(content, open_idx)]
        line_base = content.count("\n", 0, open_idx)

        if body.startswith("["):           # webpack array form
            index = 1
            while index < len(body):
                brace = body.find("{", index)
                if brace < 0:
                    break
                end = _balanced(body, brace)
                entry = body[brace:end]
                contexts = ["/"]
                if ctx := _CONTEXT_LIST.search(entry):
                    contexts = _QUOTED_STR.findall(ctx.group(1)) or ["/"]
                for context in contexts:
                    rule = GatewayRouteRule(
                        gateway_kind="js-proxy",
                        match_path=_norm_path(context), target="",
                        attrs={"dev": True},
                        line=line_base + body.count("\n", 0, brace) + 1)
                    rule.target = _js_target(entry, rule.attrs)
                    _js_rewrite(entry, _norm_path(context), rule)
                    rules.append(rule)
                index = end
            continue

        # object form: '/api': 'http://x' | '/v2': { target: ..., rewrite }
        index = 1
        while index < len(body) - 1:
            key = _PROXY_KEY.search(body, index)
            if not key or not key.group(1).startswith("/"):
                break
            value_start = key.end()
            while value_start < len(body) and body[value_start] in " \t\r\n":
                value_start += 1
            rule = GatewayRouteRule(
                gateway_kind="js-proxy", match_path=_norm_path(key.group(1)),
                target="", attrs={"dev": True},
                line=line_base + body.count("\n", 0, key.start()) + 1)
            if value_start < len(body) and body[value_start] == "{":
                end = _balanced(body, value_start)
                options = body[value_start:end]
                rule.target = _js_target(options, rule.attrs)
                _js_rewrite(options, rule.match_path, rule)
                index = end
            elif literal := re.match(r"['\"`]([^'\"`]*)['\"`]",
                                     body[value_start:]):
                rule.target = _target_from_url(literal.group(1), rule.attrs)
                index = value_start + literal.end()
            else:
                index = value_start + 1
                continue                   # unparseable value: skip entry
            rules.append(rule)
    return rules


def parse_js_proxies(file_path: str, content: str) -> list[GatewayRouteRule]:
    """http-proxy-middleware + Vite/webpack devServer proxies."""
    try:
        return _hpm_rules(content) + _proxy_map_rules(content)
    except Exception as exc:
        logger.debug("js proxy parse failed for %s: %s", file_path, exc)
        return []


# --------------------------------------------------------------------------
# dispatcher
# --------------------------------------------------------------------------

def sniff_gateway_file(file_name: str, content: str) -> str:
    """Classify a file for gateway parsing; "" when not confidently one.

    Used by ingestion to dispatch. Precision-first: an unrecognized file
    returns "" rather than a guess.
    """
    try:
        base = file_name.rsplit("/", 1)[-1].lower()
        stem = base.rsplit(".", 1)[0]

        if base.startswith("next.config."):
            return "next"
        if (stem.startswith(("vite.config", "webpack.config"))
                or base == "setupproxy.js"):
            return "jsproxy"
        if base.endswith(".conf") and "proxy_pass" in content:
            return "nginx"
        if base.endswith((".yml", ".yaml")):
            if "_format_version" in content and "services" in content:
                return "kong"
            if "static_resources" in content or "virtual_hosts" in content:
                return "envoy"
            data = _safe_yaml(content, "http")
            if isinstance(data, dict) and isinstance(data.get("http"), dict) \
                    and "routers" in data["http"]:
                return "traefik"
            return ""
        if base.endswith((".js", ".mjs", ".cjs", ".ts", ".mts")):
            if "createProxyMiddleware" in content:
                return "jsproxy"
            if _PROXY_OBJECT.search(content) and ("devServer" in content
                                                  or "server" in content):
                return "jsproxy"
        return ""
    except Exception:
        return ""
