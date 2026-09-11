"""Agentic-surface sites: MCP servers/clients, A2A cards, LLM calls, vector
stores.

Agent topology never shows up in HTTP call graphs or K8s manifests: the joins
live in tool names and server names (MCP), agent URLs and skill ids (A2A),
model ids (LLM SDKs), and index/collection names (vector stores). These
extractors record both halves of each surface — who *provides* a tool and who
*consumes* a server, which agents exist and who calls them, which models a
repo depends on, and which vector collections it reads or writes — so the
linker can meet them the same way gRPC sites meet on the service name.

Precision-first, as in messaging_extractor: a fabricated tool or collection
name creates a false edge, which is worse than no edge. Dynamic names yield an
empty identifier plus ``dynamic=True`` in ``attrs``; we never chase
assignments. Framework-distinctive idioms are additionally gated on an import
or package mention in the file (``FastMCP``, ``@modelcontextprotocol``,
``anthropic``, ``pinecone``, ``pymilvus``, ...) so look-alike APIs from other
libraries (Twilio ``messages.create``, langchain ``Tool(name=...)``) are never
claimed.

Secrets rule: MCP client configs carry credentials in ``env`` and ``headers``.
``parse_mcp_config`` builds ``attrs`` from a whitelist (command, first arg,
url, type) and never reads those blocks, so a config can be ingested without
leaking a token into the graph.

Regex rather than AST for the same reason as env_extractor: these are
single-expression idioms stable across SDK versions, and a file with a partial
parse must still yield its sites.
"""

import json
import re
from dataclasses import dataclass, field

# --- shared helpers ---------------------------------------------------------

# Bound on how far a call's argument scan may run; a missing close paren must
# not turn extraction into an O(file) walk per site.
_MAX_ARGS = 4000

# Whole-argument string literal at the start of an argument list.
_FIRST_STR_ARG = re.compile(r"\s*[\"']([^\"']+)[\"']")
_HTTP_URL_LIT = re.compile(r"[\"'`](https?://[^\"'`\s]+)[\"'`]")


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def _call_args(content: str, open_paren: int) -> str:
    """Text between a call's parentheses: depth-balanced, roughly string-aware,
    bounded by ``_MAX_ARGS``. ``open_paren`` must index the ``(`` itself."""
    depth = 0
    quote = ""
    i = open_paren
    end = min(len(content), open_paren + _MAX_ARGS)
    while i < end:
        ch = content[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return content[open_paren + 1:i]
        i += 1
    return content[open_paren + 1:end]


def _kwarg(args: str, *names: str) -> tuple[str, bool, str]:
    """(literal_value, key_present, raw_expr) for the first of ``names`` found.

    ``model="claude-x"`` / ``model: 'claude-x'`` -> ("claude-x", True, ...).
    ``model=settings.model`` / ``model: MODEL`` -> ("", True, "settings.model").
    Key absent -> ("", False, ""). An f-string or template literal falls into
    the dynamic branch because the quote is not the first character.
    """
    for name in names:
        lit = re.search(rf"\b{name}\s*[:=]\s*([\"'])([^\"'\n]*)\1", args)
        if lit:
            return lit.group(2), True, lit.group(2)
        dyn = re.search(rf"\b{name}\s*[:=]\s*([^,)\n}}]+)", args)
        if dyn:
            return "", True, dyn.group(1).strip()
    return "", False, ""


# --- MCP (servers, client configs + transports) -----------------------------

@dataclass
class McpToolSite:
    """One MCP tool/resource/prompt provided by a server, or one server
    consumed by a client config."""
    server: str        # server name ("" when not stated in-file)
    tool: str          # tool/resource/prompt name
    kind: str          # "tool" | "resource" | "prompt"
    role: str          # "provides" (server registration) | "consumes" (client)
    line: int
    framework: str     # fastmcp | mcp-python | mcp-ts | mcp-config
    transport: str = ""    # stdio | sse | http | ""
    attrs: dict = field(default_factory=dict)


# Python FastMCP: `mcp = FastMCP("github")`, `@mcp.tool()`, `@mcp.resource(uri)`.
_PY_FASTMCP_NAMED = re.compile(
    r"\b(\w+)\s*=\s*FastMCP\s*\(\s*(?:name\s*=\s*)?[\"']([^\"']+)[\"']")
_PY_FASTMCP_ANY = re.compile(r"\b(\w+)\s*=\s*FastMCP\s*\(")
# \b after the alternation keeps `@mcp.tools`/`@mcp.tool_router` unmatched.
_PY_FASTMCP_DECOR = re.compile(r"@(\w+)\.(tool|resource|prompt)\b\s*(\()?")
_PY_DEF_AFTER = re.compile(r"(?:async\s+)?\bdef\s+(\w+)\s*\(")
_PY_MCP_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:mcp|fastmcp)\b", re.M)
_PY_NAME_KWARG = re.compile(r"\bname\s*=\s*[\"']([^\"']+)[\"']")
# `mcp.run(transport="sse")` — only an explicit literal counts.
_PY_RUN_TRANSPORT = re.compile(r"\.run\s*\(\s*transport\s*=\s*[\"']([\w-]+)[\"']")
# Low-level python SDK: `server = Server("weather")` + `types.Tool(name=...)`.
_PY_SERVER_NAMED = re.compile(r"\b(\w+)\s*=\s*Server\s*\(\s*[\"']([^\"']+)[\"']")
_PY_TYPES_DEF = re.compile(r"\b(?:types\.)?(Tool|Resource|Prompt)\s*\(")

