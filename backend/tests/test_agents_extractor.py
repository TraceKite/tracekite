"""M9 agentic surface: MCP servers/clients, A2A cards, LLM calls, vector
stores.

The join keys these extractors feed the linker are names that appear verbatim
on both sides (tool name, server name, agent url, model id, collection name),
so the tests pin exact identifiers, roles and lines — and pin the negatives:
look-alike APIs (Twilio ``messages.create``, langchain ``Tool``) must yield
nothing, and config ``env``/``headers`` blocks must never reach ``attrs``.
"""

from tracekite.services.agents_extractor import (
    AgentCard,
    LlmCallSite,
    McpToolSite,
    VectorStoreSite,
    extract_a2a_call_sites,
    extract_llm_sites,
    extract_mcp_sites,
    extract_vector_sites,
    is_agent_card_file,
    is_mcp_config_file,
    parse_agent_card,
    parse_mcp_config,
)


def _line(fixture: str, needle: str) -> int:
    return fixture[: fixture.index(needle)].count("\n") + 1


# --- MCP servers in code ----------------------------------------------------

FASTMCP_PY = '''"""GitHub MCP server."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("github")


@mcp.tool()
def create_issue(repo: str, title: str) -> str:
    """Create an issue. def-heavy docstring should not confuse capture."""
    return do(repo, title)


@mcp.tool(name="search_issues", description="search across definitions")
async def _search(query: str) -> list:
    return []


@mcp.resource("repo://{owner}/{name}/readme")
def readme(owner: str, name: str) -> str:
    return ""


@mcp.prompt()
def triage(issue: str) -> str:
    return f"triage {issue}"


if __name__ == "__main__":
    mcp.run(transport="sse")
'''

LOWLEVEL_PY = '''import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

server = Server("weather")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(name="get_forecast", inputSchema={"type": "object"}),
        types.Tool(name="get_alerts", inputSchema={"type": "object"}),
    ]


async def main():
    async with mcp.server.stdio.stdio_server() as (r, w):
        await server.run(r, w, options)
'''

TS_MCP = '''import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({ name: "payments", version: "1.0.0" });

server.tool("charge_card", { amount: z.number() }, async ({ amount }) => ({}));
server.registerTool("refund", { description: "refund a charge" }, async () => ({}));
server.resource("config", "config://app", async () => ({}));
server.prompt("dispute_letter", async () => ({}));

const transport = new StdioServerTransport();
await server.connect(transport);
'''

TS_LIST_TOOLS = '''import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  { name: "search", version: "0.1.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "web_search",
      description: "Search the web",
      inputSchema: { type: "object", properties: { query: { type: "string" } } },
    },
    { name: "news_search", description: "News", inputSchema: { type: "object" } },
  ],
}));
'''

LANGCHAIN_PY = '''from langchain.tools import Tool

calculator = Tool(name="calculator", func=run_math, description="math")
'''


class TestFastMcpServer:
    def test_all_four_kinds(self):
        sites = extract_mcp_sites("server.py", FASTMCP_PY, "python")
        assert len(sites) == 4
        assert {s.kind for s in sites} == {"tool", "resource", "prompt"}
        assert all(s.role == "provides" for s in sites)
        assert all(s.framework == "fastmcp" for s in sites)

    def test_server_name_binds_through_the_variable(self):
        sites = extract_mcp_sites("server.py", FASTMCP_PY, "python")
        assert {s.server for s in sites} == {"github"}

    def test_tool_names_kwarg_beats_function_name(self):
        tools = {s.tool for s in extract_mcp_sites("s.py", FASTMCP_PY, "python")
                 if s.kind == "tool"}
        assert tools == {"create_issue", "search_issues"}

    def test_resource_uri_and_prompt_name(self):
        sites = extract_mcp_sites("s.py", FASTMCP_PY, "python")
        resource = next(s for s in sites if s.kind == "resource")
        assert resource.tool == "repo://{owner}/{name}/readme"
        assert resource.attrs["uri"] == "repo://{owner}/{name}/readme"
        prompt = next(s for s in sites if s.kind == "prompt")
        assert prompt.tool == "triage"

    def test_transport_and_line(self):
        sites = extract_mcp_sites("s.py", FASTMCP_PY, "python")
        assert all(s.transport == "sse" for s in sites)
        create = next(s for s in sites if s.tool == "create_issue")
        assert create.line == _line(FASTMCP_PY, "@mcp.tool()")


