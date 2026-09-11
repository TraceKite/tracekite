"""Dependency manifest, lockfile, and SBOM parsers.

What is read, and by what:
- publish-side identity        -> parse_publish_identity / PublishIdentity
- Go module path join          -> go.mod module/require/replace parsing
- git/VCS dependencies         -> DependencyInfo.git_url (npm, pip, cargo,
                                  poetry, go replace, bazel git_repository)
- NuGet                        -> *.csproj + Directory.Packages.props
- Gradle catalogs / Maven BOM  -> libs.versions.toml, platform()/BOM import,
                                  <dependencyManagement>, <parent>, ${props}
- npm workspaces               -> parse_npm_workspaces, workspace:*/catalog:
- lockfiles (resolved truth)   -> package-lock.json, pnpm-lock.yaml,
                                  yarn.lock, poetry.lock, go.sum,
                                  Gemfile.lock, Cargo.lock (resolved=True)
- SBOM ingestion               -> parse_sbom (CycloneDX JSON, SPDX JSON)
- Bazel build graphs           -> MODULE.bazel / WORKSPACE bazel_dep

Conventions:
- Declared manifest entries keep resolved=False; lockfile/SBOM entries set
  resolved=True (the version is a fact, not a range).
- ecosystem is the purl ecosystem (maven|npm|pypi|golang|nuget|cargo|gem|composer);
  internal project references (gradle project(), ProjectReference, cargo path)
  keep ecosystem="" because they have no purl.
- Maven-family names stay "group:artifact" (legacy back-compat) with
  namespace=groupId. Legacy gradle string deps keep the literal "g:a:v" string
  as name (pinned by existing tests); namespace still carries the group.
- Parsers never raise on malformed input: they log and return what was
  collected so far. All regexes are precompiled at module scope.
"""

import json
import logging
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote

logger = logging.getLogger(__name__)


@dataclass
class DependencyInfo:
    name: str
    version: str = ""
    scope: str = ""  # compile, test, provided, bom-import, parent, project, ...
    source_file: str = ""
    type: str = ""   # npm, pypi, maven, gradle, go, nuget, cargo, gem, composer, bazel, sbom
    # Roadmap M7 additions (all optional, backward-compatible):
    ecosystem: str = ""   # purl ecosystem: maven|npm|pypi|golang|nuget|cargo|gem|composer
    namespace: str = ""   # maven groupId, npm @scope, golang host/org path prefix
    resolved: bool = False  # True when from a lockfile/SBOM (version is truth, not a range)
    git_url: str = ""     # VCS dependency target
    license: str = ""     # SPDX id/expression when a source (SBOM) carries it


@dataclass
class PublishIdentity:
    """What a repo publishes - the join key consumers point at."""
    ecosystem: str
    name: str            # artifactId / package name / module path / PackageId
    namespace: str = ""  # groupId / @scope
    version: str = ""
    private: bool = False  # package.json "private": true, csproj IsPackable=false, cargo publish=false


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PURL_TYPE_TO_ECOSYSTEM = {
    "maven": "maven", "npm": "npm", "pypi": "pypi", "golang": "golang",
    "nuget": "nuget", "cargo": "cargo", "gem": "gem", "composer": "composer",
}

_RE_VERSION_NUM = re.compile(r'[=<>~!^]+\s*([\d.]+)')


def _parse_purl(purl: str) -> tuple[str, str, str, str]:
    """pkg:type/namespace/name@version?qualifiers -> (ecosystem, namespace, name, version)."""
    try:
        if not purl.startswith("pkg:"):
            return "", "", "", ""
        body = purl[4:].split("?", 1)[0].split("#", 1)[0].strip("/")
        segments = body.split("/")
        eco = _PURL_TYPE_TO_ECOSYSTEM.get(segments[0].lower(), "")
        rest = segments[1:]
        if not rest:
            return eco, "", "", ""
        name, _, version = rest[-1].partition("@")
        namespace = "/".join(unquote(s) for s in rest[:-1])
        return eco, namespace, unquote(name), unquote(version)
    except Exception:  # pragma: no cover - defensive
        return "", "", "", ""


def _npm_namespace(name: str) -> str:
    if name.startswith("@") and "/" in name:
        return name.split("/", 1)[0]
    return ""


def _go_namespace(module_path: str) -> str:
    return module_path.rsplit("/", 1)[0] if "/" in module_path else ""


# ---------------------------------------------------------------------------
# npm: package.json / workspaces / package-lock.json / pnpm-lock.yaml / yarn.lock
# ---------------------------------------------------------------------------

_RE_NPM_GIT = re.compile(
    r'^(?:git\+|git://|git@|github:|gitlab:|bitbucket:|https?://[^\s#]+\.git(?:#|$))')


