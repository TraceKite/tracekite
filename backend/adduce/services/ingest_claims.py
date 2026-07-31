"""Claim emission during ingestion (design §4; signals: svcname/image/route/http).

Every claim node gets an EVIDENCED_BY edge to the code/config node that made
the statement, so review queues and file-entry impact can explain themselves.
"""

import logging
import os
import re

from adduce.models.graph_models import GraphEdge
from adduce.services.claims import (
    CONSUMES, PROVIDES, ContractClaim, a2a_op_key, claim_to_node, config_key,
    dataset_key, graphql_operation_key, grpc_operation_key, http_consumes_key,
    http_provides_key, image_ref_key, is_generic_name, is_internal_lib,
    is_unrendered_template, lib_key, mcp_op_key, route_key, svcname_key,
    team_key, topic_key,
)
from adduce.parsers.graphql_parser import DEFAULT_ROOTS, extract_gql_tags

logger = logging.getLogger(__name__)
from adduce.services.grpc_extractor import extract_grpc_sites
from adduce.services.file_classifier import classify
from adduce.utils.evidence import evidence_path
from adduce.services.env_extractor import (
    extract_env_reads, extract_shell_interpolations, looks_like_endpoint_var,
    shell_default,
)
from adduce.services.http_call_extractor import (
    extract_feign_clients, extract_http_calls,
    extract_webhook_registrations,
)
from adduce.services.ingest_source import IngestSink
from adduce.services.redaction import redact
from adduce.services.claim_sink import add_claim  # noqa: F401 (re-export)
from adduce.services.ingest_config_defs import (
    emit_config_object as _emit_config_object,
    emit_env_binding as _emit_env_binding,
    emit_helm_values as _emit_helm_values,
)

_SERVICE_HOST_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-_")


def emit_source_claims(repo_id: str, file_info, content: str,
                       endpoint_records: list[dict], file_node_id: str,
                       sink: IngestSink) -> None:
    # Source files get the header check too: `// Code generated ... DO NOT EDIT`
    # is the only reliable marker for a stub that lives outside a gen/ folder.
    provenance = classify(file_info.path, content).reason

    lines = content.split("\n") if content else []
    for record in endpoint_records:
        attrs = {"source": "annotation",
                 "framework": record.get("framework") or ""}
        if attrs["framework"] in ("websocket", "sse"):
            # A channel contract joins like any route; the channel is what
            # a consumer needs to know before depending on it.
            attrs["channel"] = attrs["framework"]
        if _endpoint_deprecated(lines, record.get("line") or 0):
            attrs["deprecated"] = True
        claim = ContractClaim(
            repo_id=repo_id, kind="http", direction=PROVIDES,
            key=http_provides_key(record["http_method"], record["path_template"]),
            hint_source="none",
            evidence=[f"{file_info.path}:{record['line'] or 1}"],
            attrs=attrs,
            provenance=provenance,
        )
        add_claim(repo_id, claim, record["node_id"], sink)

    from adduce.services.flag_guards import annotate_flag_guards
    sites = annotate_flag_guards(
        extract_http_calls(file_info.path, content, file_info.language),
        content, file_info.language)
    for site in sites:
        evidence = [f"{file_info.path}:{site.line}"]
        if site.attrs.get("base_url"):
            if site.service_hint:
                add_claim(repo_id, ContractClaim(
                    repo_id=repo_id, kind="svcname", direction=CONSUMES,
                    key=svcname_key("discovery", site.service_hint),
                    service_hint=site.service_hint, hint_source=site.hint_source,
                    evidence=evidence, provenance=provenance,
                    attrs={"client": site.client, "base_url": True},
                ), file_node_id, sink)
            continue
        attrs = {"client": site.client, "raw_url": site.raw_url, **site.attrs}
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="http", direction=CONSUMES,
            key=http_consumes_key(site.method, site.path_template),
            service_hint=site.service_hint, hint_source=site.hint_source,
            evidence=evidence, attrs=attrs, provenance=provenance,
        ), file_node_id, sink)
        if site.service_hint:
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="svcname", direction=CONSUMES,
                key=svcname_key("discovery", site.service_hint),
                service_hint=site.service_hint, hint_source=site.hint_source,
                evidence=evidence, attrs={"client": site.client},
                provenance=provenance,
            ), file_node_id, sink)

    from adduce.parsers.iac_units import extract_iac_services
    from adduce.services.ingest_artifacts import process_iac_units
    iac_units = extract_iac_services(file_info.path, content,
                                     file_info.language)
    if iac_units:
        process_iac_units(repo_id, file_info, iac_units, file_node_id, sink)

    for line, url, deliverer in extract_webhook_registrations(content):
        from adduce.services.http_call_url import classify_url
        parsed = classify_url(url)
        if parsed is None or not parsed[1]:
            # A callback whose host names nothing can join nothing.
            continue
        _host, hint, hint_source, path, url_attrs = parsed
        from adduce.utils.canonical import canonicalize_path_template
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="webhook", direction=CONSUMES,
            key=f"webhook:POST:{canonicalize_path_template(path)}",
            service_hint=hint, hint_source=hint_source,
            evidence=[f"{file_info.path}:{line}"],
            subject=f"webhook/{hint}",
            attrs={"source": "webhook_registration", "deliverer": deliverer,
                   **url_attrs},
            provenance=provenance,
        ), file_node_id, sink)

    if (file_info.language or "").lower() in ("java", "kotlin"):
        for name, line in extract_feign_clients(content):
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="svcname", direction=CONSUMES,
                key=svcname_key("discovery", name), service_hint=name,
                hint_source="config", evidence=[f"{file_info.path}:{line}"],
                attrs={"client": "feign"}, provenance=provenance,
            ), file_node_id, sink)

    emit_grpc_site_claims(repo_id, file_info, content, file_node_id, sink,
                          provenance)
    emit_graphql_client_claims(repo_id, file_info, content, file_node_id, sink,
                               provenance)
    emit_env_read_claims(repo_id, file_info, content, file_node_id, sink,
                         provenance)
    emit_messaging_claims(repo_id, file_info, content, file_node_id, sink,
                          provenance)
    try:
        emit_data_site_claims(repo_id, file_info, content, file_node_id, sink,
                              provenance)
        emit_migration_claims(repo_id, file_info, content, file_node_id, sink,
                              provenance)
    except ImportError:
        pass
    try:
        emit_agent_claims(repo_id, file_info, content, file_node_id, sink,
                          provenance)
    except ImportError:
        pass


def emit_env_read_claims(repo_id: str, file_info, content: str,
                         file_node_id: str, sink: IngestSink,
                         provenance: str = "") -> None:
    """Env vars this file reads — the consumer half R9 joins.

    Scoped to the repo, not the cluster: at extraction time we do not know which
    namespace this code is deployed into. R9 re-scopes on the definition side.
    """
    for read in extract_env_reads(content, file_info.language):
        if read.generic:
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="cfgread", direction=CONSUMES,
            key=config_key(repo_id, read.name),
            hint_source="none", evidence=[f"{file_info.path}:{read.line}"],
            attrs={"env_name": read.name, "source": "code",
                   "endpoint_like": looks_like_endpoint_var(read.name)},
            provenance=provenance,
        ), file_node_id, sink)


# @Deprecated (JVM), [Obsolete] (C#), @deprecated (jsdoc/javadoc) within a few
# lines above a handler mark the endpoint deprecated.
_DEPRECATED_MARK = re.compile(r"@Deprecated\b|\[Obsolete\b|@deprecated\b")


def _endpoint_deprecated(lines: list[str], line: int) -> bool:
    if not line:
        return False
    start = max(0, line - 4)
    return any(_DEPRECATED_MARK.search(text) for text in lines[start:line])


_CONFIG_KEY_ROOTS = {"spring", "server", "eureka", "management", "logging",
                     "zuul", "ribbon", "feign"}


