"""Package coordinates a repository consumes and publishes.

Extracted from `ingest_claims.py` while giving these claims a real line
number. Every dependency claim used to cite `manifest:1`, so following the
receipt for one package landed on whatever happened to be the first line of
the file — a comment, in the resolved `requirements.txt` files that
motivated the fix. The coordinate was right and the citation was not, which
is the half of provenance that is easy to leave broken because the graph
still renders.
"""

from evigraph.services.claim_sink import add_claim
from evigraph.services.claims import CONSUMES, PROVIDES, ContractClaim, lib_key
from evigraph.services.claims import is_internal_lib
from evigraph.services.ingest_source import IngestSink
from evigraph.services.manifest_lines import declaration_line_any

_TYPE_ECOSYSTEMS = {"npm": "npm", "pypi": "pypi", "pip": "pypi",
                    "maven": "maven", "gradle": "maven", "gradle-catalog-ref": "",
                    "go": "golang", "golang": "golang", "nuget": "nuget",
                    "cargo": "cargo", "gem": "gem", "composer": "composer",
                    "bazel": ""}

_internal_namespaces_cache: dict | None = None


def _internal_namespaces() -> dict:
    global _internal_namespaces_cache
    if _internal_namespaces_cache is None:
        from evigraph.services.linker.base import load_internal_namespaces
        _internal_namespaces_cache = load_internal_namespaces()
    return _internal_namespaces_cache


def _lib_key_of(dep) -> str:
    ecosystem = (getattr(dep, "ecosystem", "")
                 or _TYPE_ECOSYSTEMS.get((dep.type or "").lower(), ""))
    if not ecosystem or not dep.name:
        return ""
    namespace = getattr(dep, "namespace", "") or ""
    name = dep.name
    if ecosystem == "maven" and ":" in name:
        namespace, _, name = name.partition(":")
    elif ecosystem == "npm" and name.startswith("@") and "/" in name:
        namespace, _, name = name.partition("/")
    elif ecosystem == "golang" and "/" in name:
        namespace, _, name = name.rpartition("/")
    return lib_key(ecosystem, name, namespace)


def _cite(file_info, content: str, dep) -> list[str]:
    """`manifest:line` for the row declaring this package.

    The full coordinate is offered before the bare name because a go.mod row
    is the whole module path, and `mux` alone would match the wrong line in
    a file that also requires `github.com/gorilla/mux/v2`. Line 1 stays the
    fallback: a manifest whose grammar this does not model still gets a
    citation to the right file, which is what the claim id already hashes.
    """
    name = getattr(dep, "name", "") or ""
    namespace = getattr(dep, "namespace", "") or ""
    full = f"{namespace}/{name}" if namespace and "/" not in name else name
    line = declaration_line_any(content, full, name) if content else 0
    return [f"{file_info.path}:{line or 1}"]


def emit_dependency_claims(repo_id: str, file_info, dependencies,
                           file_node_id: str, sink: IngestSink,
                           content: str = "") -> None:
    """Consumed package coordinates.

    Direct manifest declarations always claim; lockfile/SBOM entries claim only
    when internal — an enterprise lockfile carries thousands of external
    transitive rows, and a graph where every repo depends on `lodash` answers
    no blast-radius question. External rows stay visible as a counter.
    """
    namespaces = _internal_namespaces()
    for dep in dependencies:
        key = _lib_key_of(dep)
        if not key:
            continue
        resolved = bool(getattr(dep, "resolved", False))
        git_url = getattr(dep, "git_url", "") or ""
        if resolved and not git_url and not is_internal_lib(key, namespaces):
            sink.count_claim("lib_external_skipped")
            continue
        add_claim(repo_id, ContractClaim(
            repo_id=repo_id, kind="lib", direction=CONSUMES, key=key,
            hint_source="none", evidence=_cite(file_info, content, dep),
            subject=f"dep/{dep.type}/{dep.version or 'unpinned'}",
            attrs={"version": dep.version or "", "scope": dep.scope or "",
                   "resolved": resolved, "manager": dep.type or "",
                   "git_url": git_url,
                   "internal": is_internal_lib(key, namespaces)},
        ), file_node_id, sink)


def emit_publish_claims(repo_id: str, file_info, identity, file_node_id: str,
                        sink: IngestSink, content: str = "") -> None:
    """What this repo publishes — the strong half of the library join."""
    if identity is None or not identity.name:
        return
    key = lib_key(identity.ecosystem, identity.name, identity.namespace or "")
    line = declaration_line_any(content, identity.name) if content else 0
    add_claim(repo_id, ContractClaim(
        repo_id=repo_id, kind="lib", direction=PROVIDES, key=key,
        hint_source="none", evidence=[f"{file_info.path}:{line or 1}"],
        subject=f"publish/{identity.ecosystem}",
        attrs={"version": identity.version or "",
               "private": bool(getattr(identity, "private", False)),
               "ecosystem": identity.ecosystem},
    ), file_node_id, sink)
