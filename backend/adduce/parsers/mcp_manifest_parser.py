"""MCP capability manifests — the declarative tool surface of an MCP server.

An MCP server does not declare its tools with a decorator. It ships a
`capability-manifest.json` naming the server, the gateway URL it registers
under, and every tool it exposes; a sibling `tools/` directory holds one
module per tool. On the estate this was written for, the two agree exactly
across ten servers, and `@mcp.tool` appears once in the whole repository — so
a decorator-based extractor finds nothing while the manifest describes all 80
tools precisely.

A manifest is a declaration, not an inference: each tool listed here is a
provider contract as real as an HTTP route, and `call_tool("name")` in a
client is a consumer of one.
"""

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Filenames are a fast path, not the test. There is no single standard name in
# the MCP ecosystem -- estates use capability-manifest.json, mcp-manifest.json,
# server.json (the MCP registry spec), .mcp.json and others -- so recognising
# one repo's convention would make this extractor useless everywhere else.
# Detection is by SHAPE, exactly as is_asyncapi_file sniffs for a top-level
# `asyncapi:` key rather than trusting the filename.
MANIFEST_NAMES = (
    "capability-manifest.json", "mcp-manifest.json", "mcp.json",
    ".mcp.json", "server.json", "tools.json",
)
# Any JSON small enough to be a manifest gets sniffed; a lockfile or an SBOM
# should never be read into memory on the off-chance.
_SNIFF_MAX_BYTES = 256 * 1024

# From the estate's own manifests/schema.json. A manifest missing these is not
# a capability manifest, and guessing at its shape would invent contracts.
_REQUIRED_TOP = ("name", "tools")
_REQUIRED_TOOL = ("name",)


@dataclass
class McpTool:
    name: str
    description: str = ""
    destructive: bool = False
    entity_kind: str = ""
    target_argument: str = ""


@dataclass
class McpManifest:
    server: str
    version: str = ""
    description: str = ""
    domain: str = ""
    gateway_url: str = ""
    transport: str = ""
    tools: list[McpTool] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_mcp_manifest(file_path: str, content: str = "") -> bool:
    """A capability manifest by name, or by shape.

    Shape means: a JSON object carrying a server `name` and a `tools` array
    whose entries are objects with names. That is what an MCP tool surface
    IS, independent of what a given estate calls the file.
    """
    if not file_path.lower().endswith(".json"):
        return False
    if os.path.basename(file_path) in MANIFEST_NAMES:
        return True
    if not content or len(content) > _SNIFF_MAX_BYTES:
        return False
    # Cheap reject before paying for a JSON parse.
    if '"tools"' not in content or '"name"' not in content:
        return False
    return _looks_like_manifest(content)


def _looks_like_manifest(content: str) -> bool:
    try:
        doc = json.loads(content)
    except (ValueError, TypeError):
        return False
    if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
        return False
    if not str(doc.get("name") or "").strip():
        return False
    tools = doc["tools"]
    # A `tools` key is common in unrelated config (npm scripts, CI matrices).
    # Require the entries to look like tool declarations.
    named = [t for t in tools if isinstance(t, dict) and str(t.get("name") or "").strip()]
    return bool(named) and len(named) >= max(1, len(tools) // 2)


def parse_mcp_manifest(file_path: str, content: str) -> McpManifest | None:
    """Parse a capability manifest, or decline.

    Returns None when the file is not a capability manifest at all. A manifest
    that IS one but is malformed comes back with `errors` set and whatever
    tools could be read, so a single bad entry never silently drops the rest.
    """
    try:
        doc = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(doc, dict):
        return None
    if any(key not in doc for key in _REQUIRED_TOP):
        return None

    server = str(doc.get("name") or "").strip()
    raw_tools = doc.get("tools")
    if not server or not isinstance(raw_tools, list):
        return None

    foyer = doc.get("foyer") if isinstance(doc.get("foyer"), dict) else {}
    manifest = McpManifest(
        server=server,
        version=str(doc.get("version") or ""),
        description=str(doc.get("description") or ""),
        domain=str(doc.get("domain") or ""),
        gateway_url=str(foyer.get("url") or ""),
        transport=str(foyer.get("transport") or ""),
    )

    seen: set[str] = set()
    for index, entry in enumerate(raw_tools):
        if not isinstance(entry, dict):
            manifest.errors.append(f"tools[{index}] is not an object")
            continue
        if any(key not in entry for key in _REQUIRED_TOOL):
            manifest.errors.append(f"tools[{index}] has no name")
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            manifest.errors.append(f"tools[{index}] has an empty name")
            continue
        if name in seen:
            # Two entries for one tool is one contract, not two.
            manifest.errors.append(f"duplicate tool {name!r}")
            continue
        seen.add(name)
        target = entry.get("entity_target") if isinstance(
            entry.get("entity_target"), dict) else {}
        manifest.tools.append(McpTool(
            name=name,
            description=str(entry.get("description") or ""),
            destructive=bool(entry.get("destructive")),
            entity_kind=str(target.get("entity_kind") or ""),
            target_argument=str(target.get("target_argument") or ""),
        ))
    return manifest