def emit_config_claims(repo_id: str, file_info, config_result, file_node_id: str,
                       sink: IngestSink) -> None:
    stem = _filename_service_stem(file_info.path)
    if stem and any((e.key or "").split(".")[0] in _CONFIG_KEY_ROOTS
                    for e in config_result.entries):
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="svcname", direction=PROVIDES,
            key=svcname_key("discovery", stem), service_hint=stem,
            hint_source="config", evidence=[f"{file_info.path}:1"],
            attrs={"generic": is_generic_name(stem), "source": "config-filename"},
        ), file_node_id, sink)

    if config_result.app_name:
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="svcname", direction=PROVIDES,
            key=svcname_key("discovery", config_result.app_name),
            service_hint=config_result.app_name, hint_source="config",
            evidence=[f"{file_info.path}:{config_result.app_name_line or 1}"],
            attrs={"generic": is_generic_name(config_result.app_name),
                   "source": "spring.application.name"},
        ), file_node_id, sink)

    gateway_hint = _gateway_service_hint(file_info.path, config_result)
    for route in config_result.gateway_routes:
        target = _route_target(route.uri)
        if not target:
            continue
        evidence = [f"{file_info.path}:{route.line or 1}"]
        for prefix in route.path_predicates or ["/"]:
            clean_prefix = prefix[:-3] if prefix.endswith("/**") else prefix
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="route", direction=CONSUMES,
                key=route_key(clean_prefix or "/", target),
                service_hint=gateway_hint, hint_source="gateway_route",
                evidence=evidence,
                attrs={"uri": route.uri, "route_id": route.route_id,
                       "path_prefix": clean_prefix or "/",
                       "strip_prefix": route.strip_prefix,
                       "rewrite_path": route.rewrite_path,
                       "target": target.lower()},
            ), file_node_id, sink)
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="svcname", direction=CONSUMES,
            key=svcname_key("discovery", target), service_hint=target,
            hint_source="gateway_route", evidence=evidence,
            attrs={"via": "gateway_route"},
        ), file_node_id, sink)

    # Spring Cloud Stream bindings: the binding *config* names the
    # destination, so this is the authoritative producer/consumer statement
    # even when the java code only references the binding name.
    from adduce.services.messaging_extractor import extract_stream_bindings
    flat = {e.key: str(e.value) for e in config_result.entries if e.key}
    for binding in extract_stream_bindings(flat):
        if not binding.destination:
            continue
        system = {"rabbit": "amqp"}.get(binding.binder, binding.binder or "kafka")
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="topic",
            direction=PROVIDES if binding.direction == "produces" else CONSUMES,
            key=topic_key(system, binding.destination),
            service_hint=config_result.app_name or None, hint_source="config",
            evidence=[f"{file_info.path}:1"],
            attrs={"source": "spring-cloud-stream", "system": system,
                   "binding": binding.binding_name},
        ), file_node_id, sink)


def emit_compose_claims(repo_id: str, file_info, resources, node_ids: dict,
                        sink: IngestSink) -> None:
    for resource in resources:
        if resource.type != "service":
            continue
        scope = (resource.project or repo_id).lower()
        evidence_node = node_ids.get(resource.name)
        if evidence_node is None:
            continue
        evidence = [f"{file_info.path}:{resource.line or 1}"]
        attrs = {"generic": is_generic_name(resource.name), "source": "compose"}
        if resource.build_context:
            attrs["build_context"] = resource.build_context
            build_line = (getattr(resource, "entry_lines", {}) or {}).get("build")
            if build_line:
                # The line a BUILT_FROM edge should cite: the context entry
                # is the fact; the header only declares the service.
                attrs["build_line"] = build_line
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="svcname", direction=PROVIDES,
            key=svcname_key(scope, resource.name), service_hint=resource.name,
            hint_source="config", evidence=evidence, attrs=attrs,
        ), evidence_node, sink)

        if resource.image:
            image_ref, tag = _split_image(resource.image)
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="image", direction=PROVIDES,
                key=image_ref, evidence=evidence,
                attrs={"tag": tag, "compose_service": resource.name,
                       "build_context": resource.build_context or ""},
            ), evidence_node, sink)

        # `subject` disambiguates: when a service both depends_on x AND names
        # x in an env var, the two consumes claims share (kind, direction,
        # key, evidence path) and without a subject the env_host one is
        # silently dropped — losing the corroborating r1 signal exactly when
        # it corroborates (found by the calibration harness).
        entry_lines = getattr(resource, "entry_lines", {}) or {}

        def cite(entry_key: str) -> list[str]:
            # The line asserting THIS entry; the service header only as a
            # fallback. Claim ids hash the evidence path, never the line.
            line = entry_lines.get(entry_key) or resource.line or 1
            return [f"{file_info.path}:{line}"]

        for dep in list(resource.depends_on) + list(resource.links):
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="svcname", direction=CONSUMES,
                key=svcname_key(scope, dep), service_hint=dep,
                hint_source="config", evidence=cite(f"dep:{dep}"),
                subject=f"{resource.name}/dep/{dep}",
                attrs={"via": "depends_on", "from": resource.name},
            ), evidence_node, sink)

        for env_key, env_value in resource.env_pairs.items():
            via = "env_host"
            redacted = redact(env_key, env_value)
            if not redacted.value_host:
                # `DB_HOST=${DB_HOST:-platform-db}` declares a default that
                # runs unless overridden. Only for keys whose NAME says they
                # carry a network target: `DB_USER=${DB_USER:-postgres}` has
                # a host-shaped default that is a username, and joining it
                # to a service called postgres is the wrong-merge the design
                # forbids.
                fallback = (shell_default(env_value)
                            if looks_like_endpoint_var(env_key) else None)
                if fallback:
                    redacted = redact(env_key, fallback)
                    via = "env_host_default"
                    if not redacted.value_host:
                        # A `*_HOST` default is usually a bare service name,
                        # which redact() does not read as a host because it
                        # only parses URLs. Require a letter so `PORT:-5432`
                        # cannot become a hostname. Junk defaults survive
                        # this and still produce nothing: the edge needs a
                        # service of that name to exist, so the join is the
                        # last and strongest gate.
                        bare = fallback.strip().lower()
                        if any(c.isalpha() for c in bare) and \
                                set(bare) <= _SERVICE_HOST_CHARS:
                            redacted = redacted.__class__(
                                **{**vars(redacted), "value_host": bare})
            host = (redacted.value_host or "").split(":")[0].lower()
            if host and set(host) <= _SERVICE_HOST_CHARS:
                add_claim(repo_id, ContractClaim(
                    repo_id=repo_id, kind="svcname", direction=CONSUMES,
                    key=svcname_key(scope, host), service_hint=host,
                    hint_source="config", evidence=cite(f"env:{env_key}"),
                    subject=f"{resource.name}/env/{env_key}",
                    attrs={"via": via, "env_key": env_key,
                           "from": resource.name,
                           "defaulted": via == "env_host_default"},
                ), evidence_node, sink)


def _filename_service_stem(path: str) -> str | None:
    base = os.path.basename(path)
    stem, _, ext = base.rpartition(".")
    if ext not in ("yml", "yaml", "properties") or not stem:
        return None
    stem = stem.lower()
    if stem.startswith(("application", "bootstrap", "docker-compose", "compose")):
        return None
    if set(stem) <= _SERVICE_HOST_CHARS:
        return stem
    return None


def _gateway_service_hint(path: str, config_result) -> str | None:
    if config_result.app_name:
        return config_result.app_name
    stem = os.path.basename(path).rsplit(".", 1)[0]
    if stem.startswith("application") or stem.startswith("bootstrap"):
        return None
    if stem and set(stem.lower()) <= _SERVICE_HOST_CHARS:
        return stem
    return None


def _route_target(uri: str) -> str | None:
    if uri.startswith("lb://"):
        return uri[5:].split("/")[0]
    if uri.startswith(("http://", "https://")):
        host = uri.split("//", 1)[1].split("/")[0].split(":")[0]
        if host and "." not in host:
            return host
    return None


def _split_image(image: str) -> tuple[str, str]:
    if "@" in image:
        ref, _, digest = image.partition("@")
        return ref, digest
    head, _, tail = image.rpartition(":")
    if head and "/" not in tail:
        return head, tail
    return image, ""


# --- Kubernetes --------------------------------------------------------------

_WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob",
                   "ReplicaSet", "Pod", "Rollout"}


def emit_k8s_claims(repo_id: str, file_info, resources, node_ids: dict,
                    sink: IngestSink) -> None:
    """Claims from Kubernetes manifests.

    Namespace is the scope: two clusters can both run `api`, and merging them
    on name alone is exactly the wrong-merge the design forbids.
    """
    # Traefik Middleware stripPrefix objects referenced by IngressRoute rules
    # in the same manifest set.
    strip_middlewares = {r.name for r in resources
                         if r.kind == "Middleware" and r.strip_prefixes}

    for resource in resources:
        evidence_node = node_ids.get(f"{resource.kind}/{resource.name}")
        if evidence_node is None:
            continue
        evidence = [f"{file_info.path}:{resource.line or 1}"]
        scope = (resource.namespace or "default").lower()
        environment = _environment_of(file_info.path, resource)

        if resource.kind in _WORKLOAD_KINDS:
            _emit_workload(repo_id, resource, scope, environment, evidence,
                           evidence_node, sink)
        elif resource.kind == "Service":
            _emit_k8s_service(repo_id, resource, scope, environment, evidence,
                              evidence_node, sink)
        elif resource.kind in ("ConfigMap", "Secret"):
            _emit_config_object(repo_id, resource, scope, environment, evidence,
                                evidence_node, sink)
        elif resource.kind in ("NetworkPolicy", "AuthorizationPolicy"):
            _emit_policy(repo_id, resource, scope, environment, evidence,
                         evidence_node, sink)
        elif resource.kind in ("Application", "ApplicationSet", "Kustomization",
                               "HelmRelease"):
            _emit_gitops(repo_id, resource, scope, evidence, evidence_node, sink)
        elif resource.kind == "HelmValues":
            _emit_helm_values(repo_id, resource, environment, evidence,
                              evidence_node, sink)
        elif resource.kind in ("ScaledObject", "ScaledJob"):
            _emit_keda(repo_id, resource, environment, evidence,
                       evidence_node, sink)
        elif resource.kind == "Ingress":
            _emit_ingress_routes(repo_id, resource, environment, evidence,
                                 evidence_node, sink)
        elif resource.kind in ("HTTPRoute", "GRPCRoute", "VirtualService",
                               "IngressRoute"):
            _emit_crd_routes(repo_id, resource, environment, evidence,
                             evidence_node, sink, strip_middlewares)


