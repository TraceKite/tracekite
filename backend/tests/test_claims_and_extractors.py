"""Stage A units: claim registry, http-call extractor, parser upgrades, emission."""

from types import SimpleNamespace

import pytest

from evigraph.services.claims import (
    ContractClaim, GENERIC_NAME_DENYLIST, http_consumes_key, http_provides_key,
    is_generic_name, route_key, svcname_key, claim_to_node,
)
from evigraph.parsers.config_parser import parse_config_file
from evigraph.parsers.docker_parser import parse_docker_file
from evigraph.services.http_call_extractor import extract_feign_clients, extract_http_calls
from evigraph.services.ingest_claims import (
    emit_compose_claims, emit_config_claims, emit_source_claims,
)
from evigraph.services.ingest_source import IngestSink
from evigraph.services.redaction import redact


def _file(path, language="java"):
    return SimpleNamespace(path=path, language=language)


def _claims(sink):
    return [n for n in sink.nodes if n.type == "ContractClaim"]


class TestClaimRegistry:
    def test_id_deterministic_and_repo_scoped(self):
        a = ContractClaim(repo_id="r1", kind="svcname", direction="provides",
                          key="s:api", evidence=["a.yml:1"])
        b = ContractClaim(repo_id="r1", kind="svcname", direction="provides",
                          key="s:api", evidence=["a.yml:1"])
        c = ContractClaim(repo_id="r2", kind="svcname", direction="provides",
                          key="s:api", evidence=["a.yml:1"])
        assert a.id == b.id
        assert a.id != c.id
        assert a.id.startswith("r1:ContractClaim:")

    def test_unmatchable_keys(self):
        empty = ContractClaim(repo_id="r", kind="svcname", direction="consumes",
                              key="", evidence=[])
        templated = ContractClaim(repo_id="r", kind="svcname", direction="consumes",
                                  key="s:${HOST}", evidence=[])
        solid = ContractClaim(repo_id="r", kind="svcname", direction="consumes",
                              key="s:api", evidence=[])
        assert not empty.matchable
        assert not templated.matchable
        assert solid.matchable

    def test_generic_denylist(self):
        assert "api" in GENERIC_NAME_DENYLIST
        assert is_generic_name("API")
        assert not is_generic_name("customers-service")

    def test_claim_to_node_props(self):
        claim = ContractClaim(repo_id="r", kind="http", direction="consumes",
                              key=http_consumes_key("get", "/owners/{}"),
                              service_hint="customers-service", hint_source="host",
                              evidence=["a.java:10"])
        node = claim_to_node(claim)
        assert node.type == "ContractClaim"
        assert node.extra_props["kind"] == "http"
        assert node.extra_props["direction"] == "consumes"
        assert node.extra_props["key"] == "httpcall:GET:/owners/{}"
        assert node.extra_props["service_hint"] == "customers-service"
        assert node.extra_props["hint_source"] == "host"
        assert node.extra_props["matchable"] is True

    def test_key_builders(self):
        assert svcname_key("Scope", "Name") == "scope:name"
        assert route_key("/api/customers", "customers-service") == \
            "/api/customers\u2192svcname:customers-service"
        assert http_provides_key("get", "/x") == "GET:/x"


