"""R6 topic resolver: join producers and consumers at Topic rendezvous nodes.

Messaging is deliberately decoupled — a producer never names its consumers —
so unlike R7 there is no service hint to disambiguate with and none is needed:
the topic name IS the rendezvous. What makes topics hard is *indirection*:
half of real-world destinations come from env vars or config placeholders, so
R6 resolves `kafka:env:ORDERS_TOPIC` claims against the env-value index that
R9 builds. Config values are redacted at ingest (Invariant 6), so that join
runs on `redaction.hmac16` equality: a code literal's hmac is computed at link
time and matched against the stored hmac of the config value — the value
itself never enters the graph. Two env-indirected sides that share a config
value can even join with *no* literal anywhere; the rendezvous is then keyed
by the hmac and displayed redacted.

Emits Topic rendezvous nodes plus PUBLISHES_TO / CONSUMES_FROM (site -> topic,
and Service -> topic when the site's module resolves), DECLARES_TOPIC for
IaC/AsyncAPI/Avro declarations, and FANS_OUT_TO for SNS->SQS subscriptions.
"""

import logging
from collections import defaultdict

from evigraph.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    linker_edge,
)
from evigraph.services.redaction import hmac16
from evigraph.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.topic@1"

# Systems an AsyncAPI document without a recognizable protocol falls into;
# folded onto a concrete system when exactly one claims the same name.
_UNKNOWN_SYSTEM = "channel"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    seen: set[str] = set()

    literal, indirect, fan_out = _split_claims(index, ctx)
    literal = _fold_unknown_system(literal, ctx)
    hmac_of = _hmac_index(literal)

    for key, claims in sorted(literal.items()):
        _emit_topic(ctx, out, seen, key, claims)

    _resolve_indirect(ctx, out, seen, indirect, literal, hmac_of)
    _emit_fan_out(ctx, out, seen, fan_out, literal)
    return out


def _split_claims(index: ClaimIndex, ctx: LinkContext):
    literal: dict[str, list[ClaimRecord]] = defaultdict(list)
    indirect: list[ClaimRecord] = []
    fan_out: list[ClaimRecord] = []

    for claim in index.kind("topic"):
        if not claim.matchable:
            # A dynamic destination is a visible recall gap, not a silent one.
            ctx.count("r6.dynamic_unlinked")
            continue
        if claim.attrs.get("fan_out"):
            fan_out.append(claim)
            continue
        system, _, name = claim.key.partition(":")
        if name.startswith(("env:", "cfg:")):
            indirect.append(claim)
        elif system and name:
            literal[claim.key].append(claim)
    return literal, indirect, fan_out


def _fold_unknown_system(literal: dict, ctx: LinkContext) -> dict:
    """`channel:orders` (AsyncAPI, protocol unknown) joins `kafka:orders` when
    exactly one concrete system uses that name; two candidates would be a coin
    flip, so those stay on their own rendezvous and are counted."""
    by_name: dict[str, set[str]] = defaultdict(set)
    for key in literal:
        system, _, name = key.partition(":")
        if system != _UNKNOWN_SYSTEM:
            by_name[name].add(system)

    folded: dict[str, list[ClaimRecord]] = defaultdict(list)
    for key, claims in literal.items():
        system, _, name = key.partition(":")
        if system == _UNKNOWN_SYSTEM:
            targets = by_name.get(name, set())
            if len(targets) == 1:
                ctx.count("r6.channel_folded")
                folded[f"{targets.pop()}:{name}"].extend(claims)
                continue
            if len(targets) > 1:
                ctx.count("r6.channel_ambiguous")
        folded[key].extend(claims)
    return folded


def _hmac_index(literal: dict) -> dict[tuple[str, str], str]:
    """(system, hmac16(name)) -> full literal key, for redacted-value joins."""
    table: dict[tuple[str, str], str] = {}
    for key in literal:
        system, _, name = key.partition(":")
        table[(system, hmac16(name))] = key
    return table


def _emit_topic(ctx: LinkContext, out: ResolverOutput, seen: set[str],
                key: str, claims: list[ClaimRecord],
                redacted: bool = False) -> str:
    system, _, name = key.partition(":")
    node_id = rid.topic_id(key)
    for claim in claims:
        ctx.contract_repos[node_id].add(claim.repo_id)

    if node_id not in seen:
        seen.add(node_id)
        out.rendezvous.append(RendezvousSpec("Topic", node_id, {
            "system": system,
            "key": key,
            "name": f"#{name[1:9]}" if redacted else name,
            "redacted": redacted,
            "repo_ids": sorted(ctx.contract_repos[node_id]),
        }))
        ctx.count("r6.topics")

    for claim in claims:
        _emit_claim_edges(ctx, out, claim, node_id, key,
                          tier="declared" if claim.attrs.get("declares")
                          else "literal")
    return node_id


