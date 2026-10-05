"""Literal table and procedure references in raw SQL text."""

import re

# One identifier, optionally quoted per dialect: `t`, "T", [T], sch.t.
_IDENT = r"[`\"\[]?[A-Za-z_][\w.$]*[`\"\]]?(?:\.[`\"\[]?[A-Za-z_][\w$]*[`\"\]]?)*"
_QUOTES = "`\"[]"

_SQL_KEYWORDS = {
    "select", "from", "where", "join", "on", "set", "values", "into",
    "table", "if", "not", "exists", "only", "inner", "left", "right",
    "outer", "cross", "lateral", "dual", "unnest", "function",
    "procedure", "immediate", "when",
}

_SQL_CREATE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:UNLOGGED\s+|TEMP(?:ORARY)?\s+)?TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(" + _IDENT + ")", re.I)
_SQL_ALTER = re.compile(
    r"\bALTER\s+TABLE\s+(?:ONLY\s+)?(?:IF\s+EXISTS\s+)?(" + _IDENT + ")",
    re.I)
_SQL_DROP = re.compile(
    r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(" + _IDENT + ")", re.I)
_SQL_FROM = re.compile(r"\bFROM\s+(?!\()(" + _IDENT + ")", re.I)
_SQL_JOIN = re.compile(r"\bJOIN\s+(?!\()(" + _IDENT + ")", re.I)
_SQL_INSERT = re.compile(
    r"\bINSERT\s+(?:IGNORE\s+)?INTO\s+(" + _IDENT + ")", re.I)
_SQL_UPDATE = re.compile(r"\bUPDATE\s+(" + _IDENT + r")\s+SET\b", re.I)
_SQL_DELETE = re.compile(r"\bDELETE\s+FROM\s+(" + _IDENT + ")", re.I)
_SQL_PROC = re.compile(r"\b(?:CALL|EXEC(?:UTE)?)\s+(" + _IDENT + ")", re.I)
_SQL_DYNAMIC = re.compile(
    r"\b(FROM|INTO|UPDATE|JOIN)\s+(?:%s|%\(\w+\)s|\?|\{[^}]*\}|\$\{[^}]*\})",
    re.I)
_DELETE_BEFORE = re.compile(r"DELETE\s+$", re.I)


def line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def clean_identifier(raw: str) -> str:
    """Identity form of a SQL identifier: quotes stripped, lowercased."""
    return "".join(ch for ch in raw if ch not in _QUOTES).lower().rstrip(".")


def _collect(pattern: re.Pattern, content: str, out: list,
             *, skip_after_delete: bool = False) -> None:
    for match in pattern.finditer(content):
        raw = match.group(1)
        name = clean_identifier(raw)
        if not name or name.split(".")[0] in _SQL_KEYWORDS:
            continue
        if skip_after_delete and _DELETE_BEFORE.search(
                content[max(0, match.start() - 12):match.start()]):
            continue
        out.append((name, line_of(content, match.start()), raw))


def parse_sql_tables(content: str) -> dict:
    """Table references grouped by SQL statement class.

    Each static reference is ``(normalised name, line, raw spelling)``.
    Dynamic table positions are retained only as ``(role, line)`` declines.
    """
    out: dict = {key: [] for key in (
        "created", "altered", "dropped", "reads", "writes", "procedures",
        "dynamic",
    )}
    _collect(_SQL_CREATE, content, out["created"])
    _collect(_SQL_ALTER, content, out["altered"])
    _collect(_SQL_DROP, content, out["dropped"])
    _collect(_SQL_FROM, content, out["reads"], skip_after_delete=True)
    _collect(_SQL_JOIN, content, out["reads"])
    _collect(_SQL_INSERT, content, out["writes"])
    _collect(_SQL_UPDATE, content, out["writes"])
    _collect(_SQL_DELETE, content, out["writes"])
    _collect(_SQL_PROC, content, out["procedures"])
    for match in _SQL_DYNAMIC.finditer(content):
        role = "reads" if match.group(1).upper() in ("FROM", "JOIN") \
            else "writes"
        if role == "reads" and _DELETE_BEFORE.search(
                content[max(0, match.start() - 12):match.start()]):
            role = "writes"
        out["dynamic"].append((role, line_of(content, match.start())))
    return out