class TestHttpCallExtractor:
    def test_resttemplate_and_template_braces(self):
        content = 'restTemplate.getForObject("http://customers-service/owners/" + id, X.class);'
        sites = extract_http_calls("A.java", content, "java")
        assert len(sites) == 1
        site = sites[0]
        assert site.method == "GET"
        assert site.path_template == "/owners/{}"
        assert site.service_hint == "customers-service"
        assert site.hint_source == "host"

    def test_webclient_lb_uri(self):
        content = 'webClient.get().uri("lb://visits-service/pets/visits?petId={id}", x)'
        sites = extract_http_calls("B.java", content, "java")
        assert len(sites) == 1
        assert sites[0].service_hint == "visits-service"
        assert sites[0].hint_source == "discovery"
        assert sites[0].path_template == "/pets/visits"

    def test_env_ref_unmatchable(self):
        content = 'restTemplate.getForObject("${API_URL}/pets", X.class);'
        sites = extract_http_calls("C.java", content, "java")
        assert sites and sites[0].attrs.get("env_ref")

    def test_local_and_external_flags(self):
        local = extract_http_calls(
            "D.java", 'restTemplate.getForObject("http://localhost:8080/x", X.class);',
            "java")
        ext = extract_http_calls(
            "E.java", 'restTemplate.getForObject("https://api.stripe.com/v1/charges", X.class);',
            "java")
        assert local[0].attrs.get("local")
        assert ext[0].attrs.get("external")
        assert ext[0].service_hint is None

    def test_js_fetch_axios_and_angular(self):
        content = """
        fetch('/api/gateway/owners', {method: 'POST'})
        axios.get('/api/visits')
        $http.get('api/gateway/owners/' + ownerId)
        """
        sites = extract_http_calls("app.js", content, "javascript")
        by_client = {s.client: s for s in sites}
        assert by_client["fetch"].method == "POST"
        assert by_client["axios"].path_template == "/api/visits"
        assert by_client["angular"].path_template == "/api/gateway/owners/{}"

    def test_python_requests(self):
        sites = extract_http_calls(
            "x.py", 'requests.post("http://billing/invoices", json=data)', "python")
        assert sites[0].method == "POST"
        assert sites[0].service_hint == "billing"

    def test_feign_clients(self):
        content = '@FeignClient(name = "customers-service")\ninterface C {}'
        assert extract_feign_clients(content) == [("customers-service", 1)]


class TestParserUpgrades:
    def test_gateway_routes_and_app_name(self, tmp_path):
        yml = tmp_path / "api-gateway.yml"
        yml.write_text("""
spring:
  application:
    name: api-gateway
  cloud:
    gateway:
      routes:
        - id: customers
          uri: lb://customers-service
          predicates:
            - Path=/api/customer/**
          filters:
            - StripPrefix=2
""")
        result = parse_config_file(str(yml), yml.read_text())
        assert result.app_name == "api-gateway"
        route = result.gateway_routes[0]
        assert route.uri == "lb://customers-service"
        assert route.path_predicates == ["/api/customer/**"]
        assert route.strip_prefix == 2

    def test_compose_depth(self, tmp_path):
        yml = tmp_path / "docker-compose.yml"
        yml.write_text("""
name: petclinic
services:
  api:
    image: acme/api:1.2
    build:
      context: ./api
    depends_on:
      db:
        condition: service_healthy
    links: [cache]
    environment:
      DB_URL: postgres://db:5432/app
  db:
    image: postgres:16
""")
        resources = parse_docker_file(str(yml), yml.read_text())
        api = next(r for r in resources if r.name == "api")
        assert api.project == "petclinic"
        assert api.depends_on == ["db"]
        assert api.links == ["cache"]
        assert api.build_context == "./api"
        assert api.env_pairs["DB_URL"] == "postgres://db:5432/app"


