"""Ownership and observability service identity.

Three independent signal families live here because they answer the same two
questions — *who owns this service* and *what does this service call itself*:

- CODEOWNERS: the cheapest ownership signal. Rules are returned in
  file order and never resolved here — "later rules win" is precedence, and
  precedence belongs to the resolver, not the parser.
- Backstage catalog-info.yaml (PagerDuty/OpsGenie annotations): declared
  service identity + ownership. Corroboration only, never
  load-bearing.
- Observability config: OTel, Datadog, New Relic, Sentry and
  Prometheus each make a service state its own name. Each hit is a second
  independent vote for alias unification.

Secrets never enter the output: PagerDuty integration keys, Datadog/New Relic
API and license keys, Sentry DSNs and auth tokens are either never read or
live under key names this module does not lift. Nothing here raises — a
malformed file yields whatever was parseable, or an empty list.
"""

import logging
import re
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)


def _str(value) -> str:
    return "" if value is None else str(value)


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _basename(file_path: str) -> str:
    return _str(file_path).replace("\\", "/").rstrip("/").split("/")[-1]


def _clean_value(raw) -> str:
    """Strip a trailing ` # comment` and one layer of matching quotes."""
    text = _str(raw).strip()
    text = re.sub(r"\s+#.*$", "", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text.strip()


# ---------------------------------------------------------------------------
# CODEOWNERS
# ---------------------------------------------------------------------------

@dataclass
class OwnershipRule:
    pattern: str        # path pattern exactly as written (incl. escaped spaces)
    owners: list[str]   # leading @ stripped; org/team kept; emails verbatim
    line: int


_CODEOWNERS_LOCATIONS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")

# A token is a run of non-space characters, where a backslash-escaped space
# (`docs/my\ file.md`) counts as part of the token.
_CODEOWNERS_TOKEN = re.compile(r"(?:\\ |\S)+")


def is_codeowners_file(file_path: str) -> bool:
    """CODEOWNERS is only honored at the repo root, .github/ or docs/."""
    path = _str(file_path).replace("\\", "/").lstrip("/")
    if path.startswith("./"):
        path = path[2:]
    return path in _CODEOWNERS_LOCATIONS


def parse_codeowners(file_path: str, content: str) -> list[OwnershipRule]:
    """All rules, in file order, precedence unresolved.

    GitHub gives the *last* matching rule the ownership, so the full ordered
    list is the signal; collapsing it here would throw away the tie-break the
    resolver needs. A pattern with no owners is kept too — it un-owns paths a
    broader earlier rule matched.
    """
    rules: list[OwnershipRule] = []
    if not isinstance(content, str) or not content:
        return rules
    try:
        for lineno, raw in enumerate(content.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # GitLab section headers ([Section], ^[Optional]) are not rules.
            if line.startswith("[") or line.startswith("^["):
                continue
            line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
            tokens = _CODEOWNERS_TOKEN.findall(line)
            if not tokens:
                continue
            owners = []
            for token in tokens[1:]:
                owner = token.lstrip("@")   # @acme/team -> acme/team; emails untouched
                if owner:
                    owners.append(owner)
            rules.append(OwnershipRule(pattern=tokens[0], owners=owners, line=lineno))
    except Exception as exc:  # never raise; keep whatever parsed
        logger.debug("CODEOWNERS parse stopped in %s: %s", file_path, exc)
    return rules


# ---------------------------------------------------------------------------
# Backstage catalog-info.yaml
# ---------------------------------------------------------------------------

@dataclass
class CatalogEntity:
    kind: str          # Component | System | API | Resource | Domain | Group
    name: str
    owner: str = ""            # spec.owner, group:default/team-a -> team-a
    system: str = ""           # spec.system, ref-normalized
    lifecycle: str = ""
    entity_type: str = ""      # spec.type (service, library, website, ...)
    provides_apis: list[str] = field(default_factory=list)
    consumes_apis: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    pagerduty_service: str = ""   # pagerduty.com/service-id annotation only
    opsgenie_team: str = ""
    attrs: dict = field(default_factory=dict)


CATALOG_KINDS = {"Component", "System", "API", "Resource", "Domain", "Group"}

_PAGERDUTY_SERVICE_ID = "pagerduty.com/service-id"
_OPSGENIE_TEAM = "opsgenie.com/team"
_PROJECT_SLUG = "github.com/project-slug"


def is_catalog_file(file_name: str) -> bool:
    name = _basename(file_name).lower()
    return name in ("catalog-info.yaml", "catalog-info.yml")


def _bare_ref(ref) -> str:
    """Backstage ref `[kind:][namespace/]name` -> bare name.

    group:default/team-a -> team-a, api:billing -> billing, team-a -> team-a.
    """
    text = _str(ref).strip()
    if ":" in text:
        text = text.split(":", 1)[1]
    if "/" in text:
        text = text.rsplit("/", 1)[1]
    return text.strip()


def _ref_list(value) -> tuple[list[str], list[str]]:
    originals = [_str(v).strip() for v in _as_list(value) if _str(v).strip()]
    return [_bare_ref(v) for v in originals], originals


def parse_catalog_info(file_path: str, content: str) -> list[CatalogEntity]:
    """Every Backstage entity in a (possibly multi-doc) catalog-info.yaml.

    Only specifically known-safe annotations are lifted; the annotations map
    is never copied wholesale, because `pagerduty.com/integration-key` is a
    credential and must not enter the graph in any field.
    """
    entities: list[CatalogEntity] = []
    if not isinstance(content, str) or not content:
        return entities
    try:
        documents = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        logger.debug("Not parseable as catalog YAML %s: %s", file_path, exc)
        return entities
    try:
        for document in documents:
            if not isinstance(document, dict):
                continue
            kind = _str(document.get("kind"))
            if kind not in CATALOG_KINDS:
                continue
            metadata = document.get("metadata") or {}
            if not isinstance(metadata, dict):
                continue
            name = _str(metadata.get("name")).strip()
            if not name:
                continue
            spec = document.get("spec") or {}
            if not isinstance(spec, dict):
                spec = {}
            annotations = metadata.get("annotations") or {}
            if not isinstance(annotations, dict):
                annotations = {}

            entity = CatalogEntity(
                kind=kind,
                name=name,
                owner=_bare_ref(spec.get("owner")),
                system=_bare_ref(spec.get("system")),
                lifecycle=_str(spec.get("lifecycle")),
                entity_type=_str(spec.get("type")),
                pagerduty_service=_str(annotations.get(_PAGERDUTY_SERVICE_ID)),
                opsgenie_team=_str(annotations.get(_OPSGENIE_TEAM)),
            )
            entity.provides_apis, provides_raw = _ref_list(spec.get("providesApis"))
            entity.consumes_apis, consumes_raw = _ref_list(spec.get("consumesApis"))
            entity.depends_on, depends_raw = _ref_list(spec.get("dependsOn"))

            attrs = {
                "apiVersion": _str(document.get("apiVersion")),
                "namespace": _str(metadata.get("namespace")),
                "title": _str(metadata.get("title")),
                "project_slug": _str(annotations.get(_PROJECT_SLUG)),
            }
            if provides_raw:
                attrs["providesApis"] = provides_raw
            if consumes_raw:
                attrs["consumesApis"] = consumes_raw
            if depends_raw:
                attrs["dependsOn"] = depends_raw
            entity.attrs = {k: v for k, v in attrs.items() if v}
            entities.append(entity)
    except Exception as exc:  # never raise; keep whatever parsed
        logger.debug("Catalog parse stopped in %s: %s", file_path, exc)
    return entities


# ---------------------------------------------------------------------------
# Observability service identity
# ---------------------------------------------------------------------------

@dataclass
class ObservabilityIdentity:
    service_name: str
    source: str        # otel-env | otel-resource | datadog | newrelic |
                       # sentry-project | prometheus-job
    line: int = 0
    environment: str = ""
    team: str = ""     # Datadog team tag when present
    attrs: dict = field(default_factory=dict)


_CODE_EXTS = {"py", "js", "ts", "jsx", "tsx", "mjs", "cjs"}

_KNOWN_ENV_VARS = ("OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES",
                   "DD_SERVICE", "DD_ENV", "DD_TAGS",
                   "NEW_RELIC_APP_NAME", "SENTRY_PROJECT")

# NAME=value / NAME: value, incl. `export`, Dockerfile `ENV`, compose `- X=y`.
_ENV_PLAIN = re.compile(
    r"^\s*(?:export\s+|ENV\s+|-\s+)?(" + "|".join(_KNOWN_ENV_VARS) + r")\s*[:=]\s*(.+?)\s*$")
# Kubernetes env style: `- name: OTEL_SERVICE_NAME` / `value: orders` pairs.
_ENV_PAIR_NAME = re.compile(
    r"^\s*-?\s*name:\s*[\"']?(" + "|".join(_KNOWN_ENV_VARS) + r")[\"']?\s*$")
_ENV_ANY_NAME = re.compile(r"^\s*-\s*name:")
_ENV_PAIR_VALUE = re.compile(r"^\s*value:\s*(.+?)\s*$")

_DD_LABEL_SERVICE = re.compile(
    r"^\s*[\"']?tags\.datadoghq\.com/service[\"']?\s*:\s*(.+?)\s*$")
_DD_LABEL_ENV = re.compile(
    r"^\s*[\"']?tags\.datadoghq\.com/env[\"']?\s*:\s*(.+?)\s*$")

# Code-level OTel resource attributes.
#   Resource.create({SERVICE_NAME: "orders"})                       (python)
#   new Resource({[SemanticResourceAttributes.SERVICE_NAME]: "x"})  (js/ts)
#   {"service.name": "orders"} literal key                          (both)
_OTEL_CODE_CONST = re.compile(r"SERVICE_NAME\s*\]?\s*:\s*[\"']([^\"']+)[\"']")
_OTEL_CODE_LITERAL = re.compile(r"[\"']service\.name[\"']\s*:\s*[\"']([^\"']+)[\"']")


def _line_map(content: str, pattern: re.Pattern) -> dict[str, int]:
    """First line number for each cleaned first-group value of ``pattern``."""
    mapping: dict[str, int] = {}
    for lineno, line in enumerate(content.splitlines(), start=1):
        match = pattern.match(line)
        if match:
            mapping.setdefault(_clean_value(match.group(1)), lineno)
    return mapping


def _scan_env_assignments(content: str) -> list[tuple[str, str, int]]:
    """(VAR, cleaned value, line) for the recognized observability env vars."""
    found: list[tuple[str, str, int]] = []
    lines = content.splitlines()
    for index, raw in enumerate(lines):
        if match := _ENV_PLAIN.match(raw):
            value = _clean_value(match.group(2))
            if value:
                found.append((match.group(1), value, index + 1))
            continue
        if match := _ENV_PAIR_NAME.match(raw):
            # `value:` must arrive within the next 2 lines and before the
            # next env entry, or the name stays unpaired.
            for offset in (1, 2):
                if index + offset >= len(lines):
                    break
                candidate = lines[index + offset]
                if _ENV_ANY_NAME.match(candidate):
                    break
                if value_match := _ENV_PAIR_VALUE.match(candidate):
                    value = _clean_value(value_match.group(1))
                    if value:
                        found.append((match.group(1), value, index + 1))
                    break
    return found


def _parse_tag_string(raw: str) -> dict[str, str]:
    """`service:orders,team:payments env:prod` -> {service: ..., team: ...}."""
    tags: dict[str, str] = {}
    for chunk in re.split(r"[,\s]+", _str(raw)):
        if ":" in chunk:
            key, _, value = chunk.partition(":")
            if key and value:
                tags.setdefault(key.strip(), value.strip())
    return tags


def _identities_from_env(content: str) -> list[ObservabilityIdentity]:
    """OTel / Datadog / New Relic / Sentry env conventions in one pass.

    OTel and Datadog get file-level enrichment: OTEL_RESOURCE_ATTRIBUTES'
    deployment.environment attaches to the OTEL_SERVICE_NAME identity, and
    DD_ENV / DD_TAGS team attach to the DD_SERVICE identity.
    """
    results: list[ObservabilityIdentity] = []
    otel_services: list[tuple[str, int]] = []
    otel_environment = ""
    otel_attrs: dict = {}
    dd_services: list[tuple[str, int]] = []
    dd_environment = ""
    dd_team = ""

    for var, value, line in _scan_env_assignments(content):
        if var == "OTEL_SERVICE_NAME":
            otel_services.append((value, line))
        elif var == "OTEL_RESOURCE_ATTRIBUTES":
            pairs = {}
            for chunk in value.split(","):
                if "=" in chunk:
                    key, _, val = chunk.partition("=")
                    pairs[key.strip()] = val.strip()
            if pairs.get("service.name"):
                otel_services.append((pairs["service.name"], line))
            otel_environment = (otel_environment
                               or pairs.get("deployment.environment", "")
                               or pairs.get("deployment.environment.name", ""))
            for key in ("service.namespace", "service.version"):
                if pairs.get(key):
                    otel_attrs.setdefault(key, pairs[key])
        elif var == "DD_SERVICE":
            dd_services.append((value, line))
        elif var == "DD_ENV":
            dd_environment = dd_environment or value
        elif var == "DD_TAGS":
            tags = _parse_tag_string(value)
            if tags.get("service"):
                dd_services.append((tags["service"], line))
            dd_environment = dd_environment or tags.get("env", "")
            dd_team = dd_team or tags.get("team", "")
        elif var == "NEW_RELIC_APP_NAME":
            results.append(ObservabilityIdentity(
                service_name=value, source="newrelic", line=line))
        elif var == "SENTRY_PROJECT":
            results.append(ObservabilityIdentity(
                service_name=value, source="sentry-project", line=line))

    for name, line in otel_services:
        results.append(ObservabilityIdentity(
            service_name=name, source="otel-env", line=line,
            environment=otel_environment, attrs=dict(otel_attrs)))
    for name, line in dd_services:
        results.append(ObservabilityIdentity(
            service_name=name, source="datadog", line=line,
            environment=dd_environment, team=dd_team))
    return results


def _identities_from_dd_labels(content: str) -> list[ObservabilityIdentity]:
    """`tags.datadoghq.com/service` labels in Kubernetes manifests.

    The env label sits in the same label block, so it is looked up within a
    few lines of the service label rather than file-wide.
    """
    results: list[ObservabilityIdentity] = []
    lines = content.splitlines()
    for index, raw in enumerate(lines):
        match = _DD_LABEL_SERVICE.match(raw)
        if not match:
            continue
        service = _clean_value(match.group(1))
        if not service:
            continue
        environment = ""
        for nearby in lines[max(0, index - 3):index + 4]:
            if env_match := _DD_LABEL_ENV.match(nearby):
                environment = _clean_value(env_match.group(1))
                break
        results.append(ObservabilityIdentity(
            service_name=service, source="datadog", line=index + 1,
            environment=environment))
    return results


def _identities_from_code(content: str) -> list[ObservabilityIdentity]:
    """OTel Resource attributes set in Python/JS code -> otel-resource."""
    if "opentelemetry" not in content.lower() and "Resource" not in content:
        return []
    results: list[ObservabilityIdentity] = []
    for pattern in (_OTEL_CODE_CONST, _OTEL_CODE_LITERAL):
        for match in pattern.finditer(content):
            value = match.group(1).strip()
            if value:
                line = content.count("\n", 0, match.start()) + 1
                results.append(ObservabilityIdentity(
                    service_name=value, source="otel-resource", line=line))
    return results


def _safe_load_first(content: str):
    """First mapping document, or None. Multi-doc and garbage tolerant."""
    try:
        for document in yaml.safe_load_all(content):
            if isinstance(document, dict):
                return document
    except yaml.YAMLError:
        return None
    return None


def _parse_datadog_config(file_path: str, content: str) -> list[ObservabilityIdentity]:
    """datadog.yaml agent config: service / env / tags. api_key is never read."""
    data = _safe_load_first(content)
    if not isinstance(data, dict):
        return []
    service = _str(data.get("service")).strip()
    environment = _str(data.get("env")).strip()
    team = ""
    raw_tags = data.get("tags")
    tag_chunks = (raw_tags if isinstance(raw_tags, list)
                  else _str(raw_tags).split(","))
    tags = _parse_tag_string(" ".join(_str(t) for t in tag_chunks))
    service = service or tags.get("service", "")
    environment = environment or tags.get("env", "")
    team = tags.get("team", "")
    if not service:
        return []
    lines = _line_map(content, re.compile(r"^\s*service\s*:\s*(.+?)\s*$"))
    return [ObservabilityIdentity(
        service_name=service, source="datadog", line=lines.get(service, 0),
        environment=environment, team=team)]


def _parse_newrelic_yaml(file_path: str, content: str) -> list[ObservabilityIdentity]:
    """newrelic.yml: common app_name plus per-environment overrides.

    Only app_name is ever read — license_key lives beside it and stays there.
    A `Name One;Name Two` value declares multiple reporting names.
    """
    data = _safe_load_first(content)
    if not isinstance(data, dict):
        return []
    common = data.get("common") if isinstance(data.get("common"), dict) else {}
    base_app = _str(data.get("app_name") or common.get("app_name")).strip()
    lines = _line_map(content, re.compile(r"^\s*app_name\s*:\s*(.+?)\s*$"))

    results: list[ObservabilityIdentity] = []

    def _emit(app_value: str, environment: str) -> None:
        for name in _str(app_value).split(";"):
            name = name.strip()
            if name:
                results.append(ObservabilityIdentity(
                    service_name=name, source="newrelic",
                    line=lines.get(name, 0), environment=environment))

    if base_app:
        _emit(base_app, "")
    for key, value in data.items():
        if key in ("common", "app_name") or not isinstance(value, dict):
            continue
        app = _str(value.get("app_name")).strip()
        # YAML merge keys copy the common app_name into every section;
        # only a real override is a new identity.
        if app and app != base_app:
            _emit(app, _str(key))
    return results


_INI_APP_NAME = re.compile(r"^\s*app_name\s*[:=]\s*([^;#\n]+)", re.MULTILINE)


def _parse_newrelic_ini(file_path: str, content: str) -> list[ObservabilityIdentity]:
    """newrelic.ini (Python agent). license_key is never read."""
    results = []
    lines = _line_map(content, re.compile(r"^\s*app_name\s*[:=]\s*([^;#\n]+)"))
    for match in _INI_APP_NAME.finditer(content):
        for name in _clean_value(match.group(1)).split(";"):
            name = name.strip()
            if name:
                results.append(ObservabilityIdentity(
                    service_name=name, source="newrelic",
                    line=lines.get(_clean_value(match.group(1)), 0)))
    return results


_SENTRY_PROJECT = re.compile(r"^\s*defaults\.project\s*[:=]\s*(.+?)\s*$")
_SENTRY_ORG = re.compile(r"^\s*defaults\.org\s*[:=]\s*(.+?)\s*$")


def _parse_sentry_properties(file_path: str, content: str) -> list[ObservabilityIdentity]:
    """sentry.properties defaults.project. auth.token/dsn never read."""
    project, org, line = "", "", 0
    for lineno, raw in enumerate(content.splitlines(), start=1):
        if match := _SENTRY_PROJECT.match(raw):
            if not project:
                project, line = _clean_value(match.group(1)), lineno
        elif match := _SENTRY_ORG.match(raw):
            org = org or _clean_value(match.group(1))
    if not project:
        return []
    attrs = {"org": org} if org else {}
    return [ObservabilityIdentity(service_name=project, source="sentry-project",
                                  line=line, attrs=attrs)]


def _parse_prometheus_jobs(file_path: str, content: str) -> list[ObservabilityIdentity]:
    """prometheus.yml scrape_configs -> one identity per job."""
    data = _safe_load_first(content)
    if not isinstance(data, dict) or not isinstance(data.get("scrape_configs"), list):
        return []
    lines = _line_map(content, re.compile(r"^\s*-?\s*job_name\s*:\s*(.+?)\s*$"))
    results: list[ObservabilityIdentity] = []
    for job in data["scrape_configs"]:
        if not isinstance(job, dict):
            continue
        name = _str(job.get("job_name")).strip()
        if not name:
            continue
        targets = []
        for static in _as_list(job.get("static_configs")):
            if isinstance(static, dict):
                targets += [_str(t) for t in _as_list(static.get("targets")) if _str(t)]
        attrs = {"targets": targets} if targets else {}
        results.append(ObservabilityIdentity(
            service_name=name, source="prometheus-job",
            line=lines.get(name, 0), attrs=attrs))
    return results


def _parse_consul_service(file_path: str, content: str) -> list:
    """Consul agent service definitions: `{"service": {"name": ..}}`
    is a discovery registration — the strongest self-identification there is,
    because other services resolve exactly that spelling."""
    import json as _json
    identities = []
    try:
        data = _json.loads(content)
    except (ValueError, TypeError):
        return identities
    if not isinstance(data, dict):
        return identities
    services = data.get("service") or data.get("services") or []
    if isinstance(services, dict):
        services = [services]
    for service in services:
        if isinstance(service, dict) and service.get("name"):
            identities.append(ObservabilityIdentity(
                service_name=str(service["name"]), source="consul-service",
                attrs={"port": service.get("port"),
                       "tags": [str(t) for t in service.get("tags") or []][:5]},
            ))
    return identities


def extract_observability_identity(file_path: str,
                                   content: str) -> list[ObservabilityIdentity]:
    """Every service self-identification in one file.

    Dispatches on the file name where a tool owns the name (datadog.yaml,
    newrelic.yml/ini, sentry.properties), on content for the generic cases
    (env conventions in any yaml/properties/env-ish file, scrape_configs,
    Datadog pod labels), and on code extensions for OTel Resource attributes.
    """
    identities: list[ObservabilityIdentity] = []
    if not isinstance(content, str) or not content:
        return identities
    try:
        name = _basename(file_path).lower()
        extension = name.rsplit(".", 1)[-1] if "." in name else ""

        if name == "sentry.properties":
            identities += _parse_sentry_properties(file_path, content)
        if name in ("newrelic.yml", "newrelic.yaml"):
            identities += _parse_newrelic_yaml(file_path, content)
        elif name in ("newrelic.ini", "newrelic.cfg"):
            identities += _parse_newrelic_ini(file_path, content)
        if name in ("datadog.yaml", "datadog.yml"):
            identities += _parse_datadog_config(file_path, content)
        if extension in ("yml", "yaml"):
            identities += _parse_prometheus_jobs(file_path, content)
        if extension == "json":
            identities += _parse_consul_service(file_path, content)

        if extension in _CODE_EXTS:
            identities += _identities_from_code(content)
        else:
            identities += _identities_from_env(content)
            identities += _identities_from_dd_labels(content)
    except Exception as exc:  # never raise; keep whatever parsed
        logger.debug("Observability extraction stopped in %s: %s", file_path, exc)

    deduped: dict[tuple, ObservabilityIdentity] = {}
    for identity in identities:
        key = (identity.source, identity.service_name,
               identity.environment, identity.team)
        deduped.setdefault(key, identity)
    return list(deduped.values())