# TypeScript SDK. The whole scan is gated on "@modelcontextprotocol" (or an
# unambiguous `new McpServer(`) so `new Server(`/`x.tool(` elsewhere never fire.
_TS_MCP_GATE = "@modelcontextprotocol"
_TS_SERVER_NEW = re.compile(
    r"(?:(?:const|let|var)\s+(\w+)\s*=\s*)?\bnew\s+(?:McpServer|Server)\s*\(")
# Longer method names first: `.tool(` must not shadow `.registerTool(`.
_TS_REGISTER = re.compile(
    r"\b(\w+)\.(registerTool|registerResource|registerPrompt|tool|resource|prompt)"
    r"\s*\(\s*[\"']([^\"']+)[\"']")
_TS_LIST_TOOLS = re.compile(r"setRequestHandler\s*\(\s*ListToolsRequestSchema")
_TS_TOOLS_ARRAY = re.compile(r"\btools\s*:\s*\[")
# `name: "x"` — a JSON-schema property named `name` is followed by `{`, not a
# quote, so tool-name capture inside inputSchema stays safe.
_TS_NAME_PROP = re.compile(r"\bname\s*:\s*[\"']([^\"']+)[\"']")
_TS_TRANSPORTS = (
    (re.compile(r"\bnew\s+StdioServerTransport\b"), "stdio"),
    (re.compile(r"\bnew\s+SSEServerTransport\b"), "sse"),
    (re.compile(r"\bnew\s+StreamableHTTPServerTransport\b"), "http"),
)

_MCP_CONFIG_NAMES = {"mcp.json", ".mcp.json", "claude_desktop_config.json"}
_KIND_BY_METHOD = {
    "tool": "tool", "registertool": "tool",
    "resource": "resource", "registerresource": "resource",
    "prompt": "prompt", "registerprompt": "prompt",
}


def _norm_transport(value: str) -> str:
    value = value.lower()
    if value in ("stdio", "sse"):
        return value
    if "http" in value:
        return "http"
    return ""


def extract_mcp_sites(file_path: str, content: str,
                      language: str | None) -> list[McpToolSite]:
    """MCP tool/resource/prompt registrations in one source file."""
    lang = (language or "").lower()
    if not lang:
        low_path = file_path.lower()
        if low_path.endswith(".py"):
            lang = "python"
        elif low_path.endswith((".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs",
                                ".cjs")):
            lang = "typescript"

    sites: list[McpToolSite] = []
    if lang == "python":
        _py_mcp(content, sites)
    elif lang in ("typescript", "javascript"):
        _ts_mcp(content, sites)
    else:
        _py_mcp(content, sites)
        _ts_mcp(content, sites)

    seen: set[tuple[str, str, str, str]] = set()
    unique: list[McpToolSite] = []
    for site in sites:
        key = (site.server, site.tool, site.kind, site.role)
        if key not in seen:
            seen.add(key)
            unique.append(site)
    return unique


