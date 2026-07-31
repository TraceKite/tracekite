"""M9 agents: MCP/A2A extraction -> claims -> R11 -> agent-surface edges.

The MCP server name is the join key — the client config names the server, the
implementation registers under it — with the same *-fans-to-all-tools
semantics a gRPC stub has, and the same ambiguity discipline: two repos
claiming one server name is a declined coin flip.
"""

from types import SimpleNamespace

from adduce.parsers.parser_registry import parse_file
from adduce.services.agents_extractor import parse_agent_card, parse_mcp_config
from adduce.services.ingest_claims import (
    emit_agent_card_claims, emit_agent_claims, emit_mcp_config_claims,
)
from adduce.services.ingest_source import IngestSink
from adduce.services.linker import r11_agent
from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, load_confidence,
)

FASTMCP_SERVER = '''
from fastmcp import FastMCP

mcp = FastMCP("github")

@mcp.tool()
def create_issue(title: str) -> str:
    """Create an issue."""
    return title

@mcp.tool(name="list_prs")
def list_pull_requests() -> list:
    return []
'''

MCP_CONFIG = """
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@acme/github-mcp"],
      "env": {"GITHUB_TOKEN": "secret-token-value"}
    },
    "search": {"url": "https://search.internal/mcp"}
  }
}
"""

AGENT_CARD = """
{
  "name": "billing-agent",
  "url": "https://agents.acme.io/billing/",
  "skills": [{"id": "issue_refund"}, {"id": "explain_charge"}]
}
"""

A2A_CALLER = """
from a2a.client import A2AClient

client = A2AClient(url="https://agents.acme.io/billing")
"""

LLM_AND_VECTOR = """
import anthropic
import pinecone

client = anthropic.Anthropic()
msg = client.messages.create(model="claude-sonnet-5", max_tokens=100,
                             messages=[])

pc = pinecone.Pinecone()
index = pc.Index("products")
index.upsert(vectors=[])
"""


def _file(path, language=None):
    return SimpleNamespace(path=path, language=language)


def _claims(sink, repo_id):
    records = []
    for node in sink.nodes:
        if node.type != "ContractClaim":
            continue
        extra = node.extra_props
        records.append(ClaimRecord(
            id=node.id, repo_id=repo_id, kind=extra["kind"],
            direction=extra["direction"], key=extra["key"],
            service_hint=extra.get("service_hint"),
            hint_source=extra.get("hint_source", "none"),
            matchable=bool(extra.get("matchable", True)),
            evidence=list(extra.get("evidence") or []),
            attrs=dict(node.metadata or {}),
            evidence_node_id=f"node:{node.id}", evidence_node_type="File",
        ))
    return records


def _server_claims(repo_id="repo_mcp"):
    sink = IngestSink()
    emit_agent_claims(repo_id, _file("server.py", "python"), FASTMCP_SERVER,
                      "file:server", sink)
    return _claims(sink, repo_id)


def _config_claims(repo_id="repo_client"):
    sink = IngestSink()
    sites = parse_mcp_config(".mcp.json", MCP_CONFIG)
    emit_mcp_config_claims(repo_id, _file(".mcp.json"), sites, "file:cfg", sink)
    return _claims(sink, repo_id)


def run_linker(claims):
    ctx = LinkContext("linkrun_test", load_confidence(), {})
    ctx.known_repos = {c.repo_id for c in claims}
    out = ResolverOutput()
    out.extend(r11_agent.resolve(ClaimIndex(claims), ctx))
    return ctx, out


class TestMcpJoin:
    def test_registrations_become_operations(self):
        ctx, out = run_linker(_server_claims())
        keys = {r.props["key"] for r in out.rendezvous}
        assert keys == {"mcp:github/create_issue", "mcp:github/list_prs"}
        assert ctx.counters["r11.mcp_tools"] == 2

    def test_config_star_fans_to_every_tool(self):
        ctx, out = run_linker(_server_claims() + _config_claims())
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert {e.target_id for e in invokes} == {
            "global:Op:mcp:github/create_issue",
            "global:Op:mcp:github/list_prs"}
        assert all(e.target_repo_id == "repo_mcp" for e in invokes)
        assert all(e.cross_repo for e in invokes)
        # The `search` server has no ingested implementation: counted.
        assert ctx.counters["r11.unmatched_client"] == 1

    def test_two_repos_same_server_name_declines(self):
        ctx, out = run_linker(_server_claims("repo_a")
                              + _server_claims("repo_b") + _config_claims())
        assert ctx.counters["r11.ambiguous_server"] >= 1
        assert not [e for e in out.edges if e.type == "INVOKES"]

    def test_config_secrets_never_reach_claims(self):
        claims = _config_claims()
        assert "secret-token-value" not in str([c.attrs for c in claims])
        assert "GITHUB_TOKEN" not in str([c.attrs for c in claims])


class TestA2aJoin:
    def test_card_declares_and_url_call_joins(self):
        sink = IngestSink()
        card = parse_agent_card(".well-known/agent.json", AGENT_CARD)
        emit_agent_card_claims("repo_billing", _file(".well-known/agent.json"),
                               card, "file:card", sink)
        provider = _claims(sink, "repo_billing")

        caller = IngestSink()
        emit_agent_claims("repo_support", _file("src/call.py", "python"),
                          A2A_CALLER, "file:caller", caller)
        ctx, out = run_linker(provider + _claims(caller, "repo_support"))

        skills = {r.props["key"] for r in out.rendezvous}
        assert skills == {"a2a:billing-agent/issue_refund",
                          "a2a:billing-agent/explain_charge"}
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert invokes and all(e.match_type == "a2a_url" for e in invokes)
        assert all(e.target_repo_id == "repo_billing" for e in invokes)
        assert ctx.counters["r11.a2a_calls_matched"] == 1


class TestInventoryClaims:
    def test_llm_and_vector_sites_claim(self):
        sink = IngestSink()
        emit_agent_claims("repo_ai", _file("src/ai.py", "python"),
                          LLM_AND_VECTOR, "file:ai", sink)
        claims = _claims(sink, "repo_ai")
        llm = [c for c in claims if c.key.startswith("llm:")]
        assert llm and llm[0].key == "llm:anthropic:claude-sonnet-5"
        vector = [c for c in claims if c.key.startswith("vector:")]
        assert vector and vector[0].key == "vector:pinecone:products"
        assert vector[0].direction == "provides"    # upsert writes


class TestRegistryDispatch:
    def test_mcp_config_and_card_route_through_parse_file(self):
        result = parse_file(".mcp.json", MCP_CONFIG)
        assert result["mcp_config"] and len(result["mcp_config"]) == 2
        result = parse_file("static/.well-known/agent.json", AGENT_CARD)
        assert result["agent_card"] is not None
        assert result["agent_card"].name == "billing-agent"
