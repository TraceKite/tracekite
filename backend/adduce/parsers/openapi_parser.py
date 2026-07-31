"""OpenAPI/Swagger documents as DECLARED operations.

A spec is a promise, not an observation: the code may serve endpoints the
spec never mentions, and the spec may declare endpoints nobody implements.
Both directions are drift, and drift is the finding — so declared
operations are extracted for reconciliation and nothing else. They become
unmatchable claims downstream: a contract minted from a spec would assert
an endpoint exists because a document says so, which is exactly the
invented edge this tool refuses.
"""

import json
import re
from dataclasses import dataclass

import yaml

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_SPEC_FILE = re.compile(
    r"(^|/)(openapi|swagger)[^/]*\.(ya?ml|json)$", re.IGNORECASE)


@dataclass
class DeclaredOperation:
    method: str
    path: str
    line: int
    title: str


def is_openapi_file(file_path: str) -> bool:
    return bool(_SPEC_FILE.search(file_path))


def parse_openapi(file_path: str, content: str) -> list[DeclaredOperation]:
    """Every operation the document declares. `[]` for non-specs.

    Content is the discriminator, not just the filename: an
    `openapi.yaml` holding a helm values block declares nothing.
    """
    if not is_openapi_file(file_path):
        return []
    try:
        doc = (json.loads(content) if content.lstrip().startswith("{")
               else yaml.safe_load(content))
    except (yaml.YAMLError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(doc, dict) or not (
            doc.get("openapi") or doc.get("swagger")):
        return []
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return []

    title = str((doc.get("info") or {}).get("title") or "")
    # First line each path literal appears on, so the drift report can cite
    # the spec the way everything else cites source.
    lines: dict[str, int] = {}
    for number, line in enumerate(content.splitlines(), start=1):
        for path in paths:
            if isinstance(path, str) and path not in lines and path in line:
                lines[path] = number
    operations: list[DeclaredOperation] = []
    for path, item in sorted(paths.items()):
        if not isinstance(path, str) or not path.startswith("/") \
                or not isinstance(item, dict):
            continue
        for method in _METHODS:
            if method in item:
                operations.append(DeclaredOperation(
                    method=method.upper(), path=path,
                    line=lines.get(path, 1), title=title))
    return operations