def _py_mcp(content: str, sites: list[McpToolSite]) -> None:
    has_import = bool(_PY_MCP_IMPORT.search(content))
    has_fastmcp = "FastMCP" in content
    # Tools registered against a shared instance imported from another module
    # (`from server import mcp`) carry neither, but by convention name it mcp.
    bare_mcp = bool(re.search(r"@mcp\.(?:tool|resource|prompt)\b", content))
    if not (has_import or has_fastmcp or bare_mcp):
        return

    run = _PY_RUN_TRANSPORT.search(content)
    transport = _norm_transport(run.group(1)) if run else ""
    if not transport and "stdio_server" in content:
        transport = "stdio"

    servers: dict[str, str] = {}
    for m in _PY_FASTMCP_NAMED.finditer(content):
        servers[m.group(1)] = m.group(2)
    for m in _PY_FASTMCP_ANY.finditer(content):
        servers.setdefault(m.group(1), "")  # constructed, name dynamic -> ""

    for m in _PY_FASTMCP_DECOR.finditer(content):
        var, kind = m.group(1), m.group(2)
        if var not in servers and var != "mcp":
            continue
        args = _call_args(content, m.start(3)) if m.group(3) else ""
        named = _PY_NAME_KWARG.search(args) if args else None
        first = _FIRST_STR_ARG.match(args) if args else None
        name = named.group(1) if named else ""
        attrs: dict = {}
        if kind == "resource":
            if first:
                attrs["uri"] = first.group(1)
            name = name or (first.group(1) if first else "")
        else:
            name = name or (first.group(1) if first else "")
        if not name:
            nxt = _PY_DEF_AFTER.search(content, m.end())
            if nxt and nxt.start() - m.end() < 300:
                name = nxt.group(1)
        if not name:
            continue  # dynamic name -> decline, never guess
        sites.append(McpToolSite(
            server=servers.get(var, ""), tool=name, kind=kind, role="provides",
            line=_line_of(content, m.start()), framework="fastmcp",
            transport=transport, attrs=attrs))

    # Low-level SDK. Gated on an mcp import: `Tool(name=...)` also exists in
    # langchain and must not be claimed from a file that never imports mcp.
    if not has_import:
        return
    server_names = {name for _, name in _PY_SERVER_NAMED.findall(content)}
    server = server_names.pop() if len(server_names) == 1 else ""
    for m in _PY_TYPES_DEF.finditer(content):
        kind = m.group(1).lower()
        args = _call_args(content, m.end() - 1)
        named = _PY_NAME_KWARG.search(args)
        uri = re.search(r"\buri\s*=\s*[\"']([^\"']+)[\"']", args)
        name = named.group(1) if named else (uri.group(1) if uri else "")
        if not name:
            continue
        attrs = {"uri": uri.group(1)} if (uri and kind == "resource") else {}
        sites.append(McpToolSite(
            server=server, tool=name, kind=kind, role="provides",
            line=_line_of(content, m.start()), framework="mcp-python",
            transport=transport, attrs=attrs))


def _ts_mcp(content: str, sites: list[McpToolSite]) -> None:
    if _TS_MCP_GATE not in content and not re.search(
            r"\bnew\s+McpServer\s*\(", content):
        return

    transport = ""
    for pattern, value in _TS_TRANSPORTS:
        if pattern.search(content):
            transport = value
            break

    servers: dict[str, str] = {}
    default = ""
    for m in _TS_SERVER_NEW.finditer(content):
        named = _TS_NAME_PROP.search(_call_args(content, m.end() - 1))
        name = named.group(1) if named else ""
        if m.group(1):
            servers[m.group(1)] = name
        if name and not default:
            default = name

    for m in _TS_REGISTER.finditer(content):
        var, method, name = m.group(1), m.group(2), m.group(3)
        if var in servers:
            server = servers[var] or default
        elif var in ("server", "mcp"):
            server = default
        else:
            continue
        sites.append(McpToolSite(
            server=server, tool=name, kind=_KIND_BY_METHOD[method.lower()],
            role="provides", line=_line_of(content, m.start()),
            framework="mcp-ts", transport=transport))

    # ListTools handler: best-effort literal `name:` entries inside the
    # `tools: [...]` array the handler returns.
    for m in _TS_LIST_TOOLS.finditer(content):
        arr = _TS_TOOLS_ARRAY.search(content, m.end(), m.end() + 2500)
        if not arr:
            continue
        body = _call_args(content, arr.end() - 1)
        for prop in _TS_NAME_PROP.finditer(body):
            sites.append(McpToolSite(
                server=default, tool=prop.group(1), kind="tool",
                role="provides",
                line=_line_of(content, arr.end() + prop.start()),
                framework="mcp-ts", transport=transport))


