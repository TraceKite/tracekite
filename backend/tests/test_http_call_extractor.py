"""Outbound HTTP call-site extraction across JVM, .NET, Python, Node, Go, and
Rust client libraries (tracekite/services/http_call_extractor).

Existing RestTemplate/WebClient/fetch/axios/requests coverage lives in
test_claims_and_extractors.py and test_ingest_gap_fill.py; this file covers the
client families added on top, reusing the same _add/_classify_url semantics.
"""

import pytest

from tracekite.services.http_call_extractor import extract_http_calls


def _by_client(sites):
    grouped = {}
    for site in sites:
        grouped.setdefault(site.client, []).append(site)
    return grouped


class TestJavaKotlinClients:
    def test_okhttp_url_with_post(self):
        content = (
            "Request request = new Request.Builder()\n"
            '    .url("http://payments-service/api/charges")\n'
            "    .post(body)\n"
            "    .build();"
        )
        sites = extract_http_calls("A.java", content, "java")
        assert len(sites) == 1
        site = sites[0]
        assert site.client == "okhttp"
        assert site.method == "POST"
        assert site.path_template == "/api/charges"
        assert site.service_hint == "payments-service"
        assert site.hint_source == "host"
        assert site.line == 2

    def test_okhttp_defaults_to_get_inferred(self):
        content = 'new Request.Builder().url("https://api.stripe.com/v1/charges").build();'
        sites = extract_http_calls("B.java", content, "java")
        assert sites[0].method == "GET"
        assert sites[0].attrs.get("method_inferred") is True
        assert sites[0].attrs.get("external") is True

    def test_okhttp_kotlin_without_new(self):
        content = 'val req = Request.Builder().url("http://orders-service/orders").build()'
        sites = extract_http_calls("A.kt", content, "kotlin")
        assert len(sites) == 1
        assert sites[0].client == "okhttp"
        assert sites[0].service_hint == "orders-service"

    def test_okhttp_verb_does_not_leak_into_next_statement(self):
        content = (
            'Request a = new Request.Builder().url("http://x-service/a").build();\n'
            'Request b = new Request.Builder().url("http://x-service/b").post(body).build();'
        )
        sites = extract_http_calls("C.java", content, "java")
        methods = {s.path_template: s.method for s in sites}
        assert methods == {"/a": "GET", "/b": "POST"}

    def test_apache_httpclient_constructors(self):
        content = (
            'HttpPost post = new HttpPost("http://inventory-service/items");\n'
            'client.execute(new HttpDelete("http://inventory-service/items/9"));'
        )
        sites = extract_http_calls("D.java", content, "java")
        assert [(s.method, s.path_template) for s in sites] == [
            ("POST", "/items"), ("DELETE", "/items/9")]
        assert all(s.client == "apache" for s in sites)

    def test_java11_httprequest_builder(self):
        content = (
            "HttpRequest request = HttpRequest.newBuilder()\n"
            '    .uri(URI.create("http://billing-service/invoices"))\n'
            "    .POST(HttpRequest.BodyPublishers.ofString(json))\n"
            "    .build();"
        )
        sites = extract_http_calls("E.java", content, "java")
        assert len(sites) == 1
        assert sites[0].client == "java-http"
        assert sites[0].method == "POST"
        assert sites[0].service_hint == "billing-service"

    def test_java11_uri_in_newbuilder_arg_defaults_get(self):
        content = 'HttpRequest.newBuilder(URI.create("http://vets-service/vets")).build();'
        sites = extract_http_calls("F.java", content, "java")
        assert sites[0].method == "GET"
        assert sites[0].attrs.get("method_inferred") is True

    def test_spring_restclient_create_and_uri_chain(self):
        content = (
            'RestClient client = RestClient.create("http://catalog-service");\n'
            'String s = restClient.get().uri("http://catalog-service/skus").retrieve();'
        )
        sites = extract_http_calls("G.java", content, "java")
        grouped = _by_client(sites)
        base = grouped["restclient"][0]
        assert base.attrs.get("base_url") is True
        assert base.service_hint == "catalog-service"
        # .get().uri(..) chains ride the existing receiver-agnostic
        # WebClient-family pattern, so the client label stays "webclient".
        chain = grouped["webclient"][0]
        assert chain.method == "GET"
        assert chain.path_template == "/skus"

    def test_retrofit_annotations_and_url_dynamic_skip(self):
        content = (
            "public interface OwnerApi {\n"
            '  @GET("owners/{ownerId}")\n'
            "  Call<Owner> owner(@Path(\"ownerId\") String id);\n"
            '  @POST("/owners")\n'
            "  Call<Owner> create(@Body Owner o);\n"
            "  @GET\n"
            "  Call<ResponseBody> dynamic(@Url String url);\n"
            "}"
        )
        sites = extract_http_calls("OwnerApi.java", content, "java")
        assert [(s.method, s.path_template) for s in sites] == [
            ("GET", "/owners/{}"), ("POST", "/owners")]
        assert all(s.client == "retrofit" for s in sites)
        assert all(s.host is None for s in sites)