class TestClaimEmission:
    def test_source_claims(self):
        sink = IngestSink()
        records = [{"node_id": "n1", "http_method": "GET",
                    "path_template": "/owners/{ownerId}", "framework": "spring",
                    "line": 12}]
        content = (
            'webClient.get().uri("lb://customers-service/owners/" + id, x);\n'
            '@FeignClient(name = "visits-service")\n'
        )
        emit_source_claims("r1", _file("A.java"), content, records, "file1", sink)
        claims = _claims(sink)
        keys = {c.extra_props["key"] for c in claims}
        assert "GET:/owners/{ownerId}" in keys
        assert "httpcall:GET:/owners/{}" in keys
        assert "discovery:customers-service" in keys
        assert "discovery:visits-service" in keys
        edges = {(e.source_id, e.target_id) for e in sink.edges}
        provides = next(c for c in claims
                        if c.extra_props["key"] == "GET:/owners/{ownerId}")
        assert (provides.id, "n1") in edges

    def test_config_claims_scg(self, tmp_path):
        yml = tmp_path / "api-gateway.yml"
        yml.write_text("""
spring:
  cloud:
    gateway:
      routes:
        - id: visits
          uri: lb://visits-service
          predicates:
            - Path=/api/visit/**
          filters:
            - StripPrefix=2
""")
        result = parse_config_file(str(yml), yml.read_text())
        sink = IngestSink()
        emit_config_claims("r1", _file("config/api-gateway.yml", "yaml"),
                           result, "file1", sink)
        claims = _claims(sink)
        route = next(c for c in claims if c.extra_props["kind"] == "route")
        assert route.extra_props["key"] == "/api/visit\u2192svcname:visits-service"
        assert route.extra_props["service_hint"] == "api-gateway"
        assert route.metadata["uri"] == "lb://visits-service"
        assert route.metadata["strip_prefix"] == 2
        svc = next(c for c in claims if c.extra_props["kind"] == "svcname"
                   and c.extra_props["direction"] == "consumes")
        assert svc.extra_props["key"] == "discovery:visits-service"

    def test_compose_claims(self, tmp_path):
        yml = tmp_path / "docker-compose.yml"
        yml.write_text("""
services:
  web:
    image: acme/web:2.0
    depends_on: [api]
    environment:
      - API_URL=http://api:8080
  api:
    image: acme/api@sha256:abc123
""")
        resources = parse_docker_file(str(yml), yml.read_text())
        sink = IngestSink()
        emit_compose_claims("r9", _file("docker-compose.yml", "yaml"), resources,
                            {"web": "dweb", "api": "dapi"}, sink)
        claims = _claims(sink)
        keys = {c.extra_props["key"] for c in claims}
        assert "r9:web" in keys
        assert "r9:api" in keys
        assert "acme/web" in keys
        assert "acme/api" in keys
        consumes = [c for c in claims if c.extra_props["direction"] == "consumes"]
        assert {c.extra_props["key"] for c in consumes} == {"r9:api"}
        # 4, not 3: the subject fix keeps the env_host consumes claim that
        # previously collided with depends_on and was silently dropped.
        assert sink.claims["svcname"] == 4

    def test_config_filename_provider(self, tmp_path):
        yml = tmp_path / "customers-service.yml"
        yml.write_text("spring:\n  datasource:\n    url: jdbc:h2:mem:db\n")
        result = parse_config_file(str(yml), yml.read_text())
        sink = IngestSink()
        emit_config_claims("r1", _file("customers-service.yml", "yaml"),
                           result, "f1", sink)
        provides = [c for c in _claims(sink)
                    if c.extra_props["direction"] == "provides"]
        assert any(c.extra_props["key"] == "discovery:customers-service"
                   for c in provides)

    def test_config_filename_provider_skips_non_service_files(self, tmp_path):
        for name, body in [("application.yml", "spring:\n  a: b\n"),
                           ("messages.properties", "welcome=Hi\n")]:
            f = tmp_path / name
            f.write_text(body)
            result = parse_config_file(str(f), f.read_text())
            sink = IngestSink()
            emit_config_claims("r1", _file(name, "yaml"), result, "f1", sink)
            assert not [c for c in _claims(sink)
                        if c.metadata.get("source") == "config-filename"]

    def test_redaction_template_port(self):
        redacted = redact("some.url", "http://localhost:${server.port}/x")
        assert redacted.value_class == "url"
        assert redacted.value_port is None


class TestSourceParserFallback:
    """Tree-sitter claims an extension as soon as a grammar loads, even where
    it extracts nothing from it. Without a fallback every .ts/.tsx/.js file
    lands in the graph as a bare File node."""

    def test_typescript_component_is_recovered(self):
        from evigraph.parsers.parser_registry import parse_source
        src = (
            "import '@/styles/globals.css';\n"
            "export const metadata = { title: 'x' };\n"
            "export default function RootLayout({ children }) {\n"
            "  return <html>{children}</html>;\n"
            "}\n"
        )
        result = parse_source("apps/web/src/app/layout.tsx", src)
        assert result is not None
        assert "RootLayout" in [e.name for e in result.entities]

    def test_python_is_untouched_by_the_fallback(self):
        from evigraph.parsers.parser_registry import parse_source
        src = "class Settings:\n    def load(self):\n        return 1\n"
        result = parse_source("svc/config.py", src)
        assert [e.name for e in result.entities][:1] == ["Settings"]

    def test_genuinely_empty_file_stays_empty(self):
        from evigraph.parsers.parser_registry import parse_source
        result = parse_source("apps/web/next-env.d.ts", "/// <reference types='next' />\n")
        assert result is not None
        assert result.entities == []