# JSONC tolerance for IDE configs: full-line // comments and trailing commas.
# Inline // is never stripped — every https:// url contains one.
_JSONC_LINE_COMMENT = re.compile(r"^\s*//[^\n]*$", re.M)
_JSON_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _load_json(content: str):
    try:
        return json.loads(content)
    except Exception:
        pass
    try:
        cleaned = _JSON_TRAILING_COMMA.sub(
            r"\1", _JSONC_LINE_COMMENT.sub("", content))
        return json.loads(cleaned)
    except Exception:
        return None


def is_mcp_config_file(file_name: str, content: str) -> bool:
    """mcp.json / .mcp.json / claude_desktop_config.json / .vscode/mcp.json,
    or any .json whose body declares an "mcpServers" block."""
    base = file_name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    low = content.lower()
    if base in _MCP_CONFIG_NAMES:
        return '"mcpservers"' in low or '"servers"' in low
    return base.endswith(".json") and '"mcpservers"' in low


def parse_mcp_config(file_path: str, content: str) -> list[McpToolSite]:
    """One consumes-site per configured server, transport from the
    declared command/url. ``attrs`` is whitelist-built; ``env`` and
    ``headers`` are credential blocks and are never read."""
    data = _load_json(content)
    if not isinstance(data, dict):
        return []

    servers = None
    nested = data.get("mcp")
    holders = [data, nested if isinstance(nested, dict) else {}]
    for holder in holders:
        for key in ("mcpServers", "servers"):
            if isinstance(holder.get(key), dict):
                servers = holder[key]
                break
        if servers is not None:
            break
    if not servers:
        return []

    sites: list[McpToolSite] = []
    for name, cfg in servers.items():
        if not isinstance(name, str) or not isinstance(cfg, dict):
            continue
        attrs: dict = {}
        transport = ""
        command = cfg.get("command")
        url = cfg.get("url") or cfg.get("serverUrl")
        if isinstance(command, str) and command:
            transport = "stdio"
            attrs["command"] = command
            args = cfg.get("args")
            if isinstance(args, list) and args and isinstance(args[0], str):
                attrs["arg0"] = args[0]
        if isinstance(url, str) and url:
            attrs["url"] = url
            if not transport:
                declared = str(cfg.get("type") or cfg.get("transport") or "")
                if "sse" in declared.lower() or url.rstrip("/").endswith("/sse"):
                    transport = "sse"
                else:
                    transport = "http"
        pos = content.find(f'"{name}"')
        sites.append(McpToolSite(
            server=name, tool="*", kind="tool", role="consumes",
            line=_line_of(content, pos) if pos >= 0 else 1,
            framework="mcp-config", transport=transport, attrs=attrs))
    return sites


# --- A2A agent cards and call sites ------------------------------------------

@dataclass
class AgentCard:
    """A declared A2A agent (card) or one A2A client call site."""
    name: str
    url: str = ""
    skills: list[str] = field(default_factory=list)   # skill ids
    attrs: dict = field(default_factory=dict)


_A2A_CAP_KEYS = {"streaming", "pushnotifications", "statetransitionhistory"}
_A2A_CLIENT_CALL = re.compile(r"\b(?:new\s+)?A2AClient\s*\(")


def is_agent_card_file(file_path: str) -> bool:
    low = file_path.replace("\\", "/").lower()
    base = low.rsplit("/", 1)[-1]
    return (low.endswith(".well-known/agent.json")
            or low.endswith(".well-known/agent-card.json")
            or base in ("agent-card.json", "agent.json"))


