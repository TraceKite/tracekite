"""M2 end-to-end: manifests -> claims -> R2/R9 -> Service edges.

Exercises the whole chain rather than each unit, because M2's value is entirely
in the join: a k8s parser that extracts env bindings is worthless unless R9 can
turn `process.env.ORDERS_URL` into an edge.
"""

import pytest

from adduce.parsers.kubernetes_parser import parse_kubernetes_yaml
from adduce.services.ingest_claims import emit_k8s_claims, emit_source_claims
from adduce.services.ingest_source import IngestSink
from adduce.services.linker import (
    r0_alias, r1_compose, r2_k8s, r4_gateway, r7_http, r9_env,
    r9_env_index,
)
from adduce.services.linker.normalize import normalize_http_calls
from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)
from adduce.services.linker.engine import materialize_pending
from types import SimpleNamespace


def _file(path, language="yaml"):
    return SimpleNamespace(path=path, language=language)


def _claims_from_sink(sink, repo_id):
    """Convert emitted claim nodes back into the linker's ClaimRecord shape."""
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


def ingest_k8s(repo_id, path, manifest, sink=None):
    sink = sink or IngestSink()
    resources = parse_kubernetes_yaml(path, manifest)
    node_ids = {f"{r.kind}/{r.name}": f"k8snode:{r.kind}:{r.name}"
                for r in resources}
    emit_k8s_claims(repo_id, _file(path), resources, node_ids, sink)
    return sink


def run_linker(claims, aliases=None):
    ctx = LinkContext("linkrun_test", load_confidence(), aliases or {})
    ctx.known_repos = {c.repo_id for c in claims}
    index = ClaimIndex(claims)
    out = ResolverOutput()
    for module in (r2_k8s, r0_alias, r1_compose, r4_gateway, r9_env_index):
        out.extend(module.resolve(index, ctx))
    ctx.normalized_calls = normalize_http_calls(index, ctx)
    for module in (r7_http, r9_env):
        out.extend(module.resolve(index, ctx))
    out.edges.extend(materialize_pending(ctx))
    return ctx, out


ORDERS_MANIFEST = """
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


class TestK8sClaims:
    def test_workload_and_service_claims_are_namespace_scoped(self):
        sink = ingest_k8s("repo_a", "k8s/prod/app.yaml", ORDERS_MANIFEST)
        keys = {c.key for c in _claims_from_sink(sink, "repo_a")
                if c.kind == "svcname"}
        # Namespace is the scope: two clusters both running `orders` must not
        # merge on the bare name.
        assert "prod:orders" in keys and "prod:vets" in keys

    def test_image_claim_strips_tag(self):
        sink = ingest_k8s("repo_a", "k8s/prod/app.yaml", ORDERS_MANIFEST)
        images = {c.key for c in _claims_from_sink(sink, "repo_a")
                  if c.kind == "image"}
        assert images == {"registry.internal/myorg/orders",
                          "registry.internal/myorg/vets"}

    def test_literal_env_becomes_cfgdef_with_redacted_structure(self):
        sink = ingest_k8s("repo_a", "k8s/prod/app.yaml", ORDERS_MANIFEST)
        [vets] = [c for c in _claims_from_sink(sink, "repo_a")
                  if c.kind == "cfgdef" and c.attrs.get("env_name") == "VETS_URL"]
        assert vets.attrs["value_class"] == "url"
        assert vets.attrs["value_host"] == "vets.prod.svc.cluster.local"
        assert vets.attrs["value_port"] == 8080

    def test_environment_inferred_from_overlay_path(self):
        sink = ingest_k8s("repo_a", "deploy/overlays/staging/app.yaml",
                          ORDERS_MANIFEST)
        scopes = {c.attrs.get("env_scope") for c in _claims_from_sink(sink, "repo_a")}
        # env_scope rides on the claim node, not attrs; assert via the node
        nodes = [n for n in sink.nodes if n.type == "ContractClaim"]
        assert any(n.extra_props.get("env_scope") == "staging" for n in nodes)

    def test_secret_env_never_carries_a_value(self):
        sink = ingest_k8s("repo_a", "k8s/app.yaml", """
