"""Data-layer call/declaration sites.

Search indices (Elasticsearch/OpenSearch clients), ORM entity->table identity,
raw SQL table references inside string literals, NoSQL clients (Mongo, Dynamo,
Cassandra, Redis-prefix), and object storage / warehouse (S3, GCS, Snowflake,
BigQuery). Precision-first: a dynamic name (variable, f-string, template
interpolation) yields ``dynamic=True`` with ``name=""`` — visible but never a
guessed identity. Redis deliberately yields almost nothing: only a literal
``prefix:`` key style is captured, everything else is skipped.

SQL identity rules (lowercase, quote-strip, dotted schema kept) live in
``evigraph.parsers.migration_parser.parse_sql_tables`` so runtime SQL and migration
DDL can never disagree.
"""

import re
from dataclasses import dataclass, field

from evigraph.parsers.migration_parser import parse_sql_tables


@dataclass
class DataSite:
    """One data-store interaction or declaration."""
    kind: str          # "index" | "table" | "collection" | "bucket" | "warehouse" | "cache"
    name: str          # index/table/collection/bucket name ("" when dynamic)
    role: str          # "reads" | "writes" | "declares"  (unknown -> "reads")
    line: int
    system: str        # elasticsearch|opensearch|sql|mongo|dynamo|redis|cassandra|s3|gcs|snowflake|bigquery|redshift
    framework: str     # client lib that evidenced it
    env_var: str = ""
    dynamic: bool = False
    attrs: dict = field(default_factory=dict)


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


# Value in a name position: literal, env-var reference, or dynamic expression.
_ENV_PY = re.compile(
    r"os\.environ(?:\.get)?\s*[\[\(]\s*[\"'](\w+)|os\.getenv\s*\(\s*[\"'](\w+)")
_ENV_JS = re.compile(r"process\.env\.(\w+)|process\.env\[\s*['\"](\w+)")


def _classify_value(value: str) -> tuple[str, str, bool]:
    """(name, env_var, dynamic) for the text in a name argument position."""
    value = value.strip()
    m = re.match(r"f?[\"']([^\"'{]+)[\"']$", value)
    if m and not value.startswith("f"):
        return m.group(1), "", False
    m = re.match(r"`([^`$]+)`$", value)
    if m:
        return m.group(1), "", False
    env = _ENV_PY.search(value) or _ENV_JS.search(value)
    if env:
        return "", env.group(1) or env.group(2), True
    return "", "", True


# --- Elasticsearch / OpenSearch ---------------------------------------------

_ES_READS = {"search", "get", "mget", "msearch", "count", "explain", "termvectors"}
_ES_WRITES = {"index", "bulk", "update", "delete", "create", "update_by_query",
              "delete_by_query", "updateByQuery", "deleteByQuery"}

# Python client: es.search(index="owners"), es.indices.create(index=...).
# The index= kwarg is the gate — nothing else in Python spells it that way.
_ES_PY = re.compile(
    r"\.\s*(search|get|mget|msearch|count|index|bulk|update|delete|create"
    r"|update_by_query|delete_by_query)\s*\(\s*[^()]{0,120}?"
    r"\bindex\s*=\s*([^,)\n]+)")
_ES_PY_INDICES = re.compile(r"\.indices\.create\s*\(\s*[^()]{0,120}?index\s*=\s*([^,)\n]+)")
# JS client: client.search({ index: 'owners' }); indices.create({ index }).
_ES_JS = re.compile(
    r"\.\s*(search|get|mget|msearch|count|index|bulk|update|delete"
    r"|updateByQuery|deleteByQuery)\s*\(\s*\{[^{}]{0,200}?"
    r"\bindex\s*:\s*([^,}\n]+)")
_ES_JS_INDICES = re.compile(r"\.indices\.create\s*\(\s*\{[^{}]{0,200}?index\s*:\s*([^,}\n]+)")
# Java new client lambda: client.search(s -> s.index("owners")...); requests:
# new SearchRequest("owners"), new IndexRequest("owners").
_ES_JAVA_LAMBDA = re.compile(
    r"\.\s*(search|index|get|delete|update|count)\s*\(\s*\w+\s*->\s*\w+"
    r"\s*\.\s*index\s*\(\s*\"([^\"]+)\"")
