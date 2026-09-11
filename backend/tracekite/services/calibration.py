"""Confidence calibration harness.

Design invariant 7: no resolver tier serves `active` edges without a measured
P/R row. This module produces those rows by running the REAL claim pipeline —
the same emit_* functions ingestion uses, the same RESOLVERS tuple the linker
runs, in the same order — over small labeled estates whose expected and
forbidden edges are constructed truth.

Per (resolver_section, tier):
  TP = expected edges found (attributed via the edge's match_type mapping)
  FP = forbidden edges that appeared, attributed to their tier
  FN = expected-but-missing, attributed to the tier named in the expectation
precision = TP/(TP+FP), recall = TP/(TP+FN), support = TP+FN.

A false positive here is not a fixture problem — the estates are constructed
truth, so an FP is a real resolver bug. `run_calibration()` therefore returns
a `_diagnostics` key naming the estate and edge behind every miss.

`write_measured()` appends/replaces a clearly-delimited `measured:` block at
the END of confidence.yml (PyYAML would drop the file's comments, so the flat
tier table above the marker is never rewritten). `coverage_gaps()` lists every
flat tier that has no measured row — the harness's own exit criteria.
"""

from __future__ import annotations

import os
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace

import yaml

from tracekite.parsers.docker_parser import parse_docker_compose
from tracekite.services.calibration_tiers import edge_tier
from tracekite.services.linker.confidence_math import wilson_interval
from tracekite.parsers.gateway_parser import parse_js_proxies, parse_nginx_conf
from tracekite.parsers.iac_parser import parse_terraform
from tracekite.parsers.kubernetes_parser import parse_kubernetes_yaml
from tracekite.parsers.ownership_parser import (
    extract_observability_identity, parse_catalog_info, parse_codeowners,
)
from tracekite.parsers.proto_parser import parse_proto
from tracekite.parsers.graphql_parser import parse_graphql_schema
from tracekite.parsers.dependency_parser import DependencyInfo
from tracekite.services.claims import CONSUMES, PROVIDES, ContractClaim, topic_key
from tracekite.services.ingest_claims import (
    add_claim, emit_catalog_claims, emit_codeowners_claims, emit_compose_claims,
    emit_gateway_claims, emit_graphql_claims,
    emit_graphql_client_claims, emit_grpc_site_claims, emit_iac_claims,
    emit_k8s_claims, emit_observability_claims, emit_proto_claims,
    emit_source_claims,
)
from tracekite.services.ingest_deps import (
    emit_dependency_claims, emit_publish_claims,
)
from tracekite.services.ingest_source import IngestSink
from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)
# RESOLVERS is imported from the linker service so the calibration pipeline can
# never drift from the production resolver order.
from tracekite.services.linker.edge_policy import apply_confidence_floor
from tracekite.services.linker.engine import materialize_pending, run_resolvers
from tracekite.utils.hashing import generate_repo_id


# Internal package boundary used by the R3 estates, mirroring the fixture
# boundary test_m7_packages.py pins. Patched in for the duration of a
# calibration run so results do not depend on the operator's live
# internal_namespaces.yml.
_INTERNAL_NAMESPACES = {
    "maven": {"namespaces": ["org.acme"]},
    "npm": {"scopes": ["@acme"]},
}


@dataclass
class LabeledEstate:
    """A small claim estate with labeled edge-level truth.

    ``expect``/``forbid`` entries match on the subset of keys given. Keys are
    GraphEdge attributes (``type``, ``match_type``, ``claim_key``,
    ``source_id``, ``target_id``, ``source_repo_id``, ``target_repo_id``) plus
    ``via`` (membership in ``extra_props["via"]``). Every entry also carries
    ``tier`` ("rN.tier_name") so misses attribute to the right measured row.
    """
    name: str
    claims: list = field(default_factory=list)
    expect: list[dict] = field(default_factory=list)
    forbid: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------
# Estate plumbing (the exact conversion pattern the M2-M10 e2e tests use)
# --------------------------------------------------------------------------

def _file(path: str, language: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(path=path, language=language)


def _sink_claims(sink: IngestSink, repo_id: str) -> list[ClaimRecord]:
    """Convert emitted claim nodes back into the linker's ClaimRecord shape."""
    records = []
    for node in sink.nodes:
        if node.type != "ContractClaim":
            continue
        extra = node.extra_props
        attrs = dict(node.metadata or {})
        if extra.get("env_scope"):
            attrs["env_scope"] = extra["env_scope"]
        records.append(ClaimRecord(
            id=node.id, repo_id=repo_id, kind=extra["kind"],
            direction=extra["direction"], key=extra["key"],
            service_hint=extra.get("service_hint"),
            hint_source=extra.get("hint_source", "none"),
            matchable=bool(extra.get("matchable", True)),
            evidence=list(extra.get("evidence") or []),
            attrs=attrs,
            evidence_node_id=f"node:{node.id}", evidence_node_type="File",
        ))
    return records


def _k8s_claims(repo_id: str, path: str, manifest: str,
                sink: IngestSink | None = None) -> list[ClaimRecord]:
    sink = sink or IngestSink()
    resources = parse_kubernetes_yaml(path, manifest)
    node_ids = {f"{r.kind}/{r.name}": f"k8s:{repo_id}:{r.kind}/{r.name}"
                for r in resources}
    emit_k8s_claims(repo_id, _file(path, "yaml"), resources, node_ids, sink)
    return _sink_claims(sink, repo_id)


def _iac_claims(repo_id: str, path: str, content: str) -> list[ClaimRecord]:
    sink = IngestSink()
    resources = parse_terraform(path, content)
    node_ids = {r.address: f"iac:{r.address}" for r in resources}
    emit_iac_claims(repo_id, _file(path), resources, node_ids, sink)
    return _sink_claims(sink, repo_id)


def _service_claim(repo_id: str, name: str, scope: str = "prod",
                   path: str = "deploy/app.yaml") -> list[ClaimRecord]:
    """A svcname provides claim so R0 mints the Service (test_m6 pattern)."""
    sink = IngestSink()
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=f"{scope}:{name}", service_hint=name, hint_source="config",
        evidence=[f"{path}:1"], subject=f"svc/{name}",
        attrs={"source": "k8s", "workload": name},
    ), f"file:{repo_id}:{path}", sink)
    return _sink_claims(sink, repo_id)


def _app_name_claim(repo_id: str, name: str, module: str) -> list[ClaimRecord]:
    """spring.application.name provider — registers the module scope."""
    sink = IngestSink()
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=f"discovery:{name}", service_hint=name, hint_source="config",
        evidence=[f"{module}/app.yml:1"], subject=f"app/{name}",
        attrs={"source": "spring.application.name"},
    ), f"file:{repo_id}:{module}", sink)
    return _sink_claims(sink, repo_id)


