"""E2: env indirection across layers — values → ConfigMap → env → code.

R9 previously stopped one layer short: an env var backed by a ConfigMap
resolved, but a ConfigMap value that was itself `{{ .Values.x }}` was a
dead end. The chain now follows the pointer into the values file — and
declines everything that would require actually RENDERING a template,
because a hand-rendered value is an invented one.
"""

from tracekite.parsers.kubernetes_parser import parse_k8s_file
from tracekite.services.ingest_claims import emit_k8s_claims, emit_source_claims
from tracekite.services.ingest_source import IngestSink
from tests.test_m2_k8s_env import (
    _claims_from_sink, _file, ingest_k8s, run_linker,
)

VALUES = """
backend:
  url: http://orders.prod.svc:8080
"""

MANIFEST_TEMPLATE = """
apiVersion: v1
kind: ConfigMap
metadata: {{name: platform, namespace: prod}}
data:
  orders.url: "{value}"
---
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
          image: i
          env:
            - name: ORDERS_URL
              valueFrom:
                configMapKeyRef: {{name: platform, key: orders.url}}
---
apiVersion: v1
kind: Service
metadata: {{name: storefront, namespace: prod}}
spec: {{selector: {{app: storefront}}}}
---
apiVersion: v1
kind: Service
metadata: {{name: orders, namespace: prod}}
spec: {{selector: {{app: orders}}}}
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
      containers: [{{name: app, image: i2}}]
"""

CODE = 'const res = await fetch(process.env.ORDERS_URL + "/v1/orders");'


def emit_values(sink):
    values = parse_k8s_file("charts/app/values.yaml", VALUES)
    node_ids = {f"{r.kind}/{r.name}": f"k8snode:{r.kind}:{r.name}"
                for r in values}
    emit_k8s_claims("repo_web", _file("charts/app/values.yaml"), values,
                    node_ids, sink)


def estate(configmap_value="{{ .Values.backend.url }}", with_values=True):
    sink = ingest_k8s(
        "repo_web", "charts/app/templates/all.yaml",
        MANIFEST_TEMPLATE.format(value=configmap_value))
    if with_values:
        emit_values(sink)
    emit_source_claims("repo_web", _file("src/c.ts", "typescript"),
                       CODE, [], "file:c", sink)
    return _claims_from_sink(sink, "repo_web")


def env_edges(out):
    return [e for e in out.edges
            if e.extra_props.get("via") == ["env_indirection"]]


class TestHelmChain:
    def test_values_configmap_env_code_resolves(self):
        ctx, out = run_linker(estate())
        assert ctx.counters["r9.resolved_ref"] >= 1
        assert ctx.counters["r9.helm_ref_resolved"] == 1
        [edge] = env_edges(out)
        assert "orders" in edge.target_id

    def test_missing_values_key_declines(self):
        ctx, out = run_linker(estate(with_values=False))
        assert ctx.counters["r9.helm_ref_unresolved"] == 1
        assert env_edges(out) == []

    def test_composite_template_is_counted_never_spliced(self):
        # Reconstructing http://{{ .Values.host }}:8080 would mean
        # rendering the chart. Declined, visibly.
        ctx, out = run_linker(
            estate(configmap_value="http://{{ .Values.backend.host }}:8080"))
        assert ctx.counters["r9.helm_composite_template"] == 1
        assert "r9.helm_ref_resolved" not in ctx.counters
        assert env_edges(out) == []

    def test_direct_env_template_also_chases(self):
        # Three layers, no ConfigMap: values → env literal → code.
        manifest = MANIFEST_TEMPLATE.replace(
            """              valueFrom:
                configMapKeyRef: {{name: platform, key: orders.url}}""",
            '              value: "{{{{ .Values.backend.url }}}}"')
        sink = ingest_k8s("repo_web", "charts/app/templates/all.yaml",
                          manifest.format(value="unused"))
        emit_values(sink)
        emit_source_claims("repo_web", _file("src/c.ts", "typescript"),
                           CODE, [], "file:c", sink)
        ctx, out = run_linker(_claims_from_sink(sink, "repo_web"))
        assert ctx.counters["r9.helm_ref_resolved"] == 1
        assert len(env_edges(out)) == 1

    def test_plain_literal_chain_is_untouched(self):
        # The pre-E2 shape must price and resolve exactly as before.
        ctx, out = run_linker(
            estate(configmap_value="http://orders.prod.svc:8080",
                   with_values=False))
        assert ctx.counters["r9.resolved_ref"] >= 1
        assert "r9.helm_ref_resolved" not in ctx.counters
        assert len(env_edges(out)) == 1
