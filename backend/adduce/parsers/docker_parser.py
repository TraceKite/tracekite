"""Parse Docker-related files (Dockerfile, docker-compose.yml) to extract container resources."""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DockerResource:
    name: str
    type: str  # image, container, service, volume, network
    image: str = ""
    ports: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    file_path: str = ""
    line: int = 0
    depends_on: list[str] = field(default_factory=list)
    # Line of each depends_on/links entry ("dep:<name>") and env pair
    # ("env:<KEY>") inside this service's block, so a claim derived from an
    # entry cites the line asserting it. Without this every compose claim
    # cited the service HEADER: schema-registry -> zookeeper pointed at
    # `schema-registry:` four lines above the `- zookeeper` that is the fact.
    entry_lines: dict = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    build_context: str = ""
    project: str = ""
    env_pairs: dict = field(default_factory=dict)


def parse_dockerfile(file_path: str, content: str) -> list[DockerResource]:
    resources = []
    base_image = ""
    
    for line_num, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        
        from_match = re.match(r'FROM\s+(\S+)', stripped, re.IGNORECASE)
        if from_match:
            base_image = from_match.group(1)
            resources.append(DockerResource(
                name=base_image.split(":")[0],
                type="image",
                image=base_image,
                file_path=file_path,
                line=line_num,
            ))
        
        expose_match = re.match(r'EXPOSE\s+(.+)', stripped, re.IGNORECASE)
        if expose_match:
            ports = expose_match.group(1).split()
            if resources:
                resources[-1].ports.extend(ports)
        
        env_match = re.match(r'ENV\s+(\w+)\s*=', stripped, re.IGNORECASE)
        if env_match:
            if resources:
                resources[-1].env_vars.append(env_match.group(1))
    
    resources.append(DockerResource(
        name=file_path.split("/")[-1],
        type="dockerfile",
        image=base_image,
        file_path=file_path,
    ))
    
    return resources


def _env_pairs(environment) -> dict:
    if isinstance(environment, dict):
        return {str(k): "" if v is None else str(v) for k, v in environment.items()}
    if isinstance(environment, list):
        pairs = {}
        for item in environment:
            key, _, value = str(item).partition("=")
            if key:
                pairs[key] = value
        return pairs
    return {}


def _find_service_line(content: str, service_name: str) -> int:
    pattern = re.compile(rf"^\s{{2,4}}{re.escape(service_name)}\s*:")
    for line_num, line in enumerate(content.split("\n"), 1):
        if pattern.match(line):
            return line_num
    return 0


def _entry_lines(content: str, header_line: int, deps: list,
                 env_keys: list) -> dict:
    """Locate each entry at or after the service header.

    First match after the header is correct by construction: the entry
    exists in THIS service's block (that is why the claim exists), and the
    block starts at the header — an identical entry in a later service sits
    strictly after this one.
    """
    lines = content.split("\n")
    found: dict[str, int] = {}
    build_header = 0
    start = max(header_line - 1, 0)
    for offset, raw in enumerate(lines[start:], start + 1):
        s = raw.strip()
        for dep in deps:
            key = f"dep:{dep}"
            if key not in found and (s == f"- {dep}" or s.startswith(f"- {dep} ")
                                     or s == f"{dep}:" or s.startswith(f"- {dep}:")):
                found[key] = offset
        for env in env_keys:
            key = f"env:{env}"
            if key not in found and (s.startswith(f"{env}=") or s.startswith(f"{env}:")
                                     or s.startswith(f"- {env}=")):
                found[key] = offset
        if "build" not in found and (s.startswith("context:") or s == "build:"
                                     or s.startswith("build: ")):
            # Prefer the context line (the directory IS the fact); a string
            # form `build: ./dir` carries it on the build line itself. The
            # bare-header fallback lives OUTSIDE `found`: counting a scratch
            # key in the tally made the early-exit fire one entry short, and
            # the entry it skipped was whatever came after `build:` — a
            # `depends_on` on the first real compose file this met.
            if s.startswith("context:") or s.startswith("build: "):
                found["build"] = offset
            elif s == "build:":
                build_header = build_header or offset
        if len(found) >= len(deps) + len(env_keys) + 1 and "build" in found:
            break
    if "build" not in found and build_header:
        found["build"] = build_header
    # Entries that never appear inside the block arrive via a YAML anchor
    # merge (`<<: *shared-env`); the pair is asserted ONCE, at the anchor's
    # definition near the top of the file, and that line is the receipt. A
    # second pass over the whole file finds it — first occurrence wins, and
    # the anchor must precede every alias that uses it.
    missing_envs = [e for e in env_keys if f"env:{e}" not in found]
    missing_deps = [d for d in deps if f"dep:{d}" not in found]
    if missing_envs or missing_deps:
        for offset, raw in enumerate(lines, 1):
            s = raw.strip()
            for env in missing_envs:
                key = f"env:{env}"
                if key not in found and (s.startswith(f"{env}=")
                                         or s.startswith(f"{env}:")
                                         or s.startswith(f"- {env}=")):
                    found[key] = offset
            for dep in missing_deps:
                key = f"dep:{dep}"
                if key not in found and (s == f"- {dep}" or s == f"{dep}:"
                                         or s.startswith(f"- {dep}:")):
                    found[key] = offset
    return found


