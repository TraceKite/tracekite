"""R5 gRPC: join `package.Service/Rpc` operations across repos.

The highest-precision cross-repo resolver available. Unlike HTTP — where a
consumer says `GET /owners/{id}` and the provider says the same thing about a
different service, so a service hint is required to disambiguate — a protobuf
operation key is globally unique by construction. Both sides emit
`petclinic.orders.OrdersService/GetOrder` independently and identically, so a
match needs no hint and carries no scope ambiguity.

Emits ContractOperation rendezvous nodes plus EXPOSES (server -> operation) and
INVOKES (client -> operation) edges.
"""

import logging
from collections import defaultdict

from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    linker_edge,
)
from tracekite.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.grpc@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    operations = _emit_operations(index, ctx, out)
    _match_stubs(index, ctx, out, operations)
    return out


def _emit_operations(index: ClaimIndex, ctx: LinkContext,
                     out: ResolverOutput) -> dict[str, list[ClaimRecord]]:
    """Every declared rpc becomes a globally-keyed ContractOperation."""
    by_key: dict[str, list[ClaimRecord]] = defaultdict(list)
    seen: set[str] = set()

    for claim in index.provides("grpcop"):
        key = claim.key
        if not key or "/" not in key:
            continue
        node_id = rid.grpc_operation_id(key)
        service_full, _, rpc = key.rpartition("/")
        by_key[key].append(claim)
        ctx.contract_repos[node_id].add(claim.repo_id)

        if node_id not in seen:
            seen.add(node_id)
            out.rendezvous.append(RendezvousSpec("ContractOperation", node_id, {
                "protocol": "grpc",
                "key": key,
                "service": service_full,
                "rpc": rpc,
                "package": str(claim.attrs.get("package") or ""),
                "streaming": str(claim.attrs.get("streaming") or "unary"),
                "repo_ids": sorted(ctx.contract_repos[node_id]),
            }))
            ctx.count("r5.operations")

        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
            source_label="ContractClaim", target_label="ContractOperation",
            confidence=ctx.conf("r5", "declared"), match_type="declared",
            evidence=claim.evidence, claim_key=key,
            source_repo=claim.repo_id, origin="declared",
        ))
        if claim.evidence_node_id:
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, "DECLARES_CONTRACT", claim.evidence_node_id,
                node_id, source_label="GraphNode",
                target_label="ContractOperation",
                confidence=ctx.conf("r5", "declared"), match_type="declared",
                evidence=claim.evidence, claim_key=key,
                source_repo=claim.repo_id, origin="declared",
                extra={"via": ["proto"]},
            ))
    return by_key


def _match_stubs(index: ClaimIndex, ctx: LinkContext, out: ResolverOutput,
                 operations: dict[str, list[ClaimRecord]]) -> None:
    """Server impls and client stubs name a service; bind them to its rpcs.

    Implementations and stubs know only the *service* name (that is all protoc
    puts in the generated class), so one stub claim binds to every rpc the
    service declares.
    """
    by_service: dict[str, list[str]] = defaultdict(list)
    for key in operations:
        service_full = key.rpartition("/")[0]
        by_service[service_full.lower()].append(key)
        # Unqualified name too: a stub says `OrdersService`, the proto says
        # `petclinic.orders.OrdersService`.
        by_service[service_full.rpartition(".")[2].lower()].append(key)

    for direction, edge_type, tier in (("provides", "EXPOSES", "server"),
                                       ("consumes", "INVOKES", "client")):
        claims = (index.provides("grpcstub") if direction == "provides"
                  else index.consumes("grpcstub"))
        for claim in claims:
            service = str(claim.attrs.get("service") or claim.key).lower()
            keys = sorted(set(by_service.get(service, [])))
            if not keys:
                ctx.count(f"r5.unmatched_{tier}")
                continue
            # A service with a very large rpc surface would fan one stub out
            # across the graph; the same guardrail as R7.
            if len(keys) > ctx.fanout_cap:
                ctx.count("r5.fanout_exceeded")
                logger.info("R5 dropped %s: %d operations exceeds cap %d",
                            claim.key, len(keys), ctx.fanout_cap)
                continue
            if claim.evidence_node_id is None:
                ctx.count("r5.no_call_site_node")
                continue

            qualified = "." in service
            confidence = ctx.conf("r5", "exact" if qualified else "service_name")
            for key in keys:
                node_id = rid.grpc_operation_id(key)
                provider_repos = sorted(ctx.contract_repos.get(node_id, set()))
                out.edges.append(linker_edge(
                    ctx, RESOLVER_ID, edge_type, claim.evidence_node_id, node_id,
                    source_label="GraphNode", target_label="ContractOperation",
                    confidence=confidence,
                    match_type="grpc_qualified" if qualified else "grpc_service_name",
                    evidence=claim.evidence, claim_key=key,
                    source_repo=claim.repo_id,
                    target_repo=provider_repos[0] if len(provider_repos) == 1 else "",
                    origin="matched", extra={"via": ["grpc"]},
                ))
                out.edges.append(linker_edge(
                    ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
                    source_label="ContractClaim",
                    target_label="ContractOperation", confidence=confidence,
                    match_type="grpc", evidence=claim.evidence, claim_key=key,
                    source_repo=claim.repo_id, origin="matched",
                ))
            ctx.count(f"r5.{tier}_matched")
            _record_call(ctx, claim, keys, direction)


def _record_call(ctx: LinkContext, claim: ClaimRecord, keys: list[str],
                 direction: str) -> None:
    """Queue a Service-level call for a matched client stub."""
    if direction != "consumes":
        return
    source = ctx.canon(ctx.module_service_name(claim.repo_id, claim.primary_path) or "")
    if not source:
        ctx.count("r5.consumer_unattributed")
        return
    for key in keys[:1]:
        target = ctx.canon(_service_short_name(key))
        if not target or target == source:
            continue
        ctx.record_service_call(
            source, target, RESOLVER_ID, ctx.conf("r5", "calls_service"),
            claim.evidence, claim.repo_id, via="grpc",
        )


def _service_short_name(key: str) -> str:
    """`petclinic.orders.OrdersService/GetOrder` -> `orders-service`.

    protoc service names are PascalCase while deployed service names are
    kebab-case, so the two only meet after normalization.
    """
    service = key.rpartition("/")[0].rpartition(".")[2]
    import re
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", service).lower()
    return kebab