def _code_topic_claim(repo_id: str, system: str, name: str, role: str,
                      path: str = "src/produce.py") -> list[ClaimRecord]:
    """A literal producer/consumer site claim (test_m4 pattern)."""
    sink = IngestSink()
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="topic",
        direction=PROVIDES if role == "produces" else CONSUMES,
        key=topic_key(system, name), hint_source="none",
        evidence=[f"{path}:10"], subject=f"msg/cal/{role}/{name}",
        attrs={"system": system, "framework": "calibration", "role": role},
    ), f"file:{repo_id}:{path}", sink)
    return _sink_claims(sink, repo_id)


def _http_claim(kind: str, direction: str, key: str, repo: str, *,
                hint: str | None = None, hint_source: str = "none",
                attrs: dict | None = None, evidence: list | None = None,
                enode: str | None = None) -> ClaimRecord:
    """Hand-built ClaimRecord — sanctioned for R7 by test_linker_matching."""
    return ClaimRecord(
        id=f"claim:{repo}:{kind}:{direction}:{key}", repo_id=repo, kind=kind,
        direction=direction, key=key, service_hint=hint,
        hint_source=hint_source, matchable=True, attrs=attrs or {},
        evidence=evidence or [f"{repo}/src/App.java:10"],
        evidence_node_id=enode, evidence_node_type="File" if enode else "",
    )


# --------------------------------------------------------------------------
# Fixture sources
# --------------------------------------------------------------------------

_PROTO = """
syntax = "proto3";

package petclinic.orders.v1;

message GetOrderRequest { string id = 1; }
message Order { string id = 1; }

service OrdersService {
  rpc GetOrder(GetOrderRequest) returns (Order);
  rpc ListOrders(ListRequest) returns (stream Order);
}
"""

_GRAPHQL_SDL = '''
type Query {
  owner(id: ID!): Owner
  owners(first: Int): [Owner!]!
}

type Owner @key(fields: "id") {
  id: ID!
  name: String
}
'''

_ORDERS_MANIFEST = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-deploy
  namespace: prod
  labels: {app.kubernetes.io/name: orders}
spec:
  template:
    metadata:
      labels: {app: orders}
    spec:
      containers:
        - name: app
          image: registry.internal/myorg/orders:1.2.3
          env:
            - name: VETS_URL
              value: http://vets.prod.svc.cluster.local:8080
---
apiVersion: v1
kind: Service
metadata: {name: orders, namespace: prod}
spec:
  selector: {app: orders}
  ports: [{port: 8080}]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vets-deploy
  namespace: prod
  labels: {app.kubernetes.io/name: vets}
spec:
  template:
    metadata:
      labels: {app: vets}
    spec:
      containers:
        - name: app
          image: registry.internal/myorg/vets:2.0.0
---
apiVersion: v1
kind: Service
metadata: {name: vets, namespace: prod}
spec:
  selector: {app: vets}
  ports: [{port: 8080}]
"""

_STOREFRONT_MANIFEST = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: storefront
  namespace: prod
  labels: {app.kubernetes.io/name: storefront}
spec:
  template:
    metadata:
      labels: {app: storefront}
    spec:
      containers:
        - name: app
          image: registry.internal/myorg/web:1
          env:
            - name: ORDERS_URL
              value: http://orders.prod.svc.cluster.local:8080
---
apiVersion: v1
kind: Service
metadata: {name: storefront, namespace: prod}
spec: {selector: {app: storefront}}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders
  namespace: prod
  labels: {app.kubernetes.io/name: orders}
spec:
  template:
    metadata:
      labels: {app: orders}
    spec:
      containers: [{name: app, image: registry.internal/myorg/orders:1}]
---
apiVersion: v1
kind: Service
metadata: {name: orders, namespace: prod}
spec: {selector: {app: orders}}
"""

_ENV_DEPLOY = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
  namespace: {namespace}
spec:
  selector:
    matchLabels: {{app: {name}}}
  template:
    metadata:
      labels: {{app: {name}}}
    spec:
      containers:
        - name: app
          image: acme/shipping:1.0
          env:
            - name: ORDERS_TOPIC
              value: {value}
"""

_KEDA_YAML = """
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orders-scaler
  namespace: prod
spec:
  scaleTargetRef:
    name: order-worker
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka:9092
        consumerGroup: order-workers
        topic: order-events
    - type: aws-sqs-queue
      metadata:
        queueURL: https://sqs.us-east-1.amazonaws.com/123456789/refund-requests
        queueLength: "5"
"""

_TERRAFORM = '''
resource "aws_sqs_queue" "refunds" {
  name = "refund-requests"
}

resource "aws_sns_topic" "order_events" {
  name = "order-fanout"
}

resource "aws_sns_topic_subscription" "fanout" {
  topic_arn = aws_sns_topic.order_events.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.refunds.arn
}
'''

_COMPOSE = """
name: shopstack
services:
  storefront:
    image: acme/storefront:1.0
    depends_on: [orders-api]
    environment:
      - PAYMENTS_URL=http://payments-svc:8080
      # The default that runs unless overridden: authored, citable, weaker
      # than a literal.
      - INVENTORY_HOST=${INVENTORY_HOST:-inventory-svc}
      # The trap. `postgres` is a USERNAME whose spelling happens to match a
      # service in this estate; the key does not name a network target, so
      # no claim may be minted and no edge may appear.
      - DB_USER=${DB_USER:-postgres}
  orders-api:
    build: ./orders
  payments-svc:
    image: acme/payments:1.0
  inventory-svc:
    image: acme/inventory:1.0
  postgres:
    image: postgres:16
"""

_NGINX = """
upstream orders_backend {
    server orders:8080;
}
server {
    listen 80;
    server_name shop.example.com;
    location /api/ {
        proxy_pass http://orders_backend/;
    }
}
"""

_VITE = """
export default {
  server: {
    proxy: {
      '/api': 'http://payments-svc:8080'
    }
  }
}
"""

_ARGO_APP = """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: orders}
spec:
  source: {repoURL: "https://github.com/myorg/orders", path: k8s}
  destination: {namespace: prod}
"""

_CATALOG = """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: orders-service
  annotations:
    pagerduty.com/service-id: PD12345
spec:
  type: service
  lifecycle: production
  owner: group:default/payments-team
  system: checkout
