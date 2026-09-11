"""PR-boundary gap-fill units: error paths, redaction classes, emitter variants.

Targets the small remaining coverage gaps in the ingestion/claims/util modules.
Fixtures are in-memory (SimpleNamespace parsed entities / resource dicts /
IngestSink claim sinks); no live Neo4j and no network are required.
"""

from types import SimpleNamespace

import pytest

from tracekite.services.claims import ContractClaim, claim_to_node
from tracekite.services.graph_factories import create_docker_node, create_k8s_node
from tracekite.services.http_call_extractor import extract_http_calls
from tracekite.services.ingest_artifacts import (
    process_config, process_dependencies, process_docker, process_k8s,
)
from tracekite.services.ingest_claims import emit_compose_claims, emit_config_claims
from tracekite.services.ingest_source import IngestSink, process_source_file
from tracekite.services.ingest_claims import (
    _filename_service_stem, _gateway_service_hint, _route_target, _split_image,
)
from tracekite.services.redaction import redact, shannon_entropy_bits
from tracekite.utils.canonical import canonicalize_path_template


def _file(path, language="java"):
    return SimpleNamespace(path=path, language=language)


def _claims(sink):
    return [n for n in sink.nodes if n.type == "ContractClaim"]


def _entity(name, type_="method", start=1, end=5, parent=None, params=None,
            modifiers=None, annotations=None):
    return SimpleNamespace(
        name=name, type=type_, start_line=start, end_line=end,
        signature=f"{name}()", modifiers=modifiers or [],
        annotations=annotations or [],
        metadata={"parent_class": parent, "parameters": params or []},
    )


def _source(entities=(), endpoints=(), imports=(), calls=()):
    return SimpleNamespace(
        entities=list(entities), api_endpoints=list(endpoints),
        imports=list(imports), method_calls=list(calls),
    )


def _src_file(path="src/App.java", language="Java"):
    return SimpleNamespace(path=path, language=language)


# ---------------------------------------------------------------------------
# tracekite/services/claims.py — 54, 56, 58, 102
# ---------------------------------------------------------------------------
class TestClaimsValidation:
    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown claim kind"):
            ContractClaim(repo_id="r", kind="bogus", direction="provides", key="k")

    def test_bad_direction_raises(self):
        with pytest.raises(ValueError, match="Bad claim direction"):
            ContractClaim(repo_id="r", kind="svcname", direction="sideways", key="k")

    def test_bad_hint_source_raises(self):
        with pytest.raises(ValueError, match="Bad hint_source"):
            ContractClaim(repo_id="r", kind="svcname", direction="provides",
                          key="k", hint_source="telepathy")

    def test_claim_to_node_promotes_env_scope(self):
        claim = ContractClaim(repo_id="r", kind="svcname", direction="provides",
                              key="s:api", env_scope="prod")
        node = claim_to_node(claim)
        assert node.extra_props["env_scope"] == "prod"


# ---------------------------------------------------------------------------
# tracekite/services/graph_factories.py — 121, 135-136
# ---------------------------------------------------------------------------
class TestGraphFactoryNodes:
    def test_create_docker_node(self):
        node = create_docker_node("r1", "docker-compose.yml", "web", "service",
                                  "acme/web:1.0", [8080, "9090"])
        assert node.type == "DockerResource"
        assert node.name == "web"
        assert node.extra_props["resource_type"] == "service"
        assert node.extra_props["image"] == "acme/web:1.0"
        assert node.extra_props["ports"] == ["8080", "9090"]

    def test_create_docker_node_null_ports(self):
        node = create_docker_node("r1", "f", "vol", "volume", "", None)
        assert node.extra_props["ports"] == []

    def test_create_k8s_node(self):
        node = create_k8s_node("r1", "deploy.yaml", "Deployment", "api",
                               "prod", "apps/v1")
        assert node.type == "KubernetesResource"
        assert node.name == "Deployment/api"
        assert node.label == "Deployment/api"
        assert node.extra_props["kind"] == "Deployment"
        assert node.extra_props["resource_name"] == "api"
        assert node.extra_props["namespace"] == "prod"
        assert node.extra_props["api_version"] == "apps/v1"


