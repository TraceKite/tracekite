"""Manifest/config/docker/k8s ingestion pass with parse-time redaction.

Raw config values never reach the graph (Invariant 6): every value is reduced
to RedactedValue fields before a node is built. K8s Secret data is never read
at all — the K8s parser only extracts resource identity.
"""

import logging

from evigraph.services.graph_factories import (
    create_config_node, create_declares_edge, create_dependency_node,
    create_depends_on_edge, create_docker_node, create_iac_node, create_k8s_node,
)
from evigraph.services.ingest_claims import (
    emit_asyncapi_claims, emit_avro_claims, emit_buf_claims,
    emit_compose_claims, emit_config_claims,
    emit_iac_claims, emit_graphql_claims, emit_k8s_claims, emit_proto_claims,
)
from evigraph.services.ingest_deps import (
    emit_dependency_claims, emit_publish_claims,
)
from evigraph.services.ingest_source import IngestSink
from evigraph.services.redaction import redact

logger = logging.getLogger(__name__)


def process_dependencies(repo_id: str, file_info, dependencies, file_node_id: str,
                         sink: IngestSink, content: str = "") -> None:
    for dep in dependencies:
        if not dep.name:
            continue
        node = create_dependency_node(
            repo_id, dep.name, dep.version or "", dep.scope or "",
            dep.type or "", file_info.path,
        )
        sink.add_node(node)
        sink.add_edge(create_depends_on_edge(
            repo_id, file_node_id, node.id, evidence=[file_info.path],
        ))
    emit_dependency_claims(repo_id, file_info, dependencies, file_node_id, sink,
                           content=content)


def process_publish(repo_id: str, file_info, identity, file_node_id: str,
                    sink: IngestSink, content: str = "") -> None:
    """Publish-side package identity."""
    emit_publish_claims(repo_id, file_info, identity, file_node_id, sink,
                        content=content)


def process_config(repo_id: str, file_info, config_result, file_node_id: str,
                   sink: IngestSink) -> None:
    for entry in config_result.entries:
        if not entry.key:
            continue
        redacted = redact(entry.key, entry.value)
        node = create_config_node(repo_id, file_info.path, entry.key, redacted)
        if sink.add_node(node):
            sink.add_edge(create_declares_edge(repo_id, file_node_id, node.id, "config"))
    emit_config_claims(repo_id, file_info, config_result, file_node_id, sink)


def process_docker(repo_id: str, file_info, docker_resources, file_node_id: str,
                   sink: IngestSink) -> None:
    node_ids: dict[str, str] = {}
    for resource in docker_resources:
        if not resource.name:
            continue
        node = create_docker_node(
            repo_id, file_info.path, resource.name, resource.type,
            resource.image or "", resource.ports,
        )
        if resource.type == "service":
            node_ids[resource.name] = node.id
        if sink.add_node(node):
            sink.add_edge(create_declares_edge(
                repo_id, file_node_id, node.id, "docker resource",
            ))
    emit_compose_claims(repo_id, file_info, docker_resources, node_ids, sink)


def process_k8s(repo_id: str, file_info, k8s_resources, file_node_id: str,
                sink: IngestSink) -> None:
    node_ids: dict[str, str] = {}
    for resource in k8s_resources:
        if not resource.name or not resource.kind:
            continue
        node = create_k8s_node(
            repo_id, file_info.path, resource.kind, resource.name,
            resource.namespace or "default", resource.api_version or "",
        )
        node_ids[f"{resource.kind}/{resource.name}"] = node.id
        if sink.add_node(node):
            sink.add_edge(create_declares_edge(
                repo_id, file_node_id, node.id, "k8s resource",
            ))
    emit_k8s_claims(repo_id, file_info, k8s_resources, node_ids, sink)


