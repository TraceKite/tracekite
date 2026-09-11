"""Ruby route extraction: Rails DSL and Sinatra.

`get` is one of the commonest method names in Ruby, so the declining tests
matter more than the extracting ones: an extractor that reads `params.get`
or a hash access as a route mints phantom endpoints across every Ruby repo
in an estate.
"""

from tracekite.services.rb_route_extractor import extract_rb_routes

ROUTES_RB = "config/routes.rb"


def routes(content, path=ROUTES_RB):
    return [(r.method, r.path) for r in extract_rb_routes(path, content)]


class TestRails:
    def test_verb_routes_with_params_normalise(self):
        found = routes("""
Rails.application.routes.draw do
  get '/owners/:id', to: 'owners#show'
  post '/owners', to: 'owners#create'
end
""")
        assert found == [("GET", "/owners/{id}"), ("POST", "/owners")]

    def test_resources_expands_to_what_rails_registers(self):
        found = routes("Rails.application.routes.draw do\n"
                       "  resources :owners\nend\n")
        assert found == [
            ("GET", "/owners"), ("POST", "/owners"),
            ("GET", "/owners/{id}"), ("PATCH", "/owners/{id}"),
            ("DELETE", "/owners/{id}")]

    def test_only_and_except_filter_the_expansion(self):
        assert routes("resources :owners, only: [:index, :show]\n") == [
            ("GET", "/owners"), ("GET", "/owners/{id}")]
        assert routes("resources :owners, except: [:destroy]\n") == [
            ("GET", "/owners"), ("POST", "/owners"),
            ("GET", "/owners/{id}"), ("PATCH", "/owners/{id}")]

    def test_namespace_prefixes_nest_and_unwind(self):
        found = routes("""
Rails.application.routes.draw do
  namespace :api do
    namespace :v1 do
      get '/owners', to: 'owners#index'
    end
    get '/health', to: 'ops#health'
  end
  get '/root', to: 'home#index'
end
""")
        assert found == [("GET", "/api/v1/owners"), ("GET", "/api/health"),
                         ("GET", "/root")]

    def test_scope_uses_its_literal_path(self):
        found = routes("scope '/internal' do\n"
                       "  get '/metrics', to: 'ops#metrics'\nend\n")
        assert found == [("GET", "/internal/metrics")]

    def test_nested_resources_gain_the_parent_member_scope(self):
        found = routes("resources :owners do\n  resources :pets\nend\n")
        assert ("GET", "/owners/{owner_id}/pets") in found
        assert ("GET", "/owners/{owner_id}/pets/{id}") in found

    def test_handler_carries_the_controller_action(self):
        [route] = extract_rb_routes(
            ROUTES_RB, "get '/owners', to: 'owners#index'\n")
        assert route.handler_name == "owners#index"
        assert route.framework == "rails"

    def test_the_rails_dsl_outside_routes_rb_is_not_a_route(self):
        """`get 'value'` in ordinary Ruby is a method call; reading it as a
        route would mint phantom endpoints across every Ruby repo."""
        assert routes("get '/owners', to: 'x#y'\n", path="app/models/o.rb") \
            == []


class TestSinatra:
    def test_a_block_route_extracts_anywhere(self):
        found = routes("get '/owners' do\n  json []\nend\n", path="app.rb")
        assert found == [("GET", "/owners")]

    def test_without_a_block_it_is_just_a_method_call(self):
        assert routes("value = get '/owners'\n", path="app.rb") == []

    def test_a_path_without_a_leading_slash_is_not_a_route(self):
        assert routes("get 'owners' do\nend\n", path="app.rb") == []

    def test_params_normalise_to_braces(self):
        assert routes("get '/owners/:id' do\nend\n", path="app.rb") \
            == [("GET", "/owners/{id}")]


class TestEndToEnd:
    def test_a_scanned_rails_repo_produces_the_contract_side(self, tmp_path):
        """The whole point: a Ruby provider must be joinable. Through the
        real scan, a Rails route becomes an ApiEndpoint a consumer's claim
        can meet."""
        from tracekite import engine_config
        from tracekite.services.scan import scan

        engine_config.configure(graph_hmac_key="rb-route-test")
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "routes.rb").write_text(
            "Rails.application.routes.draw do\n"
            "  resources :owners, only: [:index]\n"
            "end\n")
        sink = scan(str(tmp_path), "repo_rails")
        endpoints = [n for n in sink.nodes if n.type == "ApiEndpoint"]
        assert [(n.extra_props.get("http_method"),
                 n.extra_props.get("path_template"))
                for n in endpoints] == [("GET", "/owners")]