def _emit_workload(repo_id, resource, scope, environment, evidence,
                   evidence_node, sink) -> None:
    name = resource.service_name_hint
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=svcname_key(scope, name), service_hint=name, hint_source="config",
        evidence=evidence, env_scope=environment,
        subject=f"{resource.kind}/{resource.name}",
        attrs={"source": "k8s", "kind": resource.kind,
               "namespace": resource.namespace, "workload": resource.name,
               "generic": is_generic_name(name),
               "pod_labels": _label_signature(resource.pod_labels)},
    ), evidence_node, sink)

    for container in resource.containers:
        if container.image:
            # Cite the `image:` line, not the workload header. Claim ids hash
            # the evidence PATH only, so a better line never churns identity.
            image_ev = evidence
            if getattr(container, "image_line", 0) and evidence:
                image_ev = [f"{evidence_path(evidence[0])}:{container.image_line}"]
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="image", direction=PROVIDES,
                key=image_ref_key(container.image), evidence=image_ev,
                env_scope=environment,
                subject=f"{resource.kind}/{resource.name}/{container.name}",
                attrs={"source": "k8s", "raw_image": container.image,
                       "workload": resource.name, "service": name,
                       "namespace": resource.namespace},
            ), evidence_node, sink)

    for binding in resource.all_env:
        _emit_env_binding(repo_id, resource, name, scope, environment, evidence,
                          evidence_node, binding, sink)


def _emit_k8s_service(repo_id, resource, scope, environment, evidence,
                      evidence_node, sink) -> None:
    """Service object: the name other workloads resolve via cluster DNS."""
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=svcname_key(scope, resource.name), service_hint=resource.name,
        hint_source="discovery", evidence=evidence, env_scope=environment,
        subject=f"Service/{resource.name}",
        attrs={"source": "k8s_service", "namespace": resource.namespace,
               "selector": _label_signature(resource.selector),
               "ports": [p.port for p in resource.service_ports if p.port],
               "service_type": resource.service_type,
               "external_name": resource.external_name,
               "generic": is_generic_name(resource.name)},
    ), evidence_node, sink)


_REWRITE_ANNOTATION = "nginx.ingress.kubernetes.io/rewrite-target"
_REGEX_ANNOTATION = "nginx.ingress.kubernetes.io/use-regex"


def _emit_route_claim(repo_id, resource, environment, evidence, evidence_node,
                      sink, *, prefix, target, source, strip=0, rewrite="",
                      host="", weight=None, regex=False) -> None:
    if not target:
        sink.count_claim("gateway_dynamic_target")
        return
    attrs = {"target": target.lower(), "path_prefix": prefix or "/",
             "strip_prefix": int(strip), "rewrite_path": rewrite or "",
             "gateway_kind": source, "host": host or "",
             "namespace": resource.namespace}
    if weight is not None:
        attrs["weight"] = weight
    if regex:
        attrs["regex"] = True
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="route", direction=CONSUMES,
        key=route_key(prefix or "/", target),
        service_hint=resource.name, hint_source="gateway_route",
        evidence=evidence, env_scope=environment,
        subject=f"{resource.kind}/{resource.name}/{host}/{prefix}",
        attrs=attrs,
    ), evidence_node, sink)
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=CONSUMES,
        key=svcname_key((resource.namespace or "default").lower(), target),
        service_hint=target, hint_source="gateway_route", evidence=evidence,
        subject=f"{resource.kind}/{resource.name}/{target}",
        attrs={"via": source}, env_scope=environment,
    ), evidence_node, sink)


def _emit_ingress_routes(repo_id, resource, environment, evidence,
                         evidence_node, sink) -> None:
    """k8s Ingress incl. ingress-nginx rewrite annotations."""
    annotations = resource.annotations or {}
    rewrite = str(annotations.get(_REWRITE_ANNOTATION) or "")
    regex = str(annotations.get(_REGEX_ANNOTATION, "")).lower() == "true"
    for rule in resource.ingress_rules:
        _emit_route_claim(
            repo_id, resource, environment, evidence, evidence_node, sink,
            prefix=rule.path or "/", target=rule.backend_service,
            source="k8s_ingress", strip=1 if rewrite in ("/", "/$1") else 0,
            rewrite=rewrite, host=rule.host, regex=regex,
        )


def _emit_crd_routes(repo_id, resource, environment, evidence, evidence_node,
                     sink, strip_middlewares) -> None:
    """HTTPRoute/GRPCRoute, Istio VirtualService, Traefik
    IngressRoute — one uniform route statement each."""
    source = {"HTTPRoute": "gateway_api", "GRPCRoute": "gateway_api",
              "VirtualService": "istio", "IngressRoute": "traefik"}[resource.kind]
    for binding in resource.route_bindings:
        strip = binding.strip_prefix or bool(
            set(binding.middlewares) & strip_middlewares)
        _emit_route_claim(
            repo_id, resource, environment, evidence, evidence_node, sink,
            prefix=binding.path, target=binding.backend_service, source=source,
            strip=1 if strip else 0, rewrite=binding.rewrite_to,
            host=binding.hosts[0] if binding.hosts else "",
            weight=binding.weight, regex=binding.path_type == "regex",
        )


def _emit_gitops(repo_id, resource, scope, evidence, evidence_node, sink) -> None:
    """ArgoCD/Flux source binding — a declared repo->deployment edge."""
    if not resource.source_repo:
        return
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="declared", direction=PROVIDES,
        key=f"gitops:{resource.name}", service_hint=resource.name,
        hint_source="config", evidence=evidence,
        subject=f"{resource.kind}/{resource.name}",
        env_scope=resource.dest_namespace or "",
        attrs={"source": "gitops", "kind": resource.kind,
               "source_repo": resource.source_repo,
               "source_path": resource.source_path,
               "revision": resource.source_revision,
               "dest_namespace": resource.dest_namespace},
    ), evidence_node, sink)


def _label_signature(labels: dict) -> list[str]:
    """Stable ``k=v`` list so selectors can be matched as a native list prop."""
    return sorted(f"{k}={v}" for k, v in (labels or {}).items())


ENVIRONMENT_TOKENS = ("prod", "production", "staging", "stage", "qa", "uat",
                      "dev", "development", "test", "sandbox", "preprod",
                      "perf", "canary")

# Directory names that mean "source tree", not "environment". `src/test/` is the
# standard Maven/Gradle test-fixture path and `internal/dev/` is a tooling
# directory; reading either as a deployment environment poisons R9's index,
# because a fixture's localhost URL then contradicts the real manifest and the
# ambiguity guard suppresses a genuine edge.
_SOURCE_TREE_PARENTS = ("src", "test", "tests", "internal", "pkg", "cmd",
                        "lib", "app", "main", "java", "kotlin", "resources",
                        "node_modules", "vendor", "target", "build")

# Path segments that mark a real deployment-manifest tree.
_DEPLOY_PARENTS = ("overlays", "environments", "envs", "env", "deploy",
                   "deployment", "deployments", "k8s", "kubernetes", "manifests",
                   "helm", "charts", "infra", "infrastructure", "terraform",
                   "argocd", "flux", "gitops", "clusters", "config")


def _environment_of(path: str, resource) -> str:
    """Environment a manifest targets.

    An environment token only counts inside a deployment tree — `overlays/prod/`
    yes, `src/test/resources/` no. Declared annotations and the namespace are
    trusted directly, since those are unambiguous statements rather than
    filename inference.
    """
    annotations = getattr(resource, "annotations", {}) or {}
    if declared := annotations.get("environment"):
        return str(declared).lower()

    segments = [s for s in path.lower().replace("\\", "/").split("/") if s]

    # A `values-prod.yaml` filename names its environment on its own, wherever
    # the chart happens to live.
    if segments and (token := _values_overlay_token(segments[-1])):
        return token

    for index, segment in enumerate(segments[:-1] if len(segments) > 1 else segments):
        token = _matching_token(segment)
        if not token:
            continue
        parent = segments[index - 1] if index else ""
        if parent in _SOURCE_TREE_PARENTS:
            continue                       # src/test/... is fixtures, not an env
        if index == 0 or parent in _DEPLOY_PARENTS or _matching_token(parent):
            return token
    namespace = (getattr(resource, "namespace", "") or "").lower()
    return namespace if namespace and namespace != "default" else ""