class TestLowLevelPythonMcp:
    def test_tool_literals_under_the_named_server(self):
        sites = extract_mcp_sites("weather.py", LOWLEVEL_PY, "python")
        assert {s.tool for s in sites} == {"get_forecast", "get_alerts"}
        assert {s.server for s in sites} == {"weather"}
        assert all(s.framework == "mcp-python" and s.kind == "tool"
                   for s in sites)

    def test_stdio_transport_detected(self):
        sites = extract_mcp_sites("weather.py", LOWLEVEL_PY, "python")
        assert all(s.transport == "stdio" for s in sites)

    def test_langchain_tool_is_not_claimed(self):
        assert extract_mcp_sites("agent.py", LANGCHAIN_PY, "python") == []


class TestTsMcpServer:
    def test_register_calls(self):
        sites = extract_mcp_sites("index.ts", TS_MCP, "typescript")
        assert {(s.tool, s.kind) for s in sites} == {
            ("charge_card", "tool"), ("refund", "tool"),
            ("config", "resource"), ("dispute_letter", "prompt")}
        assert {s.server for s in sites} == {"payments"}
        assert all(s.framework == "mcp-ts" and s.role == "provides"
                   for s in sites)

    def test_stdio_transport_and_line(self):
        sites = extract_mcp_sites("index.ts", TS_MCP, "typescript")
        assert all(s.transport == "stdio" for s in sites)
        charge = next(s for s in sites if s.tool == "charge_card")
        assert charge.line == _line(TS_MCP, 'server.tool("charge_card"')

    def test_list_tools_handler_names(self):
        sites = extract_mcp_sites("index.ts", TS_LIST_TOOLS, "typescript")
        assert {s.tool for s in sites} == {"web_search", "news_search"}
        assert {s.server for s in sites} == {"search"}
        web = next(s for s in sites if s.tool == "web_search")
        assert web.line == _line(TS_LIST_TOOLS, '"web_search"')

    def test_language_inferred_from_extension(self):
        sites = extract_mcp_sites("src/index.ts", TS_MCP, None)
        assert {s.tool for s in sites} >= {"charge_card", "refund"}


# --- MCP client configs -----------------------------------------------------

CLAUDE_CONFIG = '''{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "ghp_SECRET_ABC123" }
    },
    "linear": {
      "url": "https://mcp.linear.app/sse",
      "headers": { "Authorization": "Bearer sk-live-SECRET-XYZ" }
    }
  }
}
'''

VSCODE_CONFIG = '''{
  // project MCP servers
  "servers": {
    "fetch": { "type": "http", "url": "https://api.example.com/mcp" },
  }
}
'''


class TestMcpConfig:
    def test_one_consumes_site_per_server(self):
        sites = parse_mcp_config("claude_desktop_config.json", CLAUDE_CONFIG)
        assert [s.server for s in sites] == ["github", "linear"]
        assert all(s.role == "consumes" and s.tool == "*" for s in sites)
        assert all(s.framework == "mcp-config" for s in sites)

    def test_transports_from_command_and_url(self):
        github, linear = parse_mcp_config("c.json", CLAUDE_CONFIG)
        assert github.transport == "stdio"
        assert linear.transport == "sse"          # url ends in /sse

    def test_attrs_carry_join_material(self):
        github, linear = parse_mcp_config("c.json", CLAUDE_CONFIG)
        assert github.attrs["command"] == "npx"
        assert github.attrs["arg0"] == "-y"
        assert linear.attrs["url"] == "https://mcp.linear.app/sse"
        assert github.line == _line(CLAUDE_CONFIG, '"github"')

    def test_env_and_header_secrets_never_leak(self):
        dump = repr(parse_mcp_config("c.json", CLAUDE_CONFIG))
        assert "ghp_SECRET_ABC123" not in dump
        assert "sk-live-SECRET-XYZ" not in dump
        assert "GITHUB_TOKEN" not in dump
        assert "Authorization" not in dump

    def test_vscode_servers_variant_with_jsonc(self):
        [fetch] = parse_mcp_config(".vscode/mcp.json", VSCODE_CONFIG)
        assert fetch.server == "fetch"
        assert fetch.transport == "http"
        assert fetch.attrs["url"] == "https://api.example.com/mcp"

    def test_is_mcp_config_file(self):
        assert is_mcp_config_file("claude_desktop_config.json", CLAUDE_CONFIG)
        assert is_mcp_config_file("repo/.mcp.json", CLAUDE_CONFIG)
        assert is_mcp_config_file(".vscode/mcp.json", VSCODE_CONFIG)
        assert is_mcp_config_file("random.json", CLAUDE_CONFIG)  # body sniff
        assert not is_mcp_config_file("package.json", '{"name": "x"}')
        assert not is_mcp_config_file("mcp.yaml", CLAUDE_CONFIG)


