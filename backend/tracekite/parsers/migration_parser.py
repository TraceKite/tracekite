"""Schema migration parsing + shared raw-SQL table extraction.

Migrations are *declared* schema — the highest-precision data claims available
(roadmap expects 0.95). Each framework names tables explicitly, so no guessing
is needed; anything not literal is dropped, not inferred.

`parse_sql_tables` is the single SQL-table regex engine, shared with
`tracekite.services.data_extractor` so runtime SQL strings and migration DDL agree
on identity rules: quotes/backticks/brackets stripped, `schema.table` keeps the
dot, names lowercased (SQL identity is case-insensitive in practice; raw text
is preserved alongside).
"""

import re
from dataclasses import dataclass, field

from tracekite.parsers.sql_tables import (
    clean_identifier, line_of, parse_sql_tables,
)


@dataclass
class MigrationInfo:
    """Declared schema change of one migration file."""
    tables_created: list[str] = field(default_factory=list)
    tables_altered: list[str] = field(default_factory=list)
    tables_dropped: list[str] = field(default_factory=list)
    table_lines: dict[str, int] = field(default_factory=dict)
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


def _captured(pattern: re.Pattern, content: str,
              group: int = 1) -> list[tuple[str, int]]:
    return [
        (clean_identifier(match.group(group)),
         line_of(content, match.start(group)))
        for match in pattern.finditer(content)
    ]


def _names(pairs: list[tuple[str, int]]) -> list[str]:
    return _dedupe([name for name, _ in pairs])


def _first_lines(*groups: list[tuple[str, int]]) -> dict[str, int]:
    lines: dict[str, int] = {}
    for pairs in groups:
        for name, line in pairs:
            lines.setdefault(name, line)
    return lines


def _from_sql(content: str, framework: str, version: str) -> MigrationInfo:
    tables = parse_sql_tables(content)
    created = [(name, line) for name, line, _ in tables["created"]]
    altered = [(name, line) for name, line, _ in tables["altered"]]
    dropped = [(name, line) for name, line, _ in tables["dropped"]]
    return MigrationInfo(
        tables_created=_names(created),
        tables_altered=_names(altered),
        tables_dropped=_names(dropped),
        table_lines=_first_lines(created, altered, dropped),
        framework=framework, version=version)


def _alembic(content: str) -> MigrationInfo:
    # Only the upgrade() body counts: downgrade() drops what upgrade creates,
    # and reading both would report every migration as create+drop of the
    # same table.
    m = re.search(r"\bdef\s+downgrade\s*\(", content)
    body = content[:m.start()] if m else content
    rev = _ALEMBIC_REVISION.search(content)
    created = _captured(_ALEMBIC_CREATE, body)
    altered = _captured(_ALEMBIC_ALTER, body)
    dropped = _captured(_ALEMBIC_DROP, body)
    return MigrationInfo(
        tables_created=_names(created),
        tables_altered=_names(altered),
        tables_dropped=_names(dropped),
        table_lines=_first_lines(created, altered, dropped),
        framework="alembic", version=rev.group(1) if rev else "")


def _django(content: str, version: str) -> MigrationInfo:
    # Explicit db_table (within that CreateModel's options) wins; otherwise
    # the lowercased model name stands in — the real table is app-prefixed,
    # so the orchestrator treats django-inferred names as lower confidence.
    created: list[tuple[str, int]] = []
    matches = list(_DJANGO_CREATE.finditer(content))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        db = _DJANGO_DB_TABLE.search(content[m.start():end])
        name = clean_identifier(db.group(1) if db else m.group(1))
        pos = m.start() + db.start(1) if db else m.start(1)
        created.append((name, line_of(content, pos)))
    altered = _captured(_DJANGO_ALTER, content)
    dropped = _captured(_DJANGO_DELETE, content)
    return MigrationInfo(
        tables_created=_names(created),
        tables_altered=_names(altered),
        tables_dropped=_names(dropped),
        table_lines=_first_lines(created, altered, dropped),
        framework="django", version=version)


def _rails(content: str, version: str) -> MigrationInfo:
    created = _captured(_RAILS_CREATE, content)
    altered = _captured(_RAILS_ALTER, content)
    dropped = _captured(_RAILS_DROP, content)
    return MigrationInfo(
        tables_created=_names(created),
        tables_altered=_names(altered),
        tables_dropped=_names(dropped),
        table_lines=_first_lines(created, altered, dropped),
        framework="rails", version=version)


def _ef(content: str, version: str) -> MigrationInfo:
    attr = _EF_ATTR_VERSION.search(content)
    created = _captured(_EF_CREATE, content)
    altered = _captured(_EF_ALTER, content)
    dropped = _captured(_EF_DROP, content)
    return MigrationInfo(
        tables_created=_names(created),
        tables_altered=_names(altered),
        tables_dropped=_names(dropped),
        table_lines=_first_lines(created, altered, dropped),
        framework="ef", version=attr.group(1) if attr else version)


def _liquibase(content: str) -> MigrationInfo:
    created: list[tuple[str, int]] = []
    altered: list[tuple[str, int]] = []
    dropped: list[tuple[str, int]] = []
    for pattern in (_LB_XML, _LB_YAML):
        for m in pattern.finditer(content):
            tag = m.group(1)
            pair = (clean_identifier(m.group(2)),
                    line_of(content, m.start(2)))
            if tag == "createTable":
                created.append(pair)
            elif tag == "dropTable":
                dropped.append(pair)
            else:
                altered.append(pair)
    for m in _LB_SQL_BLOCK.finditer(content):   # raw <sql> through the SQL path
        raw = _from_sql(m.group(1), "liquibase", "")
        offset = line_of(content, m.start(1)) - 1
        created += [(name, raw.table_lines[name] + offset)
                    for name in raw.tables_created]
        altered += [(name, raw.table_lines[name] + offset)
                    for name in raw.tables_altered]
        dropped += [(name, raw.table_lines[name] + offset)
                    for name in raw.tables_dropped]
    cs = _LB_CHANGESET_ID.search(content)
    return MigrationInfo(
        tables_created=_names(created),
        tables_altered=_names(altered),
        tables_dropped=_names(dropped),
        table_lines=_first_lines(created, altered, dropped),
        framework="liquibase",
        version=(cs.group(1) or cs.group(2) or "") if cs else "",
    )


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