"""

_CODEOWNERS = """
*            @acme/platform-team
/backend/    @acme/payments-team @jane
"""

_DATADOG_ENV = """
DD_SERVICE=orders-service
DD_ENV=prod
DD_TAGS=team:payments-team,region:us-east-1
"""

_GRPC_KEY = "petclinic.orders.v1.OrdersService"


# --------------------------------------------------------------------------
# Estates
# --------------------------------------------------------------------------

def _estate_grpc_cross_repo() -> LabeledEstate:
    proto = IngestSink()
    emit_proto_claims("repo_contracts", _file("proto/orders.proto", "proto"),
                      parse_proto("proto/orders.proto", _PROTO),
                      "file:proto", proto)
    server = IngestSink()
    emit_grpc_site_claims(
        "repo_orders", _file("src/main/java/OrdersImpl.java", "java"),
        "@GrpcService\npublic class OrdersImpl extends "
        "OrdersServiceGrpc.OrdersServiceImplBase {}", "file:server", server)
    client = IngestSink()
    emit_grpc_site_claims(
        "repo_web", _file("internal/client/orders.go", "go"),
        "client := pb.NewOrdersServiceClient(conn)", "file:client", client)
    # A stub naming the fully-qualified package.Service — the r5.exact tier.
    # No shipped extractor emits a qualified stub today (they all strip to the
    # bare generated-class name), so this half is authored through the same
    # claim pipeline instead.
    qualified = IngestSink()
    add_claim("repo_dash", ContractClaim(
        repo_id="repo_dash", kind="grpcstub", direction=CONSUMES,
        key=_GRPC_KEY, service_hint=_GRPC_KEY, hint_source="none",
        evidence=["src/dash/client.py:7"], subject="grpc/consumes/qualified",
        attrs={"source": "grpc_code", "service": _GRPC_KEY},
    ), "file:dash", qualified)

    claims = (_sink_claims(proto, "repo_contracts")
              + _sink_claims(server, "repo_orders")
              + _sink_claims(client, "repo_web")
              + _sink_claims(qualified, "repo_dash")
              # Service identities so the pending gRPC call materializes:
              # module attribution for the Go client repo and a Service that
              # matches the proto's kebab-cased short name.
              + _service_claim("repo_web", "web-shop", path="deploy/web.yaml")
              + _service_claim("repo_orders", "orders-service",
                               path="deploy/orders.yaml"))
    get_order = f"{_GRPC_KEY}/GetOrder"
    return LabeledEstate(
        name="grpc_cross_repo", claims=claims,
        expect=[
            {"tier": "r5.declared", "type": "DECLARES_CONTRACT",
             "match_type": "declared", "claim_key": get_order},
            {"tier": "r5.service_name", "type": "EXPOSES",
             "match_type": "grpc_service_name", "claim_key": get_order,
             "source_repo_id": "repo_orders"},
            {"tier": "r5.service_name", "type": "INVOKES",
             "match_type": "grpc_service_name", "claim_key": get_order,
             "source_repo_id": "repo_web"},
            {"tier": "r5.exact", "type": "INVOKES",
             "match_type": "grpc_qualified", "claim_key": get_order,
             "source_repo_id": "repo_dash"},
            {"tier": "r5.calls_service", "type": "CALLS_SERVICE",
             "match_type": "grpc", "source_id": "global:Service:web-shop",
             "target_id": "global:Service:orders-service"},
        ])


def _estate_grpc_test_provenance() -> LabeledEstate:
    """Adversarial: a stub built in a test file is not a dependency.

    Validates that the provenance gate (matchable=False upstream) holds
    through the full resolver pipeline.
    """
    proto = IngestSink()
    emit_proto_claims("repo_contracts", _file("proto/orders.proto", "proto"),
                      parse_proto("proto/orders.proto", _PROTO),
                      "file:proto", proto)
    tests = IngestSink()
    emit_grpc_site_claims(
        "repo_web", _file("src/test/java/OrdersClientTest.java", "java"),
        "var stub = OrdersServiceGrpc.newBlockingStub(channel);",
        "file:test", tests, provenance="test")
    return LabeledEstate(
        name="grpc_test_provenance",
        claims=(_sink_claims(proto, "repo_contracts")
                + _sink_claims(tests, "repo_web")),
        expect=[{"tier": "r5.declared", "type": "DECLARES_CONTRACT",
                 "match_type": "declared",
                 "claim_key": f"{_GRPC_KEY}/GetOrder"}],
        forbid=[{"tier": "r5.service_name", "type": "INVOKES"},
                {"tier": "r5.calls_service", "type": "CALLS_SERVICE"}])


def _estate_graphql_ownership() -> LabeledEstate:
    server = IngestSink()
    emit_graphql_claims(
        "repo_api", _file("schema.graphql", "graphql"),
        {"schema": parse_graphql_schema("schema.graphql", _GRAPHQL_SDL),
         "operations": []}, "file:schema", server)
    client = IngestSink()
    emit_graphql_client_claims(
        "repo_web", _file("src/queries.ts", "typescript"),
        "const Q = gql`query GetOwner { owner { id } }`;",
        "file:client", client)
    # A single-owner unfederated schema: field-name tier, no ambiguity.
    reviews = IngestSink()
    emit_graphql_claims(
        "repo_reviews", _file("reviews.graphql", "graphql"),
        {"schema": parse_graphql_schema("reviews.graphql",
                                        "type Query { reviews: String }"),
         "operations": []}, "file:reviews", reviews)
    mobile = IngestSink()
    emit_graphql_client_claims(
        "repo_mobile", _file("src/reviews.ts", "typescript"),
        "const R = gql`query { reviews }`;", "file:mobile", mobile)
    return LabeledEstate(
        name="graphql_ownership",
        claims=(_sink_claims(server, "repo_api")
                + _sink_claims(client, "repo_web")
                + _sink_claims(reviews, "repo_reviews")
                + _sink_claims(mobile, "repo_mobile")),
        expect=[
            {"tier": "r8.declared", "type": "EXPOSES",
             "match_type": "declared", "claim_key": "Query.owner",
             "source_repo_id": "repo_api"},
            {"tier": "r8.federated", "type": "INVOKES",
             "match_type": "graphql_federated", "claim_key": "Query.owner",
             "source_repo_id": "repo_web", "target_repo_id": "repo_api"},
            {"tier": "r8.field_name", "type": "INVOKES",
             "match_type": "graphql_field_name", "claim_key": "Query.reviews",
             "source_repo_id": "repo_mobile",
             "target_repo_id": "repo_reviews"},
        ])


def _estate_graphql_ambiguous() -> LabeledEstate:
    """Adversarial: `Query.user` in two repos, no federation — a coin flip."""
    plain = "type Query { user: String }"
    a, b, client = IngestSink(), IngestSink(), IngestSink()
    emit_graphql_claims("repo_a", _file("a.graphql", "graphql"),
                        {"schema": parse_graphql_schema("a.graphql", plain),
                         "operations": []}, "file:a", a)
    emit_graphql_claims("repo_b", _file("b.graphql", "graphql"),
                        {"schema": parse_graphql_schema("b.graphql", plain),
                         "operations": []}, "file:b", b)
    emit_graphql_client_claims("repo_web", _file("q.ts", "typescript"),
                               "gql`query { user }`", "file:q", client)
    return LabeledEstate(
        name="graphql_ambiguous_owner",
        claims=(_sink_claims(a, "repo_a") + _sink_claims(b, "repo_b")
                + _sink_claims(client, "repo_web")),
        forbid=[{"tier": "r8.field_name", "type": "INVOKES",
                 "claim_key": "Query.user"}])


def _estate_http_hint_tiers() -> LabeledEstate:
    """R7 hint tiers — hand-built claims, the test_linker_matching pattern."""
    provider_evidence = ["customers-service/src/main/java/OwnerResource.java:40"]
    claims = [
        _http_claim("svcname", PROVIDES, "discovery:customers-service",
                    "repo_prov", hint="customers-service",
                    hint_source="config",
                    attrs={"source": "spring.application.name"},
                    evidence=["customers-service/src/main/resources/"
                              "application.yml:2"]),
        _http_claim("http", PROVIDES, "GET:/owners/{ownerId}", "repo_prov",
                    evidence=provider_evidence,
                    enode="repo_prov:endpoint:GET:/owners/{ownerId}"),
        # Exact template spelling -> hint_exact.
        _http_claim("http", CONSUMES, "httpcall:GET:/owners/{ownerId}",
                    "repo_cons_a", hint="customers-service",
                    hint_source="discovery",
                    evidence=["repo_cons_a/src/Client.java:12"],
                    enode="repo_cons_a:file:Client.java"),
        # Positional spelling -> hint_template.
        _http_claim("http", CONSUMES, "httpcall:GET:/owners/{}",
                    "repo_cons_b", hint="customers-service",
                    hint_source="discovery",
                    evidence=["repo_cons_b/src/Client.java:12"],
                    enode="repo_cons_b:file:Client.java"),
        # Adversarial: wrong hint must not match.
        _http_claim("http", CONSUMES, "httpcall:GET:/owners/{}",
                    "repo_cons_c", hint="billing-service",
                    hint_source="discovery",
                    evidence=["repo_cons_c/src/Client.java:12"],
                    enode="repo_cons_c:file:Client.java"),
        # Adversarial: unqualified hint must not match.
        _http_claim("http", CONSUMES, "httpcall:GET:/owners/{}",
                    "repo_cons_d", hint=None, hint_source="none",
                    evidence=["repo_cons_d/src/Client.java:12"],
                    enode="repo_cons_d:file:Client.java"),
    ]
    return LabeledEstate(
        name="http_hint_tiers", claims=claims,
        expect=[
            {"tier": "r7.exposes", "type": "EXPOSES",
             "match_type": "declared", "claim_key": "GET:/owners/{ownerId}"},
            {"tier": "r7.hint_exact", "type": "INVOKES",
             "match_type": "hint_exact", "source_repo_id": "repo_cons_a",
             "target_repo_id": "repo_prov"},
            {"tier": "r7.hint_template", "type": "INVOKES",
             "match_type": "hint_template", "source_repo_id": "repo_cons_b",
             "target_repo_id": "repo_prov"},
        ],
        forbid=[
            {"tier": "r7.hint_exact", "type": "INVOKES",
             "source_repo_id": "repo_cons_c"},
            {"tier": "r7.hint_exact", "type": "INVOKES",
             "source_repo_id": "repo_cons_d"},
        ])


def _estate_http_gateway_route() -> LabeledEstate:
    """R7 gateway qualification — a client that only knows the public path.

    A browser calls `/api/vet/vets`. There is no host in the source and no env
    var to trace, so neither the literal-host rule nor config indirection can
    name the callee. The gateway's route table says `/api/vet` goes to
    vets-service stripping two segments, which leaves `/vets` — precisely what
    that service declares. Without this join the consumer holds the public path
    and the provider holds the service-local one, and the two can never meet.
    """
    claims = [
        _http_claim("svcname", PROVIDES, "discovery:vets-service", "repo_prov",
                    hint="vets-service", hint_source="config",
                    evidence=["vets-service/src/main/resources/application.yml:2"]),
        _http_claim("http", PROVIDES, "GET:/vets", "repo_prov",
                    evidence=["vets-service/src/main/java/VetResource.java:31"],
                    enode="repo_prov:endpoint:GET:/vets"),
        # The gateway's own route table — the evidence that names the callee.
        _http_claim("route", CONSUMES, "/api/vet→svcname:vets-service",
                    "repo_gw", hint="api-gateway", hint_source="config",
                    attrs={"target": "vets-service", "path_prefix": "/api/vet",
                           "strip_prefix": 2},
                    evidence=["api-gateway/src/main/resources/application.yml:21"]),
        # The call: public path, no host, no hint.
        _http_claim("http", CONSUMES, "httpcall:GET:/api/vet/vets", "repo_ui",
                    hint=None, hint_source="none",
                    evidence=["repo_ui/src/app/vet.service.ts:18"],
                    enode="repo_ui:file:vet.service.ts"),
        # Same join, but the caller spells the path positionally, so the
        # rewritten `/vets/{}` matches `/vets/{vetId}` only after
        # normalisation -> the weaker gateway_template tier.
        _http_claim("http", PROVIDES, "GET:/vets/{vetId}", "repo_prov",
                    evidence=["vets-service/src/main/java/VetResource.java:52"],
                    enode="repo_prov:endpoint:GET:/vets/{vetId}"),
        _http_claim("http", CONSUMES, "httpcall:GET:/api/vet/vets/{}", "repo_ui_p",
                    hint=None, hint_source="none",
                    evidence=["repo_ui_p/src/app/vet.service.ts:26"],
                    enode="repo_ui_p:file:vet.service.ts"),
        # Adversarial: a path under no gateway prefix stays unqualified.
        _http_claim("http", CONSUMES, "httpcall:GET:/unrouted/vets", "repo_ui2",
                    hint=None, hint_source="none",
                    evidence=["repo_ui2/src/app/other.service.ts:9"],
                    enode="repo_ui2:file:other.service.ts"),
        # Adversarial: two gateways claiming one prefix for different services
        # is real ambiguity — the resolver must decline, not pick.
        _http_claim("route", CONSUMES, "/api/dup→svcname:vets-service",
                    "repo_gw", hint="gw-one", hint_source="config",
                    attrs={"target": "vets-service", "path_prefix": "/api/dup",
                           "strip_prefix": 2},
                    evidence=["gw-one/application.yml:5"]),
        _http_claim("route", CONSUMES, "/api/dup→svcname:other-service",
                    "repo_gw", hint="gw-two", hint_source="config",
                    attrs={"target": "other-service", "path_prefix": "/api/dup",
                           "strip_prefix": 2},
                    evidence=["gw-two/application.yml:5"]),
        _http_claim("http", CONSUMES, "httpcall:GET:/api/dup/vets", "repo_ui3",
                    hint=None, hint_source="none",
                    evidence=["repo_ui3/src/app/dup.service.ts:4"],
                    enode="repo_ui3:file:dup.service.ts"),
    ]
    return LabeledEstate(
        name="http_gateway_route", claims=claims,
        expect=[
            {"tier": "r7.gateway_exact", "type": "INVOKES",
             "match_type": "gateway_exact", "source_repo_id": "repo_ui",
             "target_repo_id": "repo_prov"},
            {"tier": "r7.gateway_template", "type": "INVOKES",
             "match_type": "gateway_template", "source_repo_id": "repo_ui_p",
             "target_repo_id": "repo_prov"},
        ],
        forbid=[
            {"tier": "r7.gateway_exact", "type": "INVOKES",
             "source_repo_id": "repo_ui2"},
            {"tier": "r7.gateway_exact", "type": "INVOKES",
             "source_repo_id": "repo_ui3"},
        ])


def _estate_http_config_host() -> LabeledEstate:
    """R7 config-host qualification — a dependency-injected client.

    The host is injected from configuration, so the call site carries only a
    path. The callee is recovered by joining what the code READS (cfgread) to
    what compose says that key points at (env_host). Includes the adversarial
    cases that must decline rather than guess.
    """
    def env_host(repo, env_key, host, frm="caller"):
        return _http_claim("svcname", CONSUMES, f"discovery:{host}", repo,
                           hint=host, hint_source="config",
                           attrs={"via": "env_host", "env_key": env_key,
                                  "from": frm},
                           evidence=["docker-compose.yml:10"])

    def cfgread(repo, env_key, path):
        return _http_claim("cfgread", CONSUMES, f"{repo}:{env_key}", repo,
                           evidence=[f"{path}:3"])

    def call(repo, path, base_var):
        return _http_claim("http", CONSUMES, "httpcall:GET:/v1/callers", repo,
                           attrs={"base_var": base_var},
                           evidence=[f"{path}:12"],
                           enode=f"{repo}:file:{path}")

    claims = [
        _http_claim("svcname", PROVIDES, "discovery:capability-registry",
                    "repo_reg", hint="capability-registry", hint_source="config",
                    attrs={"source": "spring.application.name"},
                    evidence=["capability-registry/src/main/resources/"
                              "application.yml:2"]),
        _http_claim("http", PROVIDES, "GET:/v1/callers", "repo_reg",
                    evidence=["capability-registry/src/Api.java:40"],
                    enode="repo_reg:endpoint:GET:/v1/callers"),

        # a) One service URL in scope -> unambiguous.
        env_host("repo_a", "CAPABILITY_REGISTRY_URL", "capability-registry"),
        cfgread("repo_a", "CAPABILITY_REGISTRY_URL", "svc/config.py"),
        call("repo_a", "svc/clients/registry.py", "registry"),

        # b) Two service URLs in scope, variable name singles one out.
        env_host("repo_b", "CAPABILITY_REGISTRY_URL", "capability-registry"),
        env_host("repo_b", "FOYER_ORCHESTRATOR_URL", "orchestrator"),
        cfgread("repo_b", "CAPABILITY_REGISTRY_URL", "svc/config.py"),
        cfgread("repo_b", "FOYER_ORCHESTRATOR_URL", "svc/config.py"),
        call("repo_b", "svc/clients/registry.py", "registry"),

        # c) Adversarial: two service URLs, nothing distinguishes them.
        env_host("repo_c", "CAPABILITY_REGISTRY_URL", "capability-registry"),
        env_host("repo_c", "OTHER_REGISTRY_URL", "other-registry"),
        cfgread("repo_c", "CAPABILITY_REGISTRY_URL", "svc/config.py"),
        cfgread("repo_c", "OTHER_REGISTRY_URL", "svc/config.py"),
        call("repo_c", "svc/clients/thing.py", "thing"),

        # d) Adversarial: no config evidence at all in the repo.
        call("repo_d", "svc/clients/registry.py", "registry"),
    ]
    return LabeledEstate(
        name="http_config_host", claims=claims,
        expect=[
            {"tier": "r7.exposes", "type": "EXPOSES",
             "match_type": "declared", "claim_key": "GET:/v1/callers"},
            {"tier": "r7.hint_exact", "type": "INVOKES",
             "source_repo_id": "repo_a", "target_repo_id": "repo_reg"},
            {"tier": "r7.hint_exact", "type": "INVOKES",
             "source_repo_id": "repo_b", "target_repo_id": "repo_reg"},
        ],
        forbid=[
            {"tier": "r7.hint_exact", "type": "INVOKES",
             "source_repo_id": "repo_c"},
            {"tier": "r7.hint_exact", "type": "INVOKES",
             "source_repo_id": "repo_d"},
        ])


def _estate_topics_literal_declared() -> LabeledEstate:
    claims = (_code_topic_claim("repo_orders", "kafka", "order-events",
                                "produces")
              + _k8s_claims("repo_worker", "deploy/keda.yaml", _KEDA_YAML)
              + _iac_claims("repo_infra", "infra/main.tf", _TERRAFORM))
    return LabeledEstate(
        name="topics_literal_declared", claims=claims,
        expect=[
            {"tier": "r6.literal", "type": "PUBLISHES_TO",
             "match_type": "topic_literal", "claim_key": "kafka:order-events",
             "source_repo_id": "repo_orders"},
            {"tier": "r6.literal", "type": "CONSUMES_FROM",
             "match_type": "topic_literal", "claim_key": "kafka:order-events",
             "source_repo_id": "repo_worker", "target_repo_id": "repo_orders"},
            {"tier": "r6.declared", "type": "DECLARES_TOPIC",
             "match_type": "topic_declared",
             "claim_key": "sqs:refund-requests",
             "source_repo_id": "repo_infra"},
            {"tier": "r6.fanout", "type": "FANS_OUT_TO",
             "match_type": "sns_subscription",
             "source_id": "global:Topic:sns:order-fanout",
             "target_id": "global:Topic:sqs:refund-requests"},
        ])


def _estate_topics_env_indirection() -> LabeledEstate:
    manifest = _ENV_DEPLOY.format(name="shipping", namespace="prod",
                                  value="order-events")
    claims = (_code_topic_claim("repo_orders", "kafka", "order-events",
                                "produces")
              + _k8s_claims("repo_ship", "deploy/prod/shipping.yaml", manifest)
              + _code_topic_claim("repo_ship", "kafka", "env:ORDERS_TOPIC",
                                  "consumes", path="src/consume.py"))
    return LabeledEstate(
        name="topics_env_indirection", claims=claims,
        expect=[{"tier": "r6.env_resolved", "type": "CONSUMES_FROM",
                 "match_type": "topic_env_resolved",
                 "source_repo_id": "repo_ship",
                 "target_id": "global:Topic:kafka:order-events"}])


def _estate_topics_env_conflict() -> LabeledEstate:
    """Adversarial: the same variable names different topics per environment."""
    prod = _ENV_DEPLOY.format(name="shipping", namespace="prod",
                              value="order-events")
    eu = _ENV_DEPLOY.format(name="shipping-eu", namespace="prod-eu",
                            value="order-events-v2")
    claims = (_k8s_claims("repo_ship", "deploy/prod/shipping.yaml", prod)
              + _k8s_claims("repo_eu", "deploy/prod/shipping-eu.yaml", eu)
              + _code_topic_claim("repo_ship", "kafka", "env:ORDERS_TOPIC",
                                  "consumes", path="src/consume.py"))
    return LabeledEstate(
        name="topics_env_conflict", claims=claims,
        forbid=[{"tier": "r6.env_resolved", "type": "CONSUMES_FROM",
                 "source_repo_id": "repo_ship"}])


def _estate_k8s_selector_env_host() -> LabeledEstate:
    claims = _k8s_claims("repo_a", "k8s/prod/app.yaml", _ORDERS_MANIFEST)
    return LabeledEstate(
        name="k8s_selector_env_host", claims=claims,
        expect=[
            {"tier": "r2.selector_match", "type": "MEMBER_OF",
             "match_type": "selector", "claim_key": "prod:orders"},
            {"tier": "r2.selector_match", "type": "MEMBER_OF",
             "match_type": "selector", "claim_key": "prod:vets"},
            {"tier": "r2.env_host", "type": "CALLS_SERVICE",
             "match_type": "k8s_env_host",
             "source_id": "global:Service:orders",
             "target_id": "global:Service:vets"},
            # R0 tiers ride the same manifest.
            {"tier": "r0.resolved_to", "type": "RESOLVED_TO",
             "match_type": "alias", "claim_key": "prod:orders",
             "target_id": "global:SvcName:prod:orders"},
            {"tier": "r0.has_alias", "type": "HAS_ALIAS",
             "source_id": "global:Service:orders",
             "target_id": "global:SvcName:prod:orders"},
            {"tier": "r0.built_from_descriptor", "type": "BUILT_FROM",
             "source_id": "global:Service:orders", "target_id": "repo_a",
             "via": "descriptor"},
        ])


def _estate_k8s_gitops() -> LabeledEstate:
    target_repo = generate_repo_id("myorg", "orders", "github.com")
    sink = IngestSink()
    _k8s_claims("repo_deploy", "argo/orders.yaml", _ARGO_APP, sink=sink)
    claims = _sink_claims(sink, "repo_deploy")
    # The referenced repo must be in the graph for the binding to resolve
    # (test_m2 builds this record the same way).
    claims.append(ClaimRecord(
        id="cal:gitops:target", repo_id=target_repo, kind="svcname",
        direction="provides", key="prod:orders", service_hint="orders",
        hint_source="config", matchable=True, evidence=["k8s/app.yaml:1"],
        attrs={"source": "k8s"}, evidence_node_id="node:cal:gitops:target",
        evidence_node_type="File"))
    return LabeledEstate(
        name="k8s_gitops", claims=claims,
        expect=[{"tier": "r2.built_from_gitops", "type": "BUILT_FROM",
                 "match_type": "gitops", "target_id": target_repo}])


def _estate_env_indirection_call() -> LabeledEstate:
    sink = IngestSink()
    _k8s_claims("repo_web", "k8s/prod/web.yaml", _STOREFRONT_MANIFEST,
                sink=sink)
    emit_source_claims(
        "repo_web", _file("src/client.ts", "typescript"),
        'const res = await fetch(process.env.ORDERS_URL + "/v1/orders");',
        [], "file:client", sink)
    return LabeledEstate(
        name="env_indirection_call",
        claims=_sink_claims(sink, "repo_web"),
        expect=[{"tier": "r9.env_resolved", "type": "CALLS_SERVICE",
                 "match_type": "env_indirection",
                 "source_id": "global:Service:storefront",
                 "target_id": "global:Service:orders"}])


def _estate_env_scope_conflict() -> LabeledEstate:
    """Adversarial: ORDERS_URL differs between prod and staging — declined."""
    overlay = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: {ns}
  labels: {{app.kubernetes.io/name: storefront}}
spec:
  template:
    spec:
      containers:
        - name: app
          image: i
          env: [{{name: ORDERS_URL, value: "http://{host}:8080"}}]
"""
    sink = IngestSink()
    _k8s_claims("repo_web", "k8s/prod/w.yaml",
                overlay.format(ns="prod", host="orders-prod"), sink=sink)
    _k8s_claims("repo_web", "k8s/staging/w.yaml",
                overlay.format(ns="staging", host="orders-staging"), sink=sink)
    emit_source_claims(
        "repo_web", _file("src/client.ts", "typescript"),
        "fetch(process.env.ORDERS_URL)", [], "file:client", sink)
    return LabeledEstate(
        name="env_scope_conflict", claims=_sink_claims(sink, "repo_web"),
        forbid=[{"tier": "r9.env_resolved", "type": "CALLS_SERVICE",
                 "match_type": "env_indirection"}])