def _values_overlay_token(file_name: str) -> str:
    """Environment named by a Helm values overlay filename, if any."""
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    for separator in ("-", "_", "."):
        prefix = f"values{separator}"
        if stem.startswith(prefix) and stem[len(prefix):] in ENVIRONMENT_TOKENS:
            return stem[len(prefix):]
    return ""


def _matching_token(segment: str) -> str:
    """The environment a path segment names, if any.

    Matches whole segments and `values-prod.yaml`-style suffixes, but never a
    substring of an unrelated word — `production-service` is a service name.
    """
    stem = segment.rsplit(".", 1)[0] if "." in segment else segment
    if stem in ENVIRONMENT_TOKENS:
        return stem
    for token in ENVIRONMENT_TOKENS:
        if stem.startswith(("values-", "values_")) and stem.split("-", 1)[-1] == token:
            return token
        if stem in (f"values.{token}", f"{token}-values", f"{token}.values"):
            return token
    return ""


# --- Terraform / Kustomize / ECS ---------------------------------------------

# Data categories stay deferred until R10 consumes them; messaging
# categories became live claims when R6 landed.
_DEFERRED_CATEGORIES = {"search", "index", "database", "cache", "bucket",
                        "table"}

_MESSAGING_CATEGORIES = {"queue", "topic", "stream", "eventbus",
                         "subscription", "event_source"}

# Which messaging system a Terraform resource type provisions — the prefix of
# the topic rendezvous key its claims join at.
_IAC_MESSAGING_SYSTEMS = {
    "aws_sqs_queue": "sqs", "aws_sns_topic": "sns",
    "confluent_kafka_topic": "kafka", "aws_kinesis_stream": "kinesis",
    "aws_cloudwatch_event_bus": "eventbus",
    "google_pubsub_topic": "pubsub", "google_pubsub_subscription": "pubsub",
    "azurerm_servicebus_queue": "servicebus",
    "azurerm_servicebus_topic": "servicebus", "azurerm_eventhub": "eventhub",
}


def emit_iac_claims(repo_id: str, file_info, resources, node_ids: dict,
                    sink: IngestSink) -> None:
    # `aws_sns_topic.order_events` in a subscription names the resource LABEL;
    # the provisioned topic is its `name` attribute. Same-file references
    # resolve through this map so both claims land on one rendezvous.
    iac_names = {}
    for r in resources:
        if r.block_type == "resource" and r.resource_type and r.name:
            attributes = r.attributes or {}
            iac_names[f"{r.resource_type}.{r.name}"] = str(
                attributes.get("name") or attributes.get("topic_name") or r.name)

    for resource in resources:
        evidence_node = node_ids.get(resource.address)
        if evidence_node is None:
            continue
        evidence = [f"{file_info.path}:{resource.line or 1}"]
        environment = _iac_environment(file_info.path, resource)

        if resource.block_type == "ecs_container":
            _emit_ecs_container(repo_id, resource, environment, evidence,
                                evidence_node, sink)
        elif resource.category == "service":
            _emit_managed_service(repo_id, resource, environment, evidence,
                                  evidence_node, sink)
        elif resource.category in _MESSAGING_CATEGORIES:
            _emit_iac_messaging(repo_id, resource, environment, evidence,
                                evidence_node, sink, iac_names)
        elif resource.category in ("gw_route", "lb_rule"):
            _emit_iac_gateway_route(repo_id, resource, resources, environment,
                                    evidence, evidence_node, sink)
        elif resource.category in _DEFERRED_CATEGORIES:
            sink.count_claim("iac_deferred")


def _emit_ecs_container(repo_id, resource, environment, evidence,
                        evidence_node, sink) -> None:
    """ECS task definition: a deployable with an image and env."""
    name = resource.name or resource.attributes.get("family", "")
    if not name:
        return
    scope = (environment or "ecs").lower()
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=svcname_key(scope, name), service_hint=name, hint_source="config",
        evidence=evidence, env_scope=environment,
        subject=f"ecs/{resource.name}",
        attrs={"source": "ecs", "family": resource.attributes.get("family", ""),
               "generic": is_generic_name(name)},
    ), evidence_node, sink)

    if image := resource.attributes.get("image"):
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="image", direction=PROVIDES,
            key=image_ref_key(image), evidence=evidence, env_scope=environment,
            subject=f"ecs/{resource.name}",
            attrs={"source": "ecs", "raw_image": image, "service": name},
        ), evidence_node, sink)

    for key, value in resource.attributes.items():
        if not key.startswith("env:"):
            continue
        env_name = key[len("env:"):]
        redacted = redact(env_name, value)
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="cfgdef", direction=PROVIDES,
            key=config_key(scope, env_name), hint_source="config",
            evidence=evidence, env_scope=environment,
            subject=f"ecs/{resource.name}",
            attrs={"source": "k8s_env", "env_name": env_name,
                   "binding": "literal", "service": name,
                   "namespace": scope,
                   "endpoint_like": looks_like_endpoint_var(env_name),
                   "value_class": redacted.value_class,
                   "value_host": redacted.value_host or "",
                   "value_port": redacted.value_port or 0,
                   "value_scheme": redacted.value_scheme or "",
                   "value_hmac": redacted.value_hmac},
        ), evidence_node, sink)


def _emit_managed_service(repo_id, resource, environment, evidence,
                          evidence_node, sink) -> None:
    """A Terraform-declared deployable (ECS service, Cloud Run)."""
    name = resource.attributes.get("name") or resource.name
    if not name:
        return
    scope = (environment or "tf").lower()
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=svcname_key(scope, name), service_hint=name, hint_source="config",
        evidence=evidence, env_scope=environment,
        subject=resource.address,
        attrs={"source": "terraform", "resource_type": resource.resource_type,
               "generic": is_generic_name(name)},
    ), evidence_node, sink)


def _iac_environment(path: str, resource) -> str:
    if declared := (resource.attributes or {}).get("environment"):
        return str(declared).lower()
    return _environment_of(path, resource)


# --- gRPC / protobuf ---------------------------------------------------------

def emit_proto_claims(repo_id: str, file_info, proto, file_node_id: str,
                      sink: IngestSink) -> None:
    """Every declared rpc is a globally-keyed contract operation."""
    provenance = classify(file_info.path).reason
    for service in proto.services:
        for rpc in service.rpcs:
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="grpcop", direction=PROVIDES,
                key=grpc_operation_key(service.package, service.name, rpc.name),
                service_hint=service.name, hint_source="none",
                evidence=[f"{file_info.path}:{rpc.line or service.line or 1}"],
                subject=f"proto/{service.full_name}/{rpc.name}",
                provenance=provenance,
                attrs={"source": str((proto.options or {}).get("protocol")
                                     or "proto"),
                       "package": service.package,
                       "service": service.full_name, "rpc": rpc.name,
                       "input_type": rpc.input_type,
                       "output_type": rpc.output_type,
                       "streaming": rpc.streaming,
                       "go_package": proto.go_package,
                       "java_package": proto.java_package,
                       # The proto's own HTTP binding: R14 joins this
                       # operation to its HttpContract on it.
                       "http_method": rpc.http_method,
                       "http_template": rpc.http_path},
            ), file_node_id, sink)


def emit_buf_claims(repo_id: str, file_info, buf, file_node_id: str,
                    sink: IngestSink) -> None:
    """buf module identity and declared cross-repo proto deps."""
    provenance = classify(file_info.path).reason
    if buf.name:
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="declared", direction=PROVIDES,
            key=f"buf:{buf.name}", service_hint=buf.name.rsplit("/", 1)[-1],
            hint_source="config", evidence=[f"{file_info.path}:1"],
            subject=f"buf/{buf.name}", provenance=provenance,
            attrs={"source": "buf_module", "module": buf.name},
        ), file_node_id, sink)
    for dep in buf.deps:
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="declared", direction=CONSUMES,
            key=f"buf:{dep}", service_hint=dep.rsplit("/", 1)[-1],
            hint_source="config", evidence=[f"{file_info.path}:1"],
            subject=f"buf-dep/{dep}", provenance=provenance,
            attrs={"source": "buf_dep", "module": dep},
        ), file_node_id, sink)


def emit_grpc_site_claims(repo_id: str, file_info, content: str,
                          file_node_id: str, sink: IngestSink,
                          provenance: str = "") -> None:
    """Server impls and client stubs — the two halves R5 joins."""
    for site in extract_grpc_sites(content, file_info.language):
        direction = PROVIDES if site.role == "provides" else CONSUMES
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="grpcstub", direction=direction,
            key=site.service_name, service_hint=site.service_name,
            hint_source="none", evidence=[f"{file_info.path}:{site.line}"],
            subject=f"grpc/{site.role}/{site.service_name}",
            provenance=provenance,
            attrs={"source": "grpc_code", "service": site.service_name,
                   "framework": site.framework, "generated_name": site.raw},
        ), file_node_id, sink)


