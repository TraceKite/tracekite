"""M4 messaging: sites/manifests/IaC -> topic claims -> R6 -> VQ3 chains.

The join is where every M2/M3 defect surfaced, so most of this file drives the
full path: emitters -> ClaimRecords -> r0+r9+r6 -> asserted edges. Messaging is
decoupled by design — the test estate never has a producer naming a consumer —
and the redaction invariant holds throughout: no raw config value appears in
any claim these tests build.
"""

from types import SimpleNamespace

import pytest

from tracekite.parsers.asyncapi_parser import parse_asyncapi
from tracekite.parsers.iac_parser import parse_terraform
from tracekite.parsers.kubernetes_parser import parse_kubernetes_yaml
from tracekite.services.claims import CONSUMES, PROVIDES, ContractClaim, topic_key
from tracekite.services.ingest_claims import (
    add_claim, emit_asyncapi_claims, emit_avro_claims, emit_iac_claims,
    emit_k8s_claims, emit_messaging_claims,
)
from tracekite.services.ingest_source import IngestSink
from tracekite.services.linker import r0_alias, r6_topic, r9_env, r9_env_index
from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)

KEDA_YAML = """
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

DEPLOY_ENV_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shipping
  namespace: prod
spec:
  selector:
    matchLabels: {app: shipping}
  template:
    metadata:
      labels: {app: shipping}
    spec:
      containers:
        - name: app
          image: acme/shipping:1.0
          env:
            - name: ORDERS_TOPIC
              value: order-events
"""

TERRAFORM = '''
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

resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn = "arn:aws:sqs:us-east-1:123456789:refund-requests"
  function_name    = "refund-processor"
}
'''

ASYNCAPI = """
asyncapi: '2.6.0'
info:
  title: Orders Service
  version: 1.0.0
servers:
  prod:
    url: kafka.internal:9092
    protocol: kafka
channels:
  order-events:
    subscribe:
      operationId: publishOrderEvent
  audit-log:
    publish:
      operationId: onAudit
"""


def _file(path, language=None):
    return SimpleNamespace(path=path, language=language)


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
            attrs={**dict(node.metadata or {}),
                   **{k: v for k, v in extra.items()
                      if k in ("env_scope",)}},
            evidence_node_id=f"node:{node.id}", evidence_node_type="File",
        ))
    return records


def _k8s_sink(repo_id, path, content):
    sink = IngestSink()
    resources = parse_kubernetes_yaml(path, content)
    node_ids = {f"{r.kind}/{r.name}": f"k8s:{r.kind}/{r.name}"
                for r in resources}
    emit_k8s_claims(repo_id, _file(path), resources, node_ids, sink)
    return _claims(sink, repo_id)


def _iac_sink(repo_id, path, content):
    sink = IngestSink()
    resources = parse_terraform(path, content)
    node_ids = {r.address: f"iac:{r.address}" for r in resources}
    emit_iac_claims(repo_id, _file(path), resources, node_ids, sink)
    return _claims(sink, repo_id)


def _code_topic_claim(repo_id, system, name, role, path="src/produce.py"):
    """A literal producer/consumer site claim, as emit_messaging_claims makes."""
    sink = IngestSink()
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="topic",
        direction=PROVIDES if role == "produces" else CONSUMES,
        key=topic_key(system, name), hint_source="none",
        evidence=[f"{path}:10"],
        subject=f"msg/test/{role}/{name}",
        attrs={"system": system, "framework": "test", "role": role},
    ), f"file:{repo_id}:{path}", sink)
    return _claims(sink, repo_id)


def run_linker(claims):
    ctx = LinkContext("linkrun_test", load_confidence(), {})
    ctx.known_repos = {c.repo_id for c in claims}
    index = ClaimIndex(claims)
    out = ResolverOutput()
    # r9_env_index is broadcast: it builds ctx.env_values, which both
    # r9_env and r6_topic read (I10).
    for module in (r0_alias, r9_env_index, r9_env, r6_topic):
        out.extend(module.resolve(index, ctx))
    return ctx, out


def edges_of(out, edge_type):
    return [e for e in out.edges if e.type == edge_type]