def _estate_compose_topology() -> LabeledEstate:
    sink = IngestSink()
    resources = parse_docker_compose("docker-compose.yml", _COMPOSE)
    emit_compose_claims("repo_shop", _file("docker-compose.yml", "yaml"),
                        resources, {r.name: f"d:{r.name}" for r in resources},
                        sink)
    return LabeledEstate(
        name="compose_topology", claims=_sink_claims(sink, "repo_shop"),
        expect=[
            {"tier": "r1.depends_on", "type": "CALLS_SERVICE",
             "match_type": "topology", "via": "compose_depends_on",
             "claim_key": "shopstack:orders-api"},
            {"tier": "r1.env_host", "type": "CALLS_SERVICE",
             "match_type": "topology", "via": "compose_env_host",
             "claim_key": "shopstack:payments-svc"},
            {"tier": "r1.env_host_default", "type": "CALLS_SERVICE",
             "match_type": "topology", "via": "compose_env_host_default",
             "claim_key": "shopstack:inventory-svc"},
            {"tier": "r0.built_from_build_context", "type": "BUILT_FROM",
             "source_id": "global:Service:orders-api",
             "target_id": "repo_shop", "via": "build_context"},
        ],
        forbid=[
            # `DB_USER=${DB_USER:-postgres}` must not become a call to the
            # postgres service: the default is a username, and only a key
            # that names a network target may contribute a host.
            {"tier": "r1.env_host_default", "type": "CALLS_SERVICE",
             "claim_key": "shopstack:postgres"},
        ])


