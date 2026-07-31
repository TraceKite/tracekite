"""Schema migration parsing + shared raw-SQL table extraction.

Migrations are *declared* schema — the highest-precision data claims available
(roadmap expects 0.95). Each framework names tables explicitly, so no guessing
is needed; anything not literal is dropped, not inferred.

`parse_sql_tables` is the single SQL-table regex engine, shared with
`adduce.services.data_extractor` so runtime SQL strings and migration DDL agree
on identity rules: quotes/backticks/brackets stripped, `schema.table` keeps the
dot, names lowercased (SQL identity is case-insensitive in practice; raw text
is preserved alongside).
"""

import re
from dataclasses import dataclass, field

# One identifier, optionally quoted per dialect: `t`, "T", [T], sch.t, `p.d.t`.
_IDENT = r"[`\"\[]?[A-Za-z_][\w.$]*[`\"\]]?(?:\.[`\"\[]?[A-Za-z_][\w$]*[`\"\]]?)*"
_QUOTES = "`\"[]"

# Words that can follow FROM/JOIN/INTO without being tables; declining these
# beats guessing (a captured keyword is always wrong, a skip is merely absent).
_SQL_KEYWORDS = {
    "select", "from", "where", "join", "on", "set", "values", "into", "table",
    "if", "not", "exists", "only", "inner", "left", "right", "outer", "cross",
    "lateral", "dual", "unnest", "function", "procedure", "immediate", "when",
}

_SQL_CREATE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:UNLOGGED\s+|TEMP(?:ORARY)?\s+)?TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(" + _IDENT + ")", re.I)
_SQL_ALTER = re.compile(
    r"\bALTER\s+TABLE\s+(?:ONLY\s+)?(?:IF\s+EXISTS\s+)?(" + _IDENT + ")", re.I)
