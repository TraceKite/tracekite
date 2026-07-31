"""Parser registry that dispatches files to the appropriate language parser."""

import logging
import os
import re
from typing import Optional

from adduce.parsers.base import BaseParser, ParseResult
from adduce.parsers.java_parser import JavaParser
from adduce.parsers.python_parser import PythonParser
from adduce.parsers.javascript_parser import JavaScriptParser
from adduce.parsers.kotlin_parser import KotlinParser
from adduce.parsers.tree_sitter.adapter import TreeSitterSourceParser
from adduce.parsers.dependency_parser import parse_dependency_file
from adduce.parsers.config_parser import parse_config_file
from adduce.parsers.docker_parser import is_compose_filename, parse_docker_file
from adduce.parsers.iac_parser import (
    is_kustomization_file, is_terraform_file, parse_iac_file,
)
from adduce.parsers.kubernetes_parser import parse_k8s_file
from adduce.parsers.mcp_manifest_parser import is_mcp_manifest, parse_mcp_manifest
from adduce.parsers.asyncapi_parser import (
    is_asyncapi_file, is_avro_schema_file, parse_asyncapi, parse_avro_schema,
)
from adduce.parsers.graphql_parser import (
    is_graphql_schema_file, parse_graphql_operations, parse_graphql_schema,
)
from adduce.parsers.proto_parser import (
    is_buf_file, is_idl_file, is_proto_file, parse_buf, parse_proto,
)

logger = logging.getLogger(__name__)

_SOURCE_PARSERS: dict[str, BaseParser] = {}
# Second-choice parser per extension. Tree-sitter claims an extension as soon
# as a grammar loads, even where it extracts no entities from it — which is
# how every .ts/.tsx/.js file in a repo can land in the graph as a bare File
# node with nothing inside. Measured on one estate: 380 of 525 TS/TSX/JS files
# yielded zero entities while the regex parser found the components in them.
_FALLBACK_PARSERS: dict[str, BaseParser] = {}


def _register_parsers():
    ts_parser = TreeSitterSourceParser()
    for ext in ts_parser.supported_extensions:
        _SOURCE_PARSERS[ext] = ts_parser

    # Regex parsers: primary where tree-sitter has no grammar, and the
    # entity-level fallback everywhere else.
    parsers = [
        JavaParser(),
        PythonParser(),
        JavaScriptParser(),
        KotlinParser(),
    ]

    for parser in parsers:
        for ext in parser.supported_extensions:
            if ext not in _SOURCE_PARSERS:
                _SOURCE_PARSERS[ext] = parser
            elif _SOURCE_PARSERS[ext] is ts_parser:
                _FALLBACK_PARSERS[ext] = parser


def parse_source(file_path: str, content: str) -> Optional[ParseResult]:
    """Parse source, falling back when the primary parser finds no entities.

    A file with imports but no classes or functions is usually a parser gap,
    not an empty file. Only entities are taken from the fallback: imports,
    endpoints and everything else stay with the primary result, so this can
    only add nodes, never contradict the primary parser.
    """
    parser = _SOURCE_PARSERS.get(os.path.splitext(file_path)[1].lower())
    if parser is None:
        return None
    result = parser.parse(file_path, content)
    if result and result.entities:
        return result

    fallback = _FALLBACK_PARSERS.get(os.path.splitext(file_path)[1].lower())
    if fallback is None:
        return result
    try:
        alt = fallback.parse(file_path, content)
    except Exception:  # a fallback must never fail the file
        logger.debug("Fallback parser failed for %s", file_path, exc_info=True)
        return result
    if not alt or not alt.entities:
        return result
    if result is None:
        return alt
    result.entities = alt.entities
    if not result.api_endpoints and alt.api_endpoints:
        result.api_endpoints = alt.api_endpoints
    return result

_register_parsers()

DEPENDENCY_FILES = {"package.json", "package-lock.json", "requirements.txt", "pom.xml",
                    "build.gradle", "go.mod", "pyproject.toml", "poetry.lock",
                    "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
                    "build.gradle.kts", "libs.versions.toml", "go.sum",
                    "Gemfile", "Gemfile.lock", "composer.json", "Cargo.toml",
                    "Cargo.lock", "Directory.Packages.props", "MODULE.bazel",
                    "WORKSPACE", "WORKSPACE.bazel", "bom.json", "sbom.json"}
