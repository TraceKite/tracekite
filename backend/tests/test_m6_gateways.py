"""M6 gateways: CRDs and config files -> route claims -> R4 -> ROUTES_TO.

Every gateway flavor reduces to one statement — requests matching PREFIX on
HOST forward to TARGET with declared rewrite semantics — and R4 consumes that
statement identically whether it came from a Spring config, an HTTPRoute, an
Istio VirtualService, a Traefik IngressRoute+Middleware pair, an Ingress
annotation, or an nginx.conf.
"""

from types import SimpleNamespace

from evigraph.parsers.gateway_parser import parse_nginx_conf
from evigraph.parsers.kubernetes_parser import parse_kubernetes_yaml
from evigraph.services.claims import PROVIDES, ContractClaim
from evigraph.services.ingest_claims import (
    add_claim, emit_gateway_claims, emit_k8s_claims,
)
from evigraph.services.ingest_source import IngestSink
from evigraph.services.linker import r0_alias, r4_gateway
from evigraph.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)

HTTPROUTE = """
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: orders-route
  namespace: prod
spec:
  hostnames: ["shop.example.com"]
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /api/orders
      filters:
        - type: URLRewrite
          urlRewrite:
            path:
              type: ReplacePrefixMatch
              replacePrefixMatch: /
      backendRefs:
        - name: orders
          port: 8080
"""

VIRTUAL_SERVICE = """
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: reviews-vs
  namespace: prod
spec:
  hosts: ["reviews.example.com"]
  http:
    - match:
        - uri:
            prefix: /reviews
      rewrite:
        uri: /
      route:
        - destination:
            host: reviews.prod.svc.cluster.local
            port:
              number: 9080
          weight: 80
        - destination:
            host: reviews-v2
          weight: 20
"""

INGRESSROUTE = """
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: strip-api
  namespace: prod
spec:
  stripPrefix:
    prefixes:
      - /api
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: edge
  namespace: prod
spec:
  routes:
    - match: Host(`shop.example.com`) && PathPrefix(`/api`)
      kind: Rule
      middlewares:
        - name: strip-api
      services:
        - name: storefront
          port: 3000
"""

INGRESS = """
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  namespace: prod
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /billing
            pathType: Prefix
            backend:
              service:
                name: billing
                port:
                  number: 80
"""

NGINX = """
upstream orders_backend {
    server orders:8080;
    server orders-canary:8080 backup;
}
server {
    listen 80;
    server_name shop.example.com;
    location /api/ {
        proxy_pass http://orders_backend/;
    }
}
"""


def _file(path):
    return SimpleNamespace(path=path, language=None)


def _claims(sink, repo_id):
    records = []
    for node in sink.nodes:
        if node.type != "ContractClaim":
            continue
        extra = node.extra_props
        records.append(ClaimRecord(
            id=node.id, repo_id=repo_id, kind=extra["kind"],
            direction=extra["direction"], key=extra["key"],
            service_hint=extra.get("service_hint"),
            hint_source=extra.get("hint_source", "none"),
            matchable=bool(extra.get("matchable", True)),
            evidence=list(extra.get("evidence") or []),
            attrs=dict(node.metadata or {}),
            evidence_node_id=f"node:{node.id}", evidence_node_type="File",
        ))
    return records


def _k8s(repo_id, path, content):
    sink = IngestSink()
    resources = parse_kubernetes_yaml(path, content)
    node_ids = {f"{r.kind}/{r.name}": f"k8s:{r.kind}/{r.name}"
                for r in resources}
    emit_k8s_claims(repo_id, _file(path), resources, node_ids, sink)
    return _claims(sink, repo_id)


def _target_service(repo_id, name, path="deploy/app.yaml"):
    """A provides claim so R0 mints the target Service."""
    sink = IngestSink()
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=f"prod:{name}", service_hint=name, hint_source="config",
        evidence=[f"{path}:1"], subject=f"svc/{name}",
        attrs={"source": "k8s", "workload": name},
    ), f"file:{path}", sink)
    return _claims(sink, repo_id)


