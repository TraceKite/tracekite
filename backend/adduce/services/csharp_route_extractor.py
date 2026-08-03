"""ASP.NET Core Minimal API route extraction for C# (.cs).

Extracts route registrations from MapGet, MapPost, MapPut, MapDelete,
MapPatch, and MapGroup builder chains in C# source files.

Precision-first: only string literal paths (e.g. "/v1/pets") are extracted.
Route parameter constraints (e.g. "{id:int}", "{name:alpha}") are stripped to
canonical parameter templates ("{id}", "{name}").
"""

import re
from dataclasses import dataclass, field


@dataclass
class CSharpRoute:
    """One statically-declared C# Minimal API HTTP route."""
    method: str
    path: str
    line: int
    framework: str = "aspnetcore-minimal-apis"
    handler_name: str = ""
    attrs: dict = field(default_factory=dict)


# app.MapGet("/pets", ...) / app.MapPost("/orders/{id:int}", ...)
_MAP_VERB = re.compile(
    r"\b[\w.]+\s*\.\s*Map(Get|Post|Put|Delete|Patch)\s*\(\s*\"([^\"]+)\""
)

# app.MapGroup("/api/v1") or builder.MapGroup("/api")
_MAP_GROUP = re.compile(
    r"\b[\w.]+\s*\.\s*MapGroup\s*\(\s*\"([^\"]+)\"\s*\)"
)

# Strips type constraints like {id:int} or {id:guid} -> {id}
_PARAM_CONSTRAINT = re.compile(r"\{(\w+):[^}]+\}")


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def _normalize_path(path: str) -> str:
    """Strip C# parameter type constraints: /pets/{id:int} -> /pets/{id}."""
    return _PARAM_CONSTRAINT.sub(r"{\1}", path)


def extract_csharp_routes(path: str, content: str) -> list[CSharpRoute]:
    """Extract C# Minimal API routes from source text."""
    if "Map" not in content:
        return []

    # Accumulate all group prefixes in file order
    group_prefixes = [m.group(1).rstrip("/") for m in _MAP_GROUP.finditer(content)]
    group_prefix = "".join(group_prefixes) if group_prefixes else ""

    routes = []
    for match in _MAP_VERB.finditer(content):
        verb = match.group(1).upper()
        route_path = _normalize_path(match.group(2))
        full_path = f"{group_prefix}/{route_path.lstrip('/')}" if group_prefix else route_path
        line = _line_of(content, match.start())
        routes.append(CSharpRoute(method=verb, path=full_path, line=line))

    return routes