def _emit_claim_edges(ctx: LinkContext, out: ResolverOutput,
                      claim: ClaimRecord, node_id: str, key: str,
                      tier: str) -> None:
    confidence = ctx.conf("r6", tier)
    declares = bool(claim.attrs.get("declares"))
    if declares:
        edge_type = "DECLARES_TOPIC"
        ctx.count("r6.declared")
    elif claim.direction == "provides":
        edge_type = "PUBLISHES_TO"
        ctx.count("r6.publishers")
    else:
        edge_type = "CONSUMES_FROM"
        ctx.count("r6.consumers")

    match_type = f"topic_{tier}"
    via = str(claim.attrs.get("source") or claim.attrs.get("framework") or "code")
    provider_repos = sorted(ctx.contract_repos.get(node_id, set()) - {claim.repo_id})

    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
        source_label="ContractClaim", target_label="Topic",
        confidence=confidence, match_type=match_type,
        evidence=claim.evidence, claim_key=key,
        source_repo=claim.repo_id, origin="declared" if declares else "matched",
    ))
    if claim.evidence_node_id is None:
        ctx.count("r6.no_site_node")
        return

    service = _site_service(ctx, claim)
    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, edge_type, claim.evidence_node_id, node_id,
        source_label="GraphNode", target_label="Topic",
        confidence=confidence, match_type=match_type,
        evidence=claim.evidence, claim_key=key,
        source_repo=claim.repo_id,
        target_repo=provider_repos[0] if len(provider_repos) == 1 else "",
        origin="declared" if declares else "matched",
        extra={"via": [via], "service": service},
    ))
    # Service-level rollup so the map can show service -> topic directly.
    # Every failure below is counted: this rollup silently produced nothing on
    # the live estate (24 file-level edges, 0 service-level) and there was no
    # counter to say which condition had failed.
    if not declares:
        if not service:
            ctx.count("r6.rollup_no_site_service")
        else:
            service_id = ctx.service_by_name.get(ctx.canon(service))
            if not service_id:
                ctx.count("r6.rollup_service_unknown")
            else:
                out.edges.append(linker_edge(
                    ctx, RESOLVER_ID, edge_type, service_id, node_id,
                    source_label="Service", target_label="Topic",
                    confidence=confidence, match_type=match_type,
                    evidence=claim.evidence, claim_key=key,
                    source_repo=claim.repo_id, origin="matched",
                    extra={"via": [via]},
                ))
                ctx.count("r6.rollup_service_edges")


def _site_service(ctx: LinkContext, claim: ClaimRecord) -> str:
    declared = str(claim.attrs.get("service") or "")
    if declared:
        return declared
    return ctx.module_service_name(claim.repo_id, claim.primary_path) or ""


def _resolve_indirect(ctx: LinkContext, out: ResolverOutput, seen: set[str],
                      indirect: list[ClaimRecord], literal: dict,
                      hmac_of: dict) -> None:
    """`kafka:env:VAR` / `kafka:cfg:prop` -> a concrete topic, or a decline."""
    for claim in indirect:
        system, _, rest = claim.key.partition(":")
        namespace, _, ref = rest.partition(":")

        if namespace == "env":
            candidates = [v for (_, name), v in ctx.env_values.items()
                          if name == ref]
        else:
            candidates = _config_candidates(ctx, ref)
        if not candidates:
            ctx.count(f"r6.{namespace}_unresolved")
            continue

        resolved: set[str] = set()
        for value in candidates:
            found = hmac_of.get((system, getattr(value, "value_hmac", "") or ""))
            if found:
                resolved.add(found)
            elif getattr(value, "value_class", "") == "hostname" \
                    and getattr(value, "value_host", ""):
                # Dotted topic names (`orders.created.v1`) classify as
                # hostnames, so the spelling itself survived redaction.
                resolved.add(f"{system}:{value.value_host}")
            elif getattr(value, "value_hmac", ""):
                resolved.add(f"{system}:#{value.value_hmac}")

        if len(resolved) > 1:
            # The same variable names different topics per environment/file.
            ctx.count("r6.ambiguous_across_envs")
            continue
        if not resolved:
            ctx.count(f"r6.{namespace}_unresolved")
            continue

        key = resolved.pop()
        redacted = key.partition(":")[2].startswith("#")
        node_id = rid.topic_id(key)
        if node_id not in seen:
            _emit_topic(ctx, out, seen, key, [], redacted=redacted)
        ctx.contract_repos[node_id].add(claim.repo_id)
        ctx.count(f"r6.{namespace}_resolved")
        _emit_claim_edges(ctx, out, claim, node_id, key, tier="env_resolved")


def _config_candidates(ctx: LinkContext, prop: str) -> list:
    """cfgdef claims defining a `${prop}` placeholder, matched by config key."""
    return [v for (_, name), v in ctx.env_values.items()
            if name == prop or name.endswith(f"/{prop}")]


def _emit_fan_out(ctx: LinkContext, out: ResolverOutput, seen: set[str],
                  fan_out: list[ClaimRecord], literal: dict) -> None:
    """SNS->SQS subscription: topic-to-topic wiring, declared in IaC."""
    for claim in fan_out:
        source_key = claim.key
        target_key = str(claim.attrs.get("subscriber_key") or "")
        if not target_key:
            continue
        source_id = rid.topic_id(source_key)
        target_id = rid.topic_id(target_key)
        for key, node_id in ((source_key, source_id), (target_key, target_id)):
            if node_id not in seen:
                _emit_topic(ctx, out, seen, key, [])
            ctx.contract_repos[node_id].add(claim.repo_id)
        ctx.count("r6.fan_out")
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "FANS_OUT_TO", source_id, target_id,
            source_label="Topic", target_label="Topic",
            confidence=ctx.conf("r6", "fanout"), match_type="sns_subscription",
            evidence=claim.evidence, claim_key=source_key,
            source_repo=claim.repo_id, origin="declared",
            extra={"via": ["terraform"]},
        ))
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, target_id,
            source_label="ContractClaim", target_label="Topic",
            confidence=ctx.conf("r6", "fanout"), match_type="sns_subscription",
            evidence=claim.evidence, claim_key=target_key,
            source_repo=claim.repo_id, origin="declared",
        ))