# --- A2A --------------------------------------------------------------------

AGENT_CARD = '''{
  "name": "InvoiceAgent",
  "description": "Creates and voids invoices",
  "url": "https://agents.example.com/invoice",
  "version": "1.2.0",
  "capabilities": { "streaming": true, "pushNotifications": false },
  "skills": [
    { "id": "create-invoice", "name": "Create Invoice", "tags": ["billing"] },
    { "id": "void-invoice", "name": "Void Invoice" }
  ]
}
'''

A2A_CLIENT_PY = '''import httpx
from a2a.client import A2AClient

client = A2AClient(httpx_client=httpx.AsyncClient(),
                   url="https://agents.example.com/invoice")
resolver_based = A2AClient(url=discovered_url)
'''

A2A_CLIENT_TS = '''import { A2AClient } from "@a2a-js/sdk/client";
const client = new A2AClient("https://agents.internal/search");
'''


class TestAgentCard:
    def test_card_fields(self):
        card = parse_agent_card(".well-known/agent.json", AGENT_CARD)
        assert card.name == "InvoiceAgent"
        assert card.url == "https://agents.example.com/invoice"
        assert card.skills == ["create-invoice", "void-invoice"]
        assert card.attrs["version"] == "1.2.0"

    def test_is_agent_card_file(self):
        assert is_agent_card_file("services/billing/.well-known/agent.json")
        assert is_agent_card_file("agents/search/agent-card.json")
        assert is_agent_card_file(".well-known/agent-card.json")
        assert not is_agent_card_file("config/settings.json")

    def test_non_a2a_agent_json_is_declined(self):
        assert parse_agent_card("agent.json", '{"name": "cfg", "mode": 1}') is None

    def test_malformed_json_returns_none(self):
        assert parse_agent_card("agent.json", "{ not json") is None


class TestA2ACallSites:
    def test_python_client_with_literal_url(self):
        literal, dynamic = extract_a2a_call_sites(A2A_CLIENT_PY, "python")
        assert literal.url == "https://agents.example.com/invoice"
        assert literal.attrs["call_site"] is True
        assert literal.attrs["line"] == _line(A2A_CLIENT_PY, "client = A2AClient(")
        assert dynamic.url == "" and dynamic.attrs["dynamic"] is True

    def test_ts_client(self):
        [card] = extract_a2a_call_sites(A2A_CLIENT_TS, "typescript")
        assert card.url == "https://agents.internal/search"
        assert card.name == ""


# --- LLM SDK call sites -----------------------------------------------------

ANTHROPIC_PY = '''from anthropic import AsyncAnthropic

client = AsyncAnthropic()


async def ask(prompt: str) -> str:
    msg = await client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


async def routed(prompt: str, model_name: str) -> str:
    return await client.messages.create(model=model_name, max_tokens=64,
                                        messages=[])
'''

ANTHROPIC_TS = '''import Anthropic from "@anthropic-ai/sdk";
const anthropic = new Anthropic();
const msg = await anthropic.messages.create({
  model: "claude-haiku-4-5",
  max_tokens: 512,
  messages,
});
'''

TWILIO_PY = '''from twilio.rest import Client

client = Client(sid, token)
client.messages.create(to="+15551234", from_="+15550000", body="hello")
'''

OPENAI_PY = '''from openai import OpenAI

client = OpenAI()
resp = client.chat.completions.create(model="gpt-4o-mini", messages=history)
r2 = client.responses.create(model="o3-mini", input="hello")
'''

