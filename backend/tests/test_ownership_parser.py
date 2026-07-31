"""Ownership + observability identity parsing."""

from adduce.parsers.ownership_parser import (
    extract_observability_identity, is_catalog_file, is_codeowners_file,
    parse_catalog_info, parse_codeowners,
)

CODEOWNERS = """\
# Fallback: platform owns everything not matched later.
*                     @acme/platform-team

# Infrastructure is shared.
*.tf                  @acme/infra @jane  # tf reviewed by both
/backend/             @acme/backend-team
/backend/payments/**  payments-oncall@acme.com @acme/payments
/docs/getting\\ started/ @acme/docs-team
/generated/
"""


class TestCodeownersDetection:
    def test_honored_locations(self):
        assert is_codeowners_file("CODEOWNERS")
        assert is_codeowners_file(".github/CODEOWNERS")
        assert is_codeowners_file("docs/CODEOWNERS")

    def test_other_locations_rejected(self):
        assert not is_codeowners_file("src/CODEOWNERS")
        assert not is_codeowners_file("CODEOWNERS.md")
        assert not is_codeowners_file("codeowners")


class TestCodeowners:
    def test_rules_in_file_order_with_comments_and_blanks_skipped(self):
        rules = parse_codeowners("CODEOWNERS", CODEOWNERS)
        assert [r.pattern for r in rules] == [
            "*", "*.tf", "/backend/", "/backend/payments/**",
            "/docs/getting\\ started/", "/generated/",
        ]

    def test_owners_normalized_leading_at_stripped(self):
        rules = parse_codeowners("CODEOWNERS", CODEOWNERS)
        assert rules[0].owners == ["acme/platform-team"]
        assert rules[2].owners == ["acme/backend-team"]

    def test_multiple_owners_and_inline_comment_stripped(self):
        tf = parse_codeowners("CODEOWNERS", CODEOWNERS)[1]
        assert tf.owners == ["acme/infra", "jane"]
        assert tf.line == 5

    def test_email_owner_kept_verbatim(self):
        payments = parse_codeowners("CODEOWNERS", CODEOWNERS)[3]
        assert payments.owners == ["payments-oncall@acme.com", "acme/payments"]

    def test_escaped_space_stays_in_pattern(self):
        docs = parse_codeowners("CODEOWNERS", CODEOWNERS)[4]
        assert docs.pattern == "/docs/getting\\ started/"
        assert docs.owners == ["acme/docs-team"]

    def test_ownerless_pattern_kept_with_empty_owners(self):
        # A bare pattern un-owns paths; the resolver needs to see it.
        generated = parse_codeowners("CODEOWNERS", CODEOWNERS)[5]
        assert generated.owners == []

    def test_line_numbers_match_file(self):
        rules = parse_codeowners("CODEOWNERS", CODEOWNERS)
        assert rules[0].line == 2
        assert rules[5].line == 9

    def test_precedence_not_resolved_here(self):
        content = "* @acme/platform\n/backend/ @acme/backend\n"
        rules = parse_codeowners("CODEOWNERS", content)
        # Both survive: later-rule-wins is the resolver's job.
        assert len(rules) == 2


CATALOG_INFO = """\
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: orders
  namespace: default
  title: Orders Service
  annotations:
    github.com/project-slug: acme/orders
    pagerduty.com/service-id: P8XY12Z
    pagerduty.com/integration-key: e93facc04764012d7bfb002500d5d1a6
    opsgenie.com/team: payments
spec:
  type: service
  lifecycle: production
  owner: group:default/payments-team
  system: order-management
  providesApis:
    - orders-api
  consumesApis:
    - api:billing-api
  dependsOn:
    - resource:default/orders-db
    - component:auth-service
---
apiVersion: backstage.io/v1alpha1
kind: API
metadata:
  name: orders-api
spec:
  type: openapi
  lifecycle: production
  owner: user:jdoe
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: not-a-catalog-entity
spec:
  replicas: 2
"""


class TestCatalogDetection:
    def test_catalog_file_names(self):
        assert is_catalog_file("catalog-info.yaml")
        assert is_catalog_file("catalog-info.yml")
        assert is_catalog_file("services/orders/catalog-info.yaml")

    def test_other_yaml_rejected(self):
        assert not is_catalog_file("catalog.yaml")
        assert not is_catalog_file("my-catalog-info.yaml")


