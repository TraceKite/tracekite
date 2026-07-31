"""Parse configuration files to extract config keys and detect external systems."""

import logging
import re
import yaml
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

EXTERNAL_SYSTEM_PATTERNS = {
    "Redis": ["redis", "lettuce", "jedis", "spring.redis", "redisson"],
    "Kafka": ["kafka", "spring.kafka", "kafkatemplate", "kafkalistener", "kafkastreams"],
    "PostgreSQL": ["postgresql", "postgres", "jdbc:postgresql", "spring.datasource.url.*postgresql"],
    "MySQL": ["mysql", "jdbc:mysql", "spring.datasource.url.*mysql"],
    "MongoDB": ["mongodb", "mongo", "spring.data.mongodb"],
    "Elasticsearch": ["elasticsearch", "opensearch", "spring.data.elasticsearch"],
    "S3": ["amazonaws", "s3", "aws.s3", "boto3"],
    "Neo4j": ["neo4j", "spring.data.neo4j"],
    "RabbitMQ": ["rabbitmq", "spring.rabbitmq"],
    "REST Service": ["resttemplate", "webclient", "feignclient", "openapi"],
    "Databricks": ["databricks", "sql.warehouse"],
}

# Service reference patterns (e.g. Spring Cloud Gateway lb://service-name)
SERVICE_URI_PATTERN = re.compile(r"lb://([a-zA-Z0-9_-]+)")
HTTP_SERVICE_PATTERN = re.compile(r"https?://([a-zA-Z0-9._-]+(?::\d+)?)")


@dataclass
class ConfigEntry:
    key: str
    value: str = ""
    file: str = ""
    line: int = 0


@dataclass
class GatewayRoute:
    """A Spring Cloud Gateway route table entry (impl §5, M1)."""
    route_id: str
    uri: str
    path_predicates: list[str] = field(default_factory=list)
    strip_prefix: Optional[int] = None
    rewrite_path: str = ""
    file: str = ""
    line: int = 0


@dataclass
class ConfigParseResult:
    entries: list[ConfigEntry] = field(default_factory=list)
    detected_systems: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    gateway_routes: list[GatewayRoute] = field(default_factory=list)
    app_name: Optional[str] = None
    app_name_line: int = 0


def parse_properties_file(file_path: str, content: str) -> ConfigParseResult:
    result = ConfigParseResult()
    
    for line_num, line in enumerate(content.split("\n"), 1):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        
        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            
            result.entries.append(ConfigEntry(
                key=key,
                value=value,
                file=file_path,
                line=line_num,
            ))
            
            if key == "spring.application.name" and value and not result.app_name:
                result.app_name = value
                result.app_name_line = line_num

            for system_name, patterns in EXTERNAL_SYSTEM_PATTERNS.items():
                for pattern in patterns:
                    if pattern.lower() in (key + value).lower():
                        if system_name not in result.detected_systems:
                            result.detected_systems.append(system_name)
                        break
    
    return result


def parse_yaml_file(file_path: str, content: str) -> ConfigParseResult:
    """Parse YAML configuration files (multi-document: Spring profile sections)."""
    result = ConfigParseResult()
    
    try:
        for data in yaml.safe_load_all(content):
            if not isinstance(data, dict):
                continue
            _extract_yaml_keys(data, "", file_path, result)
            _extract_gateway_routes(data, file_path, content, result)
            app_name = _dig(data, "spring", "application", "name")
            if isinstance(app_name, str) and app_name and not result.app_name:
                result.app_name = app_name
                result.app_name_line = _find_line(content, app_name)
    except yaml.YAMLError as e:
        result.errors.append(f"YAML parse error: {str(e)}")
        logger.warning("Failed to parse YAML file %s: %s", file_path, e)
    
    return result


