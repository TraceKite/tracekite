"""R2 kubernetes: workloads, Service objects, selectors, cluster DNS, GitOps.

Precision basis ≈0.97 (benchmark: K8s manifest linking P 0.97 / R 0.56 —
manifests beat code heuristics).

Namespace is the scope. Two clusters both running `api` must not merge on name,
so every k8s-derived ServiceName is namespace-qualified and only the alias
resolver may cluster them, under its two-signal rule.
"""

from collections import defaultdict

from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    linker_edge,
)

RESOLVER_ID = "resolver.k8s@1"

# `<service>.<namespace>.svc.cluster.local`, `<service>.<namespace>.svc`,
# `<service>.<namespace>` and bare `<service>` all address the same Service.
_CLUSTER_SUFFIXES = (".svc.cluster.local", ".svc")


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    services = _index_services(index, ctx)
    workloads = _index_workloads(index, ctx)

    _bind_selectors(ctx, out, services, workloads)
    _emit_dns_aliases(ctx, out, services)
    _emit_env_host_calls(ctx, out, index, services)
    _emit_gitops_built_from(ctx, out, index)
    _emit_policy_edges(ctx, index, workloads)
    return out


def _index_services(index: ClaimIndex, ctx: LinkContext) -> dict:
    """Service objects by (namespace, name) — the DNS-addressable names."""
    services: dict[tuple[str, str], ClaimRecord] = {}
    for claim in index.provides("svcname"):
        if claim.attrs.get("source") != "k8s_service":
            continue
        namespace, _, name = claim.key.partition(":")
        services[(namespace, ctx.canon(name))] = claim
    return services


def _index_workloads(index: ClaimIndex, ctx: LinkContext) -> dict:
    workloads: dict[tuple[str, str], list[ClaimRecord]] = defaultdict(list)
    for claim in index.provides("svcname"):
        if claim.attrs.get("source") != "k8s":
            continue
        namespace, _, name = claim.key.partition(":")
        workloads[(namespace, ctx.canon(name))].append(claim)
    return workloads


def _bind_selectors(ctx: LinkContext, out: ResolverOutput, services: dict,
                    workloads: dict) -> None:
    """Service selector -> workload pod labels.

    A Service and its Deployment are usually named differently; the selector is
    the authoritative binding between the DNS name and the container images,
    and therefore between the DNS name and the repo that builds them.
    """
    by_namespace: dict[str, list] = defaultdict(list)
    for (namespace, name), claims in workloads.items():
        for claim in claims:
            by_namespace[namespace].append((name, claim))

    for (namespace, service_name), service_claim in sorted(services.items()):
        selector = set(service_claim.attrs.get("selector") or [])
        if not selector:
            continue
        for workload_name, workload_claim in by_namespace.get(namespace, []):
            pod_labels = set(workload_claim.attrs.get("pod_labels") or [])
            if not pod_labels or not selector.issubset(pod_labels):
                continue
            ctx.count("r2.selector_bindings")
            # The Service name is the addressable identity; alias the workload
            # name onto it so both spellings resolve to one service.
            ctx.register_alias(workload_name, service_name)
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, "MEMBER_OF", workload_claim.id,
                service_claim.id, source_label="ContractClaim",
                target_label="ContractClaim",
                confidence=ctx.conf("r2", "selector_match"),
                match_type="selector", evidence=workload_claim.evidence,
                claim_key=workload_claim.key, source_repo=workload_claim.repo_id,
                target_repo=service_claim.repo_id, origin="declared",
                extra={"via": ["k8s_selector"]},
            ))


def _emit_dns_aliases(ctx: LinkContext, out: ResolverOutput,
                      services: dict) -> None:
    """Register cluster DNS spellings so host hints resolve."""
    for (namespace, name), claim in sorted(services.items()):
        for spelling in (f"{name}.{namespace}",
                         f"{name}.{namespace}.svc",
                         f"{name}.{namespace}.svc.cluster.local"):
            ctx.register_alias(spelling, name)
        ctx.count("r2.dns_aliases")
        if external := claim.attrs.get("external_name"):
            # ExternalName services are a documented egress boundary.
            ctx.register_alias(str(external).lower(), name)
            ctx.count("r2.external_names")


