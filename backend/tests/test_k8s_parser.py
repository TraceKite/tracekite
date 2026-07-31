"""K8s spec extraction.

The previous parser read only `metadata`, so every cross-repo signal in the
spec — images, env bindings, Service selectors, Ingress backends — was dropped.
"""

import pytest

from adduce.parsers.kubernetes_parser import (
    flatten_values, parse_helm_chart, parse_helm_values, parse_k8s_file,
    parse_kubernetes_yaml,
)

DEPLOYMENT = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-deploy
  namespace: prod
  labels:
    app.kubernetes.io/name: orders-service
    app.kubernetes.io/part-of: commerce
spec:
  template:
    metadata:
      labels:
        app: orders
    spec:
      serviceAccountName: orders-sa
      initContainers:
        - name: migrate
          image: myorg/orders-migrate:1.2
      containers:
        - name: app
          image: registry.internal/myorg/orders:1.2.3
          ports:
            - containerPort: 8080
          env:
            - name: VETS_URL
              value: http://vets-service:8080
            - name: KAFKA_BOOTSTRAP
              valueFrom:
                configMapKeyRef:
                  name: platform-config
                  key: kafka.brokers
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: orders-secrets
                  key: db-password
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
          envFrom:
            - configMapRef:
                name: shared-config
              prefix: SHARED_
            - secretRef:
                name: shared-secrets
"""


class TestWorkloads:
    def test_deployment_identity_and_namespace(self):
        [res] = parse_kubernetes_yaml("k8s/deploy.yaml", DEPLOYMENT)
        assert res.kind == "Deployment"
        assert res.name == "orders-deploy"
        assert res.namespace == "prod"
        assert res.service_account == "orders-sa"

    def test_conventional_label_beats_object_name(self):
        # A Deployment is usually `orders-deploy` while everything else calls
        # the service `orders-service`; the label is the joinable name.
        [res] = parse_kubernetes_yaml("k8s/deploy.yaml", DEPLOYMENT)
        assert res.service_name_hint == "orders-service"

    def test_falls_back_to_object_name_without_labels(self):
        [res] = parse_kubernetes_yaml("d.yaml", """
apiVersion: apps/v1
kind: Deployment
metadata: {name: plain-svc}
spec:
  template:
    spec:
      containers: [{name: app, image: nginx}]
""")
        assert res.service_name_hint == "plain-svc"

    def test_containers_images_and_ports(self):
        [res] = parse_kubernetes_yaml("k8s/deploy.yaml", DEPLOYMENT)
        assert [c.image for c in res.containers] == [
            "myorg/orders-migrate:1.2", "registry.internal/myorg/orders:1.2.3"]
        app = [c for c in res.containers if c.name == "app"][0]
        assert app.ports == [8080]
        assert app.is_init is False
        assert [c.name for c in res.containers if c.is_init] == ["migrate"]

    @pytest.mark.parametrize("kind,body", [
        ("StatefulSet", "spec:\n  template:\n    spec:\n      containers: [{name: a, image: i}]"),
        ("DaemonSet", "spec:\n  template:\n    spec:\n      containers: [{name: a, image: i}]"),
        ("Job", "spec:\n  template:\n    spec:\n      containers: [{name: a, image: i}]"),
        ("Pod", "spec:\n  containers: [{name: a, image: i}]"),
    ])
    def test_all_workload_kinds_yield_containers(self, kind, body):
        [res] = parse_kubernetes_yaml("w.yaml",
                                      f"apiVersion: v1\nkind: {kind}\n"
                                      f"metadata: {{name: w}}\n{body}\n")
        assert [c.image for c in res.containers] == ["i"]

    def test_cronjob_pod_spec_nests_one_level_deeper(self):
        [res] = parse_kubernetes_yaml("cj.yaml", """
apiVersion: batch/v1
kind: CronJob
metadata: {name: nightly}
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        metadata:
          labels: {app: nightly-job}
        spec:
          containers:
            - name: job
              image: myorg/nightly:3
              env:
                - name: TARGET_URL
                  value: http://reports-service:9000