class TestCatalogInfo:
    def test_only_backstage_kinds_extracted(self):
        entities = parse_catalog_info("catalog-info.yaml", CATALOG_INFO)
        assert [e.kind for e in entities] == ["Component", "API"]

    def test_component_identity_and_spec_fields(self):
        component = parse_catalog_info("catalog-info.yaml", CATALOG_INFO)[0]
        assert component.name == "orders"
        assert component.entity_type == "service"
        assert component.lifecycle == "production"
        assert component.system == "order-management"

    def test_owner_ref_stripped_to_bare_team(self):
        entities = parse_catalog_info("catalog-info.yaml", CATALOG_INFO)
        assert entities[0].owner == "payments-team"     # group:default/ gone
        assert entities[1].owner == "jdoe"              # user: gone

    def test_api_relations_stripped_to_bare_names(self):
        component = parse_catalog_info("catalog-info.yaml", CATALOG_INFO)[0]
        assert component.provides_apis == ["orders-api"]
        assert component.consumes_apis == ["billing-api"]
        assert component.depends_on == ["orders-db", "auth-service"]

    def test_original_refs_kept_in_attrs(self):
        component = parse_catalog_info("catalog-info.yaml", CATALOG_INFO)[0]
        assert component.attrs["dependsOn"] == [
            "resource:default/orders-db", "component:auth-service"]
        assert component.attrs["consumesApis"] == ["api:billing-api"]
        assert component.attrs["project_slug"] == "acme/orders"

    def test_pagerduty_service_id_captured(self):
        component = parse_catalog_info("catalog-info.yaml", CATALOG_INFO)[0]
        assert component.pagerduty_service == "P8XY12Z"
        assert component.opsgenie_team == "payments"

    def test_pagerduty_integration_key_never_leaks(self):
        # The integration key is a credential: it must not appear in ANY field.
        entities = parse_catalog_info("catalog-info.yaml", CATALOG_INFO)
        assert "e93facc04764012d7bfb002500d5d1a6" not in repr(entities)


OTEL_ENV = """\
# tracing identity
OTEL_SERVICE_NAME=orders
OTEL_RESOURCE_ATTRIBUTES=service.namespace=shop,service.version=1.4.2,deployment.environment=prod
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317
OTEL_EXPORTER_OTLP_HEADERS=api-key=SUPERSECRET_OTLP_KEY_123
"""

K8S_OTEL = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout
spec:
  template:
    spec:
      containers:
        - name: checkout
          image: acme/checkout:3.1
          env:
            - name: OTEL_SERVICE_NAME
              value: "checkout"
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: http://otel-collector:4317
"""

OTEL_PY = """\
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

resource = Resource.create({SERVICE_NAME: "orders-worker", "service.version": "2.0"})
"""

OTEL_JS = """\
const { Resource } = require('@opentelemetry/resources');
const { SemanticResourceAttributes } = require('@opentelemetry/semantic-conventions');

const resource = new Resource({
  [SemanticResourceAttributes.SERVICE_NAME]: 'cart-web',
  [SemanticResourceAttributes.DEPLOYMENT_ENVIRONMENT]: 'prod',
});
"""


class TestOtelIdentity:
    def test_env_file_service_name_with_resource_attribute_enrichment(self):
        identities = extract_observability_identity("deploy/orders.env", OTEL_ENV)
        assert len(identities) == 1
        orders = identities[0]
        assert orders.service_name == "orders"
        assert orders.source == "otel-env"
        assert orders.environment == "prod"          # from OTEL_RESOURCE_ATTRIBUTES
        assert orders.line == 2
        assert orders.attrs["service.namespace"] == "shop"

    def test_otlp_exporter_header_secret_never_leaks(self):
        identities = extract_observability_identity("deploy/orders.env", OTEL_ENV)
        assert "SUPERSECRET_OTLP_KEY_123" not in repr(identities)

    def test_k8s_name_value_pair_within_two_lines(self):
        identities = extract_observability_identity("k8s/checkout.yaml", K8S_OTEL)
        assert len(identities) == 1
        assert identities[0].service_name == "checkout"   # quotes stripped
        assert identities[0].source == "otel-env"
        assert identities[0].line == 12

    def test_python_resource_create(self):
        identities = extract_observability_identity("app/tracing.py", OTEL_PY)
        assert len(identities) == 1
        assert identities[0].service_name == "orders-worker"
        assert identities[0].source == "otel-resource"

    def test_js_semantic_attribute_key(self):
        identities = extract_observability_identity("src/tracing.js", OTEL_JS)
        assert len(identities) == 1
        assert identities[0].service_name == "cart-web"
        assert identities[0].source == "otel-resource"

    def test_code_files_do_not_use_env_scanning(self):
        # A bare constant in code is not an env declaration.
        assert extract_observability_identity(
            "settings.py", 'OTEL_SERVICE_NAME = "unused"\n') == []


DD_ENV = """\
DD_SERVICE=payments
DD_ENV=staging
DD_TAGS=team:payments-core,region:us1
DD_API_KEY=ddapi_SECRET_abc123
DD_APP_KEY=ddapp_SECRET_def456
"""

DD_COMPOSE = """\
services:
  billing:
    image: acme/billing:1.2
    environment:
      - DD_TAGS=service:billing,team:fin-platform,env:prod
      - DD_TRACE_ENABLED=true