def _estate_gateway_nginx() -> LabeledEstate:
    sink = IngestSink()
    emit_gateway_claims("repo_edge", _file("edge/nginx.conf"),
                        parse_nginx_conf("edge/nginx.conf", _NGINX),
                        "file:nginx", sink)
    # The module owning nginx.conf becomes the gateway at link time.
    add_claim("repo_edge", ContractClaim(
        repo_id="repo_edge", kind="svcname", direction=PROVIDES,
        key="discovery:edge-gateway", service_hint="edge-gateway",
        hint_source="config", evidence=["edge/app.yml:1"],
        attrs={"source": "spring.application.name"},
    ), "file:app", sink)
    claims = (_sink_claims(sink, "repo_edge")
              + _service_claim("repo_orders", "orders"))
    return LabeledEstate(
        name="gateway_nginx", claims=claims,
        expect=[
            {"tier": "r4.route_declared", "type": "ROUTES_TO",
             "match_type": "declared",
             "source_id": "global:Service:edge-gateway",
             "target_id": "global:Service:orders"},
            {"tier": "r4.route_declared", "type": "RESOLVED_TO",
             "match_type": "gateway_route"},
            {"tier": "r0.built_from_app_name", "type": "BUILT_FROM",
             "source_id": "global:Service:edge-gateway",
             "target_id": "repo_edge", "via": "app_name"},
        ])