class TestCSharpClients:
    def test_httpclient_verb_async_absolute(self):
        content = 'var res = await client.GetAsync("http://orders-service/api/orders");'
        sites = extract_http_calls("A.cs", content, "c#")
        assert len(sites) == 1
        assert sites[0].client == "httpclient"
        assert sites[0].method == "GET"
        assert sites[0].service_hint == "orders-service"
        assert sites[0].hint_source == "host"

    def test_post_as_json_relative_and_csharp_alias(self):
        content = 'await _httpClient.PostAsJsonAsync("/api/orders", order);'
        sites = extract_http_calls("B.cs", content, "csharp")
        assert sites[0].method == "POST"
        assert sites[0].path_template == "/api/orders"
        assert sites[0].host is None

    def test_interpolated_url_and_generic_type_args(self):
        content = 'var o = await client.GetFromJsonAsync<Order>($"http://orders-service/api/orders/{id}");'
        sites = extract_http_calls("C.cs", content, "c#")
        assert sites[0].method == "GET"
        assert sites[0].path_template == "/api/orders/{}"
        assert sites[0].attrs.get("interpolated") is True

    def test_factory_created_client_receiver(self):
        content = 'await factory.CreateClient("orders").DeleteAsync("/api/orders/3");'
        sites = extract_http_calls("D.cs", content, "c#")
        assert sites[0].method == "DELETE"
        assert sites[0].path_template == "/api/orders/3"

    def test_cache_get_string_async_declined(self):
        content = 'var profile = await cache.GetStringAsync("user:profile");'
        assert extract_http_calls("E.cs", content, "c#") == []

    def test_base_address_is_base_url_site(self):
        content = 'client.BaseAddress = new Uri("http://payments-service");'
        sites = extract_http_calls("F.cs", content, "c#")
        assert sites[0].attrs.get("base_url") is True
        assert sites[0].service_hint == "payments-service"

    def test_restsharp_client_and_request(self):
        content = (
            'var client = new RestClient("https://api.github.com");\n'
            'var request = new RestRequest("/repos/{owner}/{repo}", Method.Get);\n'
            'var bare = new RestRequest("/health");'
        )
        sites = extract_http_calls("G.cs", content, "c#")
        assert all(s.client == "restsharp" for s in sites)
        base, routed, bare = sites
        assert base.attrs.get("base_url") is True
        assert base.attrs.get("external") is True
        assert routed.method == "GET"
        assert routed.path_template == "/repos/{}/{}"
        assert bare.method == "GET"
        assert bare.attrs.get("method_inferred") is True

    def test_refit_attribute_routes(self):
        content = (
            "public interface IOwnersApi {\n"
            '    [Get("/owners/{id}")]\n'
            "    Task<Owner> GetOwner(string id);\n"
            '    [Post("/owners")]\n'
            "    Task<Owner> Create([Body] Owner owner);\n"
            "}"
        )
        sites = extract_http_calls("IOwnersApi.cs", content, "c#")
        assert [(s.method, s.path_template) for s in sites] == [
            ("GET", "/owners/{}"), ("POST", "/owners")]
        assert all(s.client == "refit" for s in sites)