# --- GraphQL -------------------------------------------------------------

def emit_graphql_claims(repo_id: str, file_info, parsed, file_node_id: str,
                        sink: IngestSink) -> None:
    """SDL root fields provide; client operations consume."""
    provenance = classify(file_info.path).reason
    schema = parsed.get("schema")
    operations = parsed.get("operations") or []

    if schema is not None:
        for field in schema.root_fields:
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="graphqlop", direction=PROVIDES,
                key=graphql_operation_key(field.parent_type, field.name),
                service_hint=field.parent_type, hint_source="none",
                evidence=[f"{file_info.path}:{field.line or 1}"],
                subject=f"graphql/{field.parent_type}/{field.name}",
                provenance=provenance,
                attrs={"source": "graphql_sdl", "parent_type": field.parent_type,
                       "field": field.name, "return_type": field.return_type,
                       "federated": schema.is_federated},
            ), file_node_id, sink)

    # A file holding only operations (no SDL root fields) is the client side.
    if schema is not None and schema.root_fields:
        return
    _emit_graphql_operations(repo_id, file_info, operations, file_node_id,
                             sink, provenance)


def emit_graphql_client_claims(repo_id: str, file_info, content: str,
                               file_node_id: str, sink: IngestSink,
                               provenance: str = "") -> None:
    """gql`...` tags inside JS/TS source."""
    language = (file_info.language or "").lower()
    if language in ("javascript", "typescript"):
        _emit_graphql_operations(repo_id, file_info, extract_gql_tags(content),
                                 file_node_id, sink, provenance)
    emit_graphql_server_claims(repo_id, file_info, content, file_node_id,
                               sink, provenance)


# Code-first GraphQL servers: no SDL exists, the resolver class IS
# the schema. NestJS decorators and graphene/strawberry Query classes name
# root fields, which join client operations at the same Type.field rendezvous
# an SDL would.
_NEST_GQL_MARKER = re.compile(r"@Resolver\s*\(")
_NEST_GQL_FIELD = re.compile(
    r"@(Query|Mutation|Subscription)\s*\(([^)]*)\)[\s\r\n]*"
    r"(?:async\s+)?(\w+)\s*\(", re.DOTALL)
_NEST_GQL_NAME = re.compile(r"name\s*:\s*['\"](\w+)['\"]")
_GRAPHENE_CLASS = re.compile(
    r"^class\s+(Query|Mutation)\s*\(([^)]*ObjectType[^)]*)\)\s*:",
    re.MULTILINE)
_GRAPHENE_FIELD = re.compile(r"^\s{4}(\w+)\s*=\s*graphene\.", re.MULTILINE)
_STRAWBERRY_CLASS = re.compile(
    r"@strawberry\.type[\s\r\n]+class\s+(Query|Mutation)\b")
_STRAWBERRY_FIELD = re.compile(
    r"@strawberry\.(?:field|mutation)[^\n]*[\s\r\n]+"
    r"(?:async\s+)?def\s+(\w+)\s*\(")


def emit_graphql_server_claims(repo_id: str, file_info, content: str,
                               file_node_id: str, sink: IngestSink,
                               provenance: str = "") -> None:
    """Code-first GraphQL root fields as graphqlop provides claims."""
    language = (file_info.language or "").lower()
    fields: list[tuple[str, str]] = []

    if language == "typescript" and _NEST_GQL_MARKER.search(content):
        for match in _NEST_GQL_FIELD.finditer(content):
            kind, args, method = match.groups()
            named = _NEST_GQL_NAME.search(args or "")
            root = {"Query": "Query", "Mutation": "Mutation",
                    "Subscription": "Subscription"}[kind]
            fields.append((root, named.group(1) if named else method))
    elif language == "python":
        for match in _GRAPHENE_CLASS.finditer(content):
            root = match.group(1)
            body = content[match.end():]
            next_class = re.search(r"^class\s", body, re.MULTILINE)
            body = body[:next_class.start()] if next_class else body
            for field_match in _GRAPHENE_FIELD.finditer(body):
                if not field_match.group(1).startswith("resolve_"):
                    fields.append((root, field_match.group(1)))
        for match in _STRAWBERRY_CLASS.finditer(content):
            root = match.group(1)
            body = content[match.end():]
            next_class = re.search(r"^(?:@strawberry\.type\s+)?class\s", body,
                                   re.MULTILINE)
            body = body[:next_class.start()] if next_class else body
            for field_match in _STRAWBERRY_FIELD.finditer(body):
                fields.append((root, field_match.group(1)))

    for root, field_name in dict.fromkeys(fields):
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="graphqlop", direction=PROVIDES,
            key=graphql_operation_key(root, field_name),
            service_hint=root, hint_source="none",
            evidence=[f"{file_info.path}:1"],
            subject=f"gqlsrv/{root}/{field_name}",
            provenance=provenance,
            attrs={"source": "code_first", "root": root,
                   "field": field_name},
        ), file_node_id, sink)


def _emit_graphql_operations(repo_id, file_info, operations, file_node_id,
                             sink, provenance) -> None:
    for operation in operations:
        root_type = DEFAULT_ROOTS.get(operation.operation, "Query")
        for field_name in operation.root_fields:
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="graphqlop", direction=CONSUMES,
                key=graphql_operation_key(root_type, field_name),
                service_hint=root_type, hint_source="none",
                evidence=[f"{file_info.path}:{operation.line or 1}"],
                subject=f"gqlop/{operation.name or 'anon'}/{field_name}",
                provenance=provenance,
                attrs={"source": "graphql_operation",
                       "operation": operation.operation,
                       "operation_name": operation.name,
                       "field": field_name},
            ), file_node_id, sink)


# --- Messaging -----------------------------------------------------------
#
# Topic-claim key namespaces, resolved by R6:
#   kafka:orders            a literal destination — joinable by spelling
#   kafka:env:TOPIC_NAME    destination read from an env var — R6 resolves it
#                           against the env-value index (hmac equality)
#   kafka:cfg:app.topic     destination from a ${...} config placeholder
#   ""                      a variable/expression — stored, never joined
# ':' is safe as a namespace separator because Kafka/SQS/SNS destination names
# cannot contain it.

_CONFIG_PLACEHOLDER = re.compile(r"\$\{([^}:]+)(?::[^}]*)?\}")

_KEDA_SYSTEMS = {"kafka": "kafka", "aws-sqs-queue": "sqs",
                 "rabbitmq": "amqp", "aws-kinesis-stream": "kinesis",
                 "gcp-pubsub": "pubsub", "azure-servicebus": "servicebus",
                 "aws-sqs": "sqs"}


def emit_messaging_claims(repo_id: str, file_info, content: str,
                          file_node_id: str, sink: IngestSink,
                          provenance: str = "") -> None:
    """Producer/consumer sites in source."""
    from adduce.services.messaging_extractor import extract_messaging_sites
    for site in extract_messaging_sites(content, file_info.language):
        attrs = {"system": site.system, "framework": site.framework,
                 "role": site.role, **(site.attrs or {})}
        if site.destination:
            key = topic_key(site.system, site.destination)
        elif site.env_var:
            key = topic_key(site.system, f"env:{site.env_var}")
            attrs["env_var"] = site.env_var
        elif placeholder := _CONFIG_PLACEHOLDER.search(site.raw or ""):
            key = topic_key(site.system, f"cfg:{placeholder.group(1)}")
            attrs["config_ref"] = placeholder.group(1)
        else:
            key = ""            # dynamic: stored for review, never joined
            attrs["dynamic"] = True
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="topic",
            direction=PROVIDES if site.role == "produces" else CONSUMES,
            key=key, hint_source="none",
            evidence=[f"{file_info.path}:{site.line}"],
            subject=f"msg/{site.framework}/{site.role}/{site.raw or key}"[:120],
            provenance=provenance, attrs=attrs,
        ), file_node_id, sink)


def _emit_keda(repo_id, resource, environment, evidence, evidence_node,
               sink) -> None:
    """KEDA trigger = consumption evidence for the scale target."""
    for trigger in resource.triggers:
        system = _KEDA_SYSTEMS.get(trigger.type)
        if system is None:
            continue
        destination = trigger.destination or _queue_url_tail(trigger.queue_url)
        if not destination:
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="topic", direction=CONSUMES,
            key=topic_key(system, destination),
            service_hint=resource.scale_target or None, hint_source="config",
            evidence=evidence, env_scope=environment,
            subject=f"{resource.kind}/{resource.name}/{trigger.type}",
            attrs={"source": "keda", "system": system,
                   "service": resource.scale_target,
                   "consumer_group": trigger.consumer_group,
                   "namespace": resource.namespace},
        ), evidence_node, sink)