class TestUnrenderedTemplateNames:
    """A chart placeholder that never got substituted is not a service name.
    These reached the live graph as real Service nodes on the map."""

    def test_helm_expressions_rejected(self):
        from evigraph.services.claims import is_unrendered_template
        for value in ("{{ .values.otel.servicename | quote }}",
                      "{{.Values.name}}",
                      "${SERVICE_NAME}",
                      "%{service}",
                      "<SERVICE_NAME>",
                      "__SERVICE__",
                      "$SERVICE_NAME"):
            assert is_unrendered_template(value), value

    def test_real_names_kept(self):
        from evigraph.services.claims import is_unrendered_template
        for value in ("capability-registry", "foyer", "iasuap/web",
                      "campaign-service-mcp", "platform-db-migrate",
                      "api_gateway", "svc.prod.internal", ""):
            assert not is_unrendered_template(value), value


class TestComposeFileRecognition:
    """Overlay compose files are named by suffix. Exact-name matching skipped
    them, taking a whole observability stack out of one estate's graph."""

    def test_overlay_names_recognised(self):
        from evigraph.parsers.parser_registry import is_docker_file
        for name in ("docker-compose.yml", "docker-compose.yaml",
                     "compose.yml", "compose.yaml",
                     "docker-compose.observability.yml",
                     "docker-compose.prod.yaml",
                     "compose.override.yml",
                     "deploy/docker-compose.ci.yml"):
            assert is_docker_file(name), name

    def test_dockerfile_still_recognised(self):
        from evigraph.parsers.parser_registry import is_docker_file
        assert is_docker_file("Dockerfile")
        assert is_docker_file("svc/api.dockerfile")

    def test_unrelated_yaml_not_treated_as_compose(self):
        from evigraph.parsers.parser_registry import is_docker_file
        for name in ("values.yaml", "deployment.yaml", "prometheus.yml",
                     "decompose.yaml", "compose-notes.md"):
            assert not is_docker_file(name), name

    def test_overlay_compose_is_actually_parsed_not_just_routed(self):
        # The registry once routed overlay names in and the parser then
        # dropped them, so routing alone proves nothing.
        from evigraph.parsers.docker_parser import parse_docker_file
        compose = (
            "services:\n"
            "  otel-collector:\n"
            "    image: otel/opentelemetry-collector:0.116.1\n"
            "    depends_on:\n"
            "      - jaeger\n"
            "  jaeger:\n"
            "    image: jaegertracing/all-in-one:1.62.0\n"
        )
        for name in ("docker-compose.observability.yml", "compose.prod.yaml"):
            resources = parse_docker_file(name, compose)
            names = [r.name for r in resources if r.type == "service"]
            assert "otel-collector" in names and "jaeger" in names, name
            collector = next(r for r in resources if r.name == "otel-collector")
            assert "jaeger" in collector.depends_on


