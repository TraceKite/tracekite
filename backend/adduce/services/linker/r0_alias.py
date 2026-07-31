"""R0 alias: ServiceName rendezvous, Service minting, BUILT_FROM (design §6.2).

Cross-scope unification requires a corroborating repo that provides the same
name in both scopes; generic names never cluster on name alone and always get
scope-qualified Service ids.
"""

import posixpath
from collections import defaultdict

from adduce.services.claims import is_generic_name
from adduce.services.linker.modules import module_of
from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    ServiceSpec, linker_edge,
)
from adduce.utils import rendezvous_ids as rid
from adduce.utils.evidence import evidence_path

RESOLVER_ID = "resolver.alias@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    claims = [c for c in index.kind("svcname") if c.matchable and ":" in c.key]

    by_scope_name: dict[tuple[str, str], list[ClaimRecord]] = defaultdict(list)
    for claim in claims:
        scope, _, name = claim.key.partition(":")
        by_scope_name[(scope, ctx.canon(name))].append(claim)

    for (scope, name), group in sorted(by_scope_name.items()):
        node_id = rid.svcname_id(scope, name)
        ctx.servicename_id[(scope, name)] = node_id
        out.rendezvous.append(RendezvousSpec("ServiceName", node_id, {
            "name": name, "scope": scope, "generic": is_generic_name(name),
            "repo_ids": sorted({c.repo_id for c in group}),
        }))
        for claim in group:
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
                source_label="ContractClaim", target_label="ServiceName",
                confidence=ctx.conf("r0", "resolved_to"), match_type="alias",
                evidence=claim.evidence, claim_key=claim.key,
                source_repo=claim.repo_id, origin="declared",
            ))
        ctx.count("r0.servicenames")

    providers: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    provider_claims: dict[str, list[ClaimRecord]] = defaultdict(list)
    for claim in claims:
        if claim.direction != "provides":
            continue
        scope, _, name = claim.key.partition(":")
        name = ctx.canon(name)
        providers[name][scope].add(claim.repo_id)
        provider_claims[name].append(claim)
        _register_scope(ctx, claim, name)

    for name, scopes in sorted(providers.items()):
        clusters = _cluster_scopes(name, scopes)
        for cluster in clusters:
            service_id, primary = _service_identity(name, cluster, clusters)
            spec = ServiceSpec(service_id=service_id, name=primary)
            claims_in = [c for c in provider_claims[name]
                         if c.key.partition(":")[0] in cluster]
            _emit_module(ctx, out, service_id, claims_in)
            _emit_deployment(ctx, out, service_id, claims_in)
            for scope in sorted(cluster):
                ctx.service_by_scope_name[(scope, name)] = service_id
                sn_id = ctx.servicename_id[(scope, name)]
                out.edges.append(linker_edge(
                    ctx, RESOLVER_ID, "HAS_ALIAS", service_id, sn_id,
                    source_label="Service", target_label="ServiceName",
                    confidence=ctx.conf("r0", "has_alias"), match_type="alias",
                    evidence=_first_evidence(claims_in), origin="inferred",
                ))
            ctx.service_by_name.setdefault(primary, service_id)
            ctx.service_by_name.setdefault(name, service_id)
            ctx.service_name_of[service_id] = primary
            _built_from(ctx, out, spec, claims_in)
            spec.repo_ids = sorted(ctx.service_repos.get(service_id, set()))
            out.services.append(spec)
            ctx.count("r0.services")
    return out


# Sources where the claim names the service the FILE ITSELF belongs to, so the
# holding directory is that service's module.
_OWNING_SOURCES = frozenset({"spring.application.name", "otel-env"})

# Sources where the claim names a DIFFERENT service than the file's owner.
# These must not register any path scope in either direction.
_REFERENCING_SOURCES = frozenset({"config-filename", "prometheus-job"})