class TestKedaTriggers:
    def test_kafka_trigger_is_consumption_evidence(self):
        ctx, out = run_linker(_k8s_sink("repo_worker", "deploy/keda.yaml",
                                        KEDA_YAML))
        consumes = edges_of(out, "CONSUMES_FROM")
        keys = {e.claim_key for e in consumes}
        assert "kafka:order-events" in keys
        assert "sqs:refund-requests" in keys
        assert ctx.counters["r6.consumers"] >= 2

    def test_trigger_attributes_scale_target_service(self):
        _, out = run_linker(_k8s_sink("repo_worker", "deploy/keda.yaml",
                                      KEDA_YAML))
        kafka = [e for e in edges_of(out, "CONSUMES_FROM")
                 if e.claim_key == "kafka:order-events"]
        assert kafka[0].extra_props.get("service") == "order-worker"


class TestIacMessaging:
    def test_queue_resource_declares_topic(self):
        ctx, out = run_linker(_iac_sink("repo_infra", "infra/main.tf",
                                        TERRAFORM))
        declares = {e.claim_key for e in edges_of(out, "DECLARES_TOPIC")}
        assert "sqs:refund-requests" in declares
        assert "sns:order-fanout" in declares
        assert ctx.counters["r6.declared"] >= 2

    def test_sns_subscription_fans_out_to_queue(self):
        _, out = run_linker(_iac_sink("repo_infra", "infra/main.tf",
                                      TERRAFORM))
        fan = edges_of(out, "FANS_OUT_TO")
        assert len(fan) == 1
        assert fan[0].source_id == "global:Topic:sns:order-fanout"
        assert fan[0].target_id == "global:Topic:sqs:refund-requests"

    def test_lambda_event_source_mapping_consumes(self):
        _, out = run_linker(_iac_sink("repo_infra", "infra/main.tf",
                                      TERRAFORM))
        consumes = [e for e in edges_of(out, "CONSUMES_FROM")
                    if e.claim_key == "sqs:refund-requests"]
        assert consumes and consumes[0].extra_props.get(
            "service") == "refund-processor"


class TestCrossRepoJoin:
    def test_producer_and_keda_consumer_meet_at_rendezvous(self):
        claims = (_code_topic_claim("repo_orders", "kafka", "order-events",
                                    "produces")
                  + _k8s_sink("repo_worker", "deploy/keda.yaml", KEDA_YAML))
        ctx, out = run_linker(claims)
        topics = [r for r in out.rendezvous if r.label == "Topic"
                  and r.props["key"] == "kafka:order-events"]
        assert len(topics) == 1
        publishes = [e for e in edges_of(out, "PUBLISHES_TO")
                     if e.claim_key == "kafka:order-events"]
        consumes = [e for e in edges_of(out, "CONSUMES_FROM")
                    if e.claim_key == "kafka:order-events"]
        assert publishes[0].source_repo_id == "repo_orders"
        assert consumes[0].source_repo_id == "repo_worker"
        # The consumer edge names the producing repo as the only other party.
        assert consumes[0].target_repo_id == "repo_orders"