_ES_JAVA_REQUEST = re.compile(
    r"\bnew\s+(Search|Index|Get|Delete|Update|Count|CreateIndex)Request\s*\(\s*\"([^\"]+)\"")
_SPRING_DATA_ES = re.compile(r"@Document\s*\(\s*indexName\s*=\s*\"([^\"]+)\"")
# Go: opensearchapi.SearchRequest{Index: []string{"owners"}}.
_ES_GO = re.compile(
    r"\b(Search|Index|Get|Delete|Update|Bulk|Create)Request\s*\{[^{}]{0,200}?"
    r"\bIndex:\s*(?:\[\]string\{)?\s*\"([^\"]+)\"")


def _es_role(verb: str) -> str:
    verb = verb[0].lower() + verb[1:]
    if verb in _ES_READS:
        return "reads"
    if verb in _ES_WRITES:
        return "writes"
    return "reads"


_ES_JS_LIBS = {"elasticsearch": "@elastic/elasticsearch",
               "opensearch": "@opensearch-project/opensearch"}


def _es_system(content: str) -> tuple[str, str]:
    if re.search(r"opensearch", content, re.I):
        return "opensearch", "opensearch"
    return "elasticsearch", "elasticsearch"


def _search_indices(content: str, lang: str, sites: list[DataSite]) -> None:
    system, lib = _es_system(content)
    if lang == "python":
        # Only in files that import the client; bare .get(index=...) elsewhere
        # (e.g. pandas) must not fabricate an index claim.
        if re.search(r"\b(?:from|import)\s+(?:elasticsearch|opensearchpy)\b", content):
            for m in _ES_PY.finditer(content):
                name, env, dyn = _classify_value(m.group(2))
                sites.append(DataSite("index", name, _es_role(m.group(1)),
                                      _line_of(content, m.start()), system,
                                      f"{lib}-py", env_var=env, dynamic=dyn))
            for m in _ES_PY_INDICES.finditer(content):
                name, env, dyn = _classify_value(m.group(1))
                sites.append(DataSite("index", name, "declares",
                                      _line_of(content, m.start()), system,
                                      f"{lib}-py", env_var=env, dynamic=dyn))
    elif lang in ("javascript", "typescript"):
        if re.search(r"['\"]@elastic/elasticsearch['\"]|['\"]@opensearch-project/opensearch['\"]",
                     content):
            for m in _ES_JS.finditer(content):
                name, env, dyn = _classify_value(m.group(2))
                sites.append(DataSite("index", name, _es_role(m.group(1)),
                                      _line_of(content, m.start()), system,
                                      _ES_JS_LIBS[lib], env_var=env, dynamic=dyn))
            for m in _ES_JS_INDICES.finditer(content):
                name, env, dyn = _classify_value(m.group(1))
                sites.append(DataSite("index", name, "declares",
                                      _line_of(content, m.start()), system,
                                      _ES_JS_LIBS[lib], env_var=env, dynamic=dyn))
    elif lang in ("java", "kotlin", "scala"):
        for m in _ES_JAVA_LAMBDA.finditer(content):
            sites.append(DataSite("index", m.group(2), _es_role(m.group(1)),
                                  _line_of(content, m.start()), system,
                                  f"{lib}-java"))
        for m in _ES_JAVA_REQUEST.finditer(content):
            role = "declares" if m.group(1) == "CreateIndex" else _es_role(m.group(1))
            sites.append(DataSite("index", m.group(2), role,
                                  _line_of(content, m.start()), system,
                                  f"{lib}-java"))
        for m in _SPRING_DATA_ES.finditer(content):
            sites.append(DataSite("index", m.group(1), "declares",
                                  _line_of(content, m.start()), system,
                                  "spring-data-elasticsearch"))
    elif lang == "go":
        if re.search(r"opensearch|elastic", content, re.I):
            for m in _ES_GO.finditer(content):
                role = "declares" if m.group(1) == "Create" else _es_role(m.group(1))
                sites.append(DataSite("index", m.group(2), role,
                                      _line_of(content, m.start()), system,
                                      f"{lib}-go"))

# --- ORM entities -> tables: kind "table", role "declares" ------------------
# Table names are lowercased for identity (SQL is case-insensitive in
# practice); the raw spelling is preserved in attrs when it differs.