class TestPythonClients:
    def test_aiohttp_session_variable(self):
        content = 'async with session.get("http://visits-service/visits") as resp:\n    pass'
        sites = extract_http_calls("a.py", content, "python")
        assert len(sites) == 1
        assert sites[0].client == "session"
        assert sites[0].method == "GET"
        assert sites[0].service_hint == "visits-service"

    def test_session_dict_style_lookup_declined(self):
        content = 'user = session.get("user_id")'
        assert extract_http_calls("b.py", content, "python") == []

    def test_aiohttp_module_request(self):
        content = 'resp = await aiohttp.request("GET", "http://vets-service/vets")'
        sites = extract_http_calls("c.py", content, "python")
        assert sites[0].client == "aiohttp"
        assert sites[0].method == "GET"
        assert sites[0].service_hint == "vets-service"

    def test_urllib3_poolmanager_request(self):
        content = (
            "http = urllib3.PoolManager()\n"
            'r = http.request("POST", "http://billing-service/invoices")\n'
            'r2 = urllib3.PoolManager().request("GET", "https://api.example.com/x")'
        )
        sites = extract_http_calls("d.py", content, "python")
        assert [(s.client, s.method) for s in sites] == [
            ("urllib3", "POST"), ("urllib3", "GET")]
        assert sites[0].service_hint == "billing-service"
        assert sites[1].attrs.get("external") is True

    def test_lowercase_method_first_declined(self):
        content = 'r = http.request("get", "http://nope-service/x")'
        assert extract_http_calls("e.py", content, "python") == []

    def test_requests_session_tracked_assignment(self):
        content = (
            "s = requests.Session()\n"
            's.get("http://customers-service/owners")\n'
            's.post("api/pets")'
        )
        sites = extract_http_calls("f.py", content, "python")
        assert [(s.client, s.method, s.path_template) for s in sites] == [
            ("requests", "GET", "/owners"), ("requests", "POST", "/api/pets")]

    def test_session_named_requests_session_not_double_counted(self):
        content = (
            "session = requests.Session()\n"
            'session.get("http://x-service/a")'
        )
        sites = extract_http_calls("g.py", content, "python")
        assert len(sites) == 1
        assert sites[0].client == "requests"

    def test_plain_requests_still_extracted(self):
        sites = extract_http_calls(
            "h.py", 'requests.post("http://billing/invoices", json=data)', "python")
        assert sites[0].client == "requests"
        assert sites[0].method == "POST"


class TestNodeClients:
    def test_got_bare_with_options_method(self):
        content = "const res = await got('https://api.github.com/repos', {method: 'POST'});"
        sites = extract_http_calls("a.js", content, "javascript")
        assert sites[0].client == "got"
        assert sites[0].method == "POST"
        assert sites[0].attrs.get("external") is True

    def test_got_verb_member_and_ky(self):
        content = (
            "got.get('http://catalog-service/skus');\n"
            "ky.post('http://cart-service/items');\n"
            "const t = await ky('/api/things');"
        )
        sites = extract_http_calls("b.ts", content, "typescript")
        grouped = _by_client(sites)
        assert grouped["got"][0].method == "GET"
        assert grouped["got"][0].service_hint == "catalog-service"
        assert grouped["ky"][0].method == "POST"
        bare_ky = grouped["ky"][1]
        assert bare_ky.method == "GET"
        assert bare_ky.attrs.get("method_inferred") is True

    def test_ky_method_window_stops_at_statement_end(self):
        content = (
            "await ky('/api/things');\n"
            "await fetch('/other', {method: 'PUT'});"
        )
        sites = extract_http_calls("c.js", content, "javascript")
        ky_site = _by_client(sites)["ky"][0]
        assert ky_site.method == "GET"

    def test_superagent_gated_on_import(self):
        content = (
            "const request = require('superagent');\n"
            "request.get('http://vets-service/vets');\n"
            "request.del('/api/x');"
        )
        sites = extract_http_calls("d.js", content, "javascript")
        assert [(s.client, s.method) for s in sites] == [
            ("superagent", "GET"), ("superagent", "DELETE")]

    def test_request_receiver_without_superagent_import_declined(self):
        content = "request.get('http://vets-service/vets');"
        assert extract_http_calls("e.js", content, "javascript") == []

    def test_undici_request_and_destructured_form(self):
        content = (
            "const undici = require('undici');\n"
            "undici.request('https://api.example.com/x');\n"
            "request('http://orders-service/api/orders', { method: 'PUT' });"
        )
        sites = extract_http_calls("f.js", content, "javascript")
        assert all(s.client == "undici" for s in sites)
        assert sites[0].method == "GET"
        assert sites[0].attrs.get("method_inferred") is True
        assert sites[1].method == "PUT"
        assert sites[1].service_hint == "orders-service"

    def test_bare_request_without_undici_import_declined(self):
        content = "request('http://orders-service/x');"
        assert extract_http_calls("g.js", content, "javascript") == []

    def test_node_fetch_still_covered_by_fetch_pattern(self):
        content = (
            "import fetch from 'node-fetch';\n"
            "fetch('http://reviews-service/reviews');"
        )
        sites = extract_http_calls("h.js", content, "javascript")
        assert sites[0].client == "fetch"
        assert sites[0].service_hint == "reviews-service"