def _register_scope(ctx: LinkContext, claim: ClaimRecord, name: str) -> None:
    """Bind the path a service-name claim came from to that service.

    Every provider signal registers, not just ``spring.application.name`` —
    otherwise R7 keys non-JVM providers' HTTP contracts on repo_id and no
    consumer service hint can ever match them.
    """
    source = claim.attrs.get("source", "")
    build_context = claim.attrs.get("build_context")
    if build_context:
        # A build context names the directory that becomes this service — the
        # strongest available path evidence, and the one monorepos depend on.
        # Compose resolves it against the FILE's directory, not the repo
        # root: `build: .` in services/orders/docker-compose.yml means
        # services/orders. Resolving against the root instead registered
        # every nested service at "" rank 2, where they tied, every lookup
        # declined, and a monorepo's calls silently lost their consumers.
        compose_dir = posixpath.dirname(claim.primary_path)
        prefix = posixpath.normpath(
            posixpath.join(compose_dir, build_context.strip()))
        if prefix.startswith(".."):
            # The context leaves the repository, so no directory inside it
            # is named. Scope the whole repo at the lowest rank rather than
            # pinning rank-2 evidence to a directory that does not exist.
            ctx.count("r0.build_context_outside_repo")
            ctx.register_module_prefix(claim.repo_id, "", name, rank=0)
            return
        ctx.register_module_prefix(
            claim.repo_id, "" if prefix == "." else prefix, name, rank=2)
        return
    if source in _OWNING_SOURCES:
        # The file declares its OWN service identity, so the directory holding
        # it is that service's module. OTEL_SERVICE_NAME sits in the service's
        # own env/compose file exactly as spring.application.name sits in its
        # own application.yml — same evidence, same anchoring.
        ctx.register_module(claim.repo_id, claim.primary_path, name, rank=1)
        return
    if source in _REFERENCING_SOURCES:
        # Names some OTHER service: a config file it configures, or a scrape
        # target. Registering the holder's directory would attribute all of it
        # to the wrong service, and registering the whole repo makes every
        # path in the repo ambiguous — which is how 35 services each claiming
        # the repo root turned every lookup into a decline.
        ctx.count(f"r0.scope_skipped_{source.replace('.', '_').replace('-', '_')}")
        return
    # No directory evidence: the claim scopes the whole repo, at the lowest rank
    # so any path-anchored signal outranks it.
    ctx.register_module_prefix(claim.repo_id, "", name, rank=0)


def _cluster_scopes(name: str, scopes: dict[str, set[str]]) -> list[frozenset]:
    scope_list = sorted(scopes)
    if len(scope_list) == 1:
        return [frozenset(scope_list)]
    if is_generic_name(name):
        return [frozenset([s]) for s in scope_list]

    parent = {s: s for s in scope_list}

    def find(s):
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for i, a in enumerate(scope_list):
        for b in scope_list[i + 1:]:
            if scopes[a] & scopes[b]:
                parent[find(a)] = find(b)
    clusters: dict[str, set[str]] = defaultdict(set)
    for s in scope_list:
        clusters[find(s)].add(s)
    return [frozenset(c) for c in sorted(clusters.values(), key=sorted)]


def _service_identity(name: str, cluster: frozenset,
                      clusters: list[frozenset]) -> tuple[str, str]:
    if is_generic_name(name) or len(clusters) > 1:
        scope = sorted(cluster)[0]
        qualified = f"{scope}/{name}"
        return rid.service_id(qualified), qualified
    return rid.service_id(name), name


def _built_from(ctx: LinkContext, out: ResolverOutput, spec: ServiceSpec,
                claims_in: list[ClaimRecord]) -> None:
    best: dict[str, tuple[float, ClaimRecord, str]] = {}
    for claim in claims_in:
        source = claim.attrs.get("source", "")
        if claim.attrs.get("build_context"):
            conf, via = ctx.conf("r0", "built_from_build_context"), "build_context"
        elif source == "spring.application.name":
            conf, via = ctx.conf("r0", "built_from_app_name"), "app_name"
        elif source in ("compose", "k8s"):
            # A deployment descriptor in this repo naming this service is real
            # evidence, just weaker than a build context that points at a
            # directory — the image could be built elsewhere.
            conf, via = ctx.conf("r0", "built_from_descriptor"), "descriptor"
        else:
            # config-filename deliberately excluded: `customers-service.yml` in
            # a Spring Cloud Config repo says which service the file configures,
            # not that the service is built from that repo.
            continue
        current = best.get(claim.repo_id)
        if current is None or conf > current[0]:
            best[claim.repo_id] = (conf, claim, via)

    for repo_id, (conf, claim, via) in sorted(best.items()):
        ctx.service_repos[spec.service_id].add(repo_id)
        evidence = claim.evidence
        build_line = claim.attrs.get("build_line")
        if via == "build_context" and build_line and evidence:
            # Cite the `context:` entry, not the service header: the
            # directory the descriptor points at IS the build assertion.
            evidence = [f"{evidence_path(evidence[0])}:{build_line}"]
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "BUILT_FROM", spec.service_id, repo_id,
            source_label="Service", target_label="Repo", confidence=conf,
            match_type="alias", evidence=evidence, claim_key=claim.key,
            target_repo=repo_id, origin="inferred", extra={"via": [via]},
        ))
        ctx.count("r0.built_from")