_DEPENDENCY_SUFFIXES = (".csproj", ".cdx.json", ".spdx.json", ".gemspec")
DOCKER_FILES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                "compose.yml", "compose.yaml"}
# Overlay compose names (docker-compose.prod.yml, compose.override.yaml) come
# from docker_parser so routing and parsing cannot disagree. They did: the
# registry let the file through and the parser then dropped it, so a whole
# observability stack was missing from one estate's graph.
K8S_EXTENSIONS = {".yaml", ".yml"}
CONFIG_EXTENSIONS = {".properties", ".env", ".env.example", ".env.local", ".env.production"}


# Parsers a host registered at runtime, newest first. Kept separate from
# `_SOURCE_PARSERS` so a host extension is always visible as an extension —
# merging them would make "did we ship this or did they?" unanswerable.
_REGISTERED: list[tuple[tuple[str, ...], BaseParser]] = []


def register_parser(parser: BaseParser, extensions) -> None:
    """Add a parser for `extensions` without forking.

    A host with an in-house framework registers here rather than editing this
    file. Registered parsers take precedence over built-ins for the same
    extension: a host that went to the trouble means it.

    The parser must satisfy the same contract as every built-in — return
    structured data or None, never raise for a file it does not recognise —
    because ingestion treats a raised exception as a parse error for the file,
    not as a reason to stop.
    """
    if not hasattr(parser, "parse"):
        raise TypeError(
            f"{type(parser).__name__} has no parse(); a parser registered "
            "without one fails at the first file rather than at registration")
    keys = tuple(e.lower() if e.startswith(".") else f".{e.lower()}"
                 for e in extensions)
    if not keys:
        raise ValueError("a parser registered for no extension can never run")
    _REGISTERED.insert(0, (keys, parser))


def registered_parsers() -> list[tuple[tuple[str, ...], BaseParser]]:
    return list(_REGISTERED)


def clear_registered_parsers() -> None:
    """Drop host registrations. For tests; the app never calls this."""
    _REGISTERED.clear()


def get_parser_for_file(file_path: str) -> Optional[BaseParser]:
    ext = os.path.splitext(file_path)[1].lower()
    for extensions, parser in _REGISTERED:
        if ext in extensions:
            return parser
    return _SOURCE_PARSERS.get(ext)


def is_dependency_file(file_path: str) -> bool:
    name = os.path.basename(file_path)
    return name in DEPENDENCY_FILES or name.endswith(_DEPENDENCY_SUFFIXES)


def is_docker_file(file_path: str) -> bool:
    name = os.path.basename(file_path)
    return (name in DOCKER_FILES or file_path.endswith(".dockerfile")
            or is_compose_filename(name))


def is_k8s_file(file_path: str, file_name: str, content: str = "") -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in K8S_EXTENSIONS:
        return False

    if content and ("apiVersion:" in content or "kind:" in content):
        k8s_kinds = {"Deployment", "Service", "ConfigMap", "Secret", "Ingress",
                      "Pod", "ReplicaSet", "StatefulSet", "DaemonSet"}
        for kind in k8s_kinds:
            if f"kind: {kind}" in content:
                return True

    k8s_name_patterns = ["deployment", "service", "configmap", "secret", "ingress",
                         "pod", "replicaset", "statefulset", "daemonset", "job",
                         "cronjob", "pvc", "pv", "namespace", "values", "Chart"]
    base = os.path.splitext(file_name)[0].lower()
    return any(pattern in base for pattern in k8s_name_patterns)


def is_config_file(file_path: str, content: str = "") -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in CONFIG_EXTENSIONS:
        return True
    base = os.path.basename(file_path)
    if base.startswith(".env") or base == "application.properties" or base.endswith(".properties"):
        return True
    # Treat YAML files as config if they look like Spring/application config
    # and not like Kubernetes manifests.
    if ext in {".yml", ".yaml"}:
        if content and ("kind:" in content or "apiVersion:" in content):
            return False
        lower = content.lower()
        config_indicators = ["spring:", "server:", "management:", "eureka:", "logging:"]
        return any(ind in lower for ind in config_indicators) or "application" in base.lower()
    return False


# Cheap gate before running the observability extractor over file content.
_OBSERVABILITY_HINT = re.compile(
    r"OTEL_SERVICE_NAME|OTEL_RESOURCE_ATTRIBUTES|DD_SERVICE"
    r"|tags\.datadoghq\.com/service|NEW_RELIC_APP_NAME|SENTRY_PROJECT"
    r"|\"services?\"\s*:\s*[\[{]")


