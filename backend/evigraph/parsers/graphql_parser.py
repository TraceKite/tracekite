"""GraphQL SDL and client operations.

The join key is `Type.field` on the root operation types — `Query.owner`,
`Mutation.createOrder` — which both a schema and a client operation name
identically. Weaker than a protobuf key (no package namespace, so two teams can
both define `Query.user`), so federation metadata matters: a subgraph's
`@key`/`extend type` directives say which service owns a type, and that is the
only place the ownership is stated.
"""

import logging
import re
from dataclasses import dataclass, field
from evigraph.parsers.brace_blocks import balanced_block

logger = logging.getLogger(__name__)

_COMMENT = re.compile(r"#[^\n]*")
_BLOCK_STRING = re.compile(r'"""(?:.|\n)*?"""')

_TYPE_BLOCK = re.compile(
    r"\b(extend\s+)?(type|interface|input|enum|union|scalar)\s+(\w+)"
    r"([^{]*)(\{)?", re.MULTILINE)
_SCHEMA_BLOCK = re.compile(r"\bschema\s*\{([^}]*)\}", re.MULTILINE)
_SCHEMA_ROOT = re.compile(r"\b(query|mutation|subscription)\s*:\s*(\w+)")
# `field(arg: X): Type` or `field: Type`
_FIELD = re.compile(r"^\s*(\w+)\s*(\([^)]*\))?\s*:\s*([\[\]\w!]+)", re.MULTILINE)
_KEY_DIRECTIVE = re.compile(r'@key\s*\(\s*fields\s*:\s*"([^"]+)"')

# Client side: operations in .graphql files or gql`...` template literals
_OPERATION = re.compile(
    r"\b(query|mutation|subscription)\s+(\w+)?\s*(\([^)]*\))?\s*\{", re.MULTILINE)
_GQL_TAG = re.compile(r"(?:gql|graphql)\s*`([^`]*)`", re.DOTALL)

DEFAULT_ROOTS = {"query": "Query", "mutation": "Mutation",
                 "subscription": "Subscription"}


@dataclass
class GraphQLField:
    parent_type: str
    name: str
    return_type: str = ""
    line: int = 0

    @property
    def key(self) -> str:
        return f"{self.parent_type}.{self.name}"


@dataclass
class GraphQLType:
    name: str
    kind: str                       # type | interface | input | enum | union
    is_extension: bool = False
    key_fields: list[str] = field(default_factory=list)   # federation @key
    line: int = 0


@dataclass
class GraphQLSchema:
    types: list[GraphQLType] = field(default_factory=list)
    root_fields: list[GraphQLField] = field(default_factory=list)
    roots: dict = field(default_factory=dict)
    is_federated: bool = False
    file_path: str = ""


@dataclass
class GraphQLOperation:
    """A client-side query/mutation and the root fields it selects."""
    operation: str                  # query | mutation | subscription
    name: str
    root_fields: list[str] = field(default_factory=list)
    line: int = 0


def _strip_noise(content: str) -> str:
    """Blank comments and block strings, preserving newlines for line numbers."""
    def blank(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))
    return _COMMENT.sub(blank, _BLOCK_STRING.sub(blank, content))


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1




def parse_graphql_schema(file_path: str, content: str) -> GraphQLSchema:
    """Parse SDL into types and root operation fields."""
    clean = _strip_noise(content)
    schema = GraphQLSchema(file_path=file_path)
    schema.is_federated = "@key" in clean or "extend type" in clean

    # Custom root type names, e.g. `schema { query: RootQuery }`.
    roots = dict(DEFAULT_ROOTS)
    if match := _SCHEMA_BLOCK.search(clean):
        for operation, type_name in _SCHEMA_ROOT.findall(match.group(1)):
            roots[operation] = type_name
    schema.roots = roots
    root_type_names = set(roots.values())

    for match in _TYPE_BLOCK.finditer(clean):
        is_extension = bool(match.group(1))
        kind, name, directives = match.group(2), match.group(3), match.group(4) or ""
        gql_type = GraphQLType(
            name=name, kind=kind, is_extension=is_extension,
            key_fields=_KEY_DIRECTIVE.findall(directives),
            line=_line_of(clean, match.start()),
        )
        schema.types.append(gql_type)

        if match.group(5) is None or kind not in ("type", "interface"):
            continue
        body, _ = balanced_block(clean, clean.index("{", match.end() - 1))
        if name not in root_type_names:
            continue
        body_offset = clean.index("{", match.end() - 1) + 1
        for field_match in _FIELD.finditer(body):
            schema.root_fields.append(GraphQLField(
                parent_type=name,
                name=field_match.group(1),
                return_type=field_match.group(3),
                line=_line_of(clean, body_offset + field_match.start()),
            ))
    return schema


def parse_graphql_operations(content: str) -> list[GraphQLOperation]:
    """Client operations and the root fields they select."""
    clean = _strip_noise(content)
    operations: list[GraphQLOperation] = []
    for match in _OPERATION.finditer(clean):
        body, _ = balanced_block(clean, clean.index("{", match.end() - 1))
        # Only top-level selections are root fields: nested ones belong to the
        # types those fields return, and identifiers inside an argument list
        # are argument names, not fields.
        root_fields, depth, parens = [], 0, 0
        for token in re.finditer(r"[{}()]|\$?\b[A-Za-z_]\w*\b", body):
            text = token.group(0)
            if text == "{":
                depth += 1
            elif text == "}":
                depth = max(0, depth - 1)
            elif text == "(":
                parens += 1
            elif text == ")":
                parens = max(0, parens - 1)
            elif (depth == 0 and parens == 0 and not text.startswith("$")
                    and text not in ("fragment", "on")):
                root_fields.append(text)
        operations.append(GraphQLOperation(
            operation=match.group(1),
            name=match.group(2) or "",
            root_fields=list(dict.fromkeys(root_fields)),
            line=_line_of(clean, match.start()),
        ))
    return operations


def extract_gql_tags(content: str) -> list[GraphQLOperation]:
    """Operations embedded in gql`...` template literals in JS/TS."""
    operations: list[GraphQLOperation] = []
    for match in _GQL_TAG.finditer(content):
        base_line = _line_of(content, match.start()) - 1
        for operation in parse_graphql_operations(match.group(1)):
            operation.line += base_line
            operations.append(operation)
    return operations


def is_graphql_schema_file(file_name: str) -> bool:
    return file_name.endswith((".graphql", ".graphqls", ".gql", ".sdl"))