apiVersion: apps/v1
kind: Deployment
metadata: {name: d, namespace: prod}
spec:
  template:
    spec:
      containers:
        - name: a
          image: i
          env:
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef: {name: s, key: pw}
""")
        [claim] = [c for c in _claims_from_sink(sink, "repo_a")
                   if c.kind == "cfgdef"]
        assert claim.attrs["unresolved"] is True
        assert "value" not in claim.attrs
        assert claim.attrs.get("value_host") in (None, "")


class TestR2Kubernetes:
    def test_selector_binds_service_to_workload(self):
        sink = ingest_k8s("repo_a", "k8s/prod/app.yaml", ORDERS_MANIFEST)
        ctx, out = run_linker(_claims_from_sink(sink, "repo_a"))
        assert ctx.counters["r2.selector_bindings"] >= 2
        assert [e for e in out.edges if e.type == "MEMBER_OF"]

    def test_cluster_dns_spellings_canonicalize(self):
        sink = ingest_k8s("repo_a", "k8s/prod/app.yaml", ORDERS_MANIFEST)
        ctx, _ = run_linker(_claims_from_sink(sink, "repo_a"))
        for spelling in ("vets.prod", "vets.prod.svc",
                         "vets.prod.svc.cluster.local"):
            assert ctx.canon(spelling) == "vets"

    def test_literal_env_host_becomes_calls_service(self):
        sink = ingest_k8s("repo_a", "k8s/prod/app.yaml", ORDERS_MANIFEST)
        ctx, out = run_linker(_claims_from_sink(sink, "repo_a"))
        calls = [e for e in out.edges if e.type == "CALLS_SERVICE"]
        assert calls, ctx.counters
        edge = calls[0]
        assert ctx.service_name_of.get(edge.source_id) == "orders"
        assert ctx.service_name_of.get(edge.target_id) == "vets"
        assert edge.confidence == pytest.approx(0.95)
        assert edge.extra_props["via"] == ["k8s_env_host"]

    def test_external_name_service_registers_alias(self):
        sink = ingest_k8s("repo_a", "k8s/app.yaml", """
apiVersion: v1
kind: Service
metadata: {name: legacy, namespace: prod}
spec: {type: ExternalName, externalName: legacy.corp.example.com}
""")
        ctx, _ = run_linker(_claims_from_sink(sink, "repo_a"))
        assert ctx.canon("legacy.corp.example.com") == "legacy"

    def test_gitops_source_binds_service_to_ingested_repo(self):
        sink = ingest_k8s("repo_a", "k8s/prod/app.yaml", ORDERS_MANIFEST)
        gitops = ingest_k8s("repo_a", "argo/orders.yaml", """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: orders}
spec:
  source: {repoURL: "https://github.com/myorg/orders", path: k8s}
  destination: {namespace: prod}
""", sink=sink)
        claims = _claims_from_sink(gitops, "repo_a")
        # The referenced repo must be in the graph for the binding to resolve.
        claims_with_target = claims + [ClaimRecord(
            id="x", repo_id="myorg_orders", kind="svcname", direction="provides",
            key="prod:orders", service_hint="orders", hint_source="config",
            matchable=True, evidence=["k8s/app.yaml:1"],
            attrs={"source": "k8s"}, evidence_node_id="n", evidence_node_type="File")]
        ctx, out = run_linker(claims_with_target)
        built = [e for e in out.edges
                 if e.type == "BUILT_FROM" and e.match_type == "gitops"]
        assert built and built[0].target_id == "myorg_orders"

    def test_gitops_pointing_outside_the_roster_is_not_invented(self):
        sink = ingest_k8s("repo_a", "argo/x.yaml", """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: orders}
spec:
  source: {repoURL: "https://github.com/other/not-ingested", path: k8s}
""")
        ctx, out = run_linker(_claims_from_sink(sink, "repo_a"))
        assert not [e for e in out.edges if e.match_type == "gitops"]
        assert ctx.counters["pending.gitops_unresolved"] >= 1


class TestR9EnvIndirection:
    """The #1 documented false-negative cause: code names no service at all."""

    CODE = 'const res = await fetch(process.env.ORDERS_URL + "/v1/orders");'

    def _estate(self, env_value="http://orders.prod.svc.cluster.local:8080"):
        sink = ingest_k8s("repo_web", "k8s/prod/web.yaml", f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: storefront
  namespace: prod
  labels: {{app.kubernetes.io/name: storefront}}
spec:
  template:
    metadata:
      labels: {{app: storefront}}
    spec:
      containers:
        - name: app
          image: registry.internal/myorg/web:1
          env:
            - name: ORDERS_URL
              value: {env_value}
---
apiVersion: v1
kind: Service
metadata: {{name: storefront, namespace: prod}}
spec: {{selector: {{app: storefront}}}}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders
  namespace: prod
  labels: {{app.kubernetes.io/name: orders}}
spec:
  template:
    metadata:
      labels: {{app: orders}}
    spec:
      containers: [{{name: app, image: registry.internal/myorg/orders:1}}]
---
apiVersion: v1
kind: Service
metadata: {{name: orders, namespace: prod}}
spec: {{selector: {{app: orders}}}}
""")
        emit_source_claims("repo_web", _file("src/client.ts", "typescript"),
                           self.CODE, [], "file:client", sink)
        return _claims_from_sink(sink, "repo_web")

    def test_env_read_site_is_claimed(self):
        claims = self._estate()
        reads = [c for c in claims if c.kind == "cfgread"]
        assert [c.attrs["env_name"] for c in reads] == ["ORDERS_URL"]
        assert reads[0].attrs["endpoint_like"] is True

    def test_process_env_call_becomes_a_service_edge(self):
        ctx, out = run_linker(self._estate())
        resolved = [e for e in out.edges
                    if e.type == "CALLS_SERVICE"
                    and e.extra_props.get("via") == ["env_indirection"]]
        assert resolved, dict(ctx.counters)
        assert ctx.service_name_of[resolved[0].source_id] == "storefront"
        assert ctx.service_name_of[resolved[0].target_id] == "orders"
        assert resolved[0].confidence == pytest.approx(0.85)

    def test_generic_env_names_are_not_claimed(self):
        sink = IngestSink()
        emit_source_claims("r", _file("a.py", "python"),
                           'import os\nos.getenv("PATH")\nos.getenv("LOG_LEVEL")\n',
                           [], "f", sink)
        assert not [c for c in _claims_from_sink(sink, "r") if c.kind == "cfgread"]

    def test_configmap_reference_resolves_to_its_definition(self):
        sink = ingest_k8s("repo_web", "k8s/prod/all.yaml", """
apiVersion: v1
kind: ConfigMap
metadata: {name: platform, namespace: prod}
data:
  orders.url: http://orders.prod.svc:8080
---
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
          image: i
          env:
            - name: ORDERS_URL
              valueFrom:
                configMapKeyRef: {name: platform, key: orders.url}
---
apiVersion: v1
kind: Service
metadata: {name: storefront, namespace: prod}
spec: {selector: {app: storefront}}
---
apiVersion: v1
kind: Service
metadata: {name: orders, namespace: prod}
spec: {selector: {app: orders}}
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
      containers: [{name: app, image: i2}]
""")
        emit_source_claims("repo_web", _file("src/c.ts", "typescript"),
                           self.CODE, [], "file:c", sink)
        ctx, out = run_linker(_claims_from_sink(sink, "repo_web"))
        assert ctx.counters["r9.resolved_ref"] >= 1
        assert [e for e in out.edges
                if e.extra_props.get("via") == ["env_indirection"]]

    def test_secret_backed_var_is_counted_not_joined(self):
        sink = ingest_k8s("repo_web", "k8s/prod/s.yaml", """
apiVersion: v1
kind: Secret
metadata: {name: creds, namespace: prod}
data: {db-url: xxx}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: prod, labels: {app.kubernetes.io/name: storefront}}
spec:
  template:
    spec:
      containers:
        - name: app
          image: i
          env:
            - name: DB_URL
              valueFrom:
                secretKeyRef: {name: creds, key: db-url}
