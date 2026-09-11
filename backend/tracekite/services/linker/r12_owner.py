"""R12 ownership: join teams to what they own at Team rendezvous nodes.

Three sources make ownership statements and they disagree in predictable
ways: a Backstage catalog names a *service's* owner, CODEOWNERS names a
*path's* owner, and Datadog tags name a *deployment's* team. All reduce to
Team rendezvous plus OWNED_BY edges — Repo-level always (the claim lives in a
repo), Service-level when the named entity resolves to a minted Service.
A catalog entity that names no resolvable service is counted, not guessed:
attributing a team to the wrong service misroutes a pager.
"""

import logging
from collections import defaultdict

from tracekite.services.linker.base import (
    ClaimIndex, LinkContext, RendezvousSpec, ResolverOutput, linker_edge,
)
from tracekite.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.owner@1"

_SOURCE_TIER = {"backstage": "catalog", "codeowners": "codeowners"}


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    seen: set[str] = set()
    repo_edges: set[tuple[str, str]] = set()

    for claim in index.provides("owner"):
        team = str(claim.attrs.get("team") or "")
        if not team or not claim.key.startswith("team:"):
            continue
        node_id = rid.team_id(claim.key)
        if node_id not in seen:
            seen.add(node_id)
            out.rendezvous.append(RendezvousSpec("Team", node_id, {
                "key": claim.key, "name": team,
            }))
            ctx.count("r12.teams")

        tier = _SOURCE_TIER.get(str(claim.attrs.get("source") or ""),
                                "observability")
        confidence = ctx.conf("r12", tier)

        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
            source_label="ContractClaim", target_label="Team",
            confidence=confidence, match_type=tier,
            evidence=claim.evidence, claim_key=claim.key,
            source_repo=claim.repo_id, origin="declared",
        ))

        if (claim.repo_id, node_id) not in repo_edges:
            repo_edges.add((claim.repo_id, node_id))
            extra = {"via": [str(claim.attrs.get("source") or "owner")]}
            if pattern := claim.attrs.get("pattern"):
                extra["pattern"] = str(pattern)
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, "OWNED_BY", claim.repo_id, node_id,
                source_label="Repo", target_label="Team",
                confidence=confidence, match_type=tier,
                evidence=claim.evidence, claim_key=claim.key,
                source_repo=claim.repo_id, origin="declared", extra=extra,
            ))
            ctx.count("r12.repo_owned")

        entity = str(claim.attrs.get("entity") or claim.service_hint or "")
        if entity:
            service_id = ctx.service_by_name.get(ctx.canon(entity))
            if service_id:
                out.edges.append(linker_edge(
                    ctx, RESOLVER_ID, "OWNED_BY", service_id, node_id,
                    source_label="Service", target_label="Team",
                    confidence=confidence, match_type=tier,
                    evidence=claim.evidence, claim_key=claim.key,
                    source_repo=claim.repo_id, origin="declared",
                    extra={"via": [str(claim.attrs.get("source") or "owner")],
                           "pagerduty_service":
                               str(claim.attrs.get("pagerduty_service") or ""),
                           "opsgenie_team":
                               str(claim.attrs.get("opsgenie_team") or "")},
                ))
                ctx.count("r12.service_owned")
            else:
                ctx.count("r12.entity_unresolved")
    return out