class TestGoClients:
    def test_net_http_helpers(self):
        content = (
            'resp, err := http.Get("http://config-service/config")\n'
            'http.Post("http://audit-service/events", "application/json", body)\n'
            'http.PostForm("http://forms-service/submit", data)'
        )
        sites = extract_http_calls("main.go", content, "go")
        assert [(s.client, s.method, s.service_hint) for s in sites] == [
            ("net/http", "GET", "config-service"),
            ("net/http", "POST", "audit-service"),
            ("net/http", "POST", "forms-service")]

    def test_new_request_literal_and_method_constant(self):
        content = (
            'req, _ := http.NewRequest("PUT", "http://inventory-service/items/42", body)\n'
            'req2, _ := http.NewRequest(http.MethodPost, "http://inventory-service/items", body)'
        )
        sites = extract_http_calls("a.go", content, "go")
        assert [(s.method, s.path_template) for s in sites] == [
            ("PUT", "/items/42"), ("POST", "/items")]

    def test_new_request_with_context(self):
        content = 'req, _ := http.NewRequestWithContext(ctx, "DELETE", "http://cart-service/items/9", nil)'
        sites = extract_http_calls("b.go", content, "go")
        assert sites[0].method == "DELETE"
        assert sites[0].service_hint == "cart-service"

    def test_new_request_variable_method_declined(self):
        content = 'req, _ := http.NewRequest(verb, "http://cart-service/items", nil)'
        assert extract_http_calls("c.go", content, "go") == []

    def test_resty_chain_and_base_url(self):
        content = (
            'client := resty.New().SetBaseURL("http://customers-service")\n'
            'resp, _ := client.R().SetHeader("Accept", "application/json").Get("http://vets-service/vets")\n'
            'resp2, _ := client.R().Post("/owners")'
        )
        sites = extract_http_calls("d.go", content, "go")
        grouped = _by_client(sites)
        assert len(grouped["resty"]) == 3
        base = [s for s in grouped["resty"] if s.attrs.get("base_url")][0]
        assert base.service_hint == "customers-service"
        chained = [s for s in grouped["resty"] if not s.attrs.get("base_url")]
        assert [(s.method, s.path_template) for s in chained] == [
            ("GET", "/vets"), ("POST", "/owners")]