def _estate_gateway_dev_proxy() -> LabeledEstate:
    """Vite devServer proxy: real wiring, dev-only tier."""
    sink = IngestSink()
    emit_gateway_claims(
        "repo_front", _file("web/vite.config.js", "javascript"),
        parse_js_proxies("web/vite.config.js", _VITE), "file:vite", sink)
    add_claim("repo_front", ContractClaim(
        repo_id="repo_front", kind="svcname", direction=PROVIDES,
        key="discovery:storefront-web", service_hint="storefront-web",
        hint_source="config", evidence=["web/app.yml:1"],
        attrs={"source": "spring.application.name"},
    ), "file:app", sink)
    claims = (_sink_claims(sink, "repo_front")
              + _service_claim("repo_pay", "payments-svc"))
    return LabeledEstate(
        name="gateway_dev_proxy", claims=claims,
        expect=[{"tier": "r4.route_dev", "type": "ROUTES_TO",
                 "match_type": "declared",
                 "source_id": "global:Service:storefront-web",
                 "target_id": "global:Service:payments-svc"}])


def _estate_libraries() -> LabeledEstate:
    def consumer(repo_id, deps, path):
        sink = IngestSink()
        emit_dependency_claims(repo_id, _file(path), deps, f"file:{path}",
                               sink)
        return _sink_claims(sink, repo_id)

    def publisher(repo_id, ecosystem, name, namespace):
        sink = IngestSink()
        identity = SimpleNamespace(ecosystem=ecosystem, name=name,
                                   namespace=namespace, version="2.0.0",
                                   private=False)
        emit_publish_claims(repo_id, _file("pom.xml"), identity,
                            "file:pom", sink)
        return _sink_claims(sink, repo_id)

    def dep(name, version, dep_type, **kw):
        record = DependencyInfo(name=name, version=version, type=dep_type)
        for key, value in kw.items():
            setattr(record, key, value)
        return record

    claims = (
        publisher("repo_lib", "maven", "billing-lib", "org.acme")
        + publisher("repo_ui", "npm", "ui", "@acme")
        # Manifest-declared consumer of the maven coordinate.
        + consumer("repo_api",
                   [dep("org.acme:billing-lib", "2.0.0", "maven"),
                    # Adversarial: an external coordinate must never link.
                    dep("com.google.guava:guava", "33.0.0", "maven")],
                   "pom.xml")
        # Lockfile-resolved consumer of the npm coordinate.
        + consumer("repo_web", [dep("@acme/ui", "3.1.0", "npm",
                                    resolved=True)],
                   "package-lock.json"))
    return LabeledEstate(
        name="libraries", claims=claims,
        expect=[
            {"tier": "r3.publishes", "type": "PUBLISHES",
             "source_id": "repo_lib",
             "claim_key": "pkg:maven/org.acme/billing-lib"},
            {"tier": "r3.manifest_declared", "type": "DEPENDS_ON",
             "source_id": "repo_api",
             "claim_key": "pkg:maven/org.acme/billing-lib",
             "target_repo_id": "repo_lib"},
            {"tier": "r3.lockfile_resolved", "type": "DEPENDS_ON",
             "source_id": "repo_web", "claim_key": "pkg:npm/@acme/ui",
             "target_repo_id": "repo_ui"},
        ],
        forbid=[{"tier": "r3.manifest_declared", "type": "DEPENDS_ON",
                 "claim_key": "pkg:maven/com.google.guava/guava"}])