class TestEnvIndirection:
    def test_env_read_topic_resolves_via_hmac(self):
        # shipping's manifest sets ORDERS_TOPIC=order-events (enum-ish, only
        # its hmac survives redaction); orders publishes the literal name.
        claims = (_code_topic_claim("repo_orders", "kafka", "order-events",
                                    "produces")
                  + _k8s_sink("repo_ship", "deploy/prod/shipping.yaml",
                              DEPLOY_ENV_YAML)
                  + _code_topic_claim("repo_ship", "kafka", "env:ORDERS_TOPIC",
                                      "consumes", path="src/consume.py"))
        ctx, out = run_linker(claims)
        assert ctx.counters["r6.env_resolved"] == 1
        consumes = [e for e in edges_of(out, "CONSUMES_FROM")
                    if e.source_repo_id == "repo_ship"]
        assert consumes[0].target_id == "global:Topic:kafka:order-events"
        assert consumes[0].match_type == "topic_env_resolved"

    def test_no_definition_is_counted_not_guessed(self):
        ctx, out = run_linker(
            _code_topic_claim("repo_ship", "kafka", "env:MISSING_TOPIC",
                              "consumes"))
        assert ctx.counters["r6.env_unresolved"] == 1
        assert not edges_of(out, "CONSUMES_FROM")

    def test_conflicting_values_across_files_decline(self):
        other = DEPLOY_ENV_YAML.replace("order-events", "order-events-v2")
        other = other.replace("name: shipping", "name: shipping-eu")
        other = other.replace("app: shipping", "app: shipping-eu")
        other = other.replace("namespace: prod", "namespace: prod-eu")
        claims = (_k8s_sink("repo_ship", "deploy/prod/shipping.yaml",
                            DEPLOY_ENV_YAML)
                  + _k8s_sink("repo_eu", "deploy/prod/shipping-eu.yaml", other)
                  + _code_topic_claim("repo_ship", "kafka",
                                      "env:ORDERS_TOPIC", "consumes"))
        ctx, out = run_linker(claims)
        assert ctx.counters["r6.ambiguous_across_envs"] == 1
        assert not [e for e in edges_of(out, "CONSUMES_FROM")
                    if e.source_repo_id == "repo_ship"]

    def test_two_indirected_sides_join_on_redacted_rendezvous(self):
        # No literal anywhere: producer and consumer both read the same
        # manifest value. They still meet — at an hmac-keyed Topic.
        claims = (_k8s_sink("repo_ship", "deploy/prod/shipping.yaml",
                            DEPLOY_ENV_YAML)
                  + _code_topic_claim("repo_ship", "kafka",
                                      "env:ORDERS_TOPIC", "consumes"))
        ctx, out = run_linker(claims)
        consumes = [e for e in edges_of(out, "CONSUMES_FROM")
                    if e.source_repo_id == "repo_ship"]
        assert consumes and consumes[0].target_id.startswith(
            "global:Topic:kafka:#")
        topic = [r for r in out.rendezvous
                 if r.node_id == consumes[0].target_id][0]
        assert topic.props["redacted"] is True
        # Invariant 6: the raw value appears nowhere in the rendezvous.
        assert "order-events" not in str(topic.props)


class TestDeclarations:
    def test_asyncapi_channels_declare_with_direction(self):
        sink = IngestSink()
        doc = parse_asyncapi("asyncapi.yml", ASYNCAPI)
        emit_asyncapi_claims("repo_orders", _file("asyncapi.yml"), doc,
                             "file:asyncapi", sink)
        ctx, out = run_linker(_claims(sink, "repo_orders"))
        declares = {e.claim_key for e in edges_of(out, "DECLARES_TOPIC")}
        assert declares == {"kafka:order-events", "kafka:audit-log"}

    def test_asyncapi_unknown_protocol_folds_onto_literal_system(self):
        no_server = ASYNCAPI.replace("    protocol: kafka\n", "")
        sink = IngestSink()
        doc = parse_asyncapi("asyncapi.yml", no_server)
        emit_asyncapi_claims("repo_orders", _file("asyncapi.yml"), doc,
                             "file:asyncapi", sink)
        claims = (_claims(sink, "repo_orders")
                  + _code_topic_claim("repo_worker", "kafka", "order-events",
                                      "consumes"))
        ctx, out = run_linker(claims)
        assert ctx.counters["r6.channel_folded"] >= 1
        keys = {r.props["key"] for r in out.rendezvous if r.label == "Topic"}
        assert "kafka:order-events" in keys
        assert "channel:order-events" not in keys

    def test_avro_subject_names_its_topic(self):
        sink = IngestSink()
        schema = SimpleNamespace(subject_hint="order-events-value",
                                 full_name="com.acme.OrderEvent")
        emit_avro_claims("repo_orders", _file("schemas/order-events-value.avsc"),
                         schema, "file:avsc", sink)
        ctx, out = run_linker(_claims(sink, "repo_orders"))
        assert [e.claim_key for e in edges_of(out, "DECLARES_TOPIC")] \
            == ["kafka:order-events"]


class TestDynamicSites:
    def test_dynamic_destination_is_counted_never_joined(self):
        sink = IngestSink()
        add_claim("repo_x", ContractClaim(
            repo_id="repo_x", kind="topic", direction=PROVIDES, key="",
            evidence=["src/p.py:5"], subject="msg/test/produces/dyn",
            attrs={"system": "kafka", "dynamic": True},
        ), "file:x", sink)
        ctx, out = run_linker(_claims(sink, "repo_x"))
        assert ctx.counters["r6.dynamic_unlinked"] == 1
        assert not out.rendezvous