_JPA_TABLE = re.compile(r"@Table\s*\(\s*[^)]*?name\s*=\s*\"([^\"]+)\"")
# Bare @Entity (no @Table name before the class keyword): the class name
# lowercased as-is stands in, flagged inferred — only explicit @Table names
# are reliable.
_JPA_ENTITY = re.compile(
    r"@Entity\b(?!\s*\()([\s\S]{0,300}?)\b(?:class|record)\s+(\w+)")
_SQLA_TABLENAME = re.compile(r"__tablename__\s*=\s*[\"']([^\"']+)")
# Second arg must be *metadata to keep boto3's dynamodb.Table("x") out.
_SQLA_TABLE = re.compile(
    r"(?<![\w.])(?:sa\.|sqlalchemy\.)?Table\s*\(\s*[\"']([^\"']+)[\"']\s*,\s*[\w.]*metadata\b",
    re.I)
_DJANGO_META_TABLE = re.compile(r"\bdb_table\s*=\s*[\"']([^\"']+)")
_PRISMA_MODEL = re.compile(r"^model\s+(\w+)\s*\{", re.M)
_PRISMA_MAP = re.compile(r"@@map\s*\(\s*\"([^\"]+)\"")
_TYPEORM_ENTITY = re.compile(
    r"@Entity\s*\(\s*(?:['\"]([^'\"]+)['\"]|\{[^}]*?name\s*:\s*['\"]([^'\"]+)['\"])")
_TYPEORM_BARE = re.compile(r"@Entity\s*\(\s*\)[\s\S]{0,120}?\bclass\s+(\w+)")
_GORM_TABLENAME = re.compile(
    r"func\s*\([^)]*\)\s*TableName\s*\(\s*\)\s*string\s*\{\s*return\s*\"([^\"]+)\"")
_EFCORE_TABLE_ATTR = re.compile(r"\[Table\s*\(\s*\"([^\"]+)\"")
_EFCORE_TOTABLE = re.compile(r"\.ToTable\s*\(\s*\"([^\"]+)\"")


def _table_site(name: str, line: int, framework: str, *, inferred: bool = False,
                system: str = "sql") -> DataSite:
    attrs: dict = {}
    if inferred:
        attrs["inferred"] = True
    if name != name.lower():
        attrs["raw"] = name
    return DataSite("table", name.lower(), "declares", line, system, framework,
                    attrs=attrs)


def _orm_tables(content: str, lang: str, sites: list[DataSite]) -> None:
    if lang in ("java", "kotlin", "scala"):
        for m in _JPA_TABLE.finditer(content):
            sites.append(_table_site(m.group(1), _line_of(content, m.start()), "jpa"))
        for m in _JPA_ENTITY.finditer(content):
            # @Table may sit on either side of @Entity in the annotation
            # stack; an explicit name anywhere on this class wins.
            if "@Table" in m.group(1) or "@Table" in content[max(0, m.start() - 200):m.start()].rsplit("class", 1)[-1]:
                continue
            sites.append(_table_site(m.group(2), _line_of(content, m.start()),
                                     "jpa", inferred=True))
    elif lang == "python":
        for m in _SQLA_TABLENAME.finditer(content):
            sites.append(_table_site(m.group(1), _line_of(content, m.start()),
                                     "sqlalchemy"))
        for m in _SQLA_TABLE.finditer(content):
            sites.append(_table_site(m.group(1), _line_of(content, m.start()),
                                     "sqlalchemy"))
        for m in _DJANGO_META_TABLE.finditer(content):
            sites.append(_table_site(m.group(1), _line_of(content, m.start()),
                                     "django"))
    elif lang in ("javascript", "typescript"):
        for m in _TYPEORM_ENTITY.finditer(content):
            name = m.group(1) or m.group(2)
            sites.append(_table_site(name, _line_of(content, m.start()), "typeorm"))
        for m in _TYPEORM_BARE.finditer(content):
            sites.append(_table_site(m.group(1), _line_of(content, m.start()),
                                     "typeorm", inferred=True))
    elif lang == "go":
        for m in _GORM_TABLENAME.finditer(content):
            sites.append(_table_site(m.group(1), _line_of(content, m.start()), "gorm"))
    elif lang in ("c#", "csharp"):
        for m in _EFCORE_TABLE_ATTR.finditer(content):
            sites.append(_table_site(m.group(1), _line_of(content, m.start()), "efcore"))
        for m in _EFCORE_TOTABLE.finditer(content):
            sites.append(_table_site(m.group(1), _line_of(content, m.start()), "efcore"))
    elif lang == "prisma":
        for m in _PRISMA_MODEL.finditer(content):
            nxt = _PRISMA_MODEL.search(content, m.end())
            block = content[m.start():nxt.start() if nxt else len(content)]
            mapped = _PRISMA_MAP.search(block)
            name = mapped.group(1) if mapped else m.group(1)
            sites.append(_table_site(name, _line_of(content, m.start()),
                                     "prisma", inferred=mapped is None))

