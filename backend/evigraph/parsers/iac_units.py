"""One shape for every IaC format that declares a running unit.

Nomad, systemd, Ansible, Pulumi and CDK all say the same three things in
different syntax: a unit exists under a name, it runs an image or binary,
and its environment points at other services. Extracting them into one
shape means one claim emitter — the emission rules (which env values name
a host, how identity is scoped) are decisions, and four copies of a
decision drift.

Each parser is pure and returns `[]` for anything it does not recognise.
Only literals are taken: a Pulumi env value built from an expression might
resolve to anything, and might is not evidence.
"""

import configparser
import io
import re
from dataclasses import dataclass, field

import yaml


@dataclass
class IaCUnit:
    """One declared runtime unit, whatever wrote it down."""
    name: str
    source: str                      # nomad | systemd | ansible | pulumi | cdk
    line: int = 1
    image: str = ""
    env: dict = field(default_factory=dict)


# --- Nomad (HCL job files) --------------------------------------------------

_NOMAD_FILE = re.compile(r"\.nomad(\.hcl)?$")
_NOMAD_SERVICE = re.compile(r'\bservice\s*\{[^}]*?name\s*=\s*"([^"]+)"',
                            re.S)
_NOMAD_JOB = re.compile(r'\bjob\s+"([^"]+)"')
_NOMAD_IMAGE = re.compile(r'\bimage\s*=\s*"([^"]+)"')
_NOMAD_ENV_BLOCK = re.compile(r"\benv\s*\{([^}]*)\}", re.S)
_NOMAD_ENV_PAIR = re.compile(r'([A-Z][A-Z0-9_]*)\s*=\s*"([^"]+)"')


def parse_nomad(file_path: str, content: str) -> list[IaCUnit]:
    if not _NOMAD_FILE.search(file_path):
        return []
    named = _NOMAD_SERVICE.search(content) or _NOMAD_JOB.search(content)
    if not named:
        return []
    env = {}
    for block in _NOMAD_ENV_BLOCK.finditer(content):
        env.update(dict(_NOMAD_ENV_PAIR.findall(block.group(1))))
    image = _NOMAD_IMAGE.search(content)
    return [IaCUnit(name=named.group(1), source="nomad",
                    line=content.count("\n", 0, named.start()) + 1,
                    image=image.group(1) if image else "", env=env)]


# --- systemd unit files -----------------------------------------------------

_SYSTEMD_FILE = re.compile(r"\.service$")


def parse_systemd(file_path: str, content: str) -> list[IaCUnit]:
    """A unit file names its service by filename; env lives in [Service]."""
    if not _SYSTEMD_FILE.search(file_path) or "[Service]" not in content:
        return []
    parser = configparser.ConfigParser(strict=False)
    try:
        parser.read_file(io.StringIO(content))
    except configparser.Error:
        return []
    if not parser.has_section("Service"):
        return []
    env = {}
    for raw in parser.get("Service", "Environment", fallback="").split():
        key, sep, value = raw.strip('"').partition("=")
        if sep:
            env[key] = value
    name = re.sub(r"\.service$", "", file_path.rsplit("/", 1)[-1])
    return [IaCUnit(name=name, source="systemd", env=env)]


# --- Ansible playbooks ------------------------------------------------------

def parse_ansible(file_path: str, content: str) -> list[IaCUnit]:
    """docker_container tasks in a playbook: name, image, env.

    Recognised by structure (a list of plays with hosts/tasks), never by
    filename — `deploy.yml` names nothing.
    """
    if not file_path.endswith((".yml", ".yaml")):
        return []
    try:
        documents = list(yaml.safe_load_all(content))
    except yaml.YAMLError:
        return []
    plays = []
    for document in documents:
        if isinstance(document, list):
            plays.extend(p for p in document if isinstance(p, dict))
    units: list[IaCUnit] = []
    for play in plays:
        if "hosts" not in play:
            continue
        for task in play.get("tasks") or []:
            container = (task or {}).get("docker_container") \
                or (task or {}).get("community.docker.docker_container")
            if not isinstance(container, dict):
                continue
            name = str(container.get("name") or "")
            if not name or "{{" in name:
                # A templated name resolves at run time; asserting it now
                # would name a service after a Jinja expression.
                continue
            env = {k: str(v) for k, v in (container.get("env") or {}).items()
                   if isinstance(v, (str, int)) and "{{" not in str(v)}
            units.append(IaCUnit(
                name=name, source="ansible",
                image=str(container.get("image") or ""), env=env))
    return units


# --- Pulumi / CDK (infrastructure as code) ----------------------------------

_PULUMI_SERVICE = re.compile(
    r'new\s+(?:\w+\.)*(?:FargateService|Service)\s*\(\s*["\']([\w-]+)["\']')
_CDK_ENV_BLOCK = re.compile(
    r"environment\s*[:=]\s*\{([^}]*)\}", re.S)
_ENV_LITERAL = re.compile(
    r'["\']?([A-Z][A-Z0-9_]*)["\']?\s*[:=]\s*["\']([^"\']+)["\']')


def extract_iac_services(file_path: str, content: str,
                         language: str | None) -> list[IaCUnit]:
    """Pulumi/CDK service constructors in TS/Python source.

    Only literal names and literal env values: an expression might
    resolve to anything.
    """
    if (language or "").lower() not in ("typescript", "javascript", "python"):
        return []
    units = []
    for match in _PULUMI_SERVICE.finditer(content):
        env = {}
        block = _CDK_ENV_BLOCK.search(content, match.end())
        if block:
            env = dict(_ENV_LITERAL.findall(block.group(1)))
        units.append(IaCUnit(
            name=match.group(1), source="pulumi",
            line=content.count("\n", 0, match.start()) + 1, env=env))
    return units
