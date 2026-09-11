"""Classify one URL literal: who it points at, and how sure we are.

Extracted from `http_call_extractor.py`, which is per-language pattern
matching; this is the language-independent half — given the string a call
site holds, decide the host, the service hint and its source, and the path.
The distinction between a hint and a fact lives here: `lb://billing` names a
service by discovery, `http://billing:8080` names one by literal host, and a
bare `/v1/items` names nothing at all — three different downstream joins.
"""

import re

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal")
_RELATIVE = re.compile(r"[A-Za-z0-9_.-]+(/|$)")


def classify_url(url: str):
    attrs: dict = {}
    if url.startswith("lb://"):
        rest = url[5:]
        host, _, path = rest.partition("/")
        attrs["discovery"] = True
        result = _host_hint(host, attrs, "/" + path if path else "/")
        if result[1]:
            return result[0], result[1], "discovery", result[3], result[4]
        return result
    if url.startswith(("ws://", "wss://")):
        # A websocket URL names its host the same way http does; the
        # upgrade happens after the TCP connect and changes nothing about
        # who is being depended on.
        scheme_end = url.index("//") + 2
        rest = url[scheme_end:]
        host, _, path = rest.partition("/")
        return _host_hint(host, attrs, "/" + path if path else "/")
    if url.startswith(("http://", "https://")):
        scheme_end = url.index("//") + 2
        rest = url[scheme_end:]
        host, _, path = rest.partition("/")
        return _host_hint(host, attrs, "/" + path if path else "/")
    if url.startswith("${"):
        attrs["env_ref"] = True
        tail = url.partition("}")[2]
        path = tail if tail.startswith("/") else f"/{tail}" if tail else "/"
        return None, None, "none", path, attrs
    if url.startswith("/"):
        return None, None, "none", url, attrs
    if _RELATIVE.match(url):
        return None, None, "none", "/" + url, attrs
    return None


def _host_hint(host_port: str, attrs: dict, path: str):
    host = host_port.split(":")[0].lower()
    if "${" in host or not host:
        attrs["env_ref"] = True
        return None, None, "none", path, attrs
    if host in _LOCAL_HOSTS:
        attrs["local"] = True
        return host, None, "none", path, attrs
    bare = host.split(".")[0]
    if "." not in host or host.endswith((".svc", ".local", ".svc.cluster.local")):
        return host, bare, "host", path, attrs
    attrs["external"] = True
    return host, None, "none", path, attrs