def parse_agent_card(file_path: str, content: str) -> AgentCard | None:
    """A2A card -> name, url, skill ids. Shape-sniffed: a ``skills``
    list plus a url or A2A-shaped capabilities block; any other agent.json
    returns None rather than a guessed card."""
    data = _load_json(content)
    if not isinstance(data, dict):
        return None
    skills = data.get("skills")
    if not isinstance(skills, list):
        return None
    caps = data.get("capabilities")
    a2a_caps = isinstance(caps, dict) and bool(
        _A2A_CAP_KEYS & {str(k).lower() for k in caps})
    url = data.get("url")
    if not (isinstance(url, str) and url) and not a2a_caps:
        return None

    ids: list[str] = []
    for skill in skills:
        if isinstance(skill, dict):
            sid = skill.get("id") or skill.get("name")
            if isinstance(sid, str) and sid:
                ids.append(sid)
        elif isinstance(skill, str) and skill:
            ids.append(skill)
    attrs: dict = {}
    for key in ("version", "protocolVersion", "preferredTransport"):
        if isinstance(data.get(key), str) and data[key]:
            attrs[key] = data[key]
    return AgentCard(name=str(data.get("name") or ""),
                     url=url if isinstance(url, str) else "",
                     skills=ids, attrs=attrs)


def extract_a2a_call_sites(content: str,
                           language: str | None) -> list[AgentCard]:
    """A2AClient constructions. Each is a card-shaped site with
    ``attrs["call_site"]=True`` and the line in ``attrs`` (the dataclass has
    no line field); a non-literal target keeps url="" with dynamic=True."""
    cards: list[AgentCard] = []
    seen: set[tuple[str, int]] = set()
    for m in _A2A_CLIENT_CALL.finditer(content):
        args = _call_args(content, m.end() - 1)
        line = _line_of(content, m.start())
        found = _HTTP_URL_LIT.search(args)
        url = found.group(1) if found else ""
        if (url, line) in seen:
            continue
        seen.add((url, line))
        attrs: dict = {"call_site": True, "line": line}
        if not url:
            attrs["dynamic"] = True
        cards.append(AgentCard(name="", url=url, attrs=attrs))
    return cards


# --- LLM SDK call sites -------------------------------------------------------

@dataclass
class LlmCallSite:
    """One model-invoking SDK call (or azure deployment declaration)."""
    provider: str      # anthropic | openai | bedrock | vertex | azure-openai
    model: str         # literal model id ("" when dynamic)
    line: int
    framework: str
    attrs: dict = field(default_factory=dict)


# Gated on "anthropic" in the file: Twilio's client.messages.create must never
# be claimed, and every real caller imports the sdk (`import anthropic`,
# `@anthropic-ai/sdk`).
_ANTH_CALL = re.compile(r"\.messages\.(?:create|stream)\s*\(")
_OPENAI_CHAT = re.compile(r"\.chat\.completions\.create\s*\(")
_OPENAI_RESPONSES = re.compile(r"\.responses\.create\s*\(")
_BEDROCK_INVOKE = re.compile(r"\.invoke_model(?:_with_response_stream)?\s*\(")
# `.converse(` is too generic a name on its own; bedrock's required modelId
# kwarg is the gate.
_BEDROCK_CONVERSE = re.compile(r"\.converse(?:_stream)?\s*\(")
_BEDROCK_TS = re.compile(
    r"\bnew\s+(?:InvokeModelCommand|InvokeModelWithResponseStreamCommand"
    r"|ConverseCommand|ConverseStreamCommand)\s*\(")
_VERTEX_GM = re.compile(r"\bGenerativeModel\s*\(")
_AZURE_CTOR = re.compile(r"\b(?:new\s+)?(?:Async)?AzureOpenAI\s*\(")


def _add_llm(sites: list[LlmCallSite], content: str, pos: int, provider: str,
             framework: str, args: str, *keys: str) -> None:
    value, present, expr = _kwarg(args, *keys)
    attrs: dict = {}
    if not value:
        attrs["dynamic"] = True
        if present and expr:
            attrs["model_expr"] = expr[:80]
    sites.append(LlmCallSite(provider=provider, model=value,
                             line=_line_of(content, pos),
                             framework=framework, attrs=attrs))