BEDROCK_PY = '''import boto3

brt = boto3.client("bedrock-runtime")
out = brt.invoke_model(modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
                       body=payload)
'''

BEDROCK_TS = '''import { BedrockRuntimeClient, InvokeModelCommand } from "@aws-sdk/client-bedrock-runtime";
const client = new BedrockRuntimeClient({ region: "us-east-1" });
const cmd = new InvokeModelCommand({
  modelId: "amazon.titan-text-express-v1",
  body,
});
'''

VERTEX_PY = '''import vertexai
from vertexai.generative_models import GenerativeModel

vertexai.init(project="petclinic", location="us-central1")
model = GenerativeModel("gemini-1.5-pro")
'''

AZURE_PY = '''from openai import AzureOpenAI

client = AzureOpenAI(azure_endpoint="https://myco.openai.azure.com",
                     azure_deployment="gpt-4o-prod",
                     api_version="2024-06-01")
resp = client.chat.completions.create(model="gpt-4o-prod", messages=history)
'''


class TestLlmSites:
    def test_anthropic_python_literal_and_dynamic(self):
        literal, dynamic = extract_llm_sites(ANTHROPIC_PY, "python")
        assert literal.provider == "anthropic"
        assert literal.model == "claude-sonnet-4-5"
        assert literal.framework == "anthropic-sdk"
        assert literal.line == _line(ANTHROPIC_PY, "msg = await client.messages")
        assert dynamic.model == "" and dynamic.attrs["dynamic"] is True
        assert dynamic.attrs["model_expr"] == "model_name"

    def test_anthropic_ts(self):
        [site] = extract_llm_sites(ANTHROPIC_TS, "typescript")
        assert (site.provider, site.model) == ("anthropic", "claude-haiku-4-5")

    def test_twilio_messages_create_is_not_anthropic(self):
        assert extract_llm_sites(TWILIO_PY, "python") == []

    def test_openai_chat_and_responses(self):
        chat, responses = extract_llm_sites(OPENAI_PY, "python")
        assert (chat.provider, chat.model) == ("openai", "gpt-4o-mini")
        assert (responses.provider, responses.model) == ("openai", "o3-mini")
        assert chat.framework == "openai-sdk"

    def test_bedrock_python(self):
        [site] = extract_llm_sites(BEDROCK_PY, "python")
        assert site.provider == "bedrock"
        assert site.model == "anthropic.claude-3-5-sonnet-20241022-v2:0"
        assert site.framework == "boto3"

    def test_bedrock_ts_command(self):
        [site] = extract_llm_sites(BEDROCK_TS, "typescript")
        assert site.provider == "bedrock"
        assert site.model == "amazon.titan-text-express-v1"
        assert site.framework == "aws-sdk-js"

    def test_vertex_generative_model(self):
        [site] = extract_llm_sites(VERTEX_PY, "python")
        assert (site.provider, site.model) == ("vertex", "gemini-1.5-pro")
        assert site.framework == "vertexai"

    def test_azure_deployment_reclassifies_the_file(self):
        sites = extract_llm_sites(AZURE_PY, "python")
        assert {s.provider for s in sites} == {"azure-openai"}
        ctor = next(s for s in sites if s.attrs.get("deployment"))
        assert ctor.model == "gpt-4o-prod"
        chat = next(s for s in sites if not s.attrs.get("deployment"))
        assert chat.model == "gpt-4o-prod"


# --- vector stores ----------------------------------------------------------

PINECONE_PY = '''from pinecone import Pinecone

pc = Pinecone(api_key=key)
index = pc.Index("products")


def ingest(vectors):
    index.upsert(vectors=vectors, namespace="catalog")


def lookup(q):
    return index.query(vector=q, top_k=5)
'''

QDRANT_PY = '''from qdrant_client import QdrantClient

client = QdrantClient(url="http://qdrant:6333")
client.upsert(collection_name="support-tickets", points=points)
hits = client.search(collection_name="support-tickets", query_vector=v, limit=10)
other = client.search(collection_name=routed_collection, query_vector=v)
'''

CHROMA_PY = '''import chromadb

client = chromadb.PersistentClient(path="./db")
docs = client.get_or_create_collection("kb-articles")
docs.add(documents=texts, ids=ids)
res = docs.query(query_texts=[question], n_results=3)
'''