def _first_evidence(claims: list[ClaimRecord]) -> list[str]:
    for claim in claims:
        if claim.evidence:
            return claim.evidence[:1]
    return []


def _emit_module(ctx, out, service_id: str, claims) -> None:
    """Bind a service to the module that owns it.

    A repository is how code is stored; a module is what owns behaviour, and
    in a monorepo the second is the boundary that matters. Promoting it from a
    derived helper to a node makes "what else lives in this module" a query
    rather than a path-prefix scan every caller reimplements.

    Declines rather than guesses: a service whose claims come from two modules
    has no single owner, and picking one would be a coin flip.
    """
    modules = {module_of(c.primary_path) for c in claims if c.primary_path}
    modules.discard("")
    if not modules:
        ctx.count("r0.module_unknown")
        return
    if len(modules) > 1:
        ctx.count("r0.module_ambiguous")
        return

    module = next(iter(modules))
    module_node = rid.module_id(module)
    repos = sorted({c.repo_id for c in claims if c.repo_id})
    out.rendezvous.append(RendezvousSpec(
        "Module", module_node, {"name": module, "repo_ids": repos}))
    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, "BELONGS_TO", service_id, module_node,
        source_label="Service", target_label="Module",
        confidence=ctx.conf("r0", "belongs_to"), match_type="path",
        evidence=_first_evidence(claims), origin="inferred"))
    ctx.count("r0.modules")


def _emit_deployment(ctx, out, service_id: str, claims) -> None:
    """Bind a service to the workload that runs it.

    Closes the loop between code and runtime topology: the graph knows what a
    service *is* and what it calls, but not what actually runs it. A manifest
    naming a Deployment is a declaration, not an inference, which is why this
    is priced with the other declared k8s tiers.

    One edge per distinct workload. A service deployed twice — blue/green, or
    the same image in two namespaces — genuinely has two deployment units, and
    collapsing them would lose the fact that one of them can be rolled back
    independently.
    """
    units: dict[str, list] = {}
    for claim in claims:
        if claim.attrs.get("source") != "k8s":
            continue
        kind = str(claim.attrs.get("kind") or "").strip()
        name = str(claim.attrs.get("workload") or "").strip()
        if not kind or not name:
            # A k8s claim that names no workload cannot identify a unit;
            # guessing one from the service name would invent runtime
            # topology that no manifest declares.
            ctx.count("r2.deployment_unidentified")
            continue
        namespace = str(claim.attrs.get("namespace") or "default").strip()
        unit_id = rid.deployment_unit_id(namespace, kind, name)
        units.setdefault(unit_id, []).append(claim)

    for unit_id, unit_claims in sorted(units.items()):
        first = unit_claims[0]
        out.rendezvous.append(RendezvousSpec("DeploymentUnit", unit_id, {
            "name": first.attrs.get("workload", ""),
            "kind": first.attrs.get("kind", ""),
            "namespace": first.attrs.get("namespace", "default"),
            "repo_ids": sorted({c.repo_id for c in unit_claims if c.repo_id}),
        }))
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "DEPLOYED_AS", service_id, unit_id,
            source_label="Service", target_label="DeploymentUnit",
            confidence=ctx.conf("r2", "deployed_as"), match_type="manifest",
            evidence=_first_evidence(unit_claims), origin="declared"))
        ctx.count("r2.deployed_as")