# ---------------------------------------------------------------------------
# tracekite/services/http_call_extractor.py
# ---------------------------------------------------------------------------
class TestHttpCallExtractorGaps:
    def test_java_put_delete_literal(self):
        # line 92: _JAVA_PUT_DELETE branch
        content = 'restTemplate.delete("http://orders-service/orders/{id}", id);'
        sites = extract_http_calls("A.java", content, "java")
        assert len(sites) == 1
        assert sites[0].method == "DELETE"
        assert sites[0].service_hint == "orders-service"

    def test_webclient_create_base_url(self):
        # line 101: _WEBCLIENT_CREATE -> base_url=True
        content = 'WebClient.create("http://accounts-service")'
        sites = extract_http_calls("B.java", content, "java")
        assert len(sites) == 1
        assert sites[0].attrs.get("base_url") is True
        assert sites[0].service_hint == "accounts-service"

    def test_axios_config_object(self):
        # lines 116-119: _AXIOS_CONFIG branch
        content = "axios({ method: 'put', url: '/api/carts/checkout' })"
        sites = extract_http_calls("app.ts", content, "typescript")
        cfg = [s for s in sites if s.client == "axios"]
        assert cfg
        assert cfg[0].method == "PUT"
        assert cfg[0].path_template == "/api/carts/checkout"

    def test_axios_config_default_method(self):
        content = "axios({ url: '/api/things' })"
        sites = extract_http_calls("app.ts", content, "typescript")
        cfg = [s for s in sites if s.client == "axios"]
        assert cfg and cfg[0].method == "GET"

    def test_env_ref_url_dropped_from_host_hint(self):
        # lines 137 (parsed None path is not this) & 180-181: env_ref host
        content = 'restTemplate.getForObject("http://${SVC_HOST}/pets", X.class);'
        sites = extract_http_calls("C.java", content, "java")
        assert sites and sites[0].attrs.get("env_ref")
        assert sites[0].service_hint is None
        assert sites[0].hint_source == "none"

    def test_external_host_no_hint(self):
        # line 188-189 external; ensures classify path reached
        content = 'restTemplate.getForObject("https://api.stripe.com/v1/charges", X.class);'
        sites = extract_http_calls("D.java", content, "java")
        assert sites[0].attrs.get("external")
        assert sites[0].service_hint is None

    def test_lb_url_local_host_returns_no_hint(self):
        # line 159: lb:// where host resolves to a local host (no service hint)
        content = 'webClient.get().uri("lb://localhost/pets", x)'
        sites = extract_http_calls("E.java", content, "java")
        assert len(sites) == 1
        assert sites[0].service_hint is None
        # local host: hint_source stays "none", not "discovery"
        assert sites[0].hint_source == "none"

    def test_unclassifiable_url_dropped(self):
        # line 137/174: _classify_url returns None -> site skipped
        content = 'restTemplate.getForObject("://", X.class);'
        sites = extract_http_calls("F.java", content, "java")
        assert sites == []


# ---------------------------------------------------------------------------
# tracekite/services/ingest_artifacts.py — 25, 40, 50-64, 69-77
# ---------------------------------------------------------------------------
class TestIngestArtifactsGaps:
    def test_process_dependencies_skips_nameless(self):
        # line 25: continue on empty name
        sink = IngestSink()
        deps = [SimpleNamespace(name="", version="1", scope="", type="npm"),
                SimpleNamespace(name="express", version="4", scope="prod", type="npm")]
        process_dependencies("r1", _file("package.json"), deps, "file-a", sink)
        names = [n.name for n in sink.nodes if n.type == "Dependency"]
        assert names == ["express"]

    def test_process_config_skips_keyless(self):
        # line 40: continue on empty key
        sink = IngestSink()
        config = SimpleNamespace(
            entries=[SimpleNamespace(key="", value="x"),
                     SimpleNamespace(key="server.port", value="8080")],
            app_name=None, app_name_line=0, gateway_routes=[],
        )
        process_config("r1", _file("app.yml", "yaml"), config, "file-a", sink)
        cfg_names = [n.name for n in sink.nodes if n.type == "Config"]
        assert cfg_names == ["server.port"]

    def test_process_docker(self):
        # lines 50-64: docker resources -> nodes/edges + compose claims path
        sink = IngestSink()
        resources = [
            SimpleNamespace(name="", type="service", image="", ports=[],
                            project="", depends_on=[], links=[],
                            build_context="", env_pairs={}, line=1),
            SimpleNamespace(name="web", type="service", image="acme/web:1.0",
                            ports=[8080], project="proj", depends_on=[],
                            links=[], build_context="", env_pairs={}, line=2),
        ]
        process_docker("r1", _file("docker-compose.yml", "yaml"), resources,
                       "file-a", sink)
        docker_nodes = [n for n in sink.nodes if n.type == "DockerResource"]
        assert [n.name for n in docker_nodes] == ["web"]
        declares = [e for e in sink.edges if e.type == "DECLARES"]
        assert declares
        # svcname + image provides claims emitted for the service node
        claim_kinds = {c.extra_props["kind"] for c in _claims(sink)}
        assert "svcname" in claim_kinds and "image" in claim_kinds

    def test_process_k8s(self):
        # k8s resources -> nodes/edges/claims, skipping missing name/kind.
        # Uses real K8sResource objects: the parser is the only producer, and
        # the claim emitters read spec fields that a bare stub does not have.
        from tracekite.parsers.kubernetes_parser import K8sResource
        sink = IngestSink()
        resources = [
            K8sResource(name="", kind="Deployment"),
            K8sResource(name="api", kind=""),
            K8sResource(name="api", kind="Deployment", namespace="prod"),
        ]
        process_k8s("r1", _file("deploy.yaml", "yaml"), resources, "file-a", sink)
        k8s_nodes = [n for n in sink.nodes if n.type == "KubernetesResource"]
        assert len(k8s_nodes) == 1
        assert k8s_nodes[0].name == "Deployment/api"
        declares = [e for e in sink.edges if e.type == "DECLARES"]
        assert len(declares) == 1
        # The surviving workload still names a service, scoped by namespace.
        svcnames = [c for c in _claims(sink)
                    if c.extra_props["kind"] == "svcname"]
        assert [c.extra_props["key"] for c in svcnames] == ["prod:api"]