WEAVIATE_PY = '''import weaviate

client = weaviate.connect_to_local()
articles = client.collections.get("Article")
articles.data.insert({"title": title})
resp = articles.query.near_text(query=question, limit=2)
'''

PGVECTOR_SQL = '''CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS document_embeddings (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES documents(id),
    embedding vector(1536)
);

CREATE TABLE plain_table (
    id BIGSERIAL PRIMARY KEY,
    name TEXT
);

CREATE INDEX ON document_embeddings USING hnsw (embedding vector_cosine_ops);
'''

MILVUS_PY = '''from pymilvus import Collection, connections

connections.connect(host="milvus", port="19530")
col = Collection("product_vectors")
'''


class TestVectorSites:
    def test_pinecone_declare_write_read(self):
        sites = extract_vector_sites(PINECONE_PY, "python")
        assert {(s.role, s.collection) for s in sites} == {
            ("declares", "products"), ("writes", "products"),
            ("reads", "products")}
        assert {s.system for s in sites} == {"pinecone"}
        reads = next(s for s in sites if s.role == "reads")
        assert reads.line == _line(PINECONE_PY, "index.query(")

    def test_qdrant_kwarg_collections(self):
        sites = extract_vector_sites(QDRANT_PY, "python")
        assert (VectorStoreSite("qdrant", "support-tickets", "writes",
                                _line(QDRANT_PY, "client.upsert("))
                in sites)
        assert ("qdrant", "support-tickets", "reads") in {
            (s.system, s.collection, s.role) for s in sites}
        dynamic = next(s for s in sites if s.collection == "")
        assert dynamic.attrs["dynamic"] is True and dynamic.role == "reads"

    def test_chroma_tracked_handle(self):
        sites = extract_vector_sites(CHROMA_PY, "python")
        assert {(s.role, s.collection) for s in sites} == {
            ("declares", "kb-articles"), ("writes", "kb-articles"),
            ("reads", "kb-articles")}

    def test_weaviate_collection_and_ops(self):
        sites = extract_vector_sites(WEAVIATE_PY, "python")
        assert {(s.system, s.role) for s in sites} == {
            ("weaviate", "declares"), ("weaviate", "writes"),
            ("weaviate", "reads")}
        assert {s.collection for s in sites} == {"Article"}

    def test_pgvector_only_vector_tables(self):
        [site] = extract_vector_sites(PGVECTOR_SQL, "sql")
        assert site.system == "pgvector"
        assert site.collection == "document_embeddings"
        assert site.role == "declares"

    def test_pgvector_embedded_in_migration(self):
        migration = ('def upgrade():\n    op.execute("""CREATE TABLE '
                     'item_embeddings (id bigint, embedding vector(768));""")\n')
        [site] = extract_vector_sites(migration, "python")
        assert site.collection == "item_embeddings"

    def test_milvus_requires_pymilvus(self):
        [site] = extract_vector_sites(MILVUS_PY, "python")
        assert (site.system, site.collection, site.role) == (
            "milvus", "product_vectors", "declares")
        assert extract_vector_sites(
            'col = Collection("stuff")\ncol.load()', "python") == []


# --- malformed input never raises -------------------------------------------

JUNK = "\x00\xffdef (((]]]{{{ mcpServers FastMCP anthropic pinecone " * 50


class TestMalformedInput:
    def test_extractors_swallow_junk(self):
        assert extract_mcp_sites("x.bin", JUNK, None) == []
        assert extract_llm_sites(JUNK, None) == []
        assert extract_vector_sites(JUNK, None) == []
        assert extract_a2a_call_sites(JUNK, None) == []

    def test_config_and_card_parsers_swallow_junk(self):
        assert parse_mcp_config("mcp.json", "{ broken json") == []
        assert parse_mcp_config("mcp.json", '{"mcpServers": "nope"}') == []
        assert parse_agent_card("agent.json", JUNK) is None

    def test_truncated_call_is_bounded(self):
        truncated = 'from anthropic import Anthropic\nc.messages.create(model="claude-x", ' \
                    + "x" * 10000
        [site] = extract_llm_sites(truncated, "python")
        assert site.model == "claude-x"