def extract_llm_sites(content: str, language: str | None) -> list[LlmCallSite]:
    """LLM SDK call sites with the literal model id when stated.

    The idioms are language-distinctive (snake_case boto3 vs `new ...Command`),
    so every pattern runs regardless of ``language``; a dispatch would only
    duplicate the table.
    """
    low = content.lower()
    sites: list[LlmCallSite] = []
    azure = bool(_AZURE_CTOR.search(content))
    openai_provider = "azure-openai" if azure else "openai"

    if "anthropic" in low:
        for m in _ANTH_CALL.finditer(content):
            _add_llm(sites, content, m.start(), "anthropic", "anthropic-sdk",
                     _call_args(content, m.end() - 1), "model")
    if "openai" in low:
        for pattern in (_OPENAI_CHAT, _OPENAI_RESPONSES):
            for m in pattern.finditer(content):
                _add_llm(sites, content, m.start(), openai_provider,
                         "openai-sdk", _call_args(content, m.end() - 1),
                         "model")
    for m in _BEDROCK_INVOKE.finditer(content):
        _add_llm(sites, content, m.start(), "bedrock", "boto3",
                 _call_args(content, m.end() - 1), "modelId")
    for m in _BEDROCK_CONVERSE.finditer(content):
        args = _call_args(content, m.end() - 1)
        if "modelId" in args:
            _add_llm(sites, content, m.start(), "bedrock", "boto3", args,
                     "modelId")
    for m in _BEDROCK_TS.finditer(content):
        _add_llm(sites, content, m.start(), "bedrock", "aws-sdk-js",
                 _call_args(content, m.end() - 1), "modelId")

    vertex_gate = ("vertexai" in low or "google.generativeai" in low
                   or "google.genai" in low or "from google import genai" in low)
    for m in _VERTEX_GM.finditer(content):
        args = _call_args(content, m.end() - 1)
        first = _FIRST_STR_ARG.match(args)
        model = first.group(1) if first else _kwarg(args, "model_name", "model")[0]
        if not vertex_gate and not model.startswith("gemini"):
            continue  # GenerativeModel alone is not proof of vertex
        sites.append(LlmCallSite(
            provider="vertex", model=model, line=_line_of(content, m.start()),
            framework="vertexai", attrs={} if model else {"dynamic": True}))

    for m in _AZURE_CTOR.finditer(content):
        args = _call_args(content, m.end() - 1)
        value, _, _ = _kwarg(args, "azure_deployment", "deployment",
                             "deployment_name")
        if value:  # a ctor without a deployment literal proves nothing extra
            sites.append(LlmCallSite(
                provider="azure-openai", model=value,
                line=_line_of(content, m.start()), framework="openai-sdk",
                attrs={"deployment": value}))

    seen: set[tuple[str, str, int]] = set()
    unique: list[LlmCallSite] = []
    for site in sites:
        key = (site.provider, site.model, site.line)
        if key not in seen:
            seen.add(key)
            unique.append(site)
    return unique


# --- Vector stores -------------------------------------------------------------

@dataclass
class VectorStoreSite:
    """One vector index/collection touch: declared, read, or written."""
    system: str        # pinecone | weaviate | qdrant | chroma | pgvector | milvus
    collection: str    # index/collection/class name ("" dynamic)
    role: str          # "reads" | "writes" | "declares"
    line: int
    attrs: dict = field(default_factory=dict)


_PINECONE_INDEX = re.compile(
    r"(?:\b(\w+)\s*=\s*)?\b\w+\.Index\s*\(\s*[\"']([^\"']+)[\"']")
_QDRANT_CALL = re.compile(
    r"\.(upsert|upload_points|upload_collection|search|query_points|scroll"
    r"|retrieve|create_collection|recreate_collection)\s*\(")
_QDRANT_ROLE = {
    "upsert": "writes", "upload_points": "writes", "upload_collection": "writes",
    "search": "reads", "query_points": "reads", "scroll": "reads",
    "retrieve": "reads",
    "create_collection": "declares", "recreate_collection": "declares",
}
_WEAVIATE_COLL = re.compile(
    r"(?:\b(\w+)\s*=\s*)?\b\w+\.collections\.(?:get|create|use)\s*\("
    r"\s*[\"']([^\"']+)[\"']")
_WEAVIATE_V3_GET = re.compile(r"\.query\s*\.\s*get\s*\(\s*[\"']([^\"']+)[\"']")
_CHROMA_COLL = re.compile(
    r"(?:\b(\w+)\s*=\s*)?\b\w+\.(?:get_or_create_collection|create_collection"
    r"|get_collection)\s*\(\s*(?:name\s*=\s*)?[\"']([^\"']+)[\"']")
_MILVUS_COLL = re.compile(
    r"\bCollection\s*\(\s*(?:name\s*=\s*)?[\"']([^\"']+)[\"']")
