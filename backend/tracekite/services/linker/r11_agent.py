"""R11 agent contracts: MCP tools and A2A skills as ContractOperation
rendezvous.

An MCP server name plays the role a protobuf package plays for R5: the client
config says `"github": {command: ...}` and the implementation says
`FastMCP("github")` — equal spelling is the join, and a `*` consumer (a config
entry names the server, not its tools) binds to every tool the server
registers, exactly like a gRPC stub binds to every rpc of its service. A
server name registered by more than one repo is a coin flip and declines.

A2A joins twice: by agent/skill name (card vs anything naming the agent) and
by card URL against `a2a:url:` call-site claims — the URL is the stronger key
because cards are served from the agent's own origin.
"""

import logging
from collections import defaultdict

from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    linker_edge,
)
from tracekite.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.agent@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    seen: set[str] = set()
    _resolve_mcp(index, ctx, out, seen)
    _resolve_a2a(index, ctx, out, seen)
    return out


def _resolve_mcp(index: ClaimIndex, ctx: LinkContext, out: ResolverOutput,
                 seen: set[str]) -> None:
    tools_by_server: dict[str, list[ClaimRecord]] = defaultdict(list)
    server_repos: dict[str, set[str]] = defaultdict(set)
    for claim in index.provides("mcpop"):
        server = str(claim.attrs.get("server") or "")
        if not server:
            continue
        tools_by_server[server].append(claim)
        server_repos[server].add(claim.repo_id)

    for server, claims in sorted(tools_by_server.items()):
        if len(server_repos[server]) > 1:
            # Two repos both registering FastMCP("github"): picking an owner
            # would be a coin flip.
            ctx.count("r11.ambiguous_server")
            continue
        for claim in claims:
            node_id = rid.agent_operation_id(claim.key)
            ctx.contract_repos[node_id].add(claim.repo_id)
            if node_id not in seen:
                seen.add(node_id)
                out.rendezvous.append(RendezvousSpec(
                    "ContractOperation", node_id, {
                        "protocol": "mcp", "key": claim.key,
                        "service": server,
                        "rpc": str(claim.attrs.get("tool") or ""),
                        "op_kind": str(claim.attrs.get("op_kind") or "tool"),
                        "repo_ids": sorted(ctx.contract_repos[node_id]),
                    }))
                ctx.count("r11.mcp_tools")
            _op_edges(ctx, out, claim, node_id, "EXPOSES",
                      ctx.conf("r11", "registration"), "mcp_registration")

    for claim in index.consumes("mcpop"):
        server = str(claim.attrs.get("server")
                     or claim.key[4:].partition("/")[0])
        provider_tools = tools_by_server.get(server, [])
        if not provider_tools or len(server_repos[server]) > 1:
            ctx.count("r11.unmatched_client")
            continue
        keys = sorted({c.key for c in provider_tools})
        if len(keys) > ctx.fanout_cap:
            ctx.count("r11.fanout_exceeded")
            continue
        provider_repo = next(iter(server_repos[server]))
        for key in keys:
            node_id = rid.agent_operation_id(key)
            _op_edges(ctx, out, claim, node_id, "INVOKES",
                      ctx.conf("r11", "config"), "mcp_config",
                      target_repo=provider_repo)
        ctx.count("r11.mcp_clients_matched")


def _resolve_a2a(index: ClaimIndex, ctx: LinkContext, out: ResolverOutput,
                 seen: set[str]) -> None:
    by_url: dict[str, list[str]] = defaultdict(list)
    card_repos: dict[str, set[str]] = defaultdict(set)

    for claim in index.provides("a2aop"):
        node_id = rid.agent_operation_id(claim.key)
        agent = str(claim.attrs.get("agent") or "")
        ctx.contract_repos[node_id].add(claim.repo_id)
        card_repos[agent].add(claim.repo_id)
        if node_id not in seen:
            seen.add(node_id)
            out.rendezvous.append(RendezvousSpec(
                "ContractOperation", node_id, {
                    "protocol": "a2a", "key": claim.key,
                    "service": agent,
                    "rpc": str(claim.attrs.get("skill") or ""),
                    "url": str(claim.attrs.get("url") or ""),
                    "repo_ids": sorted(ctx.contract_repos[node_id]),
                }))
            ctx.count("r11.a2a_skills")
        _op_edges(ctx, out, claim, node_id, "EXPOSES",
                  ctx.conf("r11", "card"), "a2a_card")
        if url := str(claim.attrs.get("url") or ""):
            by_url[url].append(claim.key)

    for claim in index.consumes("a2aop"):
        if not claim.key.startswith("a2a:url:"):
            continue
        url = claim.key[len("a2a:url:"):]
        keys = by_url.get(url, [])
        if not keys:
            ctx.count("r11.a2a_url_unmatched")
            continue
        for key in sorted(set(keys)):
            node_id = rid.agent_operation_id(key)
            agent = key[4:].partition("/")[0]
            repos = card_repos.get(agent, set())
            _op_edges(ctx, out, claim, node_id, "INVOKES",
                      ctx.conf("r11", "url_resolved"), "a2a_url",
                      target_repo=(next(iter(repos))
                                   if len(repos) == 1 else ""))
        ctx.count("r11.a2a_calls_matched")


def _op_edges(ctx: LinkContext, out: ResolverOutput, claim: ClaimRecord,
              node_id: str, edge_type: str, confidence: float,
              match_type: str, target_repo: str = "") -> None:
    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
        source_label="ContractClaim", target_label="ContractOperation",
        confidence=confidence, match_type=match_type,
        evidence=claim.evidence, claim_key=claim.key,
        source_repo=claim.repo_id,
        origin="declared" if edge_type == "EXPOSES" else "matched",
    ))
    if claim.evidence_node_id is None:
        ctx.count("r11.no_site_node")
        return
    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, edge_type, claim.evidence_node_id, node_id,
        source_label="GraphNode", target_label="ContractOperation",
        confidence=confidence, match_type=match_type,
        evidence=claim.evidence, claim_key=claim.key,
        source_repo=claim.repo_id, target_repo=target_repo,
        origin="declared" if edge_type == "EXPOSES" else "matched",
        extra={"via": [match_type]},
    ))