# --- Raw SQL in string literals + warehouse routing --------------------------

# Literal scanner: triple quotes first so their bodies are not re-matched as
# single-quoted strings. Backticks are JS template literals.
_STRING_LITERAL = re.compile(
    r'f?"""(.*?)"""'
    r"|f?'''(.*?)'''"
    r'|f?"([^"\\\n]*(?:\\.[^"\\\n]*)*)"'
    r"|f?'([^'\\\n]*(?:\\.[^'\\\n]*)*)'"
    r"|`([^`]*)`", re.S)
# A literal is treated as SQL only when it *starts* with a statement verb —
# prose that merely contains "from" never enters the SQL path.
_SQL_HEAD = re.compile(
    r"^\s*(?:SELECT|INSERT|UPDATE|DELETE|WITH|MERGE|CALL|EXEC(?:UTE)?"
    r"|CREATE\s+(?:OR\s+REPLACE\s+)?TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b", re.I)
_BACKTICK_TRIPLE = re.compile(r"^`[^`]+\.[^`]+\.[^`]+`$")
_SNOWFLAKE_IMPORT = re.compile(r"\bsnowflake\.connector\b|['\"]snowflake-sdk['\"]")
_CASSANDRA_IMPORT = re.compile(r"\bfrom\s+cassandra\b|\bimport\s+cassandra\b"
                               r"|['\"]cassandra-driver['\"]")


def _sql_sites(content: str, lang: str, sites: list[DataSite]) -> None:
    if _SNOWFLAKE_IMPORT.search(content):
        default_system, default_kind = "snowflake", "warehouse"
    elif _CASSANDRA_IMPORT.search(content):
        default_system, default_kind = "cassandra", "table"
    else:
        default_system, default_kind = "sql", "table"

    if lang == "sql":
        chunks = [(0, content)]
    else:
        chunks = []
        for m in _STRING_LITERAL.finditer(content):
            body = next(g for g in m.groups() if g is not None)
            if _SQL_HEAD.match(body):
                chunks.append((m.start(), body))

    for offset, sql in chunks:
        base_line = _line_of(content, offset)
        tables = parse_sql_tables(sql)
        for key, role in (("reads", "reads"), ("writes", "writes")):
            for name, rel_line, raw in tables[key]:
                if _BACKTICK_TRIPLE.match(raw.strip()) or \
                        (raw.startswith("`") and name.count(".") == 2):
                    system, kind = "bigquery", "warehouse"   # `proj.dataset.table`
                else:
                    system, kind = default_system, default_kind
                sites.append(DataSite(kind, name, role, base_line + rel_line - 1,
                                      system, "sql", attrs={"raw": raw}))
        for name, rel_line, raw in tables["procedures"]:
            sites.append(DataSite("table", name, "reads", base_line + rel_line - 1,
                                  default_system, "sql",
                                  attrs={"procedure": True, "raw": raw}))
        for role, rel_line in tables["dynamic"]:
            sites.append(DataSite(default_kind, "", role, base_line + rel_line - 1,
                                  default_system, "sql", dynamic=True))


# --- NoSQL clients ------------------------------------------------------------

_MONGO_READS = {"find", "findOne", "find_one", "aggregate", "countDocuments",
                "count_documents", "distinct", "watch", "count"}
_MONGO_WRITES = {"insertOne", "insertMany", "insert_one", "insert_many",
                 "updateOne", "updateMany", "update_one", "update_many",
                 "replaceOne", "replace_one", "deleteOne", "deleteMany",
                 "delete_one", "delete_many", "bulkWrite", "bulk_write", "save"}
_MONGO_VERBS = _MONGO_READS | _MONGO_WRITES