# ---------------------------------------------------------------------------
# tracekite/services/ingest_claims.py
# ---------------------------------------------------------------------------
class TestIngestClaimsGaps:
    def test_base_url_service_hint_svcname_only(self):
        # lines 50-57: base_url site with a service hint -> svcname consumes
        from tracekite.services.ingest_claims import emit_source_claims
        sink = IngestSink()
        content = 'WebClient.create("http://accounts-service")'
        emit_source_claims("r1", _file("A.java"), content, [], "file1", sink)
        claims = _claims(sink)
        assert len(claims) == 1
        c = claims[0]
        assert c.extra_props["kind"] == "svcname"
        assert c.extra_props["direction"] == "consumes"
        assert c.extra_props["key"] == "discovery:accounts-service"
        assert c.metadata["base_url"] is True

    def test_base_url_without_hint_emits_nothing(self):
        # line 57: base_url but no service_hint -> continue, no claim
        from tracekite.services.ingest_claims import emit_source_claims
        sink = IngestSink()
        content = 'WebClient.create("http://localhost:8080")'
        emit_source_claims("r1", _file("A.java"), content, [], "file1", sink)
        assert _claims(sink) == []

    def test_config_app_name_provider(self):
        # line 100: config_result.app_name provides claim
        sink = IngestSink()
        config = SimpleNamespace(
            entries=[SimpleNamespace(key="spring.application.name", value="billing")],
            app_name="billing-service", app_name_line=7, gateway_routes=[],
        )
        emit_config_claims("r1", _file("application.yml", "yaml"), config,
                           "file1", sink)
        provides = [c for c in _claims(sink)
                    if c.extra_props["direction"] == "provides"]
        keys = {c.extra_props["key"] for c in provides}
        assert "discovery:billing-service" in keys

    def test_gateway_route_default_prefix_and_target_filters(self):
        # lines 113, 115-127: route with no target skipped; default "/" prefix
        route_ok = SimpleNamespace(uri="lb://cart-service", route_id="cart",
                                   path_predicates=[], strip_prefix=1,
                                   rewrite_path="", line=3)
        route_skip = SimpleNamespace(uri="kafka://nope", route_id="k",
                                     path_predicates=["/x/**"], strip_prefix=None,
                                     rewrite_path="", line=4)
        config = SimpleNamespace(entries=[], app_name="gw", app_name_line=1,
                                 gateway_routes=[route_ok, route_skip])
        sink = IngestSink()
        emit_config_claims("r1", _file("gw.yml", "yaml"), config, "file1", sink)
        routes = [c for c in _claims(sink) if c.extra_props["kind"] == "route"]
        assert len(routes) == 1
        assert routes[0].extra_props["key"] == "/\u2192svcname:cart-service"

    def test_compose_links_and_env_host_and_image_split(self):
        # lines 140/144/148/189/195/200/206/212-216/226 in ingest_claims:
        # missing evidence node skip, build_context attr, links, env_host, image
        web = SimpleNamespace(
            name="web", type="service", image="acme/web@sha256:deadbeef",
            project="proj", depends_on=["db"], links=["cache"],
            build_context="./web",
            env_pairs={"UPSTREAM": "http://payments:8080/pay",
                       "IGNORED": "42"},
            line=2)
        # service missing evidence node -> skipped (line 143-144)
        ghost = SimpleNamespace(name="ghost", type="service", image="",
                                project="proj", depends_on=[], links=[],
                                build_context="", env_pairs={}, line=9)
        non_service = SimpleNamespace(name="net", type="network", image="",
                                      project="proj", depends_on=[], links=[],
                                      build_context="", env_pairs={}, line=5)
        sink = IngestSink()
        emit_compose_claims("r1", _file("docker-compose.yml", "yaml"),
                            [web, non_service, ghost],
                            {"web": "dweb"}, sink)
        claims = _claims(sink)
        keys = {c.extra_props["key"] for c in claims}
        # svcname provides for the service itself
        assert "proj:web" in keys
        # image provides (digest split -> ref only)
        image_claim = next(c for c in claims if c.extra_props["kind"] == "image")
        assert image_claim.extra_props["key"] == "acme/web"
        assert image_claim.metadata["tag"] == "sha256:deadbeef"
        # depends_on + links consumers
        assert "proj:db" in keys
        assert "proj:cache" in keys
        # env_host consumer derived from the http URL host "payments"
        assert "proj:payments" in keys
        env_claim = next(c for c in claims if c.metadata.get("via") == "env_host")
        assert env_claim.metadata["env_key"] == "UPSTREAM"

    def test_filename_service_stem_variants(self):
        # line 189: non-config extension -> None
        assert _filename_service_stem("notes.txt") is None
        # line 195: stem has non-host chars (dot) -> None
        assert _filename_service_stem("my.service.yml") is None
        # positive: clean service stem
        assert _filename_service_stem("orders-service.yaml") == "orders-service"

    def test_gateway_service_hint_variants(self):
        # line 200: app_name wins
        assert _gateway_service_hint("x.yml", SimpleNamespace(app_name="gw")) == "gw"
        # line 203: application/bootstrap stem -> None
        assert _gateway_service_hint("application.yml",
                                     SimpleNamespace(app_name=None)) is None
        # line 204: clean stem -> stem
        assert _gateway_service_hint("edge-gateway.yml",
                                     SimpleNamespace(app_name=None)) == "edge-gateway"
        # line 206: stem with non-host chars -> None
        assert _gateway_service_hint("weird.name.yml",
                                     SimpleNamespace(app_name=None)) is None

    def test_route_target_variants(self):
        # lines 210-216
        assert _route_target("lb://cart-service/x") == "cart-service"
        # http:// with dotless host -> host
        assert _route_target("http://orders/x") == "orders"
        # http:// with dotted host -> None
        assert _route_target("http://api.example.com/x") is None
        # unknown scheme -> None
        assert _route_target("kafka://topic") is None

    def test_split_image_variants(self):
        # line 226: no tag, no digest -> ("image", "")
        assert _split_image("nginx") == ("nginx", "")
        assert _split_image("acme/api") == ("acme/api", "")
        assert _split_image("postgres:16") == ("postgres", "16")
        ref, digest = _split_image("acme/web@sha256:abc")
        assert ref == "acme/web" and digest == "sha256:abc"

    def test_compose_image_tag_split(self):
        # line 224: image "repo:tag" split (no digest)
        svc = SimpleNamespace(name="db", type="service", image="postgres:16",
                              project="proj", depends_on=[], links=[],
                              build_context="", env_pairs={}, line=1)
        sink = IngestSink()
        emit_compose_claims("r1", _file("docker-compose.yml", "yaml"), [svc],
                            {"db": "ddb"}, sink)
        image_claim = next(c for c in _claims(sink)
                           if c.extra_props["kind"] == "image")
        assert image_claim.extra_props["key"] == "postgres"
        assert image_claim.metadata["tag"] == "16"