""")
        ctx, out = run_linker(_claims_from_sink(sink, "repo_web"))
        assert ctx.counters["r9.secret_ref"] >= 1
        assert not [e for e in out.edges
                    if e.extra_props.get("via") == ["env_indirection"]]

    def test_same_var_differing_across_environments_is_declined(self):
        # Precision first: one edge would assert a fact true in only one env.
        prod = ingest_k8s("repo_web", "k8s/prod/w.yaml", """
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: prod, labels: {app.kubernetes.io/name: storefront}}
spec:
  template:
    spec:
      containers:
        - name: app
          image: i
          env: [{name: ORDERS_URL, value: "http://orders-prod:8080"}]
""")
        ingest_k8s("repo_web", "k8s/staging/w.yaml", """
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: staging, labels: {app.kubernetes.io/name: storefront}}
spec:
  template:
    spec:
      containers:
        - name: app
          image: i
          env: [{name: ORDERS_URL, value: "http://orders-staging:8080"}]
""", sink=prod)
        emit_source_claims("repo_web", _file("src/c.ts", "typescript"),
                           self.CODE, [], "file:c", prod)
        ctx, out = run_linker(_claims_from_sink(prod, "repo_web"))
        assert ctx.counters["r9.ambiguous_across_envs"] >= 1
        assert not [e for e in out.edges
                    if e.extra_props.get("via") == ["env_indirection"]]

    def test_unresolved_endpoint_var_is_surfaced_separately(self):
        sink = IngestSink()
        emit_source_claims("r", _file("a.ts", "typescript"),
                           "fetch(process.env.PAYMENTS_SERVICE_URL)", [], "f", sink)
        ctx, _ = run_linker(_claims_from_sink(sink, "r"))
        assert ctx.counters["r9.read_unresolved_endpoint"] >= 1


class TestGenericNameSafety:
    """A k8s Service literally named `web` or `api` exists in most clusters;
    clustering those across namespaces or repos would merge unrelated systems."""

    MANIFEST = """
apiVersion: v1
kind: Service
metadata: {name: api, namespace: team-a}
spec: {selector: {app: api}}
---
apiVersion: v1
kind: Service
metadata: {name: api, namespace: team-b}
spec: {selector: {app: api}}
"""

    def test_generic_service_names_stay_scope_qualified(self):
        sink = ingest_k8s("repo_a", "k8s/a.yaml", self.MANIFEST)
        ctx, _ = run_linker(_claims_from_sink(sink, "repo_a"))
        names = sorted(ctx.service_name_of.values())
        assert names == ["team-a/api", "team-b/api"]

    def test_same_generic_name_across_namespaces_is_two_services(self):
        sink = ingest_k8s("repo_a", "k8s/a.yaml", self.MANIFEST)
        ctx, _ = run_linker(_claims_from_sink(sink, "repo_a"))
        assert len(set(ctx.service_name_of)) == 2