def parse_file(file_path: str, content: str) -> dict:
    file_name = os.path.basename(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    
    result = {
        "source_result": None,
        "dependencies": None,
        "config": None,
        "docker": None,
        "kubernetes": None,
        "iac": None,
        "proto": None,
        "mcp_manifest": None,
        "buf": None,
        "graphql": None,
        "asyncapi": None,
        "avro": None,
        "publish": None,
        "gateway": None,
        "codeowners": None,
        "catalog": None,
        "observability": None,
        "pipeline": None,
        "migration": None,
        "mcp_config": None,
        "agent_card": None,
        "cron": None,
        "iac_units": None,
        "openapi": None,
    }
    
    if get_parser_for_file(file_path):
        try:
            result["source_result"] = parse_source(file_path, content)
        except Exception as e:
            logger.warning("Source parser failed for %s: %s", file_path, e)
    
    if is_dependency_file(file_path):
        try:
            result["dependencies"] = parse_dependency_file(file_path, content)
        except Exception as e:
            logger.warning("Dependency parser failed for %s: %s", file_path, e)
        try:
            from adduce.parsers.dependency_parser import parse_publish_identity
            result["publish"] = parse_publish_identity(file_path, content)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Publish identity failed for %s: %s", file_path, e)
    
    if is_config_file(file_path, content):
        try:
            result["config"] = parse_config_file(file_path, content)
        except Exception as e:
            logger.warning("Config parser failed for %s: %s", file_path, e)
    
    if is_docker_file(file_path):
        try:
            result["docker"] = parse_docker_file(file_path, content)
        except Exception as e:
            logger.warning("Docker parser failed for %s: %s", file_path, e)
    
    # MCP capability manifest: the declarative tool surface of an MCP server.
    if is_mcp_manifest(file_path, content):
        try:
            result["mcp_manifest"] = parse_mcp_manifest(file_path, content)
        except Exception as e:
            logger.warning("MCP manifest parser failed for %s: %s", file_path, e)

    if ext in K8S_EXTENSIONS and is_k8s_file(file_path, file_name, content):
        try:
            result["kubernetes"] = parse_k8s_file(file_path, content)
        except Exception as e:
            logger.warning("K8s parser failed for %s: %s", file_path, e)

    if is_proto_file(file_name):
        try:
            result["proto"] = parse_proto(file_path, content)
        except Exception as e:
            logger.warning("Proto parser failed for %s: %s", file_path, e)
    elif is_buf_file(file_name):
        try:
            result["buf"] = parse_buf(file_path, content)
        except Exception as e:
            logger.warning("Buf parser failed for %s: %s", file_path, e)
    elif idl_kind := is_idl_file(file_name):
        try:
            from adduce.parsers.proto_parser import parse_thrift, parse_wsdl
            parse_idl = parse_thrift if idl_kind == "thrift" else parse_wsdl
            result["proto"] = parse_idl(file_path, content)
        except Exception as e:
            logger.warning("IDL parser failed for %s: %s", file_path, e)

    # Try MCP client configs and A2A agent cards
    try:
        from adduce.services.agents_extractor import (
            is_agent_card_file, is_mcp_config_file, parse_agent_card,
            parse_mcp_config,
        )
        if is_mcp_config_file(file_name, content):
            result["mcp_config"] = parse_mcp_config(file_path, content)
        elif is_agent_card_file(file_path):
            result["agent_card"] = parse_agent_card(file_path, content)
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Agents parser failed for %s: %s", file_path, e)

    # Try migration parser for non-source files (.sql/.xml/.rb never reach
    # the source pass, so their CREATE TABLE evidence must be routed here)
    try:
        from adduce.parsers.migration_parser import (
            is_migration_file, parse_migration,
        )
        if is_migration_file(file_path) and not get_parser_for_file(file_path):
            result["migration"] = parse_migration(file_path, content)
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Migration parser failed for %s: %s", file_path, e)

    try:
        from adduce.parsers.pipeline_parser import (
            is_pipeline_file, parse_airflow_dag, parse_databricks_bundle,
            parse_databricks_notebook, parse_dbt_model, parse_dbt_project,
            parse_dbt_sources,
        )
        pipeline_kind = is_pipeline_file(file_path, content)
        if pipeline_kind:
            parse_pipeline = {
                "dbt-project": parse_dbt_project, "dbt-model": parse_dbt_model,
                "dbt-schema": parse_dbt_sources, "airflow": parse_airflow_dag,
                "databricks-bundle": parse_databricks_bundle,
                "databricks-notebook": parse_databricks_notebook,
            }[pipeline_kind]
            result["pipeline"] = parse_pipeline(file_path, content)
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Pipeline parser failed for %s: %s", file_path, e)

    # OpenAPI specs: declared operations, for reconciliation only.
    try:
        from adduce.parsers.openapi_parser import is_openapi_file, parse_openapi
        if is_openapi_file(file_path):
            ops = parse_openapi(file_path, content)
            if ops:
                result["openapi"] = ops
    except Exception as e:
        logger.warning("OpenAPI parser failed for %s: %s", file_path, e)

    # IaC formats that declare runtime units: one shape, one emitter.
    try:
        from adduce.parsers.iac_units import (
            parse_ansible, parse_nomad, parse_systemd,
        )
        units = (parse_nomad(file_path, content)
                 or parse_systemd(file_path, content)
                 or parse_ansible(file_path, content))
        if units:
            result["iac_units"] = units
    except Exception as e:
        logger.warning("IaC unit parser failed for %s: %s", file_path, e)

    # Crontabs: a scheduled curl is a dependency with no code behind it.
    try:
        from adduce.parsers.cron_parser import is_cron_file, parse_crontab
        if is_cron_file(file_path):
            result["cron"] = parse_crontab(file_path, content)
    except Exception as e:
        logger.warning("Cron parser failed for %s: %s", file_path, e)

    # Try GraphQL: a .graphql file is either SDL or client operations.
    if is_graphql_schema_file(file_name):
        try:
            schema = parse_graphql_schema(file_path, content)
            operations = parse_graphql_operations(content)
            result["graphql"] = {"schema": schema, "operations": operations}
        except Exception as e:
            logger.warning("GraphQL parser failed for %s: %s", file_path, e)

    try:
        from adduce.parsers.ownership_parser import (
            extract_observability_identity, is_catalog_file,
            is_codeowners_file, parse_catalog_info, parse_codeowners,
        )
        if is_codeowners_file(file_path):
            result["codeowners"] = parse_codeowners(file_path, content)
        elif is_catalog_file(file_name):
            result["catalog"] = parse_catalog_info(file_path, content)
        if _OBSERVABILITY_HINT.search(content) or file_name in (
                "datadog.yaml", "newrelic.yml", "newrelic.ini",
                "sentry.properties") or file_name.startswith("prometheus"):
            result["observability"] = extract_observability_identity(
                file_path, content)
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Ownership parser failed for %s: %s", file_path, e)

    try:
        from adduce.parsers.gateway_parser import (
            parse_envoy_config, parse_js_proxies, parse_kong_config,
            parse_next_config, parse_nginx_conf, parse_traefik_file,
            sniff_gateway_file,
        )
        gateway_kind = sniff_gateway_file(file_name, content)
        if gateway_kind:
            parse_gateway = {
                "nginx": parse_nginx_conf, "envoy": parse_envoy_config,
                "kong": parse_kong_config, "traefik": parse_traefik_file,
                "next": parse_next_config, "jsproxy": parse_js_proxies,
            }[gateway_kind]
            result["gateway"] = parse_gateway(file_path, content)
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Gateway parser failed for %s: %s", file_path, e)

    # Try AsyncAPI (messaging contract declarations) and Avro value schemas
    if is_asyncapi_file(file_name, content):
        try:
            result["asyncapi"] = parse_asyncapi(file_path, content)
        except Exception as e:
            logger.warning("AsyncAPI parser failed for %s: %s", file_path, e)
    elif is_avro_schema_file(file_name):
        try:
            result["avro"] = parse_avro_schema(file_path, content)
        except Exception as e:
            logger.warning("Avro parser failed for %s: %s", file_path, e)

    if is_iac_file(file_name, content):
        try:
            result["iac"] = parse_iac_file(file_path, content)
        except Exception as e:
            logger.warning("IaC parser failed for %s: %s", file_path, e)

    return result


def is_iac_file(file_name: str, content: str = "") -> bool:
    if is_terraform_file(file_name) or is_kustomization_file(file_name):
        return True
    # ECS task definitions are plain JSON; the key is the only reliable marker.
    return file_name.endswith(".json") and "containerDefinitions" in content