# pgvector leaves no client fingerprint; the declaration is the DDL itself,
# which may be embedded in a migration string in any language.
_PGVECTOR_CREATE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"]+)", re.I)
_PGVECTOR_COLUMN = re.compile(r"\bvector\s*\(\s*\d+\s*\)", re.I)


def _add_vec(sites: list[VectorStoreSite], content: str, pos: int, system: str,
             collection: str, role: str, attrs: dict | None = None) -> None:
    sites.append(VectorStoreSite(system=system, collection=collection,
                                 role=role, line=_line_of(content, pos),
                                 attrs=attrs or {}))


def _tracked_ops(sites: list[VectorStoreSite], content: str, system: str,
                 handles: dict[str, str], ops: tuple[tuple[str, str], ...]) -> None:
    """Reads/writes through a tracked handle var (`index = pc.Index("x")`)."""
    for var, name in handles.items():
        for op, role in ops:
            pattern = re.compile(rf"\b{re.escape(var)}\.{op}\s*\(")
            for m in pattern.finditer(content):
                _add_vec(sites, content, m.start(), system, name, role)


def extract_vector_sites(content: str,
                         language: str | None) -> list[VectorStoreSite]:
    """Vector index/collection declarations, reads and writes. Every
    system's scan is gated on its package name appearing in the file, so
    `Collection(` (pymilvus vs. everything else) and `.upsert(` (qdrant vs.
    chroma vs. pinecone) never cross wires."""
    low = content.lower()
    sites: list[VectorStoreSite] = []

    if "pinecone" in low:
        handles: dict[str, str] = {}
        for m in _PINECONE_INDEX.finditer(content):
            _add_vec(sites, content, m.start(), "pinecone", m.group(2),
                     "declares")
            if m.group(1):
                handles[m.group(1)] = m.group(2)
        _tracked_ops(sites, content, "pinecone", handles,
                     (("upsert", "writes"), ("query", "reads")))

    if "qdrant" in low:
        for m in _QDRANT_CALL.finditer(content):
            args = _call_args(content, m.end() - 1)
            value, present, _ = _kwarg(args, "collection_name")
            if not present:
                continue  # not a qdrant-style call after all
            _add_vec(sites, content, m.start(), "qdrant", value,
                     _QDRANT_ROLE[m.group(1)],
                     {} if value else {"dynamic": True})

    if "weaviate" in low:
        handles = {}
        for m in _WEAVIATE_COLL.finditer(content):
            _add_vec(sites, content, m.start(), "weaviate", m.group(2),
                     "declares")
            if m.group(1):
                handles[m.group(1)] = m.group(2)
        for var, name in handles.items():
            for suffix, role in ((r"\.data\.", "writes"), (r"\.query\.", "reads")):
                m = re.search(rf"\b{re.escape(var)}{suffix}", content)
                if m:
                    _add_vec(sites, content, m.start(), "weaviate", name, role)
        for m in _WEAVIATE_V3_GET.finditer(content):
            _add_vec(sites, content, m.start(), "weaviate", m.group(1), "reads")

    if "chroma" in low:
        handles = {}
        for m in _CHROMA_COLL.finditer(content):
            _add_vec(sites, content, m.start(), "chroma", m.group(2),
                     "declares")
            if m.group(1):
                handles[m.group(1)] = m.group(2)
        _tracked_ops(sites, content, "chroma", handles,
                     (("add", "writes"), ("upsert", "writes"),
                      ("query", "reads")))

    if "pymilvus" in low:
        for m in _MILVUS_COLL.finditer(content):
            _add_vec(sites, content, m.start(), "milvus", m.group(1),
                     "declares")

    for m in _PGVECTOR_CREATE.finditer(content):
        end = content.find(";", m.end())
        if end == -1:
            end = min(len(content), m.end() + 2000)
        if _PGVECTOR_COLUMN.search(content, m.end(), end):
            _add_vec(sites, content, m.start(), "pgvector",
                     m.group(1).strip('"'), "declares")

    seen: set[tuple[str, str, str]] = set()
    unique: list[VectorStoreSite] = []
    for site in sites:
        key = (site.system, site.collection, site.role)
        if key not in seen:
            seen.add(key)
            unique.append(site)
    return unique