""")
        assert res.schedule == "0 2 * * *"
        assert [c.image for c in res.containers] == ["myorg/nightly:3"]
        assert res.all_env[0].value == "http://reports-service:9000"
        assert res.pod_labels == {"app": "nightly-job"}


class TestEnvBindings:
    """The layer R9 resolves through."""

    @staticmethod
    def _env(name):
        [res] = parse_kubernetes_yaml("k8s/deploy.yaml", DEPLOYMENT)
        return [b for b in res.all_env if b.name == name][0]

    def test_literal_value(self):
        binding = self._env("VETS_URL")
        assert (binding.source, binding.value) == ("literal", "http://vets-service:8080")

    def test_configmap_key_ref(self):
        binding = self._env("KAFKA_BOOTSTRAP")
        assert binding.source == "configmap"
        assert (binding.ref_name, binding.ref_key) == ("platform-config", "kafka.brokers")
        assert binding.value is None

    def test_secret_key_ref_carries_no_value(self):
        binding = self._env("DB_PASSWORD")
        assert binding.source == "secret"
        assert (binding.ref_name, binding.ref_key) == ("orders-secrets", "db-password")
        assert binding.value is None

    def test_field_ref(self):
        binding = self._env("POD_IP")
        assert (binding.source, binding.ref_key) == ("field", "status.podIP")

    def test_env_from_configmap_and_secret_with_prefix(self):
        [res] = parse_kubernetes_yaml("k8s/deploy.yaml", DEPLOYMENT)
        wildcards = [b for b in res.all_env if b.name == "*"]
        assert {(b.source, b.ref_name, b.prefix) for b in wildcards} == {
            ("configmap", "shared-config", "SHARED_"),
            ("secret", "shared-secrets", ""),
        }

    def test_optional_flag_preserved(self):
        [res] = parse_kubernetes_yaml("d.yaml", """
apiVersion: apps/v1
kind: Deployment
metadata: {name: d}
spec:
  template:
    spec:
      containers:
        - name: a
          image: i
          env:
            - name: MAYBE
              valueFrom:
                configMapKeyRef: {name: cm, key: k, optional: true}
""")
        assert res.all_env[0].optional is True


class TestServiceAndIngress:
    def test_service_selector_and_ports(self):
        [res] = parse_kubernetes_yaml("svc.yaml", """
apiVersion: v1
kind: Service
metadata: {name: orders-service, namespace: prod}
spec:
  type: ClusterIP
  selector: {app: orders}
  ports:
    - name: http
      port: 8080
      targetPort: 8080
""")
        assert res.selector == {"app": "orders"}
        assert res.service_type == "ClusterIP"
        assert (res.service_ports[0].port, res.service_ports[0].name) == (8080, "http")

    def test_external_name_service(self):
        [res] = parse_kubernetes_yaml("svc.yaml", """
apiVersion: v1
kind: Service
metadata: {name: legacy}
spec: {type: ExternalName, externalName: legacy.corp.example.com}
""")
        assert res.external_name == "legacy.corp.example.com"

    def test_ingress_rules_map_path_to_backend_service(self):
        [res] = parse_kubernetes_yaml("ing.yaml", """
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: {name: edge}
spec:
  ingressClassName: nginx
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /api/orders
            pathType: Prefix
            backend:
              service:
                name: orders-service
                port: {number: 8080}
""")
        assert res.ingress_class == "nginx"
        rule = res.ingress_rules[0]
        assert (rule.host, rule.path, rule.backend_service, rule.backend_port) == (
            "shop.example.com", "/api/orders", "orders-service", "8080")

    def test_ingress_default_backend(self):
        [res] = parse_kubernetes_yaml("ing.yaml", """
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: {name: edge}
spec:
  defaultBackend:
    service: {name: fallback-service, port: {number: 80}}
""")
        assert res.ingress_rules[0].backend_service == "fallback-service"


class TestConfigMapAndSecret:
    def test_configmap_keys_and_values(self):
        [res] = parse_kubernetes_yaml("cm.yaml", """
apiVersion: v1
kind: ConfigMap
metadata: {name: platform-config}
data:
  kafka.brokers: kafka-0.kafka:9092
  search.host: http://opensearch:9200
