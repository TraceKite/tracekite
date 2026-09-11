"""R10 dataset resolver: join reads/writes/declarations at Dataset rendezvous
nodes.

Dataset identity strength varies wildly by namespace, and the resolver's
precision rules encode that:

- Distinctive namespaces join freely: an ES index (`index:owners`), a Dynamo
  table (`mongo:`/`s3:`/`wh:` likewise) is named inside a real account/cluster
  namespace, so equal spelling is strong evidence.
- Bare SQL tables (`table:orders`) are the trap — half the estate has a
  `users` table. A bare table key joins ACROSS repos only under the
  single-declarer rule: exactly one repo *declares* it (migration, ORM
  entity, dbt schema), and that declarer anchors the rendezvous. No declarer
  or several -> the cross-repo join is declined and counted; same-repo
  references still join (a repo's own migrations and queries are one system).
- Schema-qualified tables (`table:sales.orders`) carry their own namespace
  and join freely.

Edges: WRITES_TO / READS_FROM (site -> Dataset; declarations are WRITES_TO
with `declares: true` — a migration literally writes the schema).
"""

import logging
from collections import defaultdict

from evigraph.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    linker_edge,
)
from evigraph.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.dataset@1"

_FREE_JOIN_PREFIXES = ("index", "s3", "wh", "mongo", "cache", "model",
                       "pipeline", "dynamo")


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    by_key: dict[str, list[ClaimRecord]] = defaultdict(list)
    for kind in ("dataset", "db"):
        for claim in index.kind(kind):
            if not claim.matchable:
                ctx.count("r10.dynamic_unlinked")
                continue
            by_key[claim.key].append(claim)

    seen: set[str] = set()
    for key, claims in sorted(by_key.items()):
        prefix, _, name = key.partition(":")
        declarers = {c.repo_id for c in claims if c.attrs.get("declares")}
        repos = {c.repo_id for c in claims}

        if prefix == "table" and "." not in name and len(repos) > 1:
            if len(declarers) == 0:
                # `users` spelled alike in N repos is not one table.
                ctx.count("r10.ambiguous_table")
                continue
            if len(declarers) > 1:
                ctx.count("r10.multi_declarer")
                continue

        node_id = rid.dataset_id(key)
        anchor = declarers.copy().pop() if len(declarers) == 1 else ""
        for claim in claims:
            ctx.contract_repos[node_id].add(claim.repo_id)
        if node_id not in seen:
            seen.add(node_id)
            out.rendezvous.append(RendezvousSpec("Dataset", node_id, {
                "key": key, "name": name, "namespace": prefix,
                "declared_by": anchor,
                "repo_ids": sorted(ctx.contract_repos[node_id]),
            }))
            ctx.count("r10.datasets")

        for claim in claims:
            _emit(ctx, out, claim, node_id, key, anchor)
    return out


def _emit(ctx: LinkContext, out: ResolverOutput, claim: ClaimRecord,
          node_id: str, key: str, anchor: str) -> None:
    declares = bool(claim.attrs.get("declares"))
    if declares:
        tier, counter = "declared", "r10.declared"
    elif claim.attrs.get("inferred"):
        tier, counter = "inferred", "r10.inferred"
    else:
        tier, counter = "literal", ("r10.writes"
                                    if claim.direction == "provides"
                                    else "r10.reads")
    confidence = ctx.conf("r10", tier)
    edge_type = "WRITES_TO" if claim.direction == "provides" else "READS_FROM"
    via = str(claim.attrs.get("system") or claim.attrs.get("source") or "data")
    ctx.count(counter)

    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
        source_label="ContractClaim", target_label="Dataset",
        confidence=confidence, match_type=f"dataset_{tier}",
        evidence=claim.evidence, claim_key=key,
        source_repo=claim.repo_id,
        origin="declared" if declares else "matched",
    ))
    if claim.evidence_node_id is None:
        ctx.count("r10.no_site_node")
        return
    extra = {"via": [via]}
    if declares:
        extra["declares"] = True
    service = ctx.module_service_name(claim.repo_id, claim.primary_path) or ""
    if service:
        extra["service"] = service
    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, edge_type, claim.evidence_node_id, node_id,
        source_label="GraphNode", target_label="Dataset",
        confidence=confidence, match_type=f"dataset_{tier}",
        evidence=claim.evidence, claim_key=key,
        source_repo=claim.repo_id,
        target_repo=anchor if anchor and anchor != claim.repo_id else "",
        origin="declared" if declares else "matched", extra=extra,
    ))
    if service:
        service_id = ctx.service_by_name.get(ctx.canon(service))
        if service_id:
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, edge_type, service_id, node_id,
                source_label="Service", target_label="Dataset",
                confidence=confidence, match_type=f"dataset_{tier}",
                evidence=claim.evidence, claim_key=key,
                source_repo=claim.repo_id, origin="matched",
                extra={"via": [via]},
            ))