class TestMcpManifestParser:
    """MCP servers declare tools in capability-manifest.json, not with a
    decorator: `@mcp.tool` appears once in the estate this was written for,
    while the manifests describe all 80 tools."""

    MANIFEST = {
        "schema_version": "1.0",
        "name": "dashboard-mcp",
        "version": "0.1.0",
        "description": "Dashboard analytics.",
        "domain": "analytics-reporting",
        "foyer": {"url": "http://iasuap-dashboard-mcp.svc:8107/mcp",
                  "transport": "streamable-http"},
        "tools": [
            {"name": "get_campaign_performance", "description": "snapshot",
             "destructive": False,
             "entity_target": {"entity_kind": "campaign",
                               "target_argument": "campaign_id"}},
            {"name": "update_thresholds", "description": "writes",
             "destructive": True},
        ],
    }

    def _parse(self, doc):
        import json
        from evigraph.parsers.mcp_manifest_parser import parse_mcp_manifest
        return parse_mcp_manifest("capability-manifest.json", json.dumps(doc))

    def test_tools_and_server_extracted(self):
        m = self._parse(self.MANIFEST)
        assert m.server == "dashboard-mcp"
        assert [t.name for t in m.tools] == [
            "get_campaign_performance", "update_thresholds"]
        assert m.gateway_url.endswith("/mcp")
        assert m.transport == "streamable-http"
        assert m.errors == []

    def test_destructive_and_entity_preserved(self):
        # A destructive tool is a blast-radius signal, not decoration.
        m = self._parse(self.MANIFEST)
        by_name = {t.name: t for t in m.tools}
        assert by_name["update_thresholds"].destructive is True
        assert by_name["get_campaign_performance"].destructive is False
        assert by_name["get_campaign_performance"].entity_kind == "campaign"

    def test_recognised_by_filename(self):
        from evigraph.parsers.mcp_manifest_parser import is_mcp_manifest
        assert is_mcp_manifest("servers/x/capability-manifest.json")
        assert not is_mcp_manifest("servers/x/package.json")
        assert not is_mcp_manifest("manifests/schema.json")

    def test_recognised_by_shape_under_any_filename(self):
        """No filename is standard across the ecosystem, so shape decides.

        Detecting only one estate's convention would make this extractor
        useless in every other repository.
        """
        import json
        from evigraph.parsers.mcp_manifest_parser import is_mcp_manifest
        manifest = json.dumps({
            "name": "billing-mcp",
            "tools": [{"name": "create_invoice"}, {"name": "void_invoice"}],
        })
        for path in ("svc/my-capabilities.json", "server.json", ".mcp.json",
                     "deep/nested/whatever.json"):
            assert is_mcp_manifest(path, manifest), path

    def test_shape_sniff_rejects_lookalikes(self):
        """`tools` is a common key; it alone must not be enough."""
        import json
        from evigraph.parsers.mcp_manifest_parser import is_mcp_manifest
        # A package.json listing tool NAMES as bare strings, not declarations.
        assert not is_mcp_manifest(
            "cfg.json", json.dumps({"name": "pkg", "tools": ["eslint", "prettier"]}))
        # A server name is required: an anonymous tool list identifies nothing.
        assert not is_mcp_manifest(
            "cfg.json", json.dumps({"tools": [{"name": "t"}]}))
        assert not is_mcp_manifest("README.md", json.dumps(
            {"name": "x", "tools": [{"name": "t"}]}))       # not JSON at all
        assert not is_mcp_manifest("cfg.json", '{"name":"a","tools":[')  # truncated
        # Oversized files are skipped rather than parsed: a lockfile or SBOM
        # must never be read into memory on the off-chance.
        assert not is_mcp_manifest("huge.json", " " * (256 * 1024 + 1))

    def test_non_manifest_json_declined(self):
        from evigraph.parsers.mcp_manifest_parser import parse_mcp_manifest
        assert self._parse({"name": "x"}) is None                 # no tools
        assert self._parse({"tools": []}) is None                 # no name
        assert self._parse({"$schema": "...", "type": "object"}) is None
        assert parse_mcp_manifest("capability-manifest.json", "not json") is None
        assert parse_mcp_manifest("capability-manifest.json", "[1,2]") is None

    def test_bad_entries_reported_not_silently_dropped(self):
        doc = dict(self.MANIFEST)
        doc["tools"] = [{"name": "good"}, {"description": "no name"},
                        "a string", {"name": ""}, {"name": "good"}]
        m = self._parse(doc)
        assert [t.name for t in m.tools] == ["good"]     # duplicate collapsed
        assert len(m.errors) == 4                        # and every drop noted


