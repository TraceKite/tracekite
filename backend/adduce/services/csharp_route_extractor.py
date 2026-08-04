"""ASP.NET Core Minimal API route extraction for C#.

Only literal route templates are asserted. Computed group prefixes and paths
are declined and counted by the ingestion pipeline.
"""

import re
from dataclasses import dataclass, field


@dataclass
class CSharpRoute:
    """One statically declared C# Minimal API HTTP route."""

    method: str
    path: str
    line: int
    framework: str = "aspnetcore-minimal-apis"
    handler_name: str = ""
    attrs: dict = field(default_factory=dict)


_VERBS = "Get|Post|Put|Delete|Patch"
_GROUP_ASSIGN = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*"
    r"(?P<parent>[A-Za-z_]\w*)\s*\.\s*MapGroup\s*\("
    r"\s*(?P<arg>[^)\r\n]+)\s*\)")
_BUILDER_ASSIGN = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*WebApplication\s*\.\s*"
    r"CreateBuilder\s*\(")
_APP_CREATE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*WebApplication\s*\.\s*"
    r"Create\s*\(")
_APP_BUILD = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<builder>[A-Za-z_]\w*)"
    r"\s*\.\s*Build\s*\(")
_CHAINED_ROUTE = re.compile(
    rf"\b(?P<receiver>[A-Za-z_]\w*)\s*\.\s*MapGroup\s*\("
    rf"\s*(?P<group>[^)\r\n]+)\s*\)\s*\.\s*"
    rf"Map(?P<verb>{_VERBS})\s*\(\s*(?P<arg>[^,\r\n]+)\s*,")
_ROUTE = re.compile(
    rf"\b(?P<receiver>[A-Za-z_]\w*)\s*\.\s*"
    rf"Map(?P<verb>{_VERBS})\s*\(\s*(?P<arg>[^,\r\n]+)\s*,")
_LITERAL = re.compile(r'"([^"\\]*)"')
_PARAM_CONSTRAINT = re.compile(r"\{(\w+):[^}]+\}")


def _quoted_end(content: str, start: int) -> int:
    quote = content[start]
    verbatim = quote == '"' and start > 0 and content[start - 1] == "@"
    cursor = start + 1
    while cursor < len(content):
        if verbatim and content[cursor:cursor + 2] == '""':
            cursor += 2
            continue
        if content[cursor] == quote:
            return cursor + 1
        if not verbatim and content[cursor] == "\\":
            cursor += 2
        else:
            cursor += 1
    return len(content)


def _mask(chars: list[str], start: int, end: int) -> None:
    for cursor in range(start, end):
        if chars[cursor] != "\n":
            chars[cursor] = " "


def _without_comments(content: str) -> str:
    chars = list(content)
    cursor = 0
    while cursor < len(content):
        if content[cursor] in ('"', "'"):
            cursor = _quoted_end(content, cursor)
            continue
        if content[cursor:cursor + 2] == "//":
            end = content.find("\n", cursor)
            end = len(content) if end < 0 else end
            _mask(chars, cursor, end)
            cursor = end
            continue
        if content[cursor:cursor + 2] == "/*":
            end = content.find("*/", cursor + 2)
            end = len(content) if end < 0 else end + 2
            _mask(chars, cursor, end)
            cursor = end
            continue
        cursor += 1
    return "".join(chars)


def _literal(argument: str) -> str | None:
    match = _LITERAL.fullmatch(argument.strip())
    return match.group(1) if match else None


def _join(prefix: str, path: str) -> str:
    joined = f"{prefix.rstrip('/')}/{path.lstrip('/')}" if prefix else path
    if not joined.startswith("/"):
        joined = f"/{joined}"
    return _PARAM_CONSTRAINT.sub(r"{\1}", joined)


def _line_of(content: str, position: int) -> int:
    return content.count("\n", 0, position) + 1


def _group_prefix(groups: dict[str, str | None],
                  receiver: str) -> tuple[str, bool]:
    if receiver not in groups:
        return "", False
    prefix = groups[receiver]
    return prefix or "", prefix is None


def _route(match, content: str, prefix: str) -> CSharpRoute | None:
    path = _literal(match.group("arg"))
    if path is None:
        return None
    return CSharpRoute(
        method=match.group("verb").upper(),
        path=_join(prefix, path),
        line=_line_of(content, match.start()),
    )


def extract_csharp_routes_with_declines(
        path: str, content: str) -> tuple[list[CSharpRoute], int]:
    """Extract literal Minimal API routes and count ambiguous registrations."""
    del path
    if "Map" not in content:
        return [], 0

    clean = _without_comments(content)
    events = (
        [(match.start(), "builder", match)
         for match in _BUILDER_ASSIGN.finditer(clean)] +
        [(match.start(), "app", match)
         for match in _APP_CREATE.finditer(clean)] +
        [(match.start(), "build", match)
         for match in _APP_BUILD.finditer(clean)] +
        [(match.start(), "group", match)
         for match in _GROUP_ASSIGN.finditer(clean)] +
        [(match.start(), "chain", match)
         for match in _CHAINED_ROUTE.finditer(clean)] +
        [(match.start(), "route", match)
         for match in _ROUTE.finditer(clean)]
    )
    builders: set[str] = set()
    roots: set[str] = set()
    groups: dict[str, str | None] = {}
    routes: list[CSharpRoute] = []
    declined = 0

    for _position, kind, match in sorted(events, key=lambda item: item[0]):
        if kind == "builder":
            builders.add(match.group("name"))
            continue
        if kind == "app":
            roots.add(match.group("name"))
            continue
        if kind == "build":
            if match.group("builder") in builders:
                roots.add(match.group("name"))
            continue
        if kind == "group":
            parent_name = match.group("parent")
            parent, ambiguous = _group_prefix(groups, parent_name)
            ambiguous = ambiguous or (
                parent_name not in roots and parent_name not in groups)
            segment = _literal(match.group("arg"))
            groups[match.group("name")] = (
                None if ambiguous or segment is None else _join(parent, segment))
            continue

        receiver = match.group("receiver")
        prefix, ambiguous = _group_prefix(groups, receiver)
        ambiguous = ambiguous or (
            receiver not in roots and receiver not in groups)
        if kind == "chain":
            segment = _literal(match.group("group"))
            ambiguous = ambiguous or segment is None
            if not ambiguous:
                prefix = _join(prefix, segment)
        route = None if ambiguous else _route(match, content, prefix)
        if route is None:
            declined += 1
        else:
            routes.append(route)
    return routes, declined


def extract_csharp_routes(path: str, content: str) -> list[CSharpRoute]:
    """Compatibility surface for callers that only consume asserted routes."""
    routes, _declined = extract_csharp_routes_with_declines(path, content)
    return routes
