"""R8 GraphQL: join `Type.field` operations across repos.

Weaker than R5 by construction: a protobuf key carries its package, but
`Query.user` does not, so two unrelated teams can define the same key. Two
consequences, both deliberate:

- an unfederated match is a *service-name* tier, not an exact one;
- federation metadata is treated as the authority when present, because a
  subgraph's ``@key``/``extend type`` is the only explicit statement of which
  service owns a type.
"""

import logging
from collections import defaultdict

from evigraph.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    linker_edge,
)
from evigraph.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.graphql@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    providers = _emit_operations(index, ctx, out)
    _match_operations(index, ctx, out, providers)
    return out


def _emit_operations(index: ClaimIndex, ctx: LinkContext,
                     out: ResolverOutput) -> dict[str, list[ClaimRecord]]:
    providers: dict[str, list[ClaimRecord]] = defaultdict(list)
    seen: set[str] = set()

    for claim in index.provides("graphqlop"):
        key = claim.key
        if not key or "." not in key:
            continue
        node_id = rid.graphql_operation_id(key)
        providers[key.lower()].append(claim)
        ctx.contract_repos[node_id].add(claim.repo_id)

        if node_id not in seen:
            seen.add(node_id)
            parent, _, field_name = key.rpartition(".")
            out.rendezvous.append(RendezvousSpec("ContractOperation", node_id, {
                "protocol": "graphql", "key": key,
                "service": parent, "rpc": field_name,
                "federated": bool(claim.attrs.get("federated")),
                "return_type": str(claim.attrs.get("return_type") or ""),
                "repo_ids": sorted(ctx.contract_repos[node_id]),
            }))
            ctx.count("r8.operations")

        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
            source_label="ContractClaim", target_label="ContractOperation",
            confidence=ctx.conf("r8", "declared"), match_type="declared",
            evidence=claim.evidence, claim_key=key,
            source_repo=claim.repo_id, origin="declared",
        ))
        if claim.evidence_node_id:
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, "EXPOSES", claim.evidence_node_id, node_id,
                source_label="GraphNode", target_label="ContractOperation",
                confidence=ctx.conf("r8", "declared"), match_type="declared",
                evidence=claim.evidence, claim_key=key,
                source_repo=claim.repo_id, origin="declared",
                extra={"via": ["graphql_sdl"]},
            ))
    return providers


def _match_operations(index: ClaimIndex, ctx: LinkContext, out: ResolverOutput,
                      providers: dict[str, list[ClaimRecord]]) -> None:
    for claim in index.consumes("graphqlop"):
        key = claim.key
        candidates = providers.get(key.lower(), [])
        if not candidates:
            ctx.count("r8.unmatched")
            continue

        repos = {c.repo_id for c in candidates}
        federated = any(c.attrs.get("federated") for c in candidates)
        ambiguous = len(repos) > 1 and not federated
        if len(candidates) > ctx.fanout_cap:
            ctx.count("r8.fanout_exceeded")
            continue
        if claim.evidence_node_id is None:
            ctx.count("r8.no_call_site_node")
            continue

        tier = "federated" if federated else "field_name"
        confidence = ctx.conf("r8", tier)
        node_id = rid.graphql_operation_id(candidates[0].key)
        provider_repo = sorted(repos)[0] if len(repos) == 1 else ""

        if ambiguous:
            # `Query.user` defined in several repos with no federation
            # metadata to say which owns it. Picking one is a coin flip, so
            # the confidence is divided among the candidates: with N
            # mutually-exclusive owners each carries 1/N of the evidence.
            #
            # This is not a softening of decline-don't-guess. The divided
            # score falls below the floor, so `apply_confidence_floor` marks
            # these `candidate` — visible and inspectable, excluded from
            # default answers, never served as fact. The decline is still
            # counted, because for anyone reading active edges it is still a
            # decline. A ranked list beats silence only if nobody can mistake
            # it for an answer.
            ctx.count("r8.ambiguous_owner")
            confidence = confidence / len(repos)
            provider_repo = ""

        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "INVOKES", claim.evidence_node_id, node_id,
            source_label="GraphNode", target_label="ContractOperation",
            confidence=confidence, match_type=f"graphql_{tier}",
            evidence=claim.evidence, claim_key=key,
            source_repo=claim.repo_id, target_repo=provider_repo,
            origin="matched", extra={"via": ["graphql"]},
        ))
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
            source_label="ContractClaim", target_label="ContractOperation",
            confidence=confidence, match_type="graphql",
            evidence=claim.evidence, claim_key=key,
            source_repo=claim.repo_id, origin="matched",
        ))
        ctx.count("r8.matched")