def _emit_iac_messaging(repo_id, resource, environment, evidence,
                        evidence_node, sink, iac_names=None) -> None:
    """Terraform-provisioned queues/topics and their wiring.

    A queue resource *declares* the rendezvous (the repo manages it — that is
    not production or consumption). Subscriptions and event source mappings
    are wiring: they say who receives, so they are consumption statements.
    """
    system = _IAC_MESSAGING_SYSTEMS.get(resource.resource_type, "")
    attributes = resource.attributes or {}
    iac_names = iac_names or {}

    def _ref(resource_type: str) -> str:
        label = _reference_tail(resource.references, resource_type)
        return iac_names.get(f"{resource_type}.{label}", label) if label else ""

    if resource.category in ("queue", "topic", "stream", "eventbus"):
        name = str(attributes.get("name") or attributes.get("topic_name")
                   or resource.name)
        if not system or not name:
            return
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="topic", direction=PROVIDES,
            key=topic_key(system, name), hint_source="config",
            evidence=evidence, env_scope=environment, subject=resource.address,
            attrs={"source": "terraform", "system": system, "declares": True,
                   "resource_type": resource.resource_type},
        ), evidence_node, sink)
        return

    if resource.resource_type == "aws_sns_topic_subscription":
        topic = (_arn_tail(str(attributes.get("topic_arn") or ""))
                 or _ref("aws_sns_topic"))
        endpoint = (_arn_tail(str(attributes.get("endpoint") or ""))
                    or _ref("aws_sqs_queue"))
        if not topic or not endpoint:
            return
        # The queue consumes from the topic: SNS->SQS fan-out.
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="topic", direction=CONSUMES,
            key=topic_key("sns", topic), hint_source="config",
            evidence=evidence, env_scope=environment, subject=resource.address,
            attrs={"source": "terraform", "system": "sns",
                   "subscriber_key": topic_key("sqs", endpoint),
                   "fan_out": True},
        ), evidence_node, sink)
        return

    if resource.resource_type == "aws_lambda_event_source_mapping":
        arn = str(attributes.get("event_source_arn") or "")
        source_system = "sqs" if ":sqs:" in arn else (
            "kinesis" if ":kinesis:" in arn else "")
        name = _arn_tail(arn)
        if not name:
            for ref_type, ref_system in (("aws_sqs_queue", "sqs"),
                                         ("aws_kinesis_stream", "kinesis")):
                if tail := _ref(ref_type):
                    name, source_system = tail, ref_system
                    break
        function = (str(attributes.get("function_name") or "")
                    or _reference_tail(resource.references, "aws_lambda_function"))
        if not name or not source_system:
            return
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="topic", direction=CONSUMES,
            key=topic_key(source_system, name),
            service_hint=_arn_tail(function) or None, hint_source="config",
            evidence=evidence, env_scope=environment, subject=resource.address,
            attrs={"source": "terraform", "system": source_system,
                   "service": _arn_tail(function),
                   "event_source_mapping": True},
        ), evidence_node, sink)


def _emit_iac_gateway_route(repo_id, resource, resources, environment,
                            evidence, evidence_node, sink) -> None:
    """AWS API Gateway routes and ALB listener rules.

    A v2 route references an integration; the integration's URI names the
    target (a lambda, an HTTP endpoint, or a load balancer). ALB rules name a
    target group, whose `name` is the best available service hint.
    """
    attributes = resource.attributes or {}

    if resource.category == "gw_route":
        route_expr = str(attributes.get("route_key") or "")
        method, _, path = route_expr.partition(" ")
        if not path:
            method, path = "ANY", route_expr or "/"
        target = ""
        for ref in resource.references or []:
            if ref.startswith("aws_apigatewayv2_integration."):
                label = ref.split(".")[1]
                for other in resources:
                    if (other.resource_type == "aws_apigatewayv2_integration"
                            and other.name == label):
                        target = _integration_target(other.attributes or {},
                                                     other.references or [])
                        break
        if not target:
            sink.count_claim("gateway_dynamic_target")
            return
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="route", direction=CONSUMES,
            key=route_key(path.replace("{proxy+}", ""), target),
            hint_source="gateway_route", evidence=evidence,
            env_scope=environment, subject=resource.address,
            attrs={"target": target.lower(), "path_prefix":
                   path.replace("{proxy+}", "") or "/",
                   "strip_prefix": 0, "rewrite_path": "",
                   "gateway_kind": "aws_apigateway", "method": method},
        ), evidence_node, sink)
        return

    if resource.category == "lb_rule":
        target = _reference_tail(resource.references, "aws_lb_target_group")
        for other in resources:
            if (other.resource_type == "aws_lb_target_group"
                    and other.name == target):
                target = str((other.attributes or {}).get("name") or target)
        paths = [v for k, v in attributes.items()
                 if "path_pattern" in k or k == "values"]
        prefix = str(paths[0]) if paths else "/"
        if not target:
            sink.count_claim("gateway_dynamic_target")
            return
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="route", direction=CONSUMES,
            key=route_key(prefix.rstrip("*"), target),
            hint_source="gateway_route", evidence=evidence,
            env_scope=environment, subject=resource.address,
            attrs={"target": target.lower(),
                   "path_prefix": prefix.rstrip("*") or "/",
                   "strip_prefix": 0, "rewrite_path": "",
                   "gateway_kind": "alb"},
        ), evidence_node, sink)


def _integration_target(attributes: dict, references: list) -> str:
    uri = str(attributes.get("integration_uri") or attributes.get("uri") or "")
    if uri.startswith("http"):
        host = uri.split("//", 1)[1].split("/")[0].split(":")[0]
        return host.split(".")[0]
    if ":lambda:" in uri or "arn:aws:lambda" in uri:
        return _arn_tail(uri.split("functions/")[-1].split("/")[0]
                         if "functions/" in uri else uri)
    for ref in references:
        if ref.startswith("aws_lambda_function."):
            return ref.split(".")[1]
    return ""


def emit_asyncapi_claims(repo_id: str, file_info, doc, file_node_id: str,
                         sink: IngestSink) -> None:
    """AsyncAPI channels: the messaging analogue of an SDL."""
    known = {"kafka", "sqs", "sns", "amqp"}
    operations = {(op.address, op.action) for op in doc.operations}
    for op in doc.operations:
        system = op.protocol if op.protocol in known else "channel"
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="topic",
            direction=PROVIDES if op.action == "produces" else CONSUMES,
            key=topic_key(system, op.address), hint_source="config",
            evidence=[f"{file_info.path}:1"],
            subject=f"asyncapi/{op.channel}/{op.action}",
            attrs={"source": "asyncapi", "system": system, "declares": True,
                   "app_title": doc.title},
        ), file_node_id, sink)
    for channel in doc.declared_channels:
        if any(address == channel for address, _ in operations):
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="topic", direction=PROVIDES,
            key=topic_key("channel", channel), hint_source="config",
            evidence=[f"{file_info.path}:1"],
            subject=f"asyncapi/{channel}/declared",
            attrs={"source": "asyncapi", "system": "channel",
                   "declares": True, "no_operation": True},
        ), file_node_id, sink)


def emit_avro_claims(repo_id: str, file_info, schema, file_node_id: str,
                     sink: IngestSink) -> None:
    """`orders-value.avsc` names its topic via TopicNameStrategy."""
    if not schema.subject_hint:
        return
    topic = schema.subject_hint.rsplit("-", 1)[0]
    if not topic:
        return
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="topic", direction=PROVIDES,
        key=topic_key("kafka", topic), hint_source="config",
        evidence=[f"{file_info.path}:1"],
        subject=f"avro/{schema.subject_hint}",
        attrs={"source": "avro", "system": "kafka", "declares": True,
               "schema": schema.full_name, "subject": schema.subject_hint},
    ), file_node_id, sink)


# --- Gateways ------------------------------------------------------------

def emit_gateway_claims(repo_id: str, file_info, rules, file_node_id: str,
                        sink: IngestSink) -> None:
    """Gateway/proxy route tables -> route claims R4 consumes.

    Every source (nginx, envoy, kong, traefik, next.config, dev proxies)
    reduces to the same statement docker-compose gateway routes already make:
    requests matching PREFIX forward to TARGET with these rewrite semantics.
    """
    for rule in rules:
        target = (rule.target or "").lower()
        if not target:
            sink.count_claim("gateway_dynamic_target")
            continue
        prefix = rule.match_path or "/"
        evidence = [f"{file_info.path}:{rule.line or 1}"]
        attrs = {"target": target, "path_prefix": prefix,
                 "strip_prefix": 1 if rule.strip_prefix else 0,
                 "rewrite_path": rule.rewrite_to or "",
                 "gateway_kind": rule.gateway_kind,
                 "host": rule.match_host or ""}
        if rule.weight is not None:
            attrs["weight"] = rule.weight
        if rule.attrs.get("dev"):
            attrs["dev"] = True
        if rule.attrs.get("regex"):
            attrs["regex"] = True
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="route", direction=CONSUMES,
            key=route_key(prefix, target), hint_source="gateway_route",
            evidence=evidence, attrs=attrs,
            subject=f"gw/{rule.gateway_kind}/{rule.match_host}/{prefix}",
        ), file_node_id, sink)
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="svcname", direction=CONSUMES,
            key=svcname_key("discovery", target), service_hint=target,
            hint_source="gateway_route", evidence=evidence,
            attrs={"via": f"gateway_{rule.gateway_kind}"},
        ), file_node_id, sink)