def _emit_env_host_calls(ctx: LinkContext, out: ResolverOutput,
                         index: ClaimIndex, services: dict) -> None:
    """Literal env values pointing at another in-cluster service.

    `VETS_URL: http://vets-service:8080` in a Deployment is a declared
    dependency, and the highest-precision one available short of a code call.
    """
    for claim in index.provides("cfgdef"):
        if claim.attrs.get("source") != "k8s_env":
            continue
        host = str(claim.attrs.get("value_host") or "").lower()
        if not host:
            continue
        target = ctx.canon(_strip_cluster_suffix(host))
        source = ctx.canon(str(claim.attrs.get("service") or ""))
        namespace = str(claim.attrs.get("namespace") or "default").lower()
        if not target or not source or target == source:
            continue
        if (namespace, target) not in services and \
                not any(name == target for _, name in services):
            ctx.count("r2.env_host_unresolved")
            continue
        ctx.count("r2.env_host_calls")
        if claim.attrs.get("schedule"):
            ctx.count("r2.scheduled_calls")
        ctx.record_service_call(
            source, target, RESOLVER_ID,
            ctx.conf("r2", "env_host"), claim.evidence, claim.repo_id,
            via="k8s_env_host", env_scope=claim.attrs.get("env_scope") or "",
            schedule=str(claim.attrs.get("schedule") or ""),
        )


def _emit_gitops_built_from(ctx: LinkContext, out: ResolverOutput,
                            index: ClaimIndex) -> None:
    """ArgoCD/Flux source repo -> deployed service.

    A declared binding: the operator states which repo produces this workload,
    which is stronger evidence than inferring it from an image name.
    """
    for claim in index.provides("declared"):
        if claim.attrs.get("source") != "gitops":
            continue
        repo_url = str(claim.attrs.get("source_repo") or "")
        name = ctx.canon(str(claim.service_hint or ""))
        if not repo_url or not name:
            continue
        ctx.count("r2.gitops_sources")
        ctx.record_gitops_source(name, repo_url, claim)


def _strip_cluster_suffix(host: str) -> str:
    """`orders.prod.svc.cluster.local` -> `orders`."""
    for suffix in _CLUSTER_SUFFIXES:
        if host.endswith(suffix):
            host = host[: -len(suffix)]
            break
    return host.split(".")[0]


def _emit_policy_edges(ctx: LinkContext, index: ClaimIndex,
                       workloads: dict) -> None:
    """Mesh/network policy: who MAY talk to whom.

    Distinct from call edges on purpose — "billing permits orders" and
    "orders calls billing" are different facts, and folding the first into
    the second would let a permissive policy inflate the call graph. The
    target is matched by selector against pod labels, the source by
    service-account name or its own selector; either side unmatched is a
    decline, because a policy about nothing names no edge.
    """
    pods: list[tuple[str, str, set]] = []
    for (namespace, name), claims in workloads.items():
        for claim in claims:
            pods.append((namespace, name,
                         set(claim.attrs.get("pod_labels") or [])))

    def match(namespace: str, selector: list) -> set[str]:
        wanted = set(selector)
        return {name for ns, name, labels in pods
                if ns == namespace and wanted and wanted.issubset(labels)}

    for claim in index.provides("policy"):
        namespace = str(claim.attrs.get("namespace") or "default").lower()
        targets = match(namespace, claim.attrs.get("target_selector") or [])
        if not targets:
            ctx.count("r2.policy_target_unmatched")
            continue
        if claim.attrs.get("source_kind") == "service_account":
            sources = {ctx.canon(str(claim.attrs.get("source_ref") or ""))}
            sources = {s for s in sources
                       if any(name == s for _, name, _l in pods)}
        else:
            sources = match(namespace, claim.attrs.get("source_ref") or [])
        if not sources:
            ctx.count("r2.policy_source_unmatched")
            continue
        action = str(claim.attrs.get("action") or "ALLOW")
        for source in sorted(sources):
            for target in sorted(targets):
                if source == target:
                    continue
                ctx.count("r2.policy_edges")
                ctx.record_service_call(
                    source, target, RESOLVER_ID,
                    ctx.conf("r2", "policy"), claim.evidence, claim.repo_id,
                    via=f"mesh_policy_{action.lower()}",
                    edge_type="PERMITS_TRAFFIC",
                )