_SQL_DROP = re.compile(
    r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(" + _IDENT + ")", re.I)
# FROM with a subquery/parens is not a table reference; skip via (?!\().
_SQL_FROM = re.compile(r"\bFROM\s+(?!\()(" + _IDENT + ")", re.I)
_SQL_JOIN = re.compile(r"\bJOIN\s+(?!\()(" + _IDENT + ")", re.I)
_SQL_INSERT = re.compile(r"\bINSERT\s+(?:IGNORE\s+)?INTO\s+(" + _IDENT + ")", re.I)
# SET is required so prose containing "update" never yields a table.
_SQL_UPDATE = re.compile(r"\bUPDATE\s+(" + _IDENT + r")\s+SET\b", re.I)
_SQL_DELETE = re.compile(r"\bDELETE\s+FROM\s+(" + _IDENT + ")", re.I)
_SQL_PROC = re.compile(r"\b(?:CALL|EXEC(?:UTE)?)\s+(" + _IDENT + ")", re.I)
# Placeholder in table position -> dynamic, never a name.
_SQL_DYNAMIC = re.compile(
    r"\b(FROM|INTO|UPDATE|JOIN)\s+(?:%s|%\(\w+\)s|\?|\{[^}]*\}|\$\{[^}]*\})", re.I)
_DELETE_BEFORE = re.compile(r"DELETE\s+$", re.I)


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def _clean(raw: str) -> str:
    """Identity form of a SQL identifier: quotes stripped, lowercased."""
    return "".join(ch for ch in raw if ch not in _QUOTES).lower().rstrip(".")


def _collect(pattern: re.Pattern, content: str, out: list, *, skip_after_delete=False):
    for match in pattern.finditer(content):
        raw = match.group(1)
        name = _clean(raw)
        if not name or name.split(".")[0] in _SQL_KEYWORDS:
            continue
        if skip_after_delete and _DELETE_BEFORE.search(content[max(0, match.start() - 12):match.start()]):
            continue  # the FROM of DELETE FROM; the DELETE rule owns it
        out.append((name, _line_of(content, match.start()), raw))


def parse_sql_tables(content: str) -> dict:
    """Table references in a SQL text, by statement class.

    Returns lists of ``(name, line, raw)`` under keys ``created`` / ``altered``
    / ``dropped`` / ``reads`` (SELECT FROM, JOIN) / ``writes`` (INSERT, UPDATE,
    DELETE) / ``procedures`` (CALL/EXEC), plus ``dynamic``: ``(role, line)``
    pairs for placeholder table positions.
    """
    out: dict = {k: [] for k in
                 ("created", "altered", "dropped", "reads", "writes",
                  "procedures", "dynamic")}
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
        role = "reads" if match.group(1).upper() in ("FROM", "JOIN") else "writes"
        if role == "reads" and _DELETE_BEFORE.search(
                content[max(0, match.start() - 12):match.start()]):
            role = "writes"  # DELETE FROM <placeholder>
        out["dynamic"].append((role, _line_of(content, match.start())))
    return out


@dataclass
class MigrationInfo:
    """Declared schema change of one migration file."""
    tables_created: list[str] = field(default_factory=list)
    tables_altered: list[str] = field(default_factory=list)
    tables_dropped: list[str] = field(default_factory=list)
    framework: str = "sql"    # flyway | liquibase | alembic | django | rails | prisma | ef | sql
    version: str = ""         # V1_2__ prefix, alembic revision, EF [Migration], ...


# --- framework detection (path-shaped) --------------------------------------

_FLYWAY_NAME = re.compile(r"^([VvRr]\d+(?:[._]\d+)*)__.+\.sql$")
_RAILS_NAME = re.compile(r"^(\d+)_.+\.rb$")
_DJANGO_NAME = re.compile(r"^(\d{4})_.+\.py$")
_EF_NAME = re.compile(r"^(\d+)_.+\.cs$")
_LIQUIBASE_EXT = (".xml", ".yaml", ".yml")


def _segments(file_path: str) -> list[str]:
    return [s for s in file_path.replace("\\", "/").split("/") if s]


def _detect(file_path: str) -> tuple[str, str] | None:
    """(framework, version-from-path) or None when the path is not a migration."""
    segs = _segments(file_path)
    if not segs:
        return None
    name = segs[-1]
    lower = [s.lower() for s in segs]
    joined = "/".join(lower)

    m = _FLYWAY_NAME.match(name)
    if m or "db/migration" in joined and name.endswith(".sql"):
        return "flyway", (m.group(1) if m else "")
    if "prisma/migrations" in joined and name.endswith(".sql"):
        # prisma/migrations/<timestamp>_<desc>/migration.sql
        return "prisma", (segs[-2] if len(segs) >= 2 else "")
    if "db/migrate" in joined and name.endswith(".rb"):
        m = _RAILS_NAME.match(name)
        return "rails", (m.group(1) if m else "")
    if "versions" in lower[:-1] and name.endswith(".py"):
        return "alembic", ""       # revision comes from content
    if "migrations" in lower[:-1] and (m := _DJANGO_NAME.match(name)):
        return "django", m.group(1)
    if "migrations" in lower[:-1] and (m := _EF_NAME.match(name)):
        return "ef", m.group(1)
    if ("changelog" in name.lower() or "db/changelog" in joined) \
            and name.lower().endswith(_LIQUIBASE_EXT):
        return "liquibase", ""
    return None


def is_migration_file(file_path: str) -> bool:
    """Whether the path lies in a recognized migration tree/naming scheme."""
    return _detect(file_path) is not None


# --- framework content parsers ----------------------------------------------

_ALEMBIC_REVISION = re.compile(r"^revision(?:\s*:\s*str)?\s*=\s*['\"]([^'\"]+)", re.M)
_ALEMBIC_CREATE = re.compile(r"\bop\.create_table\s*\(\s*['\"]([^'\"]+)")
_ALEMBIC_DROP = re.compile(r"\bop\.drop_table\s*\(\s*['\"]([^'\"]+)")
_ALEMBIC_ALTER = re.compile(
    r"\bop\.(?:add_column|drop_column|alter_column|rename_table|create_index)"
    r"\s*\(\s*['\"]([^'\"]+)")

_DJANGO_CREATE = re.compile(r"migrations\.CreateModel\s*\(\s*name\s*=\s*['\"](\w+)")
_DJANGO_DELETE = re.compile(r"migrations\.DeleteModel\s*\(\s*name\s*=\s*['\"](\w+)")
_DJANGO_ALTER = re.compile(
    r"migrations\.(?:AddField|AlterField|RemoveField|RenameField)"
    r"\s*\(\s*model_name\s*=\s*['\"](\w+)")
_DJANGO_DB_TABLE = re.compile(r"['\"]db_table['\"]\s*:\s*['\"]([^'\"]+)")

_RAILS_CREATE = re.compile(r"\bcreate_table\s+[:\"']([\w.]+)")
_RAILS_DROP = re.compile(r"\bdrop_table\s+[:\"']([\w.]+)")
_RAILS_ALTER = re.compile(
    r"\b(?:add_column|remove_column|change_column|rename_column|add_index"
    r"|add_reference|change_table)\s+[:\"']([\w.]+)")

_EF_ATTR_VERSION = re.compile(r"\[Migration\(\s*\"([^\"]+)\"\s*\)\]")
_EF_CREATE = re.compile(r"migrationBuilder\.CreateTable\s*\(\s*name:\s*\"([^\"]+)\"")
_EF_DROP = re.compile(r"migrationBuilder\.DropTable\s*\(\s*name:\s*\"([^\"]+)\"")
_EF_ALTER = re.compile(
    r"migrationBuilder\.(?:AddColumn|DropColumn|AlterColumn|RenameColumn)"
    r"\s*(?:<[^>]+>)?\s*\([^)]*?table:\s*\"([^\"]+)\"", re.S)

_LB_XML = re.compile(r"<(createTable|dropTable|addColumn|renameTable)\b[^>]*?"
                     r"tableName\s*=\s*\"([^\"]+)\"", re.S)
_LB_SQL_BLOCK = re.compile(r"<sql\b[^>]*>(.*?)</sql>", re.S | re.I)
_LB_YAML = re.compile(r"\b(createTable|dropTable|addColumn|renameTable)\s*:"
                      r"[^\S\n]*\n(?:[^\S\n]+[-\w].*\n)*?[^\S\n]+tableName\s*:"
                      r"\s*['\"]?([\w.]+)")
_LB_CHANGESET_ID = re.compile(r"<changeSet[^>]*?\bid\s*=\s*\"([^\"]+)\""
                              r"|-\s*changeSet\s*:[\s\S]{0,80}?\bid\s*:\s*['\"]?([\w.-]+)")


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def _from_sql(content: str, framework: str, version: str) -> MigrationInfo:
    tables = parse_sql_tables(content)
    return MigrationInfo(
        tables_created=_dedupe([n for n, _, _ in tables["created"]]),
        tables_altered=_dedupe([n for n, _, _ in tables["altered"]]),
        tables_dropped=_dedupe([n for n, _, _ in tables["dropped"]]),
        framework=framework, version=version)


def _alembic(content: str) -> MigrationInfo:
    # Only the upgrade() body counts: downgrade() drops what upgrade creates,
    # and reading both would report every migration as create+drop of the
    # same table.
    m = re.search(r"\bdef\s+downgrade\s*\(", content)
    body = content[:m.start()] if m else content
    rev = _ALEMBIC_REVISION.search(content)
    return MigrationInfo(
        tables_created=_dedupe([m.group(1) for m in _ALEMBIC_CREATE.finditer(body)]),
        tables_altered=_dedupe([m.group(1) for m in _ALEMBIC_ALTER.finditer(body)]),
        tables_dropped=_dedupe([m.group(1) for m in _ALEMBIC_DROP.finditer(body)]),
        framework="alembic", version=rev.group(1) if rev else "")


def _django(content: str, version: str) -> MigrationInfo:
    # Explicit db_table (within that CreateModel's options) wins; otherwise
    # the lowercased model name stands in — the real table is app-prefixed,
    # so the orchestrator treats django-inferred names as lower confidence.
    created: list[str] = []
    matches = list(_DJANGO_CREATE.finditer(content))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        db = _DJANGO_DB_TABLE.search(content[m.start():end])
        created.append(db.group(1).lower() if db else m.group(1).lower())
    return MigrationInfo(
        tables_created=_dedupe(created),
        tables_altered=_dedupe([m.group(1).lower() for m in _DJANGO_ALTER.finditer(content)]),
        tables_dropped=_dedupe([m.group(1).lower() for m in _DJANGO_DELETE.finditer(content)]),
        framework="django", version=version)


def _rails(content: str, version: str) -> MigrationInfo:
    return MigrationInfo(
        tables_created=_dedupe([m.group(1).lower() for m in _RAILS_CREATE.finditer(content)]),
        tables_altered=_dedupe([m.group(1).lower() for m in _RAILS_ALTER.finditer(content)]),
        tables_dropped=_dedupe([m.group(1).lower() for m in _RAILS_DROP.finditer(content)]),
        framework="rails", version=version)


def _ef(content: str, version: str) -> MigrationInfo:
    attr = _EF_ATTR_VERSION.search(content)
    return MigrationInfo(
        tables_created=_dedupe([m.group(1).lower() for m in _EF_CREATE.finditer(content)]),
        tables_altered=_dedupe([m.group(1).lower() for m in _EF_ALTER.finditer(content)]),
        tables_dropped=_dedupe([m.group(1).lower() for m in _EF_DROP.finditer(content)]),
        framework="ef", version=attr.group(1) if attr else version)


def _liquibase(content: str) -> MigrationInfo:
    info = MigrationInfo(framework="liquibase")
    for pattern in (_LB_XML, _LB_YAML):
        for m in pattern.finditer(content):
            tag, name = m.group(1), _clean(m.group(2))
            if tag == "createTable":
                info.tables_created.append(name)
            elif tag == "dropTable":
                info.tables_dropped.append(name)
            else:
                info.tables_altered.append(name)
    for m in _LB_SQL_BLOCK.finditer(content):   # raw <sql> through the SQL path
        raw = _from_sql(m.group(1), "liquibase", "")
        info.tables_created += raw.tables_created
        info.tables_altered += raw.tables_altered
        info.tables_dropped += raw.tables_dropped
    info.tables_created = _dedupe(info.tables_created)
    info.tables_altered = _dedupe(info.tables_altered)
    info.tables_dropped = _dedupe(info.tables_dropped)
    cs = _LB_CHANGESET_ID.search(content)
    if cs:
        info.version = cs.group(1) or cs.group(2) or ""
    return info


def parse_migration(file_path: str, content: str) -> MigrationInfo | None:
    """Parse one migration file; None when the path is not a migration.

    A standalone ``.sql`` file outside any migration tree is still parsed
    (framework ``"sql"``, ``is_migration_file`` False) so callers can feed any
    DDL through the same identity rules.
    """
    detected = _detect(file_path)
    if detected is None:
        if file_path.replace("\\", "/").lower().endswith(".sql"):
            return _from_sql(content, "sql", "")
        return None
    framework, version = detected
    if framework in ("flyway", "prisma"):
        return _from_sql(content, framework, version)
    if framework == "alembic":
        return _alembic(content)
    if framework == "django":
        return _django(content, version)
    if framework == "rails":
        return _rails(content, version)
    if framework == "ef":
        return _ef(content, version)
    return _liquibase(content)