def parse_package_json(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse package.json for npm dependencies."""
    deps: list[DependencyInfo] = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse package.json: %s", e)
        return deps
    if not isinstance(data, dict):
        return deps
    try:
        for scope in ("dependencies", "devDependencies", "peerDependencies",
                      "optionalDependencies"):
            section = data.get(scope)
            if not isinstance(section, dict):
                continue
            for name, version in section.items():
                version = str(version)
                deps.append(DependencyInfo(
                    name=name,
                    version=version,  # workspace:* / catalog: kept as written
                    scope=scope,
                    source_file=file_path,
                    type="npm",
                    ecosystem="npm",
                    namespace=_npm_namespace(name),
                    git_url=version if _RE_NPM_GIT.match(version) else "",
                ))
    except Exception as e:
        logger.warning("Failed to parse package.json %s: %s", file_path, e)
    return deps


def parse_npm_workspaces(content: str) -> list[str]:
    """Extract package.json "workspaces" glob patterns."""
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            return []
        ws = data.get("workspaces")
        if isinstance(ws, list):
            return [str(p) for p in ws]
        if isinstance(ws, dict):
            pkgs = ws.get("packages")
            if isinstance(pkgs, list):
                return [str(p) for p in pkgs]
    except Exception as e:
        logger.warning("Failed to parse npm workspaces: %s", e)
    return []


def _npm_lock_dep(name: str, entry: dict, file_path: str) -> DependencyInfo:
    resolved_url = str(entry.get("resolved") or "")
    return DependencyInfo(
        name=name,
        version=str(entry.get("version") or ""),
        scope="dev" if entry.get("dev") else "",
        source_file=file_path,
        type="npm",
        ecosystem="npm",
        namespace=_npm_namespace(name),
        resolved=True,
        git_url=resolved_url if resolved_url.startswith(("git+", "git://", "git@")) else "",
    )


def _walk_npm_lock_v1(section, file_path: str, deps: list, seen: set) -> None:
    if not isinstance(section, dict):
        return
    for name, entry in section.items():
        if not isinstance(entry, dict):
            continue
        dep = _npm_lock_dep(name, entry, file_path)
        if (dep.name, dep.version) not in seen:
            seen.add((dep.name, dep.version))
            deps.append(dep)
        _walk_npm_lock_v1(entry.get("dependencies"), file_path, deps, seen)


def parse_package_lock(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse package-lock.json / npm-shrinkwrap.json v1/v2/v3.

    Fixes the legacy misrouting of package-lock.json into parse_package_json.
    """
    deps: list[DependencyInfo] = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse package-lock.json: %s", e)
        return deps
    if not isinstance(data, dict):
        return deps
    try:
        seen: set[tuple[str, str]] = set()
        packages = data.get("packages")
        if isinstance(packages, dict):  # lockfileVersion 2/3
            for key, entry in packages.items():
                if not key or not isinstance(entry, dict):
                    continue  # skip root "" entry
                if entry.get("link"):
                    continue  # workspace symlinks
                if "node_modules/" not in key:
                    continue  # workspace source dirs ("packages/app")
                name = key.rsplit("node_modules/", 1)[-1]
                dep = _npm_lock_dep(name, entry, file_path)
                if (dep.name, dep.version) in seen:
                    continue
                seen.add((dep.name, dep.version))
                deps.append(dep)
        else:  # lockfileVersion 1
            _walk_npm_lock_v1(data.get("dependencies"), file_path, deps, seen)
    except Exception as e:
        logger.warning("Failed to parse package lock %s: %s", file_path, e)
    return deps


_RE_PNPM_KEY = re.compile(r"""^  (["']?)(\S.*?)\1:\s*$""")
_RE_PNPM_PEERS = re.compile(r"\(.*$")


def _split_pnpm_key(key: str) -> tuple[str, str]:
    key = _RE_PNPM_PEERS.sub("", key).strip()  # strip "(peer@x)" suffixes
    if key.startswith("/"):
        key = key[1:]
    if "@" in key[1:]:  # v6 "/name@1.2.3" or v9 "name@1.2.3" (maybe @scoped)
        name, _, version = key.rpartition("@")
        if name:
            return name, version
    if "/" in key:  # v5 "name/1.2.3" or "@scope/name/1.2.3"
        name, _, version = key.rpartition("/")
        if version and version[0].isdigit():
            return name, version
    return key, ""


def parse_pnpm_lock(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse pnpm-lock.yaml packages: section keys."""
    deps: list[DependencyInfo] = []
    try:
        in_packages = False
        seen: set[tuple[str, str]] = set()
        for line in content.split("\n"):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith(" "):  # top-level key
                in_packages = line.split(":", 1)[0].strip() == "packages"
                continue
            if not in_packages:
                continue
            m = _RE_PNPM_KEY.match(line)
            if not m:
                continue
            name, version = _split_pnpm_key(m.group(2))
            if not name or not version or (name, version) in seen:
                continue
            seen.add((name, version))
            deps.append(DependencyInfo(
                name=name, version=version, source_file=file_path,
                type="npm", ecosystem="npm", namespace=_npm_namespace(name),
                resolved=True,
            ))
    except Exception as e:
        logger.warning("Failed to parse pnpm-lock.yaml %s: %s", file_path, e)
    return deps


_RE_YARN_VERSION = re.compile(r'^\s+version:?\s+"?([^"\s]+)"?')


def parse_yarn_lock(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse yarn.lock (classic and berry) entries."""
    deps: list[DependencyInfo] = []
    try:
        seen: set[tuple[str, str]] = set()
        current_name = ""
        for raw in content.split("\n"):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not raw[0].isspace() and raw.rstrip().endswith(":"):
                current_name = ""
                header = raw.rstrip()[:-1]
                sel = header.split(",")[0].strip().strip('"').strip("'")
                if not sel or sel == "__metadata":
                    continue
                # "name@^1.0.0" / "@scope/name@npm:^1.0" -> split at last "@"
                current_name = sel.rpartition("@")[0] if "@" in sel[1:] else sel
                continue
            if current_name:
                m = _RE_YARN_VERSION.match(raw)
                if m:
                    version = m.group(1)
                    if (current_name, version) not in seen:
                        seen.add((current_name, version))
                        deps.append(DependencyInfo(
                            name=current_name, version=version,
                            source_file=file_path, type="npm", ecosystem="npm",
                            namespace=_npm_namespace(current_name), resolved=True,
                        ))
                    current_name = ""
    except Exception as e:
        logger.warning("Failed to parse yarn.lock %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# Python: requirements.txt / pyproject.toml / poetry.lock
# ---------------------------------------------------------------------------

_RE_REQ_NAME = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)')
_RE_PIP_VCS = re.compile(r'^(?:(?:-e|--editable)\s+)?((?:git|hg|svn|bzr)\+\S+)\s*$')
_RE_PIP_EGG = re.compile(r'#egg=([A-Za-z0-9._-]+)')


def _vcs_url_parts(url: str) -> tuple[str, str, str]:
    """VCS url -> (git_url sans fragment, ref, default name from path)."""
    egg = _RE_PIP_EGG.search(url)
    base = url.split("#", 1)[0]
    ref = ""
    if "@" in base:
        head, _, tail = base.rpartition("@")
        if tail and "/" not in tail:  # user@host has a "/" after it; a ref doesn't
            ref = tail
            path_part = head
        else:
            path_part = base
    else:
        path_part = base
    default_name = path_part.rstrip("/").rsplit("/", 1)[-1]
    if default_name.endswith(".git"):
        default_name = default_name[:-4]
    return base, ref, (egg.group(1) if egg else default_name)


def _dep_from_pep508(spec: str, file_path: str, scope: str = "") -> Optional[DependencyInfo]:
    """PEP 508 requirement string -> DependencyInfo (extras stripped, marker dropped)."""
    spec = spec.split(";", 1)[0].strip()
    if not spec:
        return None
    git_url = ""
    version = ""
    if "@" in spec and "://" in spec:  # "name @ git+https://..." direct reference
        name_part, _, url = spec.partition("@")
        url = url.strip()
        if url.startswith(("git+", "hg+", "svn+", "bzr+")):
            git_url, version, _ = _vcs_url_parts(url)
        spec = name_part.strip()
    m = _RE_REQ_NAME.match(spec)
    if not m:
        return None
    if not version:
        vm = _RE_VERSION_NUM.search(spec)
        version = vm.group(1) if vm else ""
    return DependencyInfo(
        name=m.group(1), version=version, scope=scope, source_file=file_path,
        type="pypi", ecosystem="pypi", git_url=git_url,
    )


def parse_requirements_txt(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse requirements.txt for Python dependencies (VCS lines)."""
    deps: list[DependencyInfo] = []
    try:
        for raw in content.split("\n"):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            vcs = _RE_PIP_VCS.match(line)
            if vcs:
                git_url, ref, name = _vcs_url_parts(vcs.group(1))
                deps.append(DependencyInfo(
                    name=name, version=ref, source_file=file_path,
                    type="pypi", ecosystem="pypi", git_url=git_url,
                ))
                continue
            if line.startswith("-") or "://" in line:
                continue  # pip options / bare URLs
            dep = _dep_from_pep508(line, file_path)
            if dep:
                deps.append(dep)
    except Exception as e:
        logger.warning("Failed to parse requirements.txt %s: %s", file_path, e)
    return deps


def parse_pyproject_toml(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse pyproject.toml: [project].dependencies + [tool.poetry.*] tables."""
    deps: list[DependencyInfo] = []
    try:
        data = tomllib.loads(content)
    except Exception as e:
        logger.warning("Failed to parse pyproject.toml: %s", e)
        return deps
    try:
        project = data.get("project")
        if isinstance(project, dict):
            for spec in project.get("dependencies") or []:
                dep = _dep_from_pep508(str(spec), file_path)
                if dep:
                    deps.append(dep)
            optional = project.get("optional-dependencies")
            if isinstance(optional, dict):
                for group, specs in optional.items():
                    for spec in specs or []:
                        dep = _dep_from_pep508(str(spec), file_path,
                                               scope=f"optional:{group}")
                        if dep:
                            deps.append(dep)
        poetry = data.get("tool", {}).get("poetry")
        if isinstance(poetry, dict):
            sections: list[tuple[dict, str]] = []
            for key, scope in (("dependencies", ""), ("dev-dependencies", "dev")):
                sec = poetry.get(key)
                if isinstance(sec, dict):
                    sections.append((sec, scope))
            groups = poetry.get("group")
            if isinstance(groups, dict):
                for gname, g in groups.items():
                    sec = (g or {}).get("dependencies")
                    if isinstance(sec, dict):
                        sections.append((sec, str(gname)))
            for sec, scope in sections:
                for name, spec in sec.items():
                    if name.lower() == "python":
                        continue
                    version, git_url = "", ""
                    if isinstance(spec, str):
                        version = spec
                    elif isinstance(spec, dict):
                        version = str(spec.get("version") or "")
                        git_url = str(spec.get("git") or "")
                        if git_url and not version:
                            version = str(spec.get("tag") or spec.get("rev")
                                          or spec.get("branch") or "")
                    deps.append(DependencyInfo(
                        name=name, version=version, scope=scope,
                        source_file=file_path, type="pypi", ecosystem="pypi",
                        git_url=git_url,
                    ))
    except Exception as e:
        logger.warning("Failed to parse pyproject.toml %s: %s", file_path, e)
    return deps


def parse_poetry_lock(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse poetry.lock [[package]] entries."""
    deps: list[DependencyInfo] = []
    try:
        data = tomllib.loads(content)
    except Exception as e:
        logger.warning("Failed to parse poetry.lock: %s", e)
        return deps
    try:
        for pkg in data.get("package") or []:
            if not isinstance(pkg, dict):
                continue
            name = str(pkg.get("name") or "")
            if not name:
                continue
            category = str(pkg.get("category") or "")
            source = pkg.get("source") or {}
            git_url = ""
            if isinstance(source, dict) and source.get("type") == "git":
                git_url = str(source.get("url") or "")
            deps.append(DependencyInfo(
                name=name, version=str(pkg.get("version") or ""),
                scope="" if category in ("", "main") else category,
                source_file=file_path, type="pypi", ecosystem="pypi",
                resolved=True, git_url=git_url,
            ))
    except Exception as e:
        logger.warning("Failed to parse poetry.lock %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# Maven / Gradle (publish identity)
# ---------------------------------------------------------------------------

_RE_POM_PROP = re.compile(r'\$\{([^}]+)\}')
# Legacy regex kept as fallback for malformed XML.
_RE_POM_DEP = re.compile(
    r'<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>'
    r'(?:\s*<version>([^<]*)</version>)?(?:\s*<scope>([^<]*)</scope>)?')


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child_text(elem, name: str) -> str:
    for child in elem:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _xml_root(content: str):
    try:
        return ET.fromstring(content.lstrip("﻿\r\n\t "))
    except Exception:
        return None


def _resolve_pom_value(value: str, props: dict) -> str:
    for _ in range(5):
        if "${" not in value:
            break
        new = _RE_POM_PROP.sub(lambda m: props.get(m.group(1), m.group(0)), value)
        if new == value:
            break
        value = new
    return value


def _analyze_pom(root) -> dict:
    """Project coords, parent coords, and ${property} table for one pom."""
    props: dict[str, str] = {}
    parent_group = parent_artifact = parent_version = ""
    for child in root:
        tag = _local(child.tag)
        if tag == "parent":
            parent_group = _child_text(child, "groupId")
            parent_artifact = _child_text(child, "artifactId")
            parent_version = _child_text(child, "version")
        elif tag == "properties":
            for prop in child:
                props[_local(prop.tag)] = (prop.text or "").strip()
    group = _child_text(root, "groupId") or parent_group
    version = _child_text(root, "version") or parent_version
    for key, value in (("project.groupId", group), ("project.version", version),
                       ("pom.groupId", group), ("pom.version", version),
                       ("project.parent.groupId", parent_group),
                       ("project.parent.version", parent_version)):
        props.setdefault(key, value)
    return {
        "props": props, "group": group, "version": version,
        "artifact": _child_text(root, "artifactId"),
        "parent": (parent_group, parent_artifact, parent_version),
    }


def _walk_pom_deps(elem, in_mgmt: bool, out: list) -> None:
    for child in elem:
        tag = _local(child.tag)
        if tag == "dependency":
            out.append((child, in_mgmt))
        else:
            _walk_pom_deps(child, in_mgmt or tag == "dependencyManagement", out)


def parse_pom_xml(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse pom.xml: deps, <parent>, <dependencyManagement> BOM imports, ${props}."""
    deps: list[DependencyInfo] = []
    root = _xml_root(content)
    if root is None:
        return _parse_pom_xml_regex(file_path, content)
    try:
        info = _analyze_pom(root)
        props = info["props"]
        parent_group, parent_artifact, parent_version = info["parent"]
        if parent_group and parent_artifact:
            deps.append(DependencyInfo(
                name=f"{parent_group}:{parent_artifact}", version=parent_version,
                scope="parent", source_file=file_path, type="maven",
                ecosystem="maven", namespace=parent_group,
            ))
        found: list = []
        _walk_pom_deps(root, False, found)
        for elem, in_mgmt in found:
            group = _resolve_pom_value(_child_text(elem, "groupId"), props)
            artifact = _resolve_pom_value(_child_text(elem, "artifactId"), props)
            version = _resolve_pom_value(_child_text(elem, "version"), props)
            scope = _child_text(elem, "scope")
            if not group or not artifact:
                continue
            if in_mgmt:
                scope = "bom-import" if scope == "import" else "managed"
            else:
                scope = scope or "compile"
            deps.append(DependencyInfo(
                name=f"{group}:{artifact}", version=version, scope=scope,
                source_file=file_path, type="maven", ecosystem="maven",
                namespace=group,
            ))
    except Exception as e:
        logger.warning("Failed to parse pom.xml %s: %s", file_path, e)
    return deps


def _parse_pom_xml_regex(file_path: str, content: str) -> list[DependencyInfo]:
    """Legacy regex fallback when the XML does not parse."""
    deps: list[DependencyInfo] = []
    try:
        for match in _RE_POM_DEP.finditer(content):
            group = match.group(1)
            deps.append(DependencyInfo(
                name=f"{group}:{match.group(2)}", version=match.group(3) or "",
                scope=match.group(4) or "compile", source_file=file_path,
                type="maven", ecosystem="maven", namespace=group,
            ))
    except Exception as e:
        logger.warning("Failed to parse pom.xml %s: %s", file_path, e)
    return deps


_GRADLE_CONFIGS = (
    "testImplementation", "testCompileOnly", "testRuntimeOnly", "testCompile",
    "implementation", "compileOnlyApi", "compileOnly", "annotationProcessor",
    "runtimeOnly", "developmentOnly", "kapt", "ksp", "api", "compile",
    "provided", "runtime",
)
_G = "|".join(_GRADLE_CONFIGS)
# implementation 'g:a:v' | implementation("g:a:v")
_RE_GRADLE_STRING = re.compile(rf'\b({_G})(?:\s*\(\s*|\s+)["\']([^"\']+)["\']')
# implementation(platform("g:a:v")) | api enforcedPlatform('g:a:v')
_RE_GRADLE_PLATFORM = re.compile(
    rf'\b({_G})(?:\s*\(\s*|\s+)(?:enforcedPlatform|platform)\s*\(\s*["\']([^"\']+)["\']')
# implementation(project(":lib")) | implementation project(':lib')
_RE_GRADLE_PROJECT = re.compile(
    rf'\b({_G})(?:\s*\(\s*|\s+)project\s*\(\s*["\']([^"\']+)["\']')
# implementation(libs.spring.boot.starter) - version catalog reference
_RE_GRADLE_CATALOG = re.compile(
    rf'\b({_G})(?:\s*\(\s*|\s+)(libs(?:\.[A-Za-z0-9_]+)+)\b')


def parse_build_gradle(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse build.gradle / build.gradle.kts.

    Legacy back-compat: string-notation deps keep the literal "g:a:v" as name.
    """
    deps: list[DependencyInfo] = []
    try:
        found: list[tuple[int, str, str, str]] = []
        for kind, pattern in (("platform", _RE_GRADLE_PLATFORM),
                              ("project", _RE_GRADLE_PROJECT),
                              ("catalog", _RE_GRADLE_CATALOG),
                              ("string", _RE_GRADLE_STRING)):
            for m in pattern.finditer(content):
                found.append((m.start(), kind, m.group(1), m.group(2)))
        found.sort(key=lambda item: item[0])
        for _, kind, config, value in found:
            if kind in ("string", "platform"):
                parts = value.split(":")
                if len(parts) < 2:
                    continue
                deps.append(DependencyInfo(
                    name=value,
                    version=parts[2] if len(parts) > 2 else "",
                    scope="bom-import" if kind == "platform" else config,
                    source_file=file_path, type="gradle", ecosystem="maven",
                    namespace=parts[0],
                ))
            elif kind == "project":
                deps.append(DependencyInfo(
                    name=value, scope="project", source_file=file_path,
                    type="gradle",
                ))
            else:  # catalog reference -> join against libs.versions.toml
                deps.append(DependencyInfo(
                    name=value, version="", scope=config, source_file=file_path,
                    type="gradle-catalog-ref", ecosystem="maven",
                ))
    except Exception as e:
        logger.warning("Failed to parse build.gradle %s: %s", file_path, e)
    return deps


def _catalog_version(value, versions: dict) -> str:
    if isinstance(value, dict):
        ref = value.get("ref")
        if ref:
            return _catalog_version(versions.get(ref, ""), versions)
        return str(value.get("strictly") or value.get("require")
                   or value.get("prefer") or "")
    return str(value or "")


def parse_gradle_versions_catalog(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse gradle/libs.versions.toml [libraries] entries."""
    deps: list[DependencyInfo] = []
    try:
        data = tomllib.loads(content)
    except Exception as e:
        logger.warning("Failed to parse libs.versions.toml: %s", e)
        return deps
    try:
        versions = data.get("versions") or {}
        libraries = data.get("libraries") or {}
        if not isinstance(libraries, dict):
            return deps
        for _alias, spec in libraries.items():
            group = name = version = ""
            if isinstance(spec, str):  # "g:a:v" shorthand
                parts = spec.split(":")
                if len(parts) >= 2:
                    group, name = parts[0], parts[1]
                    version = parts[2] if len(parts) > 2 else ""
            elif isinstance(spec, dict):
                module = str(spec.get("module") or "")
                if ":" in module:
                    group, name = module.split(":", 1)
                else:
                    group = str(spec.get("group") or "")
                    name = str(spec.get("name") or "")
                version = _catalog_version(spec.get("version"), versions)
            if not name:
                continue
            deps.append(DependencyInfo(
                name=f"{group}:{name}" if group else name, version=version,
                scope="catalog", source_file=file_path, type="maven",
                ecosystem="maven", namespace=group,
            ))
    except Exception as e:
        logger.warning("Failed to parse libs.versions.toml %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# Go: go.mod / go.sum
# ---------------------------------------------------------------------------

def _go_dep(path: str, version: str, scope: str, file_path: str) -> DependencyInfo:
    return DependencyInfo(
        name=path, version=version, scope=scope, source_file=file_path,
        type="go", ecosystem="golang", namespace=_go_namespace(path),
    )


def _go_replace(text: str, deps: list, file_path: str) -> None:
    left, _, right = text.partition("=>")
    left_parts = left.split()
    right_parts = right.split()
    if not left_parts or not right_parts:
        return
    dep = _go_dep(left_parts[0],
                  right_parts[1] if len(right_parts) > 1 else "",
                  "replace", file_path)
    dep.git_url = right_parts[0]  # replacement module path or local dir
    deps.append(dep)


def parse_go_mod(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse go.mod require/replace directives; exclude lines are ignored."""
    deps: list[DependencyInfo] = []
    try:
        block = ""
        for raw in content.split("\n"):
            stripped = raw.strip()
            if not stripped or stripped.startswith("//"):
                continue
            indirect = "// indirect" in stripped
            code = stripped.split("//", 1)[0].strip()
            if not code:
                continue
            if block:
                if code == ")":
                    block = ""
                elif block == "require":
                    parts = code.split()
                    if len(parts) >= 2:
                        deps.append(_go_dep(parts[0], parts[1],
                                            "indirect" if indirect else "", file_path))
                elif block == "replace":
                    _go_replace(code, deps, file_path)
                continue
            if code.endswith("("):
                head = code[:-1].strip()
                if head in ("require", "replace", "exclude"):
                    block = head
                continue
            if code.startswith("require "):
                parts = code[len("require "):].split()
                if len(parts) >= 2:
                    deps.append(_go_dep(parts[0], parts[1],
                                        "indirect" if indirect else "", file_path))
            elif code.startswith("replace "):
                _go_replace(code[len("replace "):], deps, file_path)
            # module / go / toolchain / exclude / retract lines are not deps
    except Exception as e:
        logger.warning("Failed to parse go.mod %s: %s", file_path, e)
    return deps


def parse_go_sum(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse go.sum lines "module v1.2.3 h1:..."."""
    deps: list[DependencyInfo] = []
    try:
        seen: set[tuple[str, str]] = set()
        for line in content.split("\n"):
            parts = line.split()
            if len(parts) < 2:
                continue
            module, version = parts[0], parts[1]
            if version.endswith("/go.mod"):
                continue  # duplicate hash line for the module's go.mod
            if (module, version) in seen:
                continue
            seen.add((module, version))
            dep = _go_dep(module, version, "", file_path)
            dep.resolved = True
            deps.append(dep)
    except Exception as e:
        logger.warning("Failed to parse go.sum %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# NuGet: *.csproj / Directory.Packages.props
# ---------------------------------------------------------------------------

_RE_CSPROJ_PKG = re.compile(r'<PackageReference\b([^>]*)')
_RE_MSBUILD_INCLUDE = re.compile(r'\bInclude="([^"]+)"')
_RE_MSBUILD_VERSION = re.compile(r'\bVersion="([^"]+)"')


def _attr(elem, *names: str) -> str:
    for name in names:
        if name in elem.attrib:
            return elem.attrib[name]
    lowered = {k.lower(): v for k, v in elem.attrib.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ""


def _msbuild_stem(path: str) -> str:
    base = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return os.path.splitext(base)[0]


def parse_csproj(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse *.csproj PackageReference / ProjectReference items."""
    deps: list[DependencyInfo] = []
    root = _xml_root(content)
    if root is None:  # malformed XML - regex fallback for PackageReference
        try:
            for m in _RE_CSPROJ_PKG.finditer(content):
                body = m.group(1)
                include = _RE_MSBUILD_INCLUDE.search(body)
                if not include:
                    continue
                version = _RE_MSBUILD_VERSION.search(body)
                deps.append(DependencyInfo(
                    name=include.group(1), version=version.group(1) if version else "",
                    source_file=file_path, type="nuget", ecosystem="nuget",
                ))
        except Exception as e:
            logger.warning("Failed to parse csproj %s: %s", file_path, e)
        return deps
    try:
        for elem in root.iter():
            tag = _local(elem.tag)
            if tag == "PackageReference":
                name = _attr(elem, "Include", "Update")
                if not name:
                    continue
                version = _attr(elem, "Version") or _child_text(elem, "Version")
                deps.append(DependencyInfo(
                    name=name, version=version, source_file=file_path,
                    type="nuget", ecosystem="nuget",
                ))
            elif tag == "ProjectReference":
                include = _attr(elem, "Include")
                if not include:
                    continue
                deps.append(DependencyInfo(
                    name=_msbuild_stem(include), scope="project",
                    source_file=file_path, type="nuget",
                ))
    except Exception as e:
        logger.warning("Failed to parse csproj %s: %s", file_path, e)
    return deps


def parse_directory_packages_props(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse Directory.Packages.props central package management pins."""
    deps: list[DependencyInfo] = []
    root = _xml_root(content)
    if root is None:
        return deps
    try:
        for elem in root.iter():
            tag = _local(elem.tag)
            if tag not in ("PackageVersion", "GlobalPackageReference"):
                continue
            name = _attr(elem, "Include", "Update")
            if not name:
                continue
            deps.append(DependencyInfo(
                name=name,
                version=_attr(elem, "Version") or _child_text(elem, "Version"),
                scope="managed" if tag == "PackageVersion" else "global",
                source_file=file_path, type="nuget", ecosystem="nuget",
            ))
    except Exception as e:
        logger.warning("Failed to parse Directory.Packages.props %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# Ruby: Gemfile / Gemfile.lock
# ---------------------------------------------------------------------------

_RE_GEM_LINE = re.compile(r'''^\s*gem\s+["']([^"']+)["'](.*)$''')
_RE_GEM_VERSION = re.compile(r'''^\s*,\s*["']([^"']+)["']''')
_RE_GEM_GIT = re.compile(r'''(?::git\s*=>|\bgit:)\s*["']([^"']+)["']''')
_RE_GEM_GITHUB = re.compile(r'''(?::github\s*=>|\bgithub:)\s*["']([^"']+)["']''')


def parse_gemfile(file_path: str, content: str) -> list[DependencyInfo]:
    deps: list[DependencyInfo] = []
    try:
        for line in content.split("\n"):
            m = _RE_GEM_LINE.match(line)
            if not m:
                continue
            name, rest = m.group(1), m.group(2)
            vm = _RE_GEM_VERSION.match(rest)
            git_url = ""
            gm = _RE_GEM_GIT.search(rest)
            if gm:
                git_url = gm.group(1)
            else:
                gh = _RE_GEM_GITHUB.search(rest)
                if gh:
                    git_url = f"https://github.com/{gh.group(1)}"
            deps.append(DependencyInfo(
                name=name, version=vm.group(1) if vm else "",
                source_file=file_path, type="gem", ecosystem="gem",
                git_url=git_url,
            ))
    except Exception as e:
        logger.warning("Failed to parse Gemfile %s: %s", file_path, e)
    return deps


_RE_GEMLOCK_SPEC = re.compile(r'^    (\S+)\s+\(([^)]+)\)\s*$')


def parse_gemfile_lock(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse Gemfile.lock resolved specs.

    Only the 4-space spec entries (the resolved gem set, direct + transitive)
    are emitted, all with scope="lock"; 6-space constraint lines are skipped
    because they carry requirements ("= 7.0.4"), not resolved versions.
    """
    deps: list[DependencyInfo] = []
    try:
        section = ""
        in_specs = False
        remote = ""
        for raw in content.split("\n"):
            if not raw.strip():
                continue
            if not raw.startswith(" "):  # section header (GEM / GIT / PATH / ...)
                section = raw.strip()
                in_specs = False
                remote = ""
                continue
            stripped = raw.strip()
            if raw.startswith("  ") and not raw.startswith("    "):
                if stripped == "specs:":
                    in_specs = True
                elif stripped.startswith("remote:"):
                    remote = stripped.split("remote:", 1)[1].strip()
                continue
            if not in_specs or section not in ("GEM", "GIT", "PATH"):
                continue
            if raw.startswith("      "):
                continue  # 6-space: dependency constraints of a spec
            m = _RE_GEMLOCK_SPEC.match(raw)
            if m:
                deps.append(DependencyInfo(
                    name=m.group(1), version=m.group(2), scope="lock",
                    source_file=file_path, type="gem", ecosystem="gem",
                    resolved=True, git_url=remote if section == "GIT" else "",
                ))
    except Exception as e:
        logger.warning("Failed to parse Gemfile.lock %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# PHP: composer.json
# ---------------------------------------------------------------------------

def parse_composer_json(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse composer.json require / require-dev."""
    deps: list[DependencyInfo] = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse composer.json: %s", e)
        return deps
    if not isinstance(data, dict):
        return deps
    try:
        for scope in ("require", "require-dev"):
            section = data.get(scope)
            if not isinstance(section, dict):
                continue
            for name, version in section.items():
                if name == "php" or name.startswith(("ext-", "lib-")):
                    continue  # platform requirements, not packages
                deps.append(DependencyInfo(
                    name=name, version=str(version), scope=scope,
                    source_file=file_path, type="composer", ecosystem="composer",
                    namespace=name.split("/", 1)[0] if "/" in name else "",
                ))
    except Exception as e:
        logger.warning("Failed to parse composer.json %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# Rust: Cargo.toml / Cargo.lock
# ---------------------------------------------------------------------------

def parse_cargo_toml(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse Cargo.toml [dependencies]/[dev-dependencies]/[build-dependencies]."""
    deps: list[DependencyInfo] = []
    try:
        data = tomllib.loads(content)
    except Exception as e:
        logger.warning("Failed to parse Cargo.toml: %s", e)
        return deps
    try:
        for section_key, scope in (("dependencies", ""),
                                   ("dev-dependencies", "dev"),
                                   ("build-dependencies", "build")):
            section = data.get(section_key)
            if not isinstance(section, dict):
                continue
            for key, spec in section.items():
                name, version, git_url, dep_scope = key, "", "", scope
                if isinstance(spec, str):
                    version = spec
                elif isinstance(spec, dict):
                    name = str(spec.get("package") or key)  # renamed dep
                    version = str(spec.get("version") or "")
                    git_url = str(spec.get("git") or "")
                    if git_url and not version:
                        version = str(spec.get("tag") or spec.get("rev")
                                      or spec.get("branch") or "")
                    if spec.get("path") and not git_url:
                        dep_scope = "project"  # local workspace member
                deps.append(DependencyInfo(
                    name=name, version=version, scope=dep_scope,
                    source_file=file_path, type="cargo",
                    ecosystem="" if dep_scope == "project" else "cargo",
                    git_url=git_url,
                ))
    except Exception as e:
        logger.warning("Failed to parse Cargo.toml %s: %s", file_path, e)
    return deps


def parse_cargo_lock(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse Cargo.lock [[package]] entries."""
    deps: list[DependencyInfo] = []
    try:
        data = tomllib.loads(content)
    except Exception as e:
        logger.warning("Failed to parse Cargo.lock: %s", e)
        return deps
    try:
        for pkg in data.get("package") or []:
            if not isinstance(pkg, dict):
                continue
            name = str(pkg.get("name") or "")
            if not name:
                continue
            source = str(pkg.get("source") or "")
            deps.append(DependencyInfo(
                name=name, version=str(pkg.get("version") or ""),
                source_file=file_path, type="cargo", ecosystem="cargo",
                resolved=True,
                git_url=source if source.startswith("git+") else "",
            ))
    except Exception as e:
        logger.warning("Failed to parse Cargo.lock %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# Bazel: MODULE.bazel / WORKSPACE
# ---------------------------------------------------------------------------

_RE_BAZEL_DEP = re.compile(r'\bbazel_dep\s*\(([^)]*)\)', re.S)
_RE_BAZEL_GIT = re.compile(r'\b(?:git_repository|git_override)\s*\(([^)]*)\)', re.S)
_RE_BAZEL_KV = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|(True|False))')


def _bazel_kwargs(body: str) -> dict[str, str]:
    return {k: (s if s else b) for k, s, b in _RE_BAZEL_KV.findall(body)}


def parse_bazel_module(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse MODULE.bazel / WORKSPACE bazel_dep and git_repository rules."""
    deps: list[DependencyInfo] = []
    try:
        for m in _RE_BAZEL_DEP.finditer(content):
            kwargs = _bazel_kwargs(m.group(1))
            name = kwargs.get("name", "")
            if not name:
                continue
            deps.append(DependencyInfo(
                name=name, version=kwargs.get("version", ""),
                scope="dev" if kwargs.get("dev_dependency") == "True" else "",
                source_file=file_path, type="bazel",
            ))
        for m in _RE_BAZEL_GIT.finditer(content):
            kwargs = _bazel_kwargs(m.group(1))
            name = kwargs.get("name") or kwargs.get("module_name") or ""
            remote = kwargs.get("remote", "")
            if not name:
                continue
            deps.append(DependencyInfo(
                name=name,
                version=kwargs.get("tag") or kwargs.get("commit") or "",
                source_file=file_path, type="bazel", git_url=remote,
            ))
    except Exception as e:
        logger.warning("Failed to parse bazel file %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# SBOM: CycloneDX / SPDX JSON
# ---------------------------------------------------------------------------

def _cyclonedx_license(licenses) -> str:
    if not isinstance(licenses, list):
        return ""
    for entry in licenses:
        if not isinstance(entry, dict):
            continue
        lic = entry.get("license")
        if isinstance(lic, dict):
            value = lic.get("id") or lic.get("name")
            if value:
                return str(value)
        expression = entry.get("expression")
        if expression:
            return str(expression)
    return ""


def _sbom_join_name(name: str, namespace: str, ecosystem: str) -> str:
    """Normalize SBOM component names to this module's join-key conventions."""
    if ecosystem == "maven" and namespace and ":" not in name:
        return f"{namespace}:{name}"
    if ecosystem == "npm" and namespace and not name.startswith("@"):
        return f"{namespace}/{name}"
    return name


def parse_sbom(file_path: str, content: str) -> list[DependencyInfo]:
    """Parse a CycloneDX or SPDX JSON SBOM into resolved dependencies."""
    deps: list[DependencyInfo] = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse SBOM: %s", e)
        return deps
    if not isinstance(data, dict):
        return deps
    try:
        if data.get("bomFormat") == "CycloneDX":
            for comp in data.get("components") or []:
                if not isinstance(comp, dict):
                    continue
                eco, p_ns, p_name, p_ver = _parse_purl(str(comp.get("purl") or ""))
                name = str(comp.get("name") or "") or p_name
                if not name:
                    continue
                namespace = str(comp.get("group") or "") or p_ns
                deps.append(DependencyInfo(
                    name=_sbom_join_name(name, namespace, eco),
                    version=str(comp.get("version") or "") or p_ver,
                    source_file=file_path, type="sbom", ecosystem=eco,
                    namespace=namespace, resolved=True,
                    license=_cyclonedx_license(comp.get("licenses")),
                ))
        elif "spdxVersion" in data:
            described = set(data.get("documentDescribes") or [])
            for pkg in data.get("packages") or []:
                if not isinstance(pkg, dict):
                    continue
                if pkg.get("SPDXID") in described:
                    continue  # the root package the document describes
                name = str(pkg.get("name") or "")
                if not name:
                    continue
                eco = namespace = ""
                for ref in pkg.get("externalRefs") or []:
                    if isinstance(ref, dict) and ref.get("referenceType") == "purl":
                        eco, namespace, _, _ = _parse_purl(
                            str(ref.get("referenceLocator") or ""))
                        break
                license_value = str(pkg.get("licenseConcluded")
                                    or pkg.get("licenseDeclared") or "")
                if license_value in ("NOASSERTION", "NONE"):
                    license_value = ""
                deps.append(DependencyInfo(
                    name=_sbom_join_name(name, namespace, eco),
                    version=str(pkg.get("versionInfo") or ""),
                    source_file=file_path, type="sbom", ecosystem=eco,
                    namespace=namespace, resolved=True, license=license_value,
                ))
    except Exception as e:
        logger.warning("Failed to parse SBOM %s: %s", file_path, e)
    return deps


# ---------------------------------------------------------------------------
# Publish-side identity
# ---------------------------------------------------------------------------

_RE_GO_MODULE = re.compile(r'^\s*module\s+("?)([^\s"]+)\1\s*$', re.M)
_RE_GEMSPEC_NAME = re.compile(r'\b\w+\.name\s*=\s*["\']([^"\']+)["\']')
_RE_GEMSPEC_VERSION = re.compile(r'\b\w+\.version\s*=\s*["\']([^"\']+)["\']')


def _identity_pom(content: str) -> Optional[PublishIdentity]:
    root = _xml_root(content)
    if root is None:
        return None
    info = _analyze_pom(root)
    if not info["artifact"]:
        return None
    props = info["props"]
    return PublishIdentity(
        ecosystem="maven",
        name=info["artifact"],
        namespace=_resolve_pom_value(info["group"], props),
        version=_resolve_pom_value(info["version"], props),
    )


def _identity_package_json(content: str) -> Optional[PublishIdentity]:
    data = json.loads(content)
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not name or not isinstance(name, str):
        return None
    return PublishIdentity(
        ecosystem="npm", name=name, namespace=_npm_namespace(name),
        version=str(data.get("version") or ""),
        private=bool(data.get("private", False)),
    )


def _identity_pyproject(content: str) -> Optional[PublishIdentity]:
    data = tomllib.loads(content)
    project = data.get("project")
    if isinstance(project, dict) and project.get("name"):
        return PublishIdentity(
            ecosystem="pypi", name=str(project["name"]),
            version=str(project.get("version") or ""),
        )
    poetry = data.get("tool", {}).get("poetry")
    if isinstance(poetry, dict) and poetry.get("name"):
        return PublishIdentity(
            ecosystem="pypi", name=str(poetry["name"]),
            version=str(poetry.get("version") or ""),
        )
    return None


def _identity_go_mod(content: str) -> Optional[PublishIdentity]:
    m = _RE_GO_MODULE.search(content)
    if not m:
        return None
    module_path = m.group(2)
    return PublishIdentity(
        ecosystem="golang", name=module_path,
        namespace=_go_namespace(module_path),
    )


def _identity_csproj(file_path: str, content: str) -> Optional[PublishIdentity]:
    root = _xml_root(content)
    if root is None:
        return None
    package_id = assembly_name = version = is_packable = ""
    for elem in root.iter():
        tag = _local(elem.tag)
        text = (elem.text or "").strip()
        if tag == "PackageId" and not package_id:
            package_id = text
        elif tag == "AssemblyName" and not assembly_name:
            assembly_name = text
        elif tag in ("Version", "VersionPrefix") and not version:
            version = text
        elif tag == "IsPackable" and not is_packable:
            is_packable = text
    name = package_id or assembly_name or _msbuild_stem(file_path)
    return PublishIdentity(
        ecosystem="nuget", name=name, version=version,
        private=is_packable.strip().lower() == "false",
    )


def _identity_cargo(content: str) -> Optional[PublishIdentity]:
    data = tomllib.loads(content)
    package = data.get("package")
    if not isinstance(package, dict) or not package.get("name"):
        return None
    return PublishIdentity(
        ecosystem="cargo", name=str(package["name"]),
        version=str(package.get("version") or ""),
        private=package.get("publish") is False,
    )


def _identity_gemspec(content: str) -> Optional[PublishIdentity]:
    m = _RE_GEMSPEC_NAME.search(content)
    if not m:
        return None
    vm = _RE_GEMSPEC_VERSION.search(content)
    return PublishIdentity(
        ecosystem="gem", name=m.group(1),
        version=vm.group(1) if vm else "",
    )


def parse_publish_identity(file_path: str, content: str) -> PublishIdentity | None:
    """What this manifest publishes. None when not an identity source.

    Known gap: build.gradle group/version usually live in gradle.properties,
    allprojects blocks, or convention plugins - too unreliable to claim, so
    gradle publish identity is intentionally not emitted.
    """
    file_name = os.path.basename(file_path)
    try:
        if file_name == "pom.xml":
            return _identity_pom(content)
        if file_name == "package.json":
            return _identity_package_json(content)
        if file_name == "pyproject.toml":
            return _identity_pyproject(content)
        if file_name == "go.mod":
            return _identity_go_mod(content)
        if file_name == "Cargo.toml":
            return _identity_cargo(content)
        if file_name.endswith(".csproj"):
            return _identity_csproj(file_path, content)
        if file_name.endswith(".gemspec"):
            return _identity_gemspec(content)
    except Exception as e:
        logger.warning("Failed to parse publish identity from %s: %s", file_path, e)
    return None


# ---------------------------------------------------------------------------
# Registry / dispatch
# ---------------------------------------------------------------------------

DEPENDENCY_PARSERS = {
    "package.json": parse_package_json,
    "package-lock.json": parse_package_lock,
    "npm-shrinkwrap.json": parse_package_lock,
    "pnpm-lock.yaml": parse_pnpm_lock,
    "yarn.lock": parse_yarn_lock,
    "requirements.txt": parse_requirements_txt,
    "pyproject.toml": parse_pyproject_toml,
    "poetry.lock": parse_poetry_lock,
    "pom.xml": parse_pom_xml,
    "build.gradle": parse_build_gradle,
    "build.gradle.kts": parse_build_gradle,
    "libs.versions.toml": parse_gradle_versions_catalog,
    "go.mod": parse_go_mod,
    "go.sum": parse_go_sum,
    "Gemfile": parse_gemfile,
    "Gemfile.lock": parse_gemfile_lock,
    "composer.json": parse_composer_json,
    "Cargo.toml": parse_cargo_toml,
    "Cargo.lock": parse_cargo_lock,
    "Directory.Packages.props": parse_directory_packages_props,
    "MODULE.bazel": parse_bazel_module,
    "WORKSPACE": parse_bazel_module,
    "WORKSPACE.bazel": parse_bazel_module,
    "bom.json": parse_sbom,
    "sbom.json": parse_sbom,
}

# Extension/suffix routed parsers (checked after exact-name lookup).
_SUFFIX_PARSERS = (
    (".csproj", parse_csproj),
    (".cdx.json", parse_sbom),
    (".spdx.json", parse_sbom),
)


def parse_dependency_file(file_path: str, content: str) -> list[DependencyInfo]:
    file_name = os.path.basename(file_path)
    parser = DEPENDENCY_PARSERS.get(file_name)
    if parser is None:
        for suffix, candidate in _SUFFIX_PARSERS:
            if file_name.endswith(suffix):
                parser = candidate
                break
    if parser is not None:
        try:
            return parser(file_path, content)
        except Exception as e:
            logger.warning("Failed to parse dependency file %s: %s", file_path, e)
    return []


_DEPENDENCY_TYPE_BY_NAME = {
    "package.json": "npm",
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "requirements.txt": "pip",
    "pyproject.toml": "poetry",
    "poetry.lock": "poetry",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "libs.versions.toml": "gradle",
    "go.mod": "go",
    "go.sum": "go",
    "Cargo.toml": "cargo",
    "Cargo.lock": "cargo",
    "Gemfile": "bundler",
    "Gemfile.lock": "bundler",
    "composer.json": "composer",
    "Directory.Packages.props": "nuget",
    "MODULE.bazel": "bazel",
    "WORKSPACE": "bazel",
    "WORKSPACE.bazel": "bazel",
    "bom.json": "sbom",
    "sbom.json": "sbom",
}


def detect_dependency_type(file_name: str) -> Optional[str]:
    detected = _DEPENDENCY_TYPE_BY_NAME.get(file_name)
    if detected:
        return detected
    if file_name.endswith(".csproj"):
        return "nuget"
    if file_name.endswith(".gemspec"):
        return "gem"
    if file_name.endswith((".cdx.json", ".spdx.json")):
        return "sbom"
    return None
