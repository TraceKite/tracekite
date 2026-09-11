"""PHP route extraction: Laravel, Slim, Symfony attributes.

The load-bearing decline: `$app->get('/x')` is a Slim route and
`$client->get('/x')` is a Guzzle call — one shape, opposite edge direction,
told apart only by the receiver. Each side keeps an allowlist; an unknown
receiver matches neither, because a guessed direction is worse than a
missing edge.
"""

from evigraph.services.http_call_extractor import extract_http_calls
from evigraph.services.php_route_extractor import extract_php_routes


def routes(content, path="routes/api.php"):
    return [(r.method, r.path) for r in extract_php_routes(path, content)]


class TestLaravel:
    def test_verb_routes(self):
        found = routes("<?php\nRoute::get('/owners', [C::class, 'i']);\n"
                       "Route::post('/owners', [C::class, 'c']);\n")
        assert found == [("GET", "/owners"), ("POST", "/owners")]

    def test_api_resource_expands_to_what_laravel_registers(self):
        assert routes("<?php\nRoute::apiResource('owners', C::class);\n") == [
            ("GET", "/owners"), ("POST", "/owners"),
            ("GET", "/owners/{id}"), ("PATCH", "/owners/{id}"),
            ("DELETE", "/owners/{id}")]

    def test_full_resource_adds_the_form_routes(self):
        found = routes("<?php\nRoute::resource('owners', C::class);\n")
        assert ("GET", "/owners/create") in found
        assert ("GET", "/owners/{id}/edit") in found

    def test_any_stays_any_not_a_guessed_verb(self):
        assert routes("<?php\nRoute::any('/hook', H::class);\n") == [
            ("ANY", "/hook")]


class TestSlimVersusGuzzle:
    SOURCE = ("<?php\n"
              "$app->get('/owners', OwnerHandler::class);\n"
              "$client->get('/billing/v1/x');\n")

    def test_app_receiver_is_a_route_and_client_is_not(self):
        assert routes(self.SOURCE, path="src/routes.php") == [
            ("GET", "/owners")]

    def test_client_receiver_is_a_call_and_app_is_not(self):
        sites = extract_http_calls("src/routes.php", self.SOURCE, "php")
        assert [(s.method, s.path_template) for s in sites] == [
            ("GET", "/billing/v1/x")]

    def test_an_unknown_receiver_matches_neither_side(self):
        source = "<?php\n$thing->get('/owners');\n"
        assert routes(source, path="src/x.php") == []
        assert extract_http_calls("src/x.php", source, "php") == []


class TestSymfony:
    def test_attribute_with_methods(self):
        found = routes("<?php\n#[Route('/owners', methods: ['GET'])]\n"
                       "public function index() {}\n", path="src/C.php")
        assert found == [("GET", "/owners")]

    def test_attribute_without_methods_is_any(self):
        assert routes("<?php\n#[Route('/owners')]\nfunction i() {}\n",
                      path="src/C.php") == [("ANY", "/owners")]

    def test_a_route_name_is_not_a_path(self):
        """`#[Route('api_home')]` names the route; asserting it as a path
        would join on a word."""
        assert routes("<?php\n#[Route('api_home')]\nfunction i() {}\n",
                      path="src/C.php") == []


class TestEndToEnd:
    def test_a_scanned_laravel_repo_produces_the_contract_side(self, tmp_path):
        from evigraph import engine_config
        from evigraph.services.scan import scan

        engine_config.configure(graph_hmac_key="php-route-test")
        (tmp_path / "routes").mkdir()
        (tmp_path / "routes" / "api.php").write_text(
            "<?php\nRoute::get('/owners/{id}', [C::class, 'show']);\n")
        sink = scan(str(tmp_path), "repo_laravel")
        endpoints = [(n.extra_props.get("http_method"),
                      n.extra_props.get("path_template"))
                     for n in sink.nodes if n.type == "ApiEndpoint"]
        # Positional template: named params collapse to {} at the node so
        # `/owners/{id}` and `/owners/:id` join on one key, like every
        # other language's endpoints.
        assert endpoints == [("GET", "/owners/{}")]