"""

DD_AGENT_YAML = """\
api_key: dd_SECRET_KEY_999
site: datadoghq.com
service: inventory
env: prod
tags:
  - team:warehouse
  - tier:backend
"""

DD_K8S_LABELS = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: storefront-web
  labels:
    tags.datadoghq.com/service: storefront
    tags.datadoghq.com/env: production
    tags.datadoghq.com/version: "5.1"
spec:
  template:
    metadata:
      labels:
        tags.datadoghq.com/service: storefront
        tags.datadoghq.com/env: production
"""


class TestDatadogIdentity:
    def test_dd_service_env_var_with_team_and_env(self):
        identities = extract_observability_identity("deploy/payments.env", DD_ENV)
        assert len(identities) == 1
        payments = identities[0]
        assert payments.service_name == "payments"
        assert payments.source == "datadog"
        assert payments.environment == "staging"       # DD_ENV
        assert payments.team == "payments-core"        # DD_TAGS team:
        assert payments.line == 1

    def test_dd_api_keys_never_leak(self):
        identities = extract_observability_identity("deploy/payments.env", DD_ENV)
        text = repr(identities)
        assert "ddapi_SECRET_abc123" not in text
        assert "ddapp_SECRET_def456" not in text

    def test_dd_tags_service_tag_in_compose_list(self):
        identities = extract_observability_identity("docker-compose.yml", DD_COMPOSE)
        assert len(identities) == 1
        billing = identities[0]
        assert (billing.service_name, billing.source) == ("billing", "datadog")
        assert billing.team == "fin-platform"
        assert billing.environment == "prod"
        assert billing.line == 5

    def test_datadog_agent_config_file(self):
        identities = extract_observability_identity("etc/datadog.yaml", DD_AGENT_YAML)
        assert len(identities) == 1
        inventory = identities[0]
        assert inventory.service_name == "inventory"
        assert inventory.environment == "prod"
        assert inventory.team == "warehouse"
        assert inventory.line == 3
        assert "dd_SECRET_KEY_999" not in repr(identities)

    def test_k8s_datadog_labels_with_adjacent_env_deduped(self):
        identities = extract_observability_identity("k8s/web.yaml", DD_K8S_LABELS)
        assert len(identities) == 1                    # metadata + pod labels merge
        storefront = identities[0]
        assert storefront.service_name == "storefront"
        assert storefront.source == "datadog"
        assert storefront.environment == "production"


NEWRELIC_YML = """\
common: &default_settings
  license_key: 'nrlk_SECRET_LICENSE_123'
  app_name: Orders Service
  distributed_tracing:
    enabled: true

production:
  <<: *default_settings
  app_name: Orders Service (Production)

development:
  <<: *default_settings
"""

NEWRELIC_INI = """\
[newrelic]
license_key = nrlk_SECRET_INI_456
app_name = Billing Service
monitor_mode = true
"""