# db.collection('owners').insertOne(...) — chained verb decides the role.
_MONGO_COLLECTION = re.compile(
    r"\.collection\s*\(\s*['\"`]([^'\"`$]+)['\"`]\s*\)(?:\s*\.\s*(\w+))?")
# Shell/driver property style db.owners.find(...): only with a whitelisted
# verb is this "obviously" a collection access.
_MONGO_PROP = re.compile(r"\bdb\.(\w+)\.(\w+)\s*\(")
_MONGO_SUBSCRIPT = re.compile(
    r"\bdb\s*\[\s*['\"]([^'\"]+)['\"]\s*\](?:\s*\.\s*(\w+))?")

_DYNAMO_READS = {"get_item", "query", "scan", "batch_get_item", "Get", "Query",
                 "Scan", "BatchGetItem"}
_DYNAMO_TABLE = re.compile(
    r"\.\s*Table\s*\(\s*['\"]([^'\"]+)['\"]\s*\)(?:\s*\.\s*(\w+))?")
_DYNAMO_COMMAND = re.compile(
    r"\bnew\s+(PutItem|GetItem|Query|Scan|UpdateItem|DeleteItem|BatchGetItem"
    r"|BatchWriteItem)Command\s*\(\s*\{[^{}]{0,200}?"
    r"\bTableName\s*:\s*['\"`]([^'\"`$]+)")
_DYNAMO_NET_ATTR = re.compile(r"\[DynamoDBTable\s*\(\s*\"([^\"]+)\"")

# Redis: only a literal "prefix:" key style is stable enough to name; the
# verb whitelist plus a redis-ish receiver plus the trailing colon are all
# required. Everything else is skipped entirely — no guessing.
_REDIS_KEY_PREFIX = re.compile(
    r"\b(?:redis|cache)\w*\s*\.\s*(get|set|setex|hget|hset|hgetall|delete|del"
    r"|expire|incr|lpush|rpush)\s*\(\s*f?['\"`]([A-Za-z][\w.-]*):")
_REDIS_READS = {"get", "hget", "hgetall"}


def _nosql(content: str, lang: str, sites: list[DataSite]) -> None:
    # No \b: "pymongo" has no word boundary before the m.
    if re.search(r"mongo", content, re.I):
        for m in _MONGO_COLLECTION.finditer(content):
            verb = m.group(2) or ""
            role = "writes" if verb in _MONGO_WRITES else "reads"
            sites.append(DataSite("collection", m.group(1), role,
                                  _line_of(content, m.start()), "mongo", "mongodb"))
        for m in _MONGO_PROP.finditer(content):
            if m.group(2) in _MONGO_VERBS and m.group(1) != "collection":
                role = "writes" if m.group(2) in _MONGO_WRITES else "reads"
                sites.append(DataSite("collection", m.group(1), role,
                                      _line_of(content, m.start()), "mongo",
                                      "pymongo" if lang == "python" else "mongodb"))
        for m in _MONGO_SUBSCRIPT.finditer(content):
            verb = m.group(2) or ""
            role = "writes" if verb in _MONGO_WRITES else "reads"
            sites.append(DataSite("collection", m.group(1), role,
                                  _line_of(content, m.start()), "mongo", "pymongo"))
    if re.search(r"dynamo", content, re.I):
        for m in _DYNAMO_TABLE.finditer(content):
            verb = m.group(2) or ""
            role = "reads" if (not verb or verb in _DYNAMO_READS) else "writes"
            sites.append(DataSite("table", m.group(1), role,
                                  _line_of(content, m.start()), "dynamo", "boto3"))
        for m in _DYNAMO_COMMAND.finditer(content):
            role = "reads" if m.group(1) in _DYNAMO_READS else "writes"
            sites.append(DataSite("table", m.group(2), role,
                                  _line_of(content, m.start()), "dynamo",
                                  "aws-sdk-js"))
        for m in _DYNAMO_NET_ATTR.finditer(content):
            sites.append(DataSite("table", m.group(1), "declares",
                                  _line_of(content, m.start()), "dynamo",
                                  "aws-sdk-net"))
    if re.search(r"\bredis\b", content, re.I):
        for m in _REDIS_KEY_PREFIX.finditer(content):
            role = "reads" if m.group(1) in _REDIS_READS else "writes"
            sites.append(DataSite("cache", m.group(2), role,
                                  _line_of(content, m.start()), "redis", "redis",
                                  attrs={"prefix": True}))