class TestRustClients:
    def test_reqwest_get_and_blocking(self):
        content = (
            'let body = reqwest::get("http://catalog-service/skus").await?;\n'
            'let b2 = reqwest::blocking::get("https://api.example.com/x")?;'
        )
        sites = extract_http_calls("main.rs", content, "rust")
        assert all(s.client == "reqwest" for s in sites)
        assert sites[0].method == "GET"
        assert sites[0].service_hint == "catalog-service"
        assert sites[1].attrs.get("external") is True

    def test_client_verb_absolute_url(self):
        content = 'let r = client.post("http://orders-service/api/orders").json(&order).send().await?;'
        sites = extract_http_calls("a.rs", content, "rust")
        assert sites[0].method == "POST"
        assert sites[0].path_template == "/api/orders"

    def test_map_get_key_lookup_declined(self):
        content = 'let v = map.get("key");\nlet w = headers.get("content-type");'
        assert extract_http_calls("b.rs", content, "rust") == []


class TestMalformedInputs:
    JUNK = (
        'x.get("://") new HttpGet( Request.Builder() session.get( got( ky(\n'
        'http.request("GET", ) reqwest::get(" new RestRequest( [Get(]\n'
        'HttpRequest.newBuilder( client.R() undici.request( "unterminated\n'
        "\x00\x01 ☃ @GET(\"\") request('') new Uri("
    )

    @pytest.mark.parametrize(
        "lang", ["java", "kotlin", "scala", "javascript", "typescript",
                 "python", "c#", "csharp", "go", "rust"])
    def test_garbage_does_not_raise(self, lang):
        sites = extract_http_calls("junk", self.JUNK, lang)
        assert isinstance(sites, list)

    def test_unknown_language_returns_empty(self):
        assert extract_http_calls("x.rb", 'client.get("http://a/b")', "ruby") == []

    def test_none_language_returns_empty(self):
        assert extract_http_calls("x", 'http.Get("http://a/b")', None) == []


class TestInjectedBaseUrlPython:
    """Dependency-injected clients: the host is configuration, the path is a
    literal. These call sites were previously invisible, which is why the ap
    platform produced 3,022 provider claims and 29 consumer claims."""

    def _sites(self, src):
        return extract_http_calls("svc/client.py", src, "python")

    def test_fstring_base_url_in_call(self):
        src = 'r = await self._http.get(f"{self._registry_url}/v1/callers")\n'
        sites = self._sites(src)
        assert len(sites) == 1
        assert sites[0].method == "GET"
        assert sites[0].path_template == "/v1/callers"
        assert sites[0].attrs["base_var"] == "registry"

    def test_multiline_call_keeps_the_verb(self):
        src = (
            'resp = await self._http.post(\n'
            '    f"{self._url}/v1/registrations",\n'
            '    json=payload,\n'
            ')\n'
        )
        sites = self._sites(src)
        assert [(s.method, s.path_template) for s in sites] == [
            ("POST", "/v1/registrations")]

    def test_assigned_then_passed_to_request(self):
        src = (
            'url = f"{self._orchestrator_url}/v1/turns"\n'
            'resp = await client.post(url, json=body)\n'
        )
        sites = self._sites(src)
        assert [(s.method, s.path_template) for s in sites] == [
            ("POST", "/v1/turns")]
        assert sites[0].attrs["base_var"] == "orchestrator"

    def test_non_literal_path_is_declined(self):
        # f"{base}{CONST}" carries no template — guessing one would invent a
        # contract that does not exist.
        src = 'await self._http.get(f"{self._registry_url}{MODEL_POLICY_PATH}")\n'
        assert self._sites(src) == []

    def test_fstring_outside_a_request_is_not_a_call(self):
        src = 'label = f"{self.name}/v1/thing"\nlogger.info(label)\n'
        assert self._sites(src) == []

    def test_verb_is_never_assumed(self):
        # No enclosing verb and never passed to one: not a request.
        src = 'url = f"{self._registry_url}/v1/callers"\nreturn url\n'
        assert self._sites(src) == []

    def test_inner_call_wins_over_outer(self):
        src = 'wrap(self._http.put(f"{self._svc_url}/v1/x"))\n'
        sites = self._sites(src)
        assert [(s.method, s.path_template) for s in sites] == [("PUT", "/v1/x")]

    def test_path_params_canonicalised(self):
        src = 'await self._http.get(f"{self._registry_url}/v1/callers/{caller_id}")\n'
        sites = self._sites(src)
        assert sites[0].path_template == "/v1/callers/{}"
