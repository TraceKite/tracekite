"""Each route registration call yields its own route, once, at its own line."""

import pytest

from tracekite.parsers.tree_sitter.core.parser import TREE_SITTER_AVAILABLE
from tracekite.parsers.tree_sitter.own_call import own_match

ROUTE = r"\.route\s*\(\s*\"([^\"]+)\""
CHAIN = 'Router::new()\n    .route("/a", get(a))\n    .route("/b", post(b))'


class TestOwnMatch:
    def test_a_chained_call_owns_its_own_link_not_the_first(self):
        assert own_match(ROUTE, CHAIN, "route").group(1) == "/b"

    def test_a_call_wrapping_a_registration_owns_none(self):
        # actix: the route sits inside HttpServer::new's closure argument.
        server = 'HttpServer::new(move || App::new().route("/health", web::get()))'
        assert own_match(ROUTE, server, "new") is None

    def test_a_call_after_the_registration_owns_none(self):
        assert own_match(ROUTE, CHAIN + "\n    .layer(cors)", "layer") is None

    def test_a_call_without_its_name_in_its_text_owns_none(self):
        assert own_match(ROUTE, '.route("/a", get(a))', "") is None


AXUM = '''use axum::{routing::get, Router};

async fn a() {}
async fn b() {}

pub fn app() -> Router {
    Router::new()
        .route("/a", get(a))
        .route("/b", post(b))
        .route(
            "/c",
            get(a),
        )
}
'''

ACTIX = '''use actix_web::{web, App, HttpResponse, HttpServer};

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    HttpServer::new(move || {
        App::new()
            .wrap(RequestTracing::new())
            .route(
                "/health",
                web::get().to(|| async { HttpResponse::Ok().finish() }),
            )
    })
    .bind(&addr)?
    .run()
    .await
}
'''


@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter unavailable")
class TestThroughTheParser:
    def _routes(self, path, source):
        from tracekite.parsers.parser_registry import parse_source
        return [(e.method, e.path, e.line, e.framework)
                for e in parse_source(path, source).api_endpoints]

    def test_every_link_of_an_axum_chain_is_a_route(self):
        # Was: GET /a three times, and /b and /c never.
        assert self._routes("src/app.rs", AXUM) == [
            ("GET", "/a", 8, "axum"), ("POST", "/b", 9, "axum"),
            ("GET", "/c", 10, "axum")]

    def test_an_actix_route_is_cited_once_at_its_registration(self):
        # Was: also at the HttpServer::new, .bind and .run lines.
        assert self._routes("src/main.rs", ACTIX) == [
            ("GET", "/health", 8, "actix")]
