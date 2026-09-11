"""Data & ML pipeline parsing.

Five stacks in one module: Databricks notebooks, jobs/bundles, Unity Catalog
references and secret scopes, dbt projects, models and schema
files, Airflow DAGs and their operators, and generic
Spark + MLflow source.

Precision-first, like every parser in this package: a dataset name is emitted
only when it appears as a string literal. Jinja templating, f-string holes and
variable arguments are never guessed at — they are dropped, and where a
``PipelineInfo`` is in hand the drop is surfaced as ``attrs["dynamic"]`` /
``attrs["templated"]`` so the gap is visible instead of silent. Secret
*values* never enter the output: Databricks ``{{secrets/scope/key}}``
references and ``dbutils.secrets.get(...)`` calls contribute scope/key *names*
only.
"""

import logging
import re
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)


@dataclass
class PipelineDataset:
    """One table/model/path a pipeline touches, as referenced in source."""
    name: str          # table/model/source name as referenced
    role: str          # "reads" | "writes" | "declares"
    kind: str          # "table" | "warehouse" | "model" | "notebook" | "dataset"
    line: int = 0
    attrs: dict = field(default_factory=dict)


@dataclass
class PipelineInfo:
    """One pipeline unit: a DAG, a dbt model/project file, a notebook, a job."""
    framework: str     # dbt | airflow | databricks | spark | mlflow | dlt
    name: str = ""     # dag_id / job name / dbt project name / notebook
    datasets: list[PipelineDataset] = field(default_factory=list)
    # Cross-DAG / %run / task references that name OTHER pipelines/notebooks.
    depends_on: list[str] = field(default_factory=list)
    attrs: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def _str(value) -> str:
    return "" if value is None else str(value)


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _line_at(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _line_of(content: str, needle: str) -> int:
    idx = content.find(needle)
    return _line_at(content, idx) if idx >= 0 else 0


def _table_kind(name: str) -> str:
    """Unity-Catalog style three-part names are warehouse-level references."""
    return "warehouse" if name.count(".") == 2 else "table"


def _call_args(content: str, open_index: int) -> str:
    """Text between a call's parentheses, string-literal aware.

    An unterminated call yields "" (mirrors iac_parser's block reader): keeping
    the call's identity is useful, but attributing the rest of the file to its
    arguments would be actively wrong.
    """
    depth, i, n = 0, open_index, len(content)
    while i < n:
        char = content[i]
        if char in "\"'":
            quote = content[i:i + 3] if content[i:i + 3] in ('"""', "'''") else char
            i += len(quote)
            while i < n:
                if content[i] == "\\" and len(quote) == 1:
                    i += 2
                    continue
                if content.startswith(quote, i):
                    i += len(quote)
                    break
                i += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return content[open_index + 1:i]
        i += 1
    return ""


_STR_OPEN = r"([rRbBuU]*[fF]?[rRbBuU]*)(\"\"\"|'''|\"|')"
_QUOTED_STR = re.compile(r"[\"']([^\"']*)[\"']")


def _string_after(text: str, prefix_pattern: str) -> tuple[str, bool] | None:
    """First string literal following ``prefix_pattern``; (value, is_fstring).

    ``prefix_pattern`` must not contain capturing groups.
    """
    match = re.search(prefix_pattern + r"\s*" + _STR_OPEN, text)
    if not match:
        return None
    prefix, quote = match.group(1) or "", match.group(2)
    end = text.find(quote, match.end())
    if end < 0:
        return None
    return text[match.end():end], "f" in prefix.lower()


def _kwarg_string(args: str, key: str) -> tuple[str, bool] | None:
    return _string_after(args, rf"\b{key}\s*=")


# --------------------------------------------------------------------------
# Inline SQL (shared by Airflow operators and spark.sql)
# --------------------------------------------------------------------------

_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_FSTRING_HOLE = re.compile(r"\{[^{}]*\}")
_SQL_PART = r"(?:[A-Za-z_][\w$]*|`[^`]+`)"
_SQL_IDENT = rf"({_SQL_PART}(?:\.{_SQL_PART}){{0,2}})"
_SQL_WRITE = re.compile(
    r"\b(?:INSERT\s+(?:INTO|OVERWRITE)(?:\s+TABLE)?|MERGE\s+INTO|UPDATE"
    r"|DELETE\s+FROM|TRUNCATE\s+TABLE|COPY\s+INTO"
    r"|CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMPORARY\s+|TEMP\s+)?"
    r"(?:MATERIALIZED\s+VIEW|TABLE|VIEW)(?:\s+IF\s+NOT\s+EXISTS)?)"
    rf"\s+{_SQL_IDENT}", re.IGNORECASE)
_SQL_READ = re.compile(rf"(?<!DELETE\s)\b(?:FROM|JOIN)\s+{_SQL_IDENT}",
                       re.IGNORECASE)
# Keywords a sloppy regex could mistake for a table after jinja stripping.
_SQL_STOPWORDS = {"select", "values", "where", "dual", "unnest", "lateral",
                  "directory"}


def _sql_datasets(sql: str, fstring: bool = False,
                  base_line: int = 1) -> list[PipelineDataset]:
    """Reads/writes from inline SQL via simple FROM / INSERT INTO patterns.

    Jinja blocks (and f-string holes when the literal was an f-string) are
    replaced with a non-identifier sentinel first, so a templated table name is
    never guessed — only the literal tokens around it survive, and every
    surviving dataset carries ``attrs["templated"]``.
    """
    templated = bool(_JINJA.search(sql)) or fstring
    cleaned = _JINJA.sub(" ? ", sql)
    if fstring:
        cleaned = _FSTRING_HOLE.sub(" ? ", cleaned)

    datasets: list[PipelineDataset] = []
    seen: set[tuple[str, str]] = set()

    def _add(raw: str, role: str, pos: int) -> None:
        name = raw.replace("`", "")
        if name.lower() in _SQL_STOPWORDS or (name, role) in seen:
            return
        seen.add((name, role))
        datasets.append(PipelineDataset(
            name=name, role=role, kind=_table_kind(name),
            line=base_line + cleaned.count("\n", 0, pos),
            attrs={"templated": True} if templated else {}))

    for match in _SQL_WRITE.finditer(cleaned):
        _add(match.group(1), "writes", match.start())
    for match in _SQL_READ.finditer(cleaned):
        _add(match.group(1), "reads", match.start())
    return datasets


# --------------------------------------------------------------------------
# Spark source scanning — any py/scala/java source
# --------------------------------------------------------------------------

_SPARK_TABLE = re.compile(
    r"\bspark\s*\.\s*(?:read(?:Stream)?\s*\.\s*)?table\s*\(\s*[\"']([^\"']+)[\"']")
_SAVE_TABLE = re.compile(r"\.(saveAsTable|insertInto)\s*\(\s*[\"']([^\"']+)[\"']")
_PATH_CALL = re.compile(
    r"\.(parquet|csv|json|orc|avro|text|load)\s*\(\s*[\"']([^\"']+)[\"']")
_DBTABLE = re.compile(r"\.option\s*\(\s*[\"']dbtable[\"']\s*,\s*[\"']([^\"']+)[\"']")
_KAFKA_SUBSCRIBE = re.compile(
    r"\.option\s*\(\s*[\"']subscribe[\"']\s*,\s*[\"']([^\"']+)[\"']")
_KAFKA_TOPIC = re.compile(r"\.option\s*\(\s*[\"']topic[\"']\s*,\s*[\"']([^\"']+)[\"']")
_FORMAT_CALL = re.compile(r"\.format\s*\(\s*[\"']([^\"']+)[\"']")
_WRITE_MARK = re.compile(r"\.write\b|\bwriteStream\b")
_READ_MARK = re.compile(r"\.read\b|\breadStream\b")
_SPARK_SQL_OPEN = re.compile(r"\bspark\s*\.\s*sql\s*\(\s*" + _STR_OPEN)
_MLFLOW_REGNAME = re.compile(r"registered_model_name\s*=\s*[\"']([^\"']+)[\"']")
_MLFLOW_REGISTER = re.compile(r"\bmlflow\.register_model\s*\(([^)]*)\)", re.DOTALL)
_URI = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://([^/]+)(/\S*)?$")
# A recognized call whose first argument is not a string literal — dynamic.
_DYNAMIC_SPARK = (
    re.compile(r"\bspark\s*\.\s*(?:read(?:Stream)?\s*\.\s*)?table\s*\(\s*[^\"')\s]"),
    re.compile(r"\.(?:saveAsTable|insertInto)\s*\(\s*[^\"')\s]"),
)


def _strip_line_comments(content: str, language: str | None) -> str:
    """Blank out full-line comments (newlines kept so line numbers hold).

    Commented-out spark calls are the main noise source; trailing comments are
    left alone so string contents are never corrupted.
    """
    # [ \t]* not \s*: \s would cross the preceding blank line's newline and
    # silently shift every later line number.
    if language in ("python", "py"):
        return re.sub(r"(?m)^[ \t]*#.*$", "", content)
    if language in ("scala", "java", "kotlin"):
        return re.sub(r"(?m)^[ \t]*//.*$", "", content)
    return content


def _chain_window(text: str, pos: int) -> str:
    """The tail of the fluent chain a call at ``pos`` belongs to."""
    window = text[max(0, pos - 500):pos]
    cut = window.rfind("\n\n")
    return window[cut:] if cut >= 0 else window


def _chain_role(text: str, pos: int) -> str:
    """"reads"/"writes" from the nearest marker in the chain; "" when unknown.

    No marker means we cannot tell whether the call reads or writes — the
    match is dropped rather than guessed (this also discards look-alike calls
    such as ``response.json("...")`` that are not Spark at all).
    """
    window = _chain_window(text, pos)
    write_at = max((m.start() for m in _WRITE_MARK.finditer(window)), default=-1)
    read_at = max((m.start() for m in _READ_MARK.finditer(window)), default=-1)
    if write_at < 0 and read_at < 0:
        return ""
    return "writes" if write_at > read_at else "reads"


def _chain_format(text: str, pos: int) -> str:
    fmt = ""
    for match in _FORMAT_CALL.finditer(_chain_window(text, pos)):
        fmt = match.group(1)
    return fmt


def _path_dataset(path: str, role: str, fmt: str, line: int) -> PipelineDataset:
    """A path-addressed dataset; object-store URIs are named by their bucket."""
    uri = _URI.match(path)
    if uri:
        name, attrs = uri.group(2), {"path": path}
    else:
        name, attrs = path, {}
    if fmt:
        attrs["format"] = fmt
    return PipelineDataset(name=name, role=role, kind="dataset", line=line,
                           attrs=attrs)


def _iter_spark_sql(text: str):
    for match in _SPARK_SQL_OPEN.finditer(text):
        quote = match.group(2)
        end = text.find(quote, match.end())
        if end < 0:
            continue
        yield (text[match.end():end], "f" in (match.group(1) or "").lower(),
               _line_at(text, match.end()))


def _register_model_name(args: str) -> str:
    """Model name from mlflow.register_model(model_uri, name) — literal only."""
    got = _kwarg_string(args, "name")
    if got and not got[1]:
        return got[0]
    quoted = _QUOTED_STR.findall(args)
    if len(quoted) >= 2:
        return quoted[1]
    if len(quoted) == 1 and ":/" not in quoted[0]:
        return quoted[0]
    return ""


def extract_spark_datasets(content: str,
                           language: str | None = None) -> list[PipelineDataset]:
    """Spark read/write + MLflow model targets in any py/scala/java source.

    Emits only string-literal names; calls with variable/f-string arguments
    are skipped entirely — a wrong table is worse than a missing one.
    """
    if not content:
        return []
    text = _strip_line_comments(content, language)
    datasets: list[PipelineDataset] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(ds: PipelineDataset) -> None:
        key = (ds.name, ds.role, ds.kind)
        if ds.name and key not in seen:
            seen.add(key)
            datasets.append(ds)

    for match in _SPARK_TABLE.finditer(text):
        name = match.group(1).replace("`", "")
        _add(PipelineDataset(name, "reads", _table_kind(name),
                             _line_at(text, match.start())))
    for match in _SAVE_TABLE.finditer(text):
        name = match.group(2).replace("`", "")
        _add(PipelineDataset(name, "writes", _table_kind(name),
                             _line_at(text, match.start())))

    for match in _PATH_CALL.finditer(text):
        role = _chain_role(text, match.start())
        if not role:
            continue
        method, path = match.group(1), match.group(2)
        fmt = _chain_format(text, match.start())
        if not fmt and method != "load":
            fmt = method
        _add(_path_dataset(path, role, fmt, _line_at(text, match.start())))

    for match in _DBTABLE.finditer(text):
        role = _chain_role(text, match.start())
        if not role:
            continue
        name = match.group(1).replace("`", "")
        _add(PipelineDataset(name, role, _table_kind(name),
                             _line_at(text, match.start())))

    if "kafka" in text:
        for match in _KAFKA_SUBSCRIBE.finditer(text):
            for topic in match.group(1).split(","):
                topic = topic.strip()
                if topic:
                    _add(PipelineDataset(topic, "reads", "dataset",
                                         _line_at(text, match.start()),
                                         {"kafka_topic": topic}))
        for match in _KAFKA_TOPIC.finditer(text):
            topic = match.group(1).strip()
            role = _chain_role(text, match.start()) or "writes"
            _add(PipelineDataset(topic, role, "dataset",
                                 _line_at(text, match.start()),
                                 {"kafka_topic": topic}))

    for sql, fstring, line in _iter_spark_sql(text):
        for ds in _sql_datasets(sql, fstring=fstring, base_line=line):
            _add(ds)

    for match in _MLFLOW_REGNAME.finditer(text):
        _add(PipelineDataset(match.group(1), "declares", "dataset",
                             _line_at(text, match.start()),
                             {"mlflow_model": True}))
    for match in _MLFLOW_REGISTER.finditer(text):
        name = _register_model_name(match.group(1))
        if name:
            _add(PipelineDataset(name, "declares", "dataset",
                                 _line_at(text, match.start()),
                                 {"mlflow_model": True}))
    return datasets


def _has_dynamic_spark(content: str) -> bool:
    return any(probe.search(content) for probe in _DYNAMIC_SPARK)


# --------------------------------------------------------------------------
# dbt
# --------------------------------------------------------------------------

_DBT_REF = re.compile(
    r"\{\{\s*ref\s*\(\s*['\"]([^'\"]+)['\"]\s*"
    r"(?:,\s*['\"]([^'\"]+)['\"]\s*)?\)\s*\}\}")
_DBT_SOURCE = re.compile(
    r"\{\{\s*source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_DBT_REF_ANY = re.compile(r"\{\{\s*ref\s*\(")
_DBT_SOURCE_ANY = re.compile(r"\{\{\s*source\s*\(")
_DBT_MATERIALIZED = re.compile(r"materialized\s*=\s*['\"](\w+)['\"]")


def parse_dbt_project(file_path: str, content: str) -> PipelineInfo | None:
    """dbt_project.yml → project identity. A project file declares nothing."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        logger.debug("Not parseable as dbt project %s: %s", file_path, exc)
        return None
    if not isinstance(data, dict) or not data.get("name"):
        return None
    info = PipelineInfo(framework="dbt", name=_str(data["name"]))
    if data.get("profile"):
        info.attrs["profile"] = _str(data["profile"])
    if data.get("version") is not None:
        info.attrs["version"] = _str(data["version"])
    return info


def parse_dbt_model(file_path: str, content: str) -> PipelineInfo | None:
    """models/*.sql — the ref()/source() graph is explicit and precise.

    The model file itself writes the model named by its filename stem. Only
    jinja ``ref``/``source`` calls become reads: raw FROM clauses in a dbt
    model name CTEs and other models' *rendered* relations, which we must not
    guess at. A ref/source whose argument is not a string literal sets
    ``attrs["dynamic"]`` instead of emitting a name.
    """
    base = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    if not base.lower().endswith(".sql"):
        return None
    stem = base[:-4]
    if not stem:
        return None
    content = content or ""
    info = PipelineInfo(framework="dbt", name=stem)
    info.datasets.append(PipelineDataset(stem, "writes", "model", 1))
    seen: set[tuple[str, str]] = {(stem, "writes")}

    literal_refs = 0
    for match in _DBT_REF.finditer(content):
        literal_refs += 1
        name = match.group(2) or match.group(1)
        attrs = {"package": match.group(1)} if match.group(2) else {}
        if (name, "reads") not in seen:
            seen.add((name, "reads"))
            info.datasets.append(PipelineDataset(
                name, "reads", "model", _line_at(content, match.start()), attrs))

    literal_sources = 0
    for match in _DBT_SOURCE.finditer(content):
        literal_sources += 1
        name = f"{match.group(1)}.{match.group(2)}"
        if (name, "reads") not in seen:
            seen.add((name, "reads"))
            info.datasets.append(PipelineDataset(
                name, "reads", "table", _line_at(content, match.start()),
                {"source": match.group(1)}))

    if (len(_DBT_REF_ANY.findall(content)) > literal_refs
            or len(_DBT_SOURCE_ANY.findall(content)) > literal_sources):
        info.attrs["dynamic"] = True
    if (mat := _DBT_MATERIALIZED.search(content)):
        info.attrs["materialized"] = mat.group(1)
    return info


def parse_dbt_sources(file_path: str, content: str) -> PipelineInfo | None:
    """models/**/*.yml schema files: declared sources and models."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        logger.debug("Not parseable as dbt schema %s: %s", file_path, exc)
        return None
    if not isinstance(data, dict):
        return None
    info = PipelineInfo(framework="dbt")

    for source in _as_list(data.get("sources")):
        if not isinstance(source, dict) or not source.get("name"):
            continue
        source_name = _str(source["name"])
        schema = _str(source.get("schema")) or source_name
        for table in _as_list(source.get("tables")):
            if not isinstance(table, dict) or not table.get("name"):
                continue
            table_name = _str(table["name"])
            attrs = {"source": source_name}
            if table.get("identifier"):
                attrs["identifier"] = _str(table["identifier"])
            info.datasets.append(PipelineDataset(
                f"{schema}.{table_name}", "declares", "table",
                _line_of(content, f"name: {table_name}"), attrs))

    for model in _as_list(data.get("models")):
        if isinstance(model, dict) and model.get("name"):
            model_name = _str(model["name"])
            info.datasets.append(PipelineDataset(
                model_name, "declares", "model",
                _line_of(content, f"name: {model_name}")))

    return info if info.datasets else None


# --------------------------------------------------------------------------
# Airflow
# --------------------------------------------------------------------------

_AIRFLOW_IMPORT = re.compile(r"^\s*(?:from|import)\s+airflow\b", re.MULTILINE)
_DAG_CALL = re.compile(r"\bDAG\s*\(")
_DAG_DECORATOR = re.compile(r"@dag\b")
_OPERATOR_CALL = re.compile(r"\b([A-Z]\w*(?:Operator|Sensor))\s*\(")
_LEADING_STRING = re.compile(r"^\s*[\"']([^\"']+)[\"']")


def _record_dep(info: PipelineInfo, got: tuple[str, bool] | None) -> None:
    """A cross-DAG reference — literal only; templated ids are flagged."""
    if got is None:
        return
    value, fstring = got
    if not value or fstring or "{{" in value:
        info.attrs["dynamic"] = True
        return
    if value not in info.depends_on:
        info.depends_on.append(value)


def _add_dataset(info: PipelineInfo, dataset: PipelineDataset) -> None:
    for existing in info.datasets:
        if (existing.name, existing.role, existing.kind) == (
                dataset.name, dataset.role, dataset.kind):
            return
    info.datasets.append(dataset)


def _sql_base_line(content: str, sql: str, fallback: int) -> int:
    pos = content.find(sql)
    return _line_at(content, pos) if pos >= 0 else fallback


def parse_airflow_dag(file_path: str, content: str) -> PipelineInfo | None:
    """Python DAG files: dag identity, SQL operator tables, cross-DAG deps.

    A file counts as a DAG only when an airflow import sits next to ``DAG(``
    or ``@dag``. Operator handling is deliberately narrow: any operator with a
    literal ``sql=`` contributes tables via the shared SQL patterns,
    S3ToRedshiftOperator contributes its bucket→table copy, and
    TriggerDagRunOperator / ExternalTaskSensor contribute cross-DAG edges.
    Messaging operators are left to the messaging extractors (M4).
    """
    if not content or not _AIRFLOW_IMPORT.search(content):
        return None
    dag_call = _DAG_CALL.search(content)
    decorator = _DAG_DECORATOR.search(content)
    if not dag_call and not decorator:
        return None

    info = PipelineInfo(framework="airflow")

    if dag_call:
        args = _call_args(content, content.index("(", dag_call.start()))
        got = _kwarg_string(args, "dag_id")
        if got and not got[1]:
            info.name = got[0]
        elif (leading := _LEADING_STRING.match(args)):
            info.name = leading.group(1)
        for key in ("schedule", "schedule_interval"):
            if (got := _kwarg_string(args, key)) and not got[1]:
                info.attrs["schedule"] = got[0]
                break
    if not info.name and decorator:
        rest = content[decorator.end():]
        search_from = decorator.end()
        stripped = rest.lstrip()
        if stripped.startswith("("):
            paren = decorator.end() + (len(rest) - len(stripped))
            blob = _call_args(content, paren)
            if (got := _kwarg_string(blob, "dag_id")) and not got[1]:
                info.name = got[0]
            if "schedule" not in info.attrs:
                for key in ("schedule", "schedule_interval"):
                    if (got := _kwarg_string(blob, key)) and not got[1]:
                        info.attrs["schedule"] = got[0]
                        break
            search_from = paren + len(blob)
        if not info.name:
            after = content[search_from:search_from + 400]
            if (fn := re.search(r"\bdef\s+(\w+)", after)):
                info.name = fn.group(1)
    if not info.name:
        info.attrs["dynamic"] = True

    for match in _OPERATOR_CALL.finditer(content):
        operator = match.group(1)
        args = _call_args(content, match.end() - 1)
        op_line = _line_at(content, match.start())

        if operator == "TriggerDagRunOperator":
            _record_dep(info, _kwarg_string(args, "trigger_dag_id"))
            continue
        if operator == "ExternalTaskSensor":
            _record_dep(info, _kwarg_string(args, "external_dag_id"))
            continue
        if operator == "S3ToRedshiftOperator":
            bucket = _kwarg_string(args, "s3_bucket")
            key = _kwarg_string(args, "s3_key")
            schema = _kwarg_string(args, "schema")
            table = _kwarg_string(args, "table")
            if bucket and not bucket[1]:
                attrs = {}
                if key:
                    attrs["path"] = f"s3://{bucket[0]}/{key[0]}"
                    if key[1] or "{{" in key[0]:
                        attrs["templated"] = True
                _add_dataset(info, PipelineDataset(
                    bucket[0], "reads", "dataset", op_line, attrs))
            if table and not table[1] and "{{" not in table[0]:
                name = table[0]
                if schema and not schema[1] and "{{" not in schema[0]:
                    name = f"{schema[0]}.{name}"
                _add_dataset(info, PipelineDataset(
                    name, "writes", _table_kind(name), op_line))
            continue

        # Any SQL-carrying operator (PostgresOperator, SnowflakeOperator,
        # BigQueryInsertJobOperator, ...): the tables live in the SQL itself.
        got = _kwarg_string(args, "sql")
        if got is None and operator == "BigQueryInsertJobOperator":
            got = _string_after(args, r"[\"']query[\"']\s*:")
        if got is not None:
            sql, fstring = got
            base = _sql_base_line(content, sql, op_line)
            for ds in _sql_datasets(sql, fstring=fstring, base_line=base):
                _add_dataset(info, ds)
    return info


# --------------------------------------------------------------------------
# Databricks
# --------------------------------------------------------------------------

_NOTEBOOK_HEADER = "# Databricks notebook source"
_SECRET_SCOPE = re.compile(r"\{\{\s*secrets/([A-Za-z0-9_.-]+)/")
_MAGIC_RUN = re.compile(r"^\s*(?:#\s*MAGIC\s+)?%run\s+[\"']?([^\s\"']+)",
                        re.MULTILINE)
_NOTEBOOK_RUN = re.compile(r"dbutils\.notebook\.run\s*\(\s*[\"']([^\"']+)[\"']")
_NOTEBOOK_RUN_DYNAMIC = re.compile(r"dbutils\.notebook\.run\s*\(\s*[^\"'\s]")
_SECRETS_GET = re.compile(r"dbutils\.secrets\.get\s*\(([^)]*)\)")
_DLT_IMPORT = re.compile(r"^\s*(?:import\s+dlt\b|from\s+dlt\b)", re.MULTILINE)
_DLT_TABLE = re.compile(
    r"@dlt\.(?:table|view)\s*(?:\(([^)]*)\))?\s*"
    r"(?:@[\w.]+\s*(?:\([^)]*\))?\s*)*def\s+(\w+)", re.DOTALL)
_DLT_READ = re.compile(r"\bdlt\.(?:read|read_stream)\s*\(\s*[\"']([^\"']+)[\"']")


def parse_databricks_bundle(file_path: str, content: str) -> PipelineInfo | None:
    """databricks.yml asset bundles — a declared manifest.

    Job tasks' notebook paths and DLT pipeline libraries become ``depends_on``
    edges to the notebooks they run. ``{{secrets/scope/key}}`` references
    contribute scope *names* only — a bundle can never move a
    credential into the graph. Cluster definitions are ignored.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        logger.debug("Not parseable as bundle %s: %s", file_path, exc)
        return None
    if not isinstance(data, dict):
        return None
    bundle = _dict(data.get("bundle"))
    blocks = [_dict(data.get("resources"))]
    for target in _dict(data.get("targets")).values():
        blocks.append(_dict(_dict(target).get("resources")))
    if not bundle.get("name") and not any(blocks):
        return None

    info = PipelineInfo(framework="databricks", name=_str(bundle.get("name")))
    jobs: list[str] = []
    pipelines: list[str] = []

    def _ref(path) -> None:
        path = _str(path)
        if not path:
            return
        if "${" in path:                    # bundle variable — never guess
            info.attrs["dynamic"] = True
            return
        if path not in info.depends_on:
            info.depends_on.append(path)

    for block in blocks:
        for job_key, job in _dict(block.get("jobs")).items():
            if str(job_key) not in jobs:
                jobs.append(str(job_key))
            for task in _as_list(_dict(job).get("tasks")):
                task = _dict(task)
                _ref(_dict(task.get("notebook_task")).get("notebook_path"))
                _ref(_dict(task.get("spark_python_task")).get("python_file"))
        for pipe_key, pipe in _dict(block.get("pipelines")).items():
            if str(pipe_key) not in pipelines:
                pipelines.append(str(pipe_key))
            for library in _as_list(_dict(pipe).get("libraries")):
                library = _dict(library)
                _ref(_dict(library.get("notebook")).get("path"))
                _ref(_dict(library.get("file")).get("path"))

    if jobs:
        info.attrs["jobs"] = jobs
    if pipelines:
        info.attrs["pipelines"] = pipelines
    scopes = sorted(set(_SECRET_SCOPE.findall(content)))
    if scopes:
        info.attrs["secret_scopes"] = scopes
    return info


def parse_databricks_notebook(file_path: str, content: str) -> PipelineInfo | None:
    """.py notebooks with a ``# Databricks notebook source`` header.

    ``%run`` / ``# MAGIC %run`` / ``dbutils.notebook.run`` build the notebook
    call graph; table access comes from the shared Spark scanner (Unity
    Catalog three-part names → kind "warehouse"). ``import dlt``
    switches the framework to "dlt" and @dlt.table definitions become writes.
    Secret references keep scope/key names only.
    """
    if not content:
        return None
    first = content.lstrip("\ufeff \t\r\n").split("\n", 1)[0].strip()
    if not first.startswith(_NOTEBOOK_HEADER):
        return None

    base = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base[:-3] if base.endswith(".py") else base
    framework = "dlt" if _DLT_IMPORT.search(content) else "databricks"
    info = PipelineInfo(framework=framework, name=stem)

    for match in _MAGIC_RUN.finditer(content):
        if match.group(1) not in info.depends_on:
            info.depends_on.append(match.group(1))
    for match in _NOTEBOOK_RUN.finditer(content):
        if match.group(1) not in info.depends_on:
            info.depends_on.append(match.group(1))
    if _NOTEBOOK_RUN_DYNAMIC.search(content) or _has_dynamic_spark(content):
        info.attrs["dynamic"] = True

    for dataset in extract_spark_datasets(content, "python"):
        _add_dataset(info, dataset)

    if framework == "dlt":
        for match in _DLT_TABLE.finditer(content):
            args = match.group(1) or ""
            got = _kwarg_string(args, "name")
            name = got[0] if got and not got[1] else match.group(2)
            _add_dataset(info, PipelineDataset(
                name, "writes", "table", _line_at(content, match.start()),
                {"dlt": True}))
        for match in _DLT_READ.finditer(content):
            _add_dataset(info, PipelineDataset(
                match.group(1), "reads", "table",
                _line_at(content, match.start()), {"dlt": True}))

    refs: list[str] = []
    for match in _SECRETS_GET.finditer(content):
        args = match.group(1)
        scope = _kwarg_string(args, "scope")
        key = _kwarg_string(args, "key")
        if scope is None or key is None:
            quoted = _QUOTED_STR.findall(args)
            if scope is None and len(quoted) >= 1:
                scope = (quoted[0], False)
            if key is None and len(quoted) >= 2:
                key = (quoted[1], False)
        if scope and not scope[1] and scope[0]:
            ref = scope[0] + (f"/{key[0]}" if key and not key[1] else "")
            if ref not in refs:
                refs.append(ref)
    if refs:
        info.attrs["secret_refs"] = refs
    return info


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def is_pipeline_file(file_path: str, content: str) -> str:
    """Classify a file for this module; "" when it is not a pipeline file.

    Returns one of: "dbt-project", "dbt-model", "dbt-schema", "airflow",
    "databricks-bundle", "databricks-notebook".
    """
    path = file_path.replace("\\", "/")
    base = path.rsplit("/", 1)[-1].lower()
    content = content or ""

    if base in ("dbt_project.yml", "dbt_project.yaml"):
        return "dbt-project"
    if base in ("databricks.yml", "databricks.yaml"):
        return "databricks-bundle"
    if base.endswith(".py"):
        first = content.lstrip("\ufeff \t\r\n").split("\n", 1)[0].strip()
        if first.startswith(_NOTEBOOK_HEADER):
            return "databricks-notebook"
        if _AIRFLOW_IMPORT.search(content) and (
                _DAG_CALL.search(content) or _DAG_DECORATOR.search(content)):
            return "airflow"
        return ""
    in_models = "/models/" in path or path.startswith("models/")
    if base.endswith(".sql"):
        if in_models or _DBT_REF_ANY.search(content) or _DBT_SOURCE_ANY.search(content):
            return "dbt-model"
        return ""
    if base.endswith((".yml", ".yaml")) and in_models:
        if re.search(r"^(?:sources|models)\s*:", content, re.MULTILINE):
            return "dbt-schema"
    return ""
