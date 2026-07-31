"""A route whose path is computed is declined out loud, not silently.

Route extraction is precision-first: `r.HandleFunc(baseUrl+"/cart", h)` has
no literal path, so no endpoint is minted. That is correct — a guessed path
is an invented edge.

The bug was the silence. GoogleCloudPlatform/microservices-demo registers
thirteen gorilla/mux routes against a `baseUrl` prefix, and the ingest
reported `endpoints: 0` with no counter beside it, which reads as "this
service exposes no HTTP" rather than "thirteen paths were not literals".
Invariant I5: a decline is data.
"""

from types import SimpleNamespace

from adduce.services.framework_routes import computed_go_paths, framework_routes

# Shaped after src/frontend/main.go in that repository.
FRONTEND = """\
package main

import (
\t"net/http"
\t"github.com/gorilla/mux"
)

func main() {
\tr := mux.NewRouter()
\tr.HandleFunc(baseUrl+"/", svc.homeHandler).Methods(http.MethodGet)
\tr.HandleFunc(baseUrl+"/cart", svc.viewCartHandler).Methods(http.MethodGet)
\tr.HandleFunc("/_healthz", svc.health).Methods(http.MethodGet)
}
"""


def _go(path="src/frontend/main.go"):
    return SimpleNamespace(path=path, language="Go")


class TestComputedPathsAreCounted:
    def test_the_two_computed_registrations_are_counted(self):
        assert computed_go_paths(FRONTEND) == 2

    def test_the_literal_one_is_still_extracted(self):
        routes, _declined = framework_routes(_go(), FRONTEND)
        assert [(r.method, r.path) for r in routes] == [("GET", "/_healthz")]

    def test_the_dispatch_reports_both_halves(self):
        routes, declined = framework_routes(_go(), FRONTEND)
        assert len(routes) == 1 and declined == 2


class TestTheCounterDoesNotOvercount:
    def test_a_file_with_no_router_counts_nothing(self):
        """`c.Handle(req)` on some client is not a declined route."""
        content = ('package main\nfunc f(){ c.Handle(req, opts) }\n')
        assert computed_go_paths(content) == 0

    def test_a_commented_out_registration_is_not_a_decline(self):
        content = FRONTEND.replace(
            '\tr.HandleFunc(baseUrl+"/cart", svc.viewCartHandler).Methods(http.MethodGet)',
            '\t// r.HandleFunc(baseUrl+"/cart", svc.viewCartHandler)')
        assert computed_go_paths(content) == 1

    def test_all_literal_paths_decline_nothing(self):
        content = FRONTEND.replace('baseUrl+"/', '"/')
        assert computed_go_paths(content) == 0


class TestOtherLanguagesReportZeroRatherThanGuess:
    def test_a_python_file_is_not_dispatched_here(self):
        routes, declined = framework_routes(
            SimpleNamespace(path="app.py", language="Python"), "x = 1")
        assert routes == [] and declined == 0

    def test_an_unchecked_extractor_reports_no_declines(self):
        routes, declined = framework_routes(
            SimpleNamespace(path="config/routes.rb", language="Ruby"),
            "Rails.application.routes.draw do\n"
            "  get '/owners', to: 'owners#index'\n"
            "end\n")
        assert declined == 0
        assert routes, "the Ruby extractor should still return its routes"