# ---------------------------------------------------------------------------
# tracekite/services/ingest_source.py — 75, 94, 115
# ---------------------------------------------------------------------------
class TestIngestSourceGaps:
    def test_unknown_entity_type_skipped(self):
        # line 75: node_type is None -> continue
        sink = IngestSink()
        source = _source(entities=[
            _entity("Weird", type_="enum"),
            _entity("real", type_="function", start=2),
        ])
        process_source_file("r1", _src_file(path="a.py", language="Python"),
                            source, "file-node", sink, "full")
        types = {n.type for n in sink.nodes}
        assert "Function" in types
        assert not [n for n in sink.nodes if n.name == "Weird"]

    def test_modifiers_promoted_to_metadata(self):
        # line 94: entity.modifiers -> metadata["modifiers"]
        sink = IngestSink()
        source = _source(entities=[
            _entity("run", type_="method", modifiers=["public", "static"],
                    annotations=["@Override"]),
        ])
        process_source_file("r1", _src_file(), source, "file-node", sink, "full")
        node = next(n for n in sink.nodes if n.type == "Method")
        assert node.metadata["modifiers"] == ["public", "static"]
        assert node.metadata["annotations"] == ["@Override"]

    def test_duplicate_entity_id_skipped(self):
        # line 115: sink.add_node returns False -> continue (no double edge)
        sink = IngestSink()
        source = _source(entities=[
            _entity("dup", type_="method", start=1),
            _entity("dup", type_="method", start=1),
        ])
        process_source_file("r1", _src_file(), source, "file-node", sink, "full")
        methods = [n for n in sink.nodes if n.type == "Method"]
        # same name/arity/occurrence-order still yields distinct occ index;
        # force a true duplicate by pre-seeding the id set instead:
        assert len(methods) == 2

    def test_true_duplicate_via_preseeded_id(self):
        sink = IngestSink()
        source1 = _source(entities=[_entity("only", type_="method", start=1)])
        process_source_file("r1", _src_file(), source1, "file-node", sink, "full")
        entities_before = sink.lang("Java")["entities"]
        # Re-run the identical file: identical ids already present -> skipped
        source2 = _source(entities=[_entity("only", type_="method", start=1)])
        process_source_file("r1", _src_file(), source2, "file-node", sink, "full")
        methods = [n for n in sink.nodes if n.type == "Method"]
        assert len(methods) == 1
        # entities counter not incremented on the skipped second pass
        assert sink.lang("Java")["entities"] == entities_before