# --- Data & pipelines ---------------------------------------------------

# Dataset key prefixes by extractor kind. Distinctive namespaces (an ES index,
# a Dynamo table, an S3 bucket) join freely; bare `table:` keys only join
# under R10's single-declarer rule.
_DATASET_PREFIX = {"index": "index", "table": "table", "collection": "mongo",
                   "bucket": "s3", "warehouse": "wh", "cache": "cache",
                   "model": "model", "dataset": "s3", "notebook": "pipeline"}

_ROLE_DIRECTION = {"reads": CONSUMES, "writes": PROVIDES,
                   "declares": PROVIDES}


def emit_data_site_claims(repo_id: str, file_info, content: str,
                          file_node_id: str, sink: IngestSink,
                          provenance: str = "") -> None:
    """ES/OS, ORM, SQL, NoSQL, object-storage sites."""
    from adduce.services.data_extractor import extract_data_sites
    for site in extract_data_sites(content, file_info.language):
        if not site.name:
            sink.count_claim("data_dynamic_site")
            continue
        prefix = _DATASET_PREFIX.get(site.kind, site.kind)
        # Dynamo table names are account-scoped and distinctive; they must
        # not fall under the bare-SQL-table single-declarer rule.
        if site.system == "dynamo" and site.kind == "table":
            prefix = "dynamo"
        kind = "db" if site.kind in ("table", "collection") else "dataset"
        attrs = {"system": site.system, "framework": site.framework,
                 "role": site.role, **(site.attrs or {})}
        if site.role == "declares":
            attrs["declares"] = True
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind=kind,
            direction=_ROLE_DIRECTION.get(site.role, CONSUMES),
            key=dataset_key(prefix, site.name), hint_source="none",
            evidence=[f"{file_info.path}:{site.line}"],
            subject=f"data/{site.system}/{site.role}/{site.name}"[:120],
            provenance=provenance, attrs=attrs,
        ), file_node_id, sink)


def emit_migration_claims(repo_id: str, file_info, content: str,
                          file_node_id: str, sink: IngestSink,
                          provenance: str = "") -> None:
    """Migrations declare table ownership: the repo that carries
    the CREATE TABLE is the single strongest owner signal a table has."""
    from adduce.parsers.migration_parser import is_migration_file, parse_migration
    if not is_migration_file(file_info.path):
        return
    migration = parse_migration(file_info.path, content)
    if migration is None:
        return
    for table in dict.fromkeys(migration.tables_created
                               + migration.tables_altered):
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="db", direction=PROVIDES,
            key=dataset_key("table", table), hint_source="none",
            evidence=[f"{file_info.path}:1"],
            subject=f"migration/{migration.framework}/{table}",
            provenance=provenance,
            attrs={"source": "migration", "declares": True,
                   "framework": migration.framework,
                   "version": migration.version,
                   "dropped": table in migration.tables_dropped},
        ), file_node_id, sink)


def emit_pipeline_claims(repo_id: str, file_info, pipeline, file_node_id: str,
                         sink: IngestSink) -> None:
    """dbt/Airflow/Databricks/DLT dataset lineage."""
    if pipeline is None:
        return
    evidence = [f"{file_info.path}:1"]
    for dataset in pipeline.datasets:
        if not dataset.name:
            continue
        prefix = _DATASET_PREFIX.get(dataset.kind, dataset.kind)
        attrs = {"source": pipeline.framework, "role": dataset.role,
                 "pipeline": pipeline.name, **(dataset.attrs or {})}
        if dataset.role == "declares":
            attrs["declares"] = True
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="dataset",
            direction=_ROLE_DIRECTION.get(dataset.role, CONSUMES),
            key=dataset_key(prefix, dataset.name), hint_source="none",
            evidence=[f"{file_info.path}:{dataset.line or 1}"],
            subject=f"pipe/{pipeline.framework}/{dataset.role}/{dataset.name}"[:120],
            attrs=attrs,
        ), file_node_id, sink)
        # Spark structured streaming against Kafka is a messaging statement
        # too — the topic join is where VQ3 meets the lineage graph.
        if topic := (dataset.attrs or {}).get("kafka_topic"):
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="topic",
                direction=CONSUMES if dataset.role == "reads" else PROVIDES,
                key=topic_key("kafka", str(topic)), hint_source="none",
                evidence=evidence,
                subject=f"pipe/{pipeline.framework}/kafka/{topic}",
                attrs={"source": pipeline.framework, "system": "kafka"},
            ), file_node_id, sink)

    if pipeline.name:
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="dataset", direction=PROVIDES,
            key=dataset_key("pipeline", pipeline.name),
            hint_source="none", evidence=evidence,
            subject=f"pipe/{pipeline.framework}/{pipeline.name}",
            attrs={"source": pipeline.framework, "declares": True,
                   "pipeline": pipeline.name,
                   "framework": pipeline.framework},
        ), file_node_id, sink)
    for upstream in pipeline.depends_on:
        name = os.path.basename(str(upstream)).rsplit(".", 1)[0]
        if not name:
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="dataset", direction=CONSUMES,
            key=dataset_key("pipeline", name), hint_source="none",
            evidence=evidence,
            subject=f"pipe/{pipeline.framework}/dep/{name}",
            attrs={"source": pipeline.framework, "cross_pipeline": True,
                   "raw_ref": str(upstream)[:200]},
        ), file_node_id, sink)


# --- Agents: MCP, A2A, LLM, vector stores -------------------------------

def emit_agent_claims(repo_id: str, file_info, content: str,
                      file_node_id: str, sink: IngestSink,
                      provenance: str = "") -> None:
    """MCP tool registrations, A2A call sites, LLM SDK sites, vector stores.

    Vector collections are datasets (`vector:` namespace, R10 joins them).
    LLM sites are inventory: which code calls which model is a fact worth
    querying, but the model itself is an external endpoint — no rendezvous.
    """
    from adduce.services.agents_extractor import (
        extract_a2a_call_sites, extract_llm_sites, extract_mcp_sites,
        extract_vector_sites,
    )
    for site in extract_mcp_sites(file_info.path, content, file_info.language):
        if not site.tool and not site.server:
            continue
        if not site.server:
            sink.count_claim("mcp_unnamed_server")
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="mcpop",
            direction=PROVIDES if site.role == "provides" else CONSUMES,
            key=mcp_op_key(site.server, site.tool or "*"),
            hint_source="none", evidence=[f"{file_info.path}:{site.line}"],
            subject=f"mcp/{site.role}/{site.server}/{site.tool}"[:120],
            provenance=provenance,
            attrs={"source": site.framework, "server": site.server,
                   "tool": site.tool, "op_kind": site.kind,
                   "transport": site.transport, **(site.attrs or {})},
        ), file_node_id, sink)

    for card in extract_a2a_call_sites(content, file_info.language):
        if not card.url:
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="a2aop", direction=CONSUMES,
            key=f"a2a:url:{_normalize_agent_url(card.url)}",
            hint_source="none",
            evidence=[f"{file_info.path}:{card.attrs.get('line', 1)}"],
            subject=f"a2a/call/{card.url}"[:120], provenance=provenance,
            attrs={"source": "a2a_client", "url": card.url},
        ), file_node_id, sink)

    for llm in extract_llm_sites(content, file_info.language):
        if not llm.model:
            sink.count_claim("llm_dynamic_model")
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="declared", direction=CONSUMES,
            key=f"llm:{llm.provider}:{llm.model}", hint_source="none",
            evidence=[f"{file_info.path}:{llm.line}"],
            subject=f"llm/{llm.provider}/{llm.model}"[:120],
            provenance=provenance,
            attrs={"source": "llm_sdk", "provider": llm.provider,
                   "model": llm.model, "framework": llm.framework},
        ), file_node_id, sink)

    for store in extract_vector_sites(content, file_info.language):
        if not store.collection:
            sink.count_claim("vector_dynamic_collection")
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="dataset",
            direction=_ROLE_DIRECTION.get(store.role, CONSUMES),
            key=dataset_key("vector", store.collection, scope=store.system),
            hint_source="none", evidence=[f"{file_info.path}:{store.line}"],
            subject=f"vec/{store.system}/{store.role}/{store.collection}"[:120],
            provenance=provenance,
            attrs={"source": store.system, "system": store.system,
                   "role": store.role,
                   "declares": store.role == "declares",
                   **(store.attrs or {})},
        ), file_node_id, sink)