def _dig(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _find_line(content: str, token: str) -> int:
    for line_num, line in enumerate(content.split("\n"), 1):
        if token in line:
            return line_num
    return 0


def _filter_text(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and item:
        name = str(next(iter(item)))
        args = item[name]
        if isinstance(args, dict):
            args = ",".join(str(v) for v in args.values())
        return f"{name}={args}"
    return ""


def _extract_gateway_routes(data, file_path: str, content: str,
                            result: ConfigParseResult) -> None:
    gateway = _dig(data, "spring", "cloud", "gateway")
    if not isinstance(gateway, dict):
        return
    routes = None
    for tail in (("routes",), ("server", "webflux", "routes"),
                 ("server", "webmvc", "routes"), ("mvc", "routes")):
        routes = _dig(gateway, *tail)
        if isinstance(routes, list):
            break
    if not isinstance(routes, list):
        return
    for route in routes:
        if not isinstance(route, dict):
            continue
        uri = str(route.get("uri", "") or "")
        route_id = str(route.get("id", "") or "") or uri
        paths: list[str] = []
        strip_prefix = None
        rewrite_path = ""
        for pred in route.get("predicates") or []:
            text = _filter_text(pred)
            if text.startswith("Path="):
                paths.extend(p.strip() for p in text[5:].split(",") if p.strip())
        for filt in route.get("filters") or []:
            text = _filter_text(filt)
            if text.startswith("StripPrefix="):
                try:
                    strip_prefix = int(text.split("=", 1)[1].strip())
                except ValueError:
                    pass
            elif text.startswith("RewritePath="):
                rewrite_path = text.split("=", 1)[1].strip()
        result.gateway_routes.append(GatewayRoute(
            route_id=route_id, uri=uri, path_predicates=paths,
            strip_prefix=strip_prefix, rewrite_path=rewrite_path,
            file=file_path, line=_find_line(content, route_id) or _find_line(content, uri),
        ))


def _extract_yaml_keys(data, prefix: str, file_path: str, result: ConfigParseResult):
    """Recursively extract keys from YAML data, including list items."""
    if isinstance(data, dict):
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            _extract_yaml_value(full_key, value, file_path, result)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            full_key = f"{prefix}[{index}]" if prefix else f"[{index}]"
            _extract_yaml_value(full_key, value, file_path, result)


def _extract_yaml_value(full_key: str, value, file_path: str, result: ConfigParseResult):
    """Extract a single YAML value (dict, list, or scalar)."""
    if isinstance(value, dict):
        _extract_yaml_keys(value, full_key, file_path, result)
    elif isinstance(value, list):
        _extract_yaml_keys(value, full_key, file_path, result)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        str_value = "" if value is None else str(value)
        result.entries.append(ConfigEntry(
            key=full_key,
            value=str_value,
            file=file_path,
        ))

        combined = f"{full_key}{str_value}".lower()
        for system_name, patterns in EXTERNAL_SYSTEM_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in combined:
                    if system_name not in result.detected_systems:
                        result.detected_systems.append(system_name)
                    break

        # Detect downstream service references (Spring Cloud Gateway lb://...)
        for match in SERVICE_URI_PATTERN.finditer(str_value):
            service_name = match.group(1)
            if service_name and service_name not in result.detected_systems:
                result.detected_systems.append(service_name)
        for match in HTTP_SERVICE_PATTERN.finditer(str_value):
            host = match.group(1)
            if host and host not in result.detected_systems:
                result.detected_systems.append(host)


def parse_env_file(file_path: str, content: str) -> ConfigParseResult:
    result = ConfigParseResult()
    
    for line_num, line in enumerate(content.split("\n"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        if "=" in line:
            key, value = line.split("=", 1)
            result.entries.append(ConfigEntry(
                key=key.strip(),
                value=value.strip(),
                file=file_path,
                line=line_num,
            ))
            
            combined = f"{key}{value}".lower()
            for system_name, patterns in EXTERNAL_SYSTEM_PATTERNS.items():
                for pattern in patterns:
                    if pattern.lower() in combined:
                        if system_name not in result.detected_systems:
                            result.detected_systems.append(system_name)
                        break
    
    return result


def detect_systems_from_imports(imports: list) -> list[str]:
    detected = []
    for imp in imports:
        module = getattr(imp, "module", str(imp)).lower()
        for system_name, patterns in EXTERNAL_SYSTEM_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in module:
                    if system_name not in detected:
                        detected.append(system_name)
                    break
    return detected


def detect_systems_from_dependencies(deps: list) -> list[str]:
    detected = []
    for dep in deps:
        dep_name = getattr(dep, "name", str(dep)).lower()
        for system_name, patterns in EXTERNAL_SYSTEM_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in dep_name:
                    if system_name not in detected:
                        detected.append(system_name)
                    break
    return detected


CONFIG_PARSERS = {
    ".properties": parse_properties_file,
    ".yml": parse_yaml_file,
    ".yaml": parse_yaml_file,
    ".env": parse_env_file,
    ".env.example": parse_env_file,
    ".env.local": parse_env_file,
    ".env.production": parse_env_file,
}


def parse_config_file(file_path: str, content: str) -> ConfigParseResult:
    ext = file_path.split(".")[-1].lower() if "." in file_path else ""

    base_name = file_path.split("/")[-1]
    if base_name.startswith(".env"):
        return parse_env_file(file_path, content)
    
    if f".{ext}" in CONFIG_PARSERS:
        try:
            return CONFIG_PARSERS[f".{ext}"](file_path, content)
        except Exception as e:
            logger.warning("Failed to parse config file %s: %s", file_path, e)
    
    return ConfigParseResult()