# ---------------------------------------------------------------------------
# tracekite/services/redaction.py — 62, 85, 107, 133, 135-139, 143
# ---------------------------------------------------------------------------
class TestRedactionGaps:
    def test_empty_value_opaque(self):
        r = redact("plain.key", "")
        assert r.value_class == "opaque"
        assert r.value_len == 0

    def test_shannon_entropy_empty_zero(self):
        # line 62: empty string -> 0.0
        assert shannon_entropy_bits("") == 0.0
        assert shannon_entropy_bits("aaaa") == 0.0
        assert shannon_entropy_bits("ab") == 1.0

    def test_url_without_host_or_path_not_url(self):
        # line 85: scheme present but no hostname/path -> not classified url
        r = redact("weird", "scheme://")
        assert r.value_class != "url"

    def test_number_float(self):
        # line 133: fullmatch float -> number
        r = redact("ratio", "3.14")
        assert r.value_class == "number"

    def test_hostname_with_port(self):
        # lines 134-140: hostname with :port
        r = redact("db.host", "db.internal:5432")
        assert r.value_class == "hostname"
        assert r.value_host == "db.internal"
        assert r.value_port == 5432

    def test_hostname_without_port(self):
        r = redact("db.host", "cache.internal")
        assert r.value_class == "hostname"
        assert r.value_host == "cache.internal"
        assert r.value_port is None

    def test_opaque_fallback(self):
        # line 143: value not matching any class -> opaque
        r = redact("blob", "not an enum has spaces!!")
        assert r.value_class == "opaque"

    def test_big_number_not_port(self):
        r = redact("count", "70000")
        assert r.value_class == "number"


# ---------------------------------------------------------------------------
# tracekite/utils/canonical.py — 32
# ---------------------------------------------------------------------------
class TestCanonicalGaps:
    def test_embedded_param_within_segment(self):
        # line 32: segment contains but is not solely a param -> partial sub
        assert canonicalize_path_template("/files/prefix-{id}.json") == \
            "/files/prefix-{}.json"

    def test_angle_embedded_param(self):
        assert canonicalize_path_template("/users/<int:id>-detail") == \
            "/users/{}-detail"
