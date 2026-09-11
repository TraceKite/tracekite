"""Policy edges distinct from call edges.

"billing permits orders" and "orders calls billing" are different facts:
one is the mesh's firewall, the other is behaviour. Folding the first into
the second would let a permissive policy inflate the call graph, so the
tests pin the distinction and the two declines that keep it precise.
"""

from tracekite import engine_config
from tracekite.db.memory_store import InMemoryLinkerStore
from tracekite.parsers.kubernetes_parser import parse_kubernetes_yaml
from tracekite.services.linker.engine import link
from tracekite.services.scan import scan

NOW = "2026-01-01T00:00:00+00:00"

MANIFEST = """
apiVersion: apps/v1
kind: Deployment
metadata: {name: billing, namespace: prod}
spec:
  template:
    metadata: {labels: {app: billing}}
    spec:
      containers: [{name: app, image: registry.internal/org/billing:1}]
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: orders, namespace: prod}
spec:
  template:
    metadata: {labels: {app: orders}}
    spec:
      containers: [{name: app, image: registry.internal/org/orders:1}]
---
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata: {name: allow-orders, namespace: prod}
spec:
  selector: {matchLabels: {app: billing}}
  action: ALLOW
  rules:
    - from:
        - source:
            principals: ["cluster.local/ns/prod/sa/orders"]
"""


class TestParser:
    def test_authorization_policy_yields_target_and_principals(self):
        policies = [r for r in parse_kubernetes_yaml("m.yaml", MANIFEST)
                    if r.kind == "AuthorizationPolicy"]
        [pol] = policies
        assert pol.policy_target == {"app": "billing"}
        assert pol.policy_source_accounts == ["orders"]

    def test_network_policy_yields_pod_selectors(self):
        [pol] = parse_kubernetes_yaml("np.yaml", """
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-web, namespace: prod}
spec:
  podSelector: {matchLabels: {app: billing}}
  ingress:
    - from:
        - podSelector: {matchLabels: {app: web}}
""")
        assert pol.policy_target == {"app": "billing"}
        assert pol.policy_source_labels == [{"app": "web"}]


class TestJoin:
    def _link(self, manifest, tmp_path):
        engine_config.configure(graph_hmac_key="mesh-policy-test")
        (tmp_path / "deploy").mkdir()
        (tmp_path / "deploy" / "mesh.yaml").write_text(manifest)
        store = InMemoryLinkerStore([scan(str(tmp_path), "mesh_repo")])
        return link(store.load_claims(), run_id="linkrun_d7", now=NOW)

    def test_a_policy_joins_as_permits_traffic_never_as_a_call(
            self, tmp_path):
        result = self._link(MANIFEST, tmp_path)
        permits = [e for e in result.edges
                   if e.type == "PERMITS_TRAFFIC" and e.status == "active"]
        assert permits, result.counters
        assert "orders" in permits[0].source_id
        assert "billing" in permits[0].target_id
        assert permits[0].extra_props["via"] == ["mesh_policy_allow"]
        assert result.counters.get("r2.policy_edges") == 1
        # The distinction that is the exit criterion: the policy minted no
        # call edge.
        assert not [e for e in result.edges
                    if e.type == "CALLS_SERVICE" and e.status == "active"]

    def test_a_policy_about_nobody_declines(self, tmp_path):
        ghost = MANIFEST.replace("app: billing}}\n  action",
                                 "app: ghost}}\n  action")
        result = self._link(ghost, tmp_path)
        assert not [e for e in result.edges if e.type == "PERMITS_TRAFFIC"]
        assert result.counters.get("r2.policy_target_unmatched") == 1

    def test_an_unknown_service_account_declines(self, tmp_path):
        stranger = MANIFEST.replace("sa/orders", "sa/stranger")
        result = self._link(stranger, tmp_path)
        assert not [e for e in result.edges if e.type == "PERMITS_TRAFFIC"]
        assert result.counters.get("r2.policy_source_unmatched") == 1