def _estate_ownership_catalog() -> LabeledEstate:
    sink = IngestSink()
    entities = parse_catalog_info("catalog-info.yaml", _CATALOG)
    emit_catalog_claims("repo_orders", _file("catalog-info.yaml"), entities,
                        "file:catalog", sink)
    claims = (_sink_claims(sink, "repo_orders")
              + _service_claim("repo_orders", "orders-service"))
    return LabeledEstate(
        name="ownership_catalog", claims=claims,
        expect=[
            {"tier": "r12.catalog", "type": "OWNED_BY",
             "match_type": "catalog", "source_id": "repo_orders",
             "target_id": "global:Team:team:payments-team"},
            {"tier": "r12.catalog", "type": "OWNED_BY",
             "match_type": "catalog",
             "source_id": "global:Service:orders-service"},
        ])


def _estate_module_boundary() -> LabeledEstate:
    """A monorepo service belongs to its module, not merely to its repo.

    `projects/billing` and `projects/orders` are one repository and two
    modules. Binding the service to the module is what makes a call between
    them legible as a boundary crossing rather than an internal detail.
    """
    claims = _service_claim("repo_mono", "billing",
                            path="projects/billing/deploy/app.yaml")
    return LabeledEstate(
        name="module_boundary", claims=claims,
        expect=[{"tier": "r0.belongs_to", "type": "BELONGS_TO",
                 "match_type": "path",
                 "source_id": "global:Service:billing",
                 "target_id": "global:Module:projects/billing"}])


def _estate_deployment_unit() -> LabeledEstate:
    """A service is bound to the workload that runs it.

    The manifest declares the Deployment; nothing is inferred. Without this
    the graph knows what a service is and what it calls, but not what would
    have to be rolled back to change it.
    """
    sink = IngestSink()
    add_claim("repo_k8s", ContractClaim(
        repo_id="repo_k8s", kind="svcname", direction=PROVIDES,
        key="prod:checkout", service_hint="checkout", hint_source="config",
        evidence=["deploy/prod/checkout.yaml:3"], subject="svc/checkout",
        attrs={"source": "k8s", "kind": "Deployment",
               "namespace": "prod", "workload": "checkout"},
    ), "file:repo_k8s:deploy/prod/checkout.yaml", sink)
    return LabeledEstate(
        name="deployment_unit", claims=_sink_claims(sink, "repo_k8s"),
        expect=[{"tier": "r2.deployed_as", "type": "DEPLOYED_AS",
                 "match_type": "manifest",
                 "source_id": "global:Service:checkout",
                 "target_id": "global:deploymentunit:prod/deployment/checkout"}])


def _estate_ownership_codeowners() -> LabeledEstate:
    sink = IngestSink()
    rules = parse_codeowners("CODEOWNERS", _CODEOWNERS)
    emit_codeowners_claims("repo_infra", _file("CODEOWNERS"), rules,
                           "file:codeowners", sink)
    return LabeledEstate(
        name="ownership_codeowners", claims=_sink_claims(sink, "repo_infra"),
        expect=[{"tier": "r12.codeowners", "type": "OWNED_BY",
                 "match_type": "codeowners", "source_id": "repo_infra"}])


def _estate_ownership_observability() -> LabeledEstate:
    sink = IngestSink()
    identities = extract_observability_identity(".env.prod", _DATADOG_ENV)
    emit_observability_claims("repo_dd", _file(".env.prod"), identities,
                              "file:env", sink)
    return LabeledEstate(
        name="ownership_observability", claims=_sink_claims(sink, "repo_dd"),
        expect=[{"tier": "r12.observability", "type": "OWNED_BY",
                 "match_type": "observability", "source_id": "repo_dd"}])