def run_linker(claims):
    ctx = LinkContext("linkrun_test", load_confidence(), {})
    ctx.known_repos = {c.repo_id for c in claims}
    index = ClaimIndex(claims)
    out = ResolverOutput()
    for module in (r0_alias, r4_gateway):
        out.extend(module.resolve(index, ctx))
    return ctx, out


class TestGatewayApiRoutes:
    def test_httproute_rewrite_reaches_rule_table(self):
        claims = _k8s("repo_gw", "deploy/routes.yaml", HTTPROUTE) \
            + _target_service("repo_orders", "orders")
        ctx, out = run_linker(claims)
        rules = ctx.rewrite_routes.get("orders-route", [])
        assert rules and rules[0].prefix == "/api/orders"
        assert rules[0].strip_prefix == 1
        assert rules[0].target_name == "orders"

    def test_route_claim_carries_host_and_gateway_kind(self):
        claims = _k8s("repo_gw", "deploy/routes.yaml", HTTPROUTE)
        route = [c for c in claims if c.kind == "route"][0]
        assert route.attrs["host"] == "shop.example.com"
        assert route.attrs["gateway_kind"] == "gateway_api"


class TestIstio:
    def test_virtual_service_weighted_destinations(self):
        claims = _k8s("repo_mesh", "deploy/vs.yaml", VIRTUAL_SERVICE)
        routes = [c for c in claims if c.kind == "route"]
        targets = {(c.attrs["target"], c.attrs.get("weight")) for c in routes}
        assert ("reviews", 80) in targets
        assert ("reviews-v2", 20) in targets

    def test_istio_rewrite_is_strip(self):
        claims = _k8s("repo_mesh", "deploy/vs.yaml", VIRTUAL_SERVICE)
        route = [c for c in claims if c.kind == "route"][0]
        assert route.attrs["strip_prefix"] == 1
        assert route.attrs["rewrite_path"] == "/"


class TestTraefik:
    def test_middleware_strip_prefix_resolves(self):
        claims = _k8s("repo_edge", "deploy/ir.yaml", INGRESSROUTE)
        routes = [c for c in claims if c.kind == "route"]
        assert routes[0].attrs["target"] == "storefront"
        assert routes[0].attrs["strip_prefix"] == 1
        assert routes[0].attrs["host"] == "shop.example.com"


class TestIngress:
    def test_rewrite_annotation_strips(self):
        claims = _k8s("repo_infra", "deploy/ingress.yaml", INGRESS)
        routes = [c for c in claims if c.kind == "route"]
        assert routes[0].key.startswith("/billing")
        assert routes[0].attrs["strip_prefix"] == 1
        assert routes[0].attrs["rewrite_path"] == "/"


class TestNginx:
    def test_upstream_resolution_and_module_fallback(self):
        rules = parse_nginx_conf("edge/nginx.conf", NGINX)
        sink = IngestSink()
        emit_gateway_claims("repo_edge", _file("edge/nginx.conf"), rules,
                            "file:nginx", sink)
        claims = _claims(sink, "repo_edge")
        route = [c for c in claims if c.kind == "route"][0]
        assert route.attrs["target"] == "orders"        # not the backup server
        assert route.attrs["strip_prefix"] == 1         # trailing slash on pass

        # The module owning nginx.conf becomes the gateway at link time.
        gateway_owner = IngestSink()
        add_claim("repo_edge", ContractClaim(
            repo_id="repo_edge", kind="svcname", direction=PROVIDES,
            key="discovery:edge-gateway", service_hint="edge-gateway",
            hint_source="config", evidence=["edge/app.yml:1"],
            attrs={"source": "spring.application.name"},
        ), "file:app", gateway_owner)
        estate = claims + _claims(gateway_owner, "repo_edge") \
            + _target_service("repo_orders", "orders")
        ctx, out = run_linker(estate)
        routes_to = [e for e in out.edges if e.type == "ROUTES_TO"]
        assert routes_to and routes_to[0].extra_props["gateway_kind"] == "nginx"
        assert ctx.rewrite_routes["edge-gateway"]
