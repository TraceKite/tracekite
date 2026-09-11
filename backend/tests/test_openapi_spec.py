"""The checked-in OpenAPI document describes the API that exists.

`lib/api-spec/openapi.yaml` was scaffolding shaped like a contract: one
path, `/healthz`, which the backend does not serve — the health route is
`/health` — while nothing imported the client orval generates from it.
AGENTS.md lists reading it as a way to get a confident wrong answer.

It is now generated from the app, so the failure mode inverts: the file
can only be wrong by being stale, and staleness is what this test
catches. Deleting the scaffolding was the alternative; making it true
costs less and leaves the generated-client option open.

The route-set assertion is the one that matters. A byte comparison alone
would fail for a reordered schema and say nothing about coverage, so
both are checked and the route set is named in the failure.
"""

import os

from fastapi.routing import APIRoute

from tracekite.routes import graph, health, jobs, links, repos, rollup, trace
from tools.export_openapi import SPEC_PATH, build_spec, render

ROUTERS = (health.router, repos.router, jobs.router, graph.router,
           links.router, trace.router, rollup.router)


def served_paths() -> set[str]:
    return {route.path for router in ROUTERS for route in router.routes
            if isinstance(route, APIRoute)}


class TestCheckedInSpec:
    def test_the_file_exists_and_is_not_the_old_stub(self):
        assert os.path.exists(SPEC_PATH)
        with open(SPEC_PATH, encoding="utf-8") as handle:
            text = handle.read()
        assert "/healthz" not in text, (
            "the fictional stub path is back; regenerate from the app")
        assert "GENERATED from the FastAPI app" in text

    def test_every_served_route_is_documented(self):
        spec = build_spec()
        documented = set(spec.get("paths") or {})
        missing = sorted(served_paths() - documented)
        assert not missing, f"routes absent from the spec: {missing}"

    def test_the_checked_in_file_is_not_stale(self):
        with open(SPEC_PATH, encoding="utf-8") as handle:
            current = handle.read()
        assert current == render(build_spec()), (
            "lib/api-spec/openapi.yaml is stale — regenerate with "
            "`python backend/tools/export_openapi.py`")

    def test_the_title_orval_depends_on_is_pinned(self):
        # orval.config.ts derives its generated import paths from the title.
        assert build_spec()["info"]["title"] == "Api"
