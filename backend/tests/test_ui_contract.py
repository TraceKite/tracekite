"""J6: the UI works against the published API alone.

`lib/api-spec/openapi.yaml` is a stub nothing imports; the live contract
is `frontend/src/lib/api.ts`, kept in step with the routes BY HAND — and
"by hand" is a promise, not a check. This test turns it into a check:
every endpoint the UI can reach is extracted from api.ts and must match
a route the server actually serves, method included. A UI call the
server cannot answer fails here, not in a browser three weeks later.

The companion sweep pins the boundary the other way: api.ts is the ONLY
module in frontend/src that talks to the backend, so "works against the
published API alone" stays true by construction — a component fetching a
private URL would have to add it here, where this test sees it.
"""

import os
import re

from fastapi.routing import APIRoute

from adduce.routes import graph, health, jobs, links, repos, rollup, trace

# The same seven routers main.py includes — the published surface.
ROUTERS = (health.router, repos.router, jobs.router, graph.router,
           links.router, trace.router, rollup.router)

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "frontend", "src")

# `${API_BASE}/api/repos/${repoId}/graph` -> ("GET"?, "/api/repos/{}/graph")
_UI_CALL = re.compile(
    r"fetch(?:Json[^(]*)?\(\s*`\$\{API_BASE\}([^`?]+)[`?]")
_METHOD = re.compile(r'method:\s*"(GET|POST|PUT|PATCH|DELETE)"')
_PARAM = re.compile(r"\$\{[^}]+\}")


def _positional(path: str) -> str:
    path = _PARAM.sub("{}", path)
    return re.sub(r"\{[^}]*\}", "{}", path)


def ui_endpoints() -> list[tuple[str, str]]:
    text = open(os.path.join(FRONTEND, "lib", "api.ts"),
                encoding="utf-8").read()
    matches = list(_UI_CALL.finditer(text))
    calls = []
    for index, match in enumerate(matches):
        # The method rides in the options object of the SAME call, so the
        # searchable window ends where the next call begins — a longer one
        # bleeds the neighbour's method onto this URL.
        end = (matches[index + 1].start()
               if index + 1 < len(matches) else len(text))
        method_match = _METHOD.search(text[match.end():end])
        method = method_match.group(1) if method_match else "GET"
        calls.append((method, _positional(match.group(1))))
    return sorted(set(calls))


def served_routes() -> set[tuple[str, str]]:
    served = set()
    for router in ROUTERS:
        for route in router.routes:
            if isinstance(route, APIRoute):
                for method in route.methods:
                    served.add((method, _positional(route.path)))
    return served


class TestUiContract:
    def test_the_extractor_actually_extracts(self):
        endpoints = ui_endpoints()
        assert len(endpoints) >= 10, endpoints
        assert ("GET", "/api/repos") in endpoints
        assert ("DELETE", "/api/repos/{}") in endpoints

    def test_every_ui_endpoint_is_a_served_route(self):
        served = served_routes()
        unserved = [(m, p) for m, p in ui_endpoints()
                    if (m, p) not in served]
        assert not unserved, (
            f"api.ts calls endpoints the server does not serve: {unserved}. "
            "Either the route moved or the UI is reaching past the "
            "published API.")

    def test_api_ts_is_the_only_module_talking_to_the_backend(self):
        offenders = []
        for dirpath, _dirs, names in os.walk(FRONTEND):
            for name in names:
                if not name.endswith((".ts", ".tsx")):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, FRONTEND)
                if rel == os.path.join("lib", "api.ts"):
                    continue
                text = open(path, encoding="utf-8").read()
                if re.search(r"\bfetch\s*\(", text) or "API_BASE" in text:
                    offenders.append(rel)
        assert not offenders, (
            f"{offenders} reach the network directly; the published API "
            "surface lives in lib/api.ts alone")