def process_iac(repo_id: str, file_info, iac_resources, file_node_id: str,
                sink: IngestSink) -> None:
    """Terraform/Kustomize/ECS resources."""
    node_ids: dict[str, str] = {}
    for resource in iac_resources:
        if not resource.block_type:
            continue
        node = create_iac_node(repo_id, file_info.path, resource)
        node_ids[resource.address] = node.id
        if sink.add_node(node):
            sink.add_edge(create_declares_edge(
                repo_id, file_node_id, node.id, "iac resource",
            ))
    emit_iac_claims(repo_id, file_info, iac_resources, node_ids, sink)


def process_proto(repo_id: str, file_info, proto, file_node_id: str,
                  sink: IngestSink) -> None:
    """Protobuf service/rpc declarations."""
    emit_proto_claims(repo_id, file_info, proto, file_node_id, sink)


def process_buf(repo_id: str, file_info, buf, file_node_id: str,
                sink: IngestSink) -> None:
    """buf module identity and declared proto dependencies."""
    emit_buf_claims(repo_id, file_info, buf, file_node_id, sink)


def process_graphql(repo_id: str, file_info, parsed, file_node_id: str,
                    sink: IngestSink) -> None:
    """GraphQL SDL and standalone operation documents."""
    emit_graphql_claims(repo_id, file_info, parsed, file_node_id, sink)


def process_gateway(repo_id: str, file_info, rules, file_node_id: str,
                    sink: IngestSink) -> None:
    """Gateway/proxy route tables."""
    from evigraph.services.ingest_claims import emit_gateway_claims
    emit_gateway_claims(repo_id, file_info, rules, file_node_id, sink)


def process_pipeline(repo_id: str, file_info, pipeline, file_node_id: str,
                     sink: IngestSink) -> None:
    """Data-pipeline lineage."""
    from evigraph.services.ingest_claims import emit_pipeline_claims
    emit_pipeline_claims(repo_id, file_info, pipeline, file_node_id, sink)


def process_migration(repo_id: str, file_info, content: str,
                      file_node_id: str, sink: IngestSink) -> None:
    """Schema migrations in non-source files."""
    from evigraph.services.ingest_claims import emit_migration_claims
    emit_migration_claims(repo_id, file_info, content, file_node_id, sink)


def process_mcp_config(repo_id: str, file_info, sites, file_node_id: str,
                       sink: IngestSink) -> None:
    """MCP client configs."""
    from evigraph.services.ingest_claims import emit_mcp_config_claims
    emit_mcp_config_claims(repo_id, file_info, sites, file_node_id, sink)


def process_agent_card(repo_id: str, file_info, card, file_node_id: str,
                       sink: IngestSink) -> None:
    """A2A agent card."""
    from evigraph.services.ingest_claims import emit_agent_card_claims
    emit_agent_card_claims(repo_id, file_info, card, file_node_id, sink)


def process_codeowners(repo_id: str, file_info, rules, file_node_id: str,
                       sink: IngestSink) -> None:
    """CODEOWNERS ownership rules."""
    from evigraph.services.ingest_claims import emit_codeowners_claims
    emit_codeowners_claims(repo_id, file_info, rules, file_node_id, sink)


def process_catalog(repo_id: str, file_info, entities, file_node_id: str,
                    sink: IngestSink) -> None:
    """Backstage catalog entities."""
    from evigraph.services.ingest_claims import emit_catalog_claims
    emit_catalog_claims(repo_id, file_info, entities, file_node_id, sink)


def process_observability(repo_id: str, file_info, identities,
                          file_node_id: str, sink: IngestSink) -> None:
    """Observability service identity."""
    from evigraph.services.ingest_claims import emit_observability_claims
    emit_observability_claims(repo_id, file_info, identities, file_node_id,
                              sink)


def process_asyncapi(repo_id: str, file_info, doc, file_node_id: str,
                     sink: IngestSink) -> None:
    """AsyncAPI channel declarations."""
    emit_asyncapi_claims(repo_id, file_info, doc, file_node_id, sink)


def process_avro(repo_id: str, file_info, schema, file_node_id: str,
                 sink: IngestSink) -> None:
    """Avro value schemas as Schema Registry subject hints."""
    emit_avro_claims(repo_id, file_info, schema, file_node_id, sink)