def _estate_alias_two_scopes() -> LabeledEstate:
    """Two spellings of one service (compose scope + k8s namespace), one repo
    corroborating both — R0 must cluster them into a single Service."""
    sink = IngestSink()
    add_claim("repo_inv", ContractClaim(
        repo_id="repo_inv", kind="svcname", direction=PROVIDES,
        key="shopfloor:inventory-svc", service_hint="inventory-svc",
        hint_source="config", evidence=["docker-compose.yml:4"],
        subject="compose/inventory-svc", attrs={"source": "compose"},
    ), "file:compose", sink)
    add_claim("repo_inv", ContractClaim(
        repo_id="repo_inv", kind="svcname", direction=PROVIDES,
        key="prod:inventory-svc", service_hint="inventory-svc",
        hint_source="config", evidence=["k8s/prod/app.yaml:2"],
        subject="k8s/inventory-svc", attrs={"source": "k8s"},
    ), "file:k8s", sink)
    return LabeledEstate(
        name="alias_two_scopes", claims=_sink_claims(sink, "repo_inv"),
        expect=[
            {"tier": "r0.resolved_to", "type": "RESOLVED_TO",
             "match_type": "alias", "claim_key": "prod:inventory-svc",
             "target_id": "global:SvcName:prod:inventory-svc"},
            {"tier": "r0.has_alias", "type": "HAS_ALIAS",
             "source_id": "global:Service:inventory-svc",
             "target_id": "global:SvcName:prod:inventory-svc"},
            {"tier": "r0.has_alias", "type": "HAS_ALIAS",
             "source_id": "global:Service:inventory-svc",
             "target_id": "global:SvcName:shopfloor:inventory-svc"},
        ])


def build_estates() -> list[LabeledEstate]:
    return [
        _estate_grpc_cross_repo(),
        _estate_grpc_test_provenance(),
        _estate_graphql_ownership(),
        _estate_graphql_ambiguous(),
        _estate_http_hint_tiers(),
        _estate_http_gateway_route(),
        _estate_http_config_host(),
        _estate_topics_literal_declared(),
        _estate_topics_env_indirection(),
        _estate_topics_env_conflict(),
        _estate_k8s_selector_env_host(),
        _estate_k8s_gitops(),
        _estate_env_indirection_call(),
        _estate_env_scope_conflict(),
        _estate_compose_topology(),
        _estate_gateway_nginx(),
        _estate_gateway_dev_proxy(),
        _estate_libraries(),
        _estate_ownership_catalog(),
        _estate_module_boundary(),
        _estate_deployment_unit(),
        _estate_ownership_codeowners(),
        _estate_ownership_observability(),
        _estate_alias_two_scopes(),
        # R10/R11 live in their own module: this file predates the 300-line
        # rule and must not get longer (AGENTS.md §3).
        *_extension_estates(),
    ]


def _extension_estates() -> list[LabeledEstate]:
    from tracekite.services.calibration_estates import (
        agent_estate, dataset_estate, operation_estate, policy_estate,
        webhook_estate,
    )

    return [dataset_estate(), agent_estate(), webhook_estate(),
            policy_estate(), operation_estate()]


# --------------------------------------------------------------------------
# Pipeline + evaluation
# --------------------------------------------------------------------------

@contextmanager
def _internal_boundary():
    """Pin the internal package boundary the R3 estates assume.

    Mirrors the fixture monkeypatch in test_m7_packages.py so calibration does
    not depend on the operator's live internal_namespaces.yml. Restored on
    exit; nothing outside the run observes the patch.
    """
    import tracekite.services.ingest_deps as ingest_deps
    from tracekite.services.linker import r3_library
    saved_cache = ingest_deps._internal_namespaces_cache
    saved_loader = r3_library.load_internal_namespaces
    ingest_deps._internal_namespaces_cache = _INTERNAL_NAMESPACES
    r3_library.load_internal_namespaces = lambda: _INTERNAL_NAMESPACES
    try:
        yield
    finally:
        ingest_deps._internal_namespaces_cache = saved_cache
        r3_library.load_internal_namespaces = saved_loader


def _run_pipeline(claims: list[ClaimRecord], confidence: dict) -> list:
    """Fresh LinkContext + ClaimIndex; the full phase sequence in production
    order; then materialize_pending, exactly as LinkerService._run does. Raw
    (pre-fusion) edges are returned because tier attribution needs each
    resolver's own match_type and served confidence, which fusion merges away.

    Going through run_resolvers rather than iterating RESOLVERS is what keeps
    calibration measuring the pipeline the linker actually runs, NORMALIZE
    included."""
    ctx = LinkContext("linkrun_calibration", confidence, {})
    ctx.known_repos = {c.repo_id for c in claims}
    index = ClaimIndex(claims)
    combined = run_resolvers(index, ctx)
    combined.edges.extend(materialize_pending(ctx))

    # Score what the product actually serves. Read paths filter on
    # `status = 'active'`, so a sub-floor edge is never in an answer and
    # cannot be a false positive in one — measuring pre-floor edges would
    # score a population no user sees, and would make the candidate
    # mechanism in design §5.5 unmeasurable by construction.
    apply_confidence_floor(ctx, combined.edges)
    return [e for e in combined.edges if e.status == "active"]


def _matches(edge, spec: dict) -> bool:
    for key, want in spec.items():
        if key == "tier":
            continue
        if key == "via":
            if want not in (edge.extra_props.get("via") or []):
                return False
        elif getattr(edge, key, None) != want:
            return False
    return True


def _edge_summary(edge) -> dict:
    return {"type": edge.type, "match_type": edge.match_type,
            "source_id": edge.source_id, "target_id": edge.target_id,
            "claim_key": edge.claim_key, "detected_by": edge.detected_by,
            "confidence": edge.confidence}


def run_calibration() -> dict:
    """Run every labeled estate and tally per-tier P/R rows.

    Returns ``{"r5": {"declared": {"precision": .., "recall": .., "support":
    .., "fp": ..}}, ...}`` plus a ``_diagnostics`` key naming the estate and
    edge behind every miss (an FP against constructed truth is a real resolver
    bug, so the evidence must survive into the report).
    """
    confidence = load_confidence()
    tallies: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0})
    missing: list[dict] = []
    forbidden: list[dict] = []

    with _internal_boundary():
        for estate in build_estates():
            edges = _run_pipeline(estate.claims, confidence)
            for spec in estate.expect:
                hits = [e for e in edges if _matches(e, spec)]
                if hits:
                    tier = edge_tier(hits[0], confidence) or spec["tier"]
                    tallies[tier]["tp"] += 1
                else:
                    tallies[spec["tier"]]["fn"] += 1
                    missing.append({"estate": estate.name,
                                    "expected": dict(spec)})
            for spec in estate.forbid:
                for edge in (e for e in edges if _matches(e, spec)):
                    tier = edge_tier(edge, confidence) or spec.get("tier")
                    if tier:
                        tallies[tier]["fp"] += 1
                    forbidden.append({"estate": estate.name, "tier": tier,
                                      "edge": _edge_summary(edge)})

    results: dict = {}
    for tier_key in sorted(tallies):
        section, _, tier = tier_key.partition(".")
        tp, fp, fn = (tallies[tier_key][k] for k in ("tp", "fp", "fn"))
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        # The interval is the honest half of the number: 1.000 on one
        # labelled edge and 1.000 on 189 are different claims.
        lo, hi = wilson_interval(tp, tp + fp)
        results.setdefault(section, {})[tier] = {
            "precision": round(precision, 4), "recall": round(recall, 4),
            "precision_lo": lo, "precision_hi": hi,
            "support": tp + fn, "fp": fp,
        }
    results["_diagnostics"] = {"missing": missing, "forbidden": forbidden}
    return results