class TestPythonEndpointPrecision:
    """`dict.get("key")` is the most common call in Python and must never
    become an HTTP endpoint. Matching any quoted first argument manufactured
    361 contracts like `GET /caller_id` on the demo corpus."""

    def _paths(self, src: str):
        from evigraph.parsers.parser_registry import parse_source
        result = parse_source("svc.py", src)
        return [(e.method, e.path) for e in (result.api_endpoints or [])]

    def test_real_decorated_routes_are_kept(self):
        assert self._paths(
            'from fastapi import FastAPI\n'
            'app = FastAPI()\n'
            '@app.get("/owners/{owner_id}")\n'
            'def get_owner(owner_id): return {}\n'
            '@app.post("/owners")\n'
            'def create(): return 1\n'
        ) == [("GET", "/owners/{owner_id}"), ("POST", "/owners")]

    def test_dict_get_is_not_an_endpoint(self):
        assert self._paths(
            'def handle(state):\n'
            '    return state.get("task_id"), state.get("shortlist")\n'
        ) == []

    def test_http_client_call_is_not_a_provider_contract(self):
        """A client call recorded as a provider inverts the edge direction,
        which is worse than missing it."""
        assert self._paths(
            'import requests\n'
            'def fetch():\n'
            '    return requests.get("/upstream/thing")\n'
        ) == []


class TestModuleBoundary:
    """A repository is how code is STORED; a module is what owns behaviour.

    Keying crossings on repo id discarded every boundary inside a monorepo —
    on the demo estate that hid foyer -> capability-registry and
    mcp-servers -> capability-registry, exactly the calls worth surfacing.
    """

    def test_monorepo_module_is_the_dir_under_the_container(self):
        from evigraph.services.linker.modules import module_of
        assert module_of("projects/foyer/plugins/x.py") == "projects/foyer"
        assert module_of("services/billing/src/a.go") == "services/billing"
        assert module_of("apps/web/pages/index.tsx") == "apps/web"

    def test_single_service_repo_module_is_the_root_dir(self):
        from evigraph.services.linker.modules import module_of
        assert module_of("spring-petclinic-api-gateway/src/main/A.java") == \
            "spring-petclinic-api-gateway"

    def test_infrastructure_dirs_name_no_module(self):
        """A deployment descriptor says where a service RUNS, not who owns it.

        The live graph carried `Module:deploy`, `Module:docker` and
        `Module:k8s` beside real modules; a BELONGS_TO edge to those reads as
        code ownership and is not one. Declining is the same rule as
        declining an edge — and it stays counted as `r0.module_unknown`.
        """
        from evigraph.services.linker.modules import module_of
        for path in ("deploy/prod/orders.yaml", "k8s/base/svc.yaml",
                     "docker/orders/Dockerfile", "charts/orders/values.yaml",
                     # `chart` singular is the one the first list missed, on
                     # the live estate, after the plural was already there.
                     "chart/templates/deployment.yaml",
                     "terraform/main.tf", ".github/workflows/ci.yml",
                     "K8S/Base/Svc.yaml"):
            assert module_of(path) == "", path

    def test_a_real_module_is_still_named(self):
        # The exclusion must not swallow a module that merely deploys itself:
        # the first segment is what decides, not the presence of the word.
        from evigraph.services.linker.modules import module_of
        assert module_of("orders-service/deploy/prod.yaml") == "orders-service"
        assert module_of("projects/deployer/src/a.py") == "projects/deployer"

    def test_degenerate_paths_do_not_raise(self):
        from evigraph.services.linker.modules import module_of
        assert module_of("") == ""
        assert module_of(None) == ""
        # A bare container directory names no module on its own.
        # A single segment is a file at the repository root, not a module:
        # callers pass evidence paths, which are always files. Returning the
        # segment minted `Module:config.properties` once C9 made this a node.
        assert module_of("projects") == ""

    def test_two_files_in_one_module_are_not_a_crossing(self):
        from evigraph.services.linker.modules import module_of
        assert module_of("projects/foyer/a.py") == module_of("projects/foyer/b/c.py")

    def test_two_projects_in_one_repo_are_a_crossing(self):
        from evigraph.services.linker.modules import module_of
        assert module_of("projects/foyer/a.py") != \
            module_of("projects/capability-registry/b.go")