def process_cron(repo_id: str, file_info, cron_calls, file_node_id: str,
                 sink) -> None:
    """Scheduled HTTP calls become consumer claims.

    Same claim shape as a code call site — the join must not care whether
    the caller is Python or a crontab line — with the trigger riding along
    so the edge downstream says "at 03:00", not "always".
    """
    from evigraph.services.claims import CONSUMES, ContractClaim, http_consumes_key
    from evigraph.services.ingest_claims import add_claim
    from evigraph.services.http_call_url import classify_url
    from evigraph.utils.canonical import canonicalize_path_template

    for call in cron_calls:
        parsed = classify_url(call.url)
        if parsed is None:
            continue
        _host, hint, hint_source, path, attrs = parsed
        attrs.update({"source": "crontab", "schedule": call.schedule,
                      "client": "cron"})
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="http", direction=CONSUMES,
            key=http_consumes_key(call.method,
                                  canonicalize_path_template(path)),
            service_hint=hint, hint_source=hint_source,
            evidence=[f"{file_info.path}:{call.line}"],
            subject=f"cron/{call.schedule}", attrs=attrs,
        ), file_node_id, sink)


def process_iac_units(repo_id: str, file_info, units, file_node_id: str,
                      sink) -> None:
    """Runtime units from Nomad/systemd/Ansible/Pulumi become claims.

    Same rules as compose, because they say the same things: the unit's
    name is a service identity, and an env value whose host names another
    unit is a declared dependency. Values pass through redact() first —
    a systemd Environment= line holds secrets exactly as often as a
    compose file does.
    """
    from evigraph.services.claims import (
        CONSUMES, PROVIDES, ContractClaim, svcname_key,
    )
    from evigraph.services.ingest_claims import _SERVICE_HOST_CHARS, add_claim
    from evigraph.services.redaction import redact

    for unit in units:
        evidence = [f"{file_info.path}:{unit.line or 1}"]
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="svcname", direction=PROVIDES,
            key=svcname_key(unit.source, unit.name), service_hint=unit.name,
            hint_source="config", evidence=evidence,
            subject=f"{unit.source}/{unit.name}",
            attrs={"source": unit.source, "image": unit.image},
        ), file_node_id, sink)
        for env_key, env_value in sorted(unit.env.items()):
            redacted = redact(env_key, str(env_value))
            host = (redacted.value_host or "").split(":")[0].lower()
            if host and set(host) <= _SERVICE_HOST_CHARS:
                add_claim(repo_id, ContractClaim(
                    repo_id=repo_id, kind="svcname", direction=CONSUMES,
                    key=svcname_key(unit.source, host), service_hint=host,
                    hint_source="config", evidence=evidence,
                    subject=f"{unit.name}/env/{env_key}",
                    attrs={"via": "env_host", "env_key": env_key,
                           "from": unit.name},
                ), file_node_id, sink)


def process_openapi(repo_id: str, file_info, operations, file_node_id: str,
                    sink) -> None:
    """Declared operations become UNMATCHABLE claims.

    matchable=False is the whole design: the claim is recorded so the
    reconciliation can diff declared against observed, and it can never
    join — a contract minted from a spec would assert an endpoint exists
    because a document says so.
    """
    from evigraph.services.claims import PROVIDES, ContractClaim, http_provides_key
    from evigraph.services.ingest_claims import add_claim

    for op in operations:
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="http", direction=PROVIDES,
            key=http_provides_key(op.method, op.path),
            # provenance="spec" is what makes the claim unmatchable: a
            # spec's statement is a promise, not an observation, and the
            # matchable property withholds promises from the join.
            hint_source="none", provenance="spec",
            evidence=[f"{file_info.path}:{op.line}"],
            subject=f"openapi/{op.method}:{op.path}",
            attrs={"source": "openapi", "declared": True,
                   "spec_title": op.title},
        ), file_node_id, sink)