def parse_docker_compose(file_path: str, content: str) -> list[DockerResource]:
    resources = []
    
    try:
        import yaml
        data = yaml.safe_load(content)
        
        if not isinstance(data, dict):
            return resources
        
        project = str(data.get("name") or "")
        services = data.get("services", {})
        for service_name, service_config in services.items():
            if isinstance(service_config, dict):
                image = service_config.get("image", "")
                ports = service_config.get("ports", [])
                env_pairs = _env_pairs(service_config.get("environment"))
                envs = list(env_pairs.keys())
                depends = service_config.get("depends_on")
                if isinstance(depends, dict):
                    depends = list(depends.keys())
                elif not isinstance(depends, list):
                    depends = []
                links = [str(l).split(":")[0] for l in service_config.get("links") or []]
                build = service_config.get("build")
                if isinstance(build, dict):
                    build_context = str(build.get("context") or "")
                elif isinstance(build, str):
                    build_context = build
                else:
                    build_context = ""
                
                header = _find_service_line(content, service_name)
                deps = [str(d) for d in depends]
                resources.append(DockerResource(
                    name=service_name,
                    type="service",
                    image=image,
                    ports=[str(p) for p in ports],
                    env_vars=envs,
                    file_path=file_path,
                    line=header,
                    depends_on=deps,
                    links=links,
                    build_context=build_context,
                    project=project,
                    env_pairs=env_pairs,
                    entry_lines=_entry_lines(content, header,
                                             deps + links, envs),
                ))
        
        volumes = data.get("volumes", {})
        if isinstance(volumes, dict):
            for vol_name in volumes.keys():
                resources.append(DockerResource(
                    name=vol_name,
                    type="volume",
                    file_path=file_path,
                ))
        elif isinstance(volumes, list):
            for vol in volumes:
                resources.append(DockerResource(
                    name=str(vol),
                    type="volume",
                    file_path=file_path,
                ))
        
        networks = data.get("networks", {})
        if isinstance(networks, dict):
            for net_name in networks.keys():
                resources.append(DockerResource(
                    name=net_name,
                    type="network",
                    file_path=file_path,
                ))
    
    except Exception as e:
        logger.warning("Failed to parse docker-compose %s: %s", file_path, e)
    
    return resources


# Compose overlays are named by suffix -- docker-compose.prod.yml,
# docker-compose.observability.yml, compose.override.yaml. This is the single
# source of truth for the name test; the registry's routing check imports it,
# because when the two were written separately only one of them got fixed and
# the file was routed in but then silently dropped here.
_COMPOSE_NAME = re.compile(r"^(?:docker-)?compose(?:[.-][\w.-]+)?\.ya?ml$", re.I)


def is_compose_filename(name: str) -> bool:
    return bool(_COMPOSE_NAME.match(name))


def parse_docker_file(file_path: str, content: str) -> list[DockerResource]:
    file_name = file_path.split("/")[-1]
    
    if file_name == "Dockerfile" or file_name.endswith(".dockerfile"):
        return parse_dockerfile(file_path, content)
    elif is_compose_filename(file_name):
        return parse_docker_compose(file_path, content)
    
    return []