# --- Object storage ------------------------------------------------------------

_S3_READ_VERBS = {"get_object", "download_file", "download_fileobj",
                  "head_object", "list_objects", "list_objects_v2",
                  "GetObject", "HeadObject", "ListObjectsV2", "ListObjects"}
_S3_KWARG = re.compile(
    r"\.\s*(get_object|put_object|delete_object|head_object|copy_object"
    r"|list_objects_v2|list_objects|upload_file(?:obj)?|download_file(?:obj)?)"
    r"\s*\(\s*[^()]{0,160}?\bBucket\s*=\s*([^,)\n]+)")
# upload_file/download_file positional: (Filename, Bucket, Key).
_S3_POSITIONAL = re.compile(
    r"\.\s*(upload_file|download_file)\s*\(\s*[^,()]+,\s*['\"]([^'\"]+)['\"]")
_S3_RESOURCE = re.compile(
    r"\.\s*Bucket\s*\(\s*['\"]([^'\"]+)['\"]\s*\)(?:\s*\.\s*(\w+))?")
_S3_COMMAND = re.compile(
    r"\bnew\s+(GetObject|PutObject|DeleteObject|HeadObject|ListObjectsV2"
    r"|ListObjects|CopyObject)Command\s*\(\s*\{[^{}]{0,200}?"
    r"\bBucket\s*:\s*([^,}\n]+)")
_GCS_IMPORT = re.compile(r"google\.cloud\b.{0,40}storage|['\"]@google-cloud/storage['\"]"
                         r"|google-cloud-storage", re.S)
_GCS_BUCKET = re.compile(r"\.\s*bucket\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_GCS_WRITE_HINT = re.compile(r"upload|write|delete", re.I)


def _object_storage(content: str, lang: str, sites: list[DataSite]) -> None:
    if re.search(r"\bs3\b|boto3|aws-sdk|S3Client", content, re.I):
        for m in _S3_KWARG.finditer(content):
            name, env, dyn = _classify_value(m.group(2))
            role = "reads" if m.group(1) in _S3_READ_VERBS else "writes"
            sites.append(DataSite("bucket", name, role,
                                  _line_of(content, m.start()), "s3", "boto3",
                                  env_var=env, dynamic=dyn))
        for m in _S3_POSITIONAL.finditer(content):
            role = "reads" if m.group(1) in _S3_READ_VERBS else "writes"
            sites.append(DataSite("bucket", m.group(2), role,
                                  _line_of(content, m.start()), "s3", "boto3"))
        for m in _S3_RESOURCE.finditer(content):
            verb = m.group(2) or ""
            role = "writes" if verb.startswith(("upload", "put", "delete")) else "reads"
            sites.append(DataSite("bucket", m.group(1), role,
                                  _line_of(content, m.start()), "s3", "boto3"))
        for m in _S3_COMMAND.finditer(content):
            name, env, dyn = _classify_value(m.group(2))
            role = "reads" if m.group(1) in _S3_READ_VERBS else "writes"
            sites.append(DataSite("bucket", name, role,
                                  _line_of(content, m.start()), "s3",
                                  "aws-sdk-js", env_var=env, dynamic=dyn))
    if _GCS_IMPORT.search(content):
        for m in _GCS_BUCKET.finditer(content):
            tail = content[m.end():m.end() + 80]
            role = "writes" if _GCS_WRITE_HINT.search(tail) else "reads"
            sites.append(DataSite("bucket", m.group(1), role,
                                  _line_of(content, m.start()), "gcs",
                                  "google-cloud-storage"))


def extract_data_sites(content: str, language: str | None) -> list[DataSite]:
    """All data-layer sites in one file, deduped on (kind, name, role, system)."""
    lang = (language or "").lower()
    sites: list[DataSite] = []
    _search_indices(content, lang, sites)
    _orm_tables(content, lang, sites)
    _sql_sites(content, lang, sites)
    _nosql(content, lang, sites)
    _object_storage(content, lang, sites)

    seen: set[tuple] = set()
    unique: list[DataSite] = []
    for site in sites:
        key = (site.kind, site.name, site.role, site.system)
        if key not in seen:
            seen.add(key)
            unique.append(site)
    return unique