""")
        assert sorted(res.data_keys) == ["kafka.brokers", "search.host"]
        assert res.config_values["search.host"] == "http://opensearch:9200"

    def test_secret_keys_without_values(self):
        # Invariant 6: a manifest must never move a credential into the graph.
        [res] = parse_kubernetes_yaml("sec.yaml", """
apiVersion: v1
kind: Secret
metadata: {name: orders-secrets}
data:
  db-password: c3VwZXJzZWNyZXQ=
stringData:
  api-token: plaintext-token
""")
        assert sorted(res.data_keys) == ["api-token", "db-password"]
        assert res.config_values == {}


class TestGitOps:
    def test_argocd_application_source_binding(self):
        [res] = parse_kubernetes_yaml("app.yaml", """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: orders}
spec:
  source:
    repoURL: https://github.com/myorg/orders-deploy
    path: overlays/prod
    targetRevision: main
  destination: {namespace: prod}
""")
        assert res.source_repo == "https://github.com/myorg/orders-deploy"
        assert (res.source_path, res.source_revision) == ("overlays/prod", "main")
        assert res.dest_namespace == "prod"

    def test_flux_kustomization(self):
        [res] = parse_kubernetes_yaml("ks.yaml", """
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata: {name: orders}
spec:
  path: ./deploy/prod
  targetNamespace: prod
  sourceRef: {kind: GitRepository, name: orders-repo}
""")
        assert res.source_path == "./deploy/prod"
        assert res.source_repo == "orders-repo"


class TestHelm:
    def test_flatten_nested_values_and_lists(self):
        flat = flatten_values({
            "image": {"repository": "myorg/orders", "tag": "1.2"},
            "env": [{"name": "A", "value": "http://x:80"}],
            "replicas": 3,
        })
        assert flat["image.repository"] == "myorg/orders"
        assert flat["env[0].value"] == "http://x:80"
        assert flat["replicas"] == "3"

    def test_values_file_flattened(self):
        [res] = parse_helm_values("chart/values.yaml",
                                  "image:\n  repository: myorg/orders\n"
                                  "vetsUrl: http://vets-service:8080\n")
        assert res.kind == "HelmValues"
        assert res.config_values["vetsUrl"] == "http://vets-service:8080"

    def test_overlay_filename_names_its_environment(self):
        [res] = parse_helm_values("chart/values-prod.yaml", "replicas: 5\n")
        assert res.annotations["environment"] == "prod"
        [base] = parse_helm_values("chart/values.yaml", "replicas: 1\n")
        assert base.annotations["environment"] == ""

    def test_chart_dependencies(self):
        [res] = parse_helm_chart("chart/Chart.yaml", """
name: orders
version: 1.0.0
dependencies:
  - name: postgresql
    version: 12.x
""")
        assert res.kind == "HelmChart"
        assert res.data_keys == ["postgresql"]

    def test_dispatch_by_filename(self):
        assert parse_k8s_file("Chart.yaml", "name: c\n")[0].kind == "HelmChart"
        assert parse_k8s_file("values.yaml", "a: 1\n")[0].kind == "HelmValues"
        assert parse_k8s_file("values-dev.yml", "a: 1\n")[0].kind == "HelmValues"


class TestRobustness:
    def test_unrendered_helm_template_is_not_an_error(self):
        assert parse_kubernetes_yaml("t.yaml", "kind: {{ .Values.kind }}\n[") == []

    def test_multi_document_manifest(self):
        docs = parse_kubernetes_yaml("all.yaml", """
apiVersion: v1
kind: Service
metadata: {name: a}
spec: {selector: {app: a}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: a}
spec:
  template:
    spec:
      containers: [{name: a, image: i}]
""")
        assert [d.kind for d in docs] == ["Service", "Deployment"]

    def test_unknown_kind_skipped(self):
        assert parse_kubernetes_yaml("x.yaml", "kind: SomeCRD\nmetadata: {name: x}\n") == []

    def test_malformed_spec_types_do_not_crash(self):
        assert parse_kubernetes_yaml("x.yaml", "kind: Deployment\nmetadata: {name: x}\nspec: notadict\n") == []
        assert parse_kubernetes_yaml("y.yaml", "- just\n- a\n- list\n") == []