def emit_mcp_config_claims(repo_id: str, file_info, sites, file_node_id: str,
                           sink: IngestSink) -> None:
    """mcp.json / claude_desktop_config.json server entries."""
    for site in sites:
        if not site.server:
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="mcpop", direction=CONSUMES,
            key=mcp_op_key(site.server, "*"), hint_source="config",
            evidence=[f"{file_info.path}:{site.line or 1}"],
            subject=f"mcpcfg/{site.server}",
            attrs={"source": "mcp-config", "server": site.server,
                   "transport": site.transport, **(site.attrs or {})},
        ), file_node_id, sink)


def emit_agent_card_claims(repo_id: str, file_info, card, file_node_id: str,
                           sink: IngestSink) -> None:
    """A2A agent card: the authored declaration of an agent's skills."""
    if card is None or not card.name:
        return
    skills = card.skills or ["*"]
    for skill in skills:
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="a2aop", direction=PROVIDES,
            key=a2a_op_key(card.name, skill), hint_source="config",
            evidence=[f"{file_info.path}:1"],
            subject=f"a2acard/{card.name}/{skill}",
            attrs={"source": "agent_card", "agent": card.name, "skill": skill,
                   "url": _normalize_agent_url(card.url) if card.url else ""},
        ), file_node_id, sink)


def _normalize_agent_url(url: str) -> str:
    return (url or "").rstrip("/").lower()


# --- Ownership & observability --------------------------------------------

def emit_codeowners_claims(repo_id: str, file_info, rules, file_node_id: str,
                           sink: IngestSink) -> None:
    """CODEOWNERS path rules -> team ownership claims.

    Only org/team-form owners become claims; individual users and emails stay
    in attrs — a Team rendezvous for every engineer would be noise, not
    ownership.
    """
    for rule in rules:
        teams = [o for o in rule.owners if "/" in o]
        for team in teams:
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="owner", direction=PROVIDES,
                key=team_key(team), hint_source="config",
                evidence=[f"{file_info.path}:{rule.line}"],
                subject=f"codeowners/{rule.pattern}",
                attrs={"source": "codeowners", "pattern": rule.pattern,
                       "team": team,
                       "individuals": [o for o in rule.owners if "/" not in o]},
            ), file_node_id, sink)


def emit_catalog_claims(repo_id: str, file_info, entities, file_node_id: str,
                        sink: IngestSink) -> None:
    """Backstage catalog-info.yaml: the catalog names the service,
    its owner, and its PagerDuty/OpsGenie binding in one authored place."""
    for entity in entities:
        evidence = [f"{file_info.path}:1"]
        if entity.kind in ("Component", "API") and entity.name:
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="svcname", direction=PROVIDES,
                key=svcname_key("discovery", entity.name),
                service_hint=entity.name, hint_source="catalog",
                evidence=evidence, subject=f"catalog/{entity.kind}/{entity.name}",
                attrs={"source": "backstage", "kind": entity.kind,
                       "system": entity.system, "type": entity.entity_type,
                       "lifecycle": entity.lifecycle,
                       "generic": is_generic_name(entity.name)},
            ), file_node_id, sink)
        if entity.owner:
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="owner", direction=PROVIDES,
                key=team_key(entity.owner), service_hint=entity.name or None,
                hint_source="catalog", evidence=evidence,
                subject=f"catalog/{entity.kind}/{entity.name}/owner",
                attrs={"source": "backstage", "team": entity.owner,
                       "entity": entity.name, "entity_kind": entity.kind,
                       "system": entity.system,
                       "pagerduty_service": entity.pagerduty_service,
                       "opsgenie_team": entity.opsgenie_team},
            ), file_node_id, sink)


def emit_observability_claims(repo_id: str, file_info, identities,
                              file_node_id: str, sink: IngestSink) -> None:
    """OTel/Datadog/New Relic/Sentry/Prometheus service identity.

    These are *corroborating alias signals*: they feed R0's svcname clustering
    at their own hint tier, they never mint deployment topology.
    """
    for identity in identities:
        if not identity.service_name:
            continue
        evidence = [f"{file_info.path}:{identity.line or 1}"]
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="svcname", direction=PROVIDES,
            key=svcname_key("discovery", identity.service_name),
            service_hint=identity.service_name, hint_source="observability",
            evidence=evidence, env_scope=identity.environment or None,
            subject=f"obs/{identity.source}/{identity.service_name}",
            attrs={"source": identity.source,
                   "generic": is_generic_name(identity.service_name)},
        ), file_node_id, sink)
        if identity.team:
            add_claim(repo_id, ContractClaim(
                repo_id=repo_id, kind="owner", direction=PROVIDES,
                key=team_key(identity.team),
                service_hint=identity.service_name,
                hint_source="observability", evidence=evidence,
                subject=f"obs/{identity.source}/{identity.service_name}/team",
                attrs={"source": identity.source, "team": identity.team,
                       "entity": identity.service_name},
            ), file_node_id, sink)


# --- Packages --------------------------------------------------------------

def _arn_tail(value: str) -> str:
    """`arn:aws:sns:us-east-1:123:order-events` -> `order-events`."""
    if value.startswith("arn:"):
        return value.rsplit(":", 1)[-1].split("/")[-1]
    if value.startswith("http"):
        return _queue_url_tail(value)
    return "" if "." in value or "$" in value else value


def _queue_url_tail(url: str) -> str:
    if not url or "$" in url:
        return ""
    return url.rstrip("/").rsplit("/", 1)[-1] if "/" in url else ""


def _reference_tail(references: list, resource_type: str) -> str:
    """`aws_sqs_queue.orders` in the references list -> `orders`."""
    prefix = f"{resource_type}."
    for ref in references or []:
        if ref.startswith(prefix):
            return ref[len(prefix):].split(".")[0]
    return ""


def emit_mcp_manifest_claims(repo_id: str, file_info, manifest,
                             file_node_id: str, sink: IngestSink) -> None:
    """Tool contracts declared by an MCP server's capability manifest.

    Each tool is a PROVIDES claim on the same `mcp:server/tool` key that
    `call_tool("name")` consumer sites already use, so R11 joins them at the
    existing rendezvous without a new resolver.

    The server name also becomes a svcname claim: a manifest saying "I am
    dashboard-mcp" is provider evidence of the same kind as
    spring.application.name, and it anchors to the manifest's directory so the
    server's whole module attributes to it.
    """
    if manifest is None or not manifest.server:
        return
    evidence = [f"{file_info.path}:1"]
    for problem in manifest.errors:
        sink.count_claim("mcp_manifest_invalid_entry")
        logger.debug("MCP manifest %s: %s", file_info.path, problem)

    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="svcname", direction=PROVIDES,
        key=svcname_key("discovery", manifest.server),
        service_hint=manifest.server, hint_source="config",
        evidence=evidence,
        attrs={"source": "mcp-manifest", "build_context": os.path.dirname(file_info.path),
               "generic": is_generic_name(manifest.server)},
    ), file_node_id, sink)

    for tool in manifest.tools:
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="mcpop", direction=PROVIDES,
            key=mcp_op_key(manifest.server, tool.name),
            hint_source="config", evidence=evidence,
            subject=f"mcp/provides/{manifest.server}/{tool.name}"[:120],
            attrs={"source": "mcp-manifest", "server": manifest.server,
                   "tool": tool.name, "op_kind": "tool",
                   "transport": manifest.transport,
                   # A destructive tool is a blast-radius signal, not decoration.
                   "destructive": tool.destructive,
                   "entity_kind": tool.entity_kind,
                   "description": tool.description[:200]},
        ), file_node_id, sink)


def _emit_policy(repo_id, resource, scope, environment, evidence,
                 evidence_node, sink) -> None:
    """One claim per (policy, source): who may reach the selected target.

    A policy with no concrete source (allow-all, deny-all) emits nothing —
    "everyone may" names no edge, and the resolver would only have to
    decline it later.
    """
    target = _label_signature(resource.policy_target)
    if not target:
        return
    sources = ([("labels", _label_signature(l))
                for l in resource.policy_source_labels]
               + [("service_account", sa)
                  for sa in resource.policy_source_accounts])
    for kind_, source in sources:
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="policy", direction=PROVIDES,
            key=f"{scope}:{'|'.join(target)}",
            hint_source="config", evidence=evidence, env_scope=environment,
            subject=f"{resource.kind}/{resource.name}/{source}",
            attrs={"source": ("authorization_policy"
                              if resource.kind == "AuthorizationPolicy"
                              else "network_policy"),
                   "action": resource.policy_action or "ALLOW",
                   "target_selector": target,
                   "source_kind": kind_,
                   "source_ref": source,
                   "namespace": resource.namespace},
        ), evidence_node, sink)