class TestNewRelicIdentity:
    def test_yaml_common_and_environment_override(self):
        identities = extract_observability_identity("newrelic.yml", NEWRELIC_YML)
        by_name = {i.service_name: i for i in identities}
        assert set(by_name) == {"Orders Service", "Orders Service (Production)"}
        assert by_name["Orders Service"].environment == ""
        assert by_name["Orders Service"].line == 3
        assert by_name["Orders Service (Production)"].environment == "production"
        assert all(i.source == "newrelic" for i in identities)

    def test_yaml_license_key_never_leaks(self):
        identities = extract_observability_identity("newrelic.yml", NEWRELIC_YML)
        assert "nrlk_SECRET_LICENSE_123" not in repr(identities)

    def test_ini_app_name(self):
        identities = extract_observability_identity("newrelic.ini", NEWRELIC_INI)
        assert len(identities) == 1
        assert identities[0].service_name == "Billing Service"
        assert identities[0].source == "newrelic"
        assert "nrlk_SECRET_INI_456" not in repr(identities)

    def test_env_var(self):
        content = "NEW_RELIC_APP_NAME=Cart Service\nNEW_RELIC_LICENSE_KEY=nrlk_SECRET\n"
        identities = extract_observability_identity("deploy/cart.env", content)
        assert [(i.service_name, i.source) for i in identities] == [
            ("Cart Service", "newrelic")]


SENTRY_PROPERTIES = """\
defaults.url=https://sentry.example.com/
defaults.org=acme
defaults.project=storefront
auth.token=sntrys_SECRET_TOKEN_789
"""


class TestSentryIdentity:
    def test_properties_project_and_org(self):
        identities = extract_observability_identity(
            "android/sentry.properties", SENTRY_PROPERTIES)
        assert len(identities) == 1
        assert identities[0].service_name == "storefront"
        assert identities[0].source == "sentry-project"
        assert identities[0].line == 3
        assert identities[0].attrs["org"] == "acme"

    def test_auth_token_never_leaks(self):
        identities = extract_observability_identity(
            "sentry.properties", SENTRY_PROPERTIES)
        assert "sntrys_SECRET_TOKEN_789" not in repr(identities)

    def test_env_var_project_without_dsn_leak(self):
        content = ("SENTRY_PROJECT=mobile-app\n"
                   "SENTRY_DSN=https://abc123SECRET@o42.ingest.sentry.io/999\n")
        identities = extract_observability_identity(".env", content)
        assert [(i.service_name, i.source) for i in identities] == [
            ("mobile-app", "sentry-project")]
        assert "abc123SECRET" not in repr(identities)


PROMETHEUS_YML = """\
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: orders-service
    metrics_path: /metrics
    static_configs:
      - targets: ["orders:8080", "orders-canary:8080"]
  - job_name: "node-exporter"
    static_configs:
      - targets:
          - node1:9100
          - node2:9100
"""


class TestPrometheusIdentity:
    def test_one_identity_per_scrape_job(self):
        identities = extract_observability_identity("prometheus.yml", PROMETHEUS_YML)
        assert [i.service_name for i in identities] == [
            "orders-service", "node-exporter"]
        assert all(i.source == "prometheus-job" for i in identities)

    def test_static_targets_kept_in_attrs(self):
        identities = extract_observability_identity("prometheus.yml", PROMETHEUS_YML)
        assert identities[0].attrs["targets"] == ["orders:8080", "orders-canary:8080"]
        assert identities[1].attrs["targets"] == ["node1:9100", "node2:9100"]

    def test_job_lines(self):
        identities = extract_observability_identity("prometheus.yml", PROMETHEUS_YML)
        assert identities[0].line == 5
        assert identities[1].line == 9


class TestNeverRaises:
    def test_codeowners_garbage(self):
        assert parse_codeowners("CODEOWNERS", "") == []
        assert parse_codeowners("CODEOWNERS", None) == []

    def test_catalog_garbage(self):
        assert parse_catalog_info("catalog-info.yaml", "foo: [unclosed") == []
        assert parse_catalog_info("catalog-info.yaml", "- 1\n- 2\n") == []
        assert parse_catalog_info("catalog-info.yaml", None) == []

    def test_observability_garbage(self):
        # Un-rendered Helm templates are not valid YAML; that is expected.
        assert extract_observability_identity(
            "prometheus.yml", "{{ .Values.scrape }}") == []
        assert extract_observability_identity("app.env", "") == []
        assert extract_observability_identity("newrelic.yml", "just a string") == []
        assert isinstance(
            extract_observability_identity(None, "DD_SERVICE=x"), list)
