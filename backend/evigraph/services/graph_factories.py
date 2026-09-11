"""Builders for Layer-0 nodes and edges with stable identity and promoted props.

Match-relevant fields (http_method, path_template, purl, image, kind) are
promoted to first-class indexed properties instead of metadata JSON.
"""

import json

from evigraph.models.graph_models import GraphEdge, GraphNode
from evigraph.services.redaction import RedactedValue
from evigraph.utils.canonical import build_purl, canonicalize_path_template, normalize_http_method
from evigraph.utils.hashing import generate_node_id


def create_repo_node(repo_id: str, owner: str, repo_name: str, github_url: str,
                     branch: str, head_commit_sha: str, language_stats: dict) -> GraphNode:
    return GraphNode(
        id=repo_id,
        repo_id=repo_id,
        type="Repo",
        name=f"{owner}/{repo_name}",
        label=f"{owner}/{repo_name}",
        extra_props={
            "owner": owner,
            "repo": repo_name,
            "github_url": github_url,
            "branch": branch,
            "head_commit_sha": head_commit_sha,
            "language_summary": json.dumps(language_stats or {}),
            "ingestion_status": "in_progress",
        },
    )


def create_folder_node(repo_id: str, folder_path: str) -> GraphNode:
    name = folder_path.rsplit("/", 1)[-1]
    return GraphNode(
        id=generate_node_id(repo_id, "Folder", folder_path),
        repo_id=repo_id,
        type="Folder",
        name=name,
        label=name,
        path=folder_path,
    )


def create_file_node(repo_id: str, file_path: str, file_name: str, language: str,
                     size_bytes: int, is_test: bool) -> GraphNode:
    return GraphNode(
        id=generate_node_id(repo_id, "File", file_path),
        repo_id=repo_id,
        type="File",
        name=file_name,
        label=file_name,
        path=file_path,
        language=language if language != "Unknown" else None,
        extra_props={"size_bytes": size_bytes, "is_test": bool(is_test)},
    )


def create_endpoint_node(repo_id: str, file_path: str, language: str, method: str,
                         raw_path: str, framework: str, handler: str,
                         controller: str, line: int) -> GraphNode:
    http_method = normalize_http_method(method)
    template = canonicalize_path_template(raw_path)
    display = f"{http_method} {template}"
    return GraphNode(
        id=generate_node_id(repo_id, "ApiEndpoint", file_path, display),
        repo_id=repo_id,
        type="ApiEndpoint",
        name=display,
        label=display,
        path=file_path,
        language=language,
        start_line=line or None,
        extra_props={
            "http_method": http_method,
            "path_template": template,
            "raw_path": raw_path,
            "framework": framework,
        },
        metadata={"handler": handler, "controller": controller},
    )


def create_dependency_node(repo_id: str, name: str, version: str, scope: str,
                           source_type: str, declared_in: str) -> GraphNode:
    purl = build_purl(source_type, name, version)
    return GraphNode(
        id=generate_node_id(repo_id, "Dependency", "", name),
        repo_id=repo_id,
        type="Dependency",
        name=name,
        label=name,
        path=declared_in,
        extra_props={
            "purl": purl,
            "version": version,
            "scope": scope,
            "source_type": source_type,
        },
    )


def create_config_node(repo_id: str, file_path: str, key: str,
                       redacted: RedactedValue) -> GraphNode:
    """Config node properties are exactly the key + RedactedValue fields (§3.4)."""
    return GraphNode(
        id=generate_node_id(repo_id, "Config", file_path, key),
        repo_id=repo_id,
        type="Config",
        name=key,
        label=key,
        path=file_path,
        extra_props={"key": key, **redacted.to_props()},
    )


def create_docker_node(repo_id: str, file_path: str, name: str, resource_type: str,
                       image: str, ports: list[str]) -> GraphNode:
    return GraphNode(
        id=generate_node_id(repo_id, "DockerResource", file_path, f"{resource_type}_{name}"),
        repo_id=repo_id,
        type="DockerResource",
        name=name,
        label=name,
        path=file_path,
        extra_props={"resource_type": resource_type, "image": image,
                     "ports": [str(p) for p in ports or []]},
    )


def create_k8s_node(repo_id: str, file_path: str, kind: str, name: str,
                    namespace: str, api_version: str) -> GraphNode:
    display = f"{kind}/{name}"
    return GraphNode(
        id=generate_node_id(repo_id, "KubernetesResource", file_path, display),
        repo_id=repo_id,
        type="KubernetesResource",
        name=display,
        label=display,
        path=file_path,
        extra_props={"kind": kind, "resource_name": name, "namespace": namespace,
                     "api_version": api_version},
    )


def create_iac_node(repo_id: str, file_path: str, resource) -> GraphNode:
    """A Terraform block, Kustomization or ECS container definition.

    Managed-resource identity (queue names, OpenSearch domains, RDS instances)
    is captured here now; the resolvers that join it land separately.
    """
    display = resource.address
    return GraphNode(
        id=generate_node_id(repo_id, "IaCResource", file_path, display),
        repo_id=repo_id,
        type="IaCResource",
        name=display,
        label=display,
        path=file_path,
        start_line=resource.line or None,
        extra_props={
            "block_type": resource.block_type,
            "resource_type": resource.resource_type,
            "resource_name": resource.name,
            "category": resource.category,
            "module_source": resource.source,
            "references": resource.references[:20],
        },
        metadata=dict(resource.attributes),
    )


def create_contains_edge(repo_id: str, source_id: str, target_id: str) -> GraphEdge:
    return GraphEdge(source_id=source_id, target_id=target_id, repo_id=repo_id,
                     type="CONTAINS", label="contains")


def create_declares_edge(repo_id: str, source_id: str, target_id: str,
                         declared_kind: str) -> GraphEdge:
    return GraphEdge(source_id=source_id, target_id=target_id, repo_id=repo_id,
                     type="DECLARES", label=f"declares {declared_kind}")


def create_calls_edge(repo_id: str, caller_id: str, callee_id: str,
                      confidence: float, evidence: list[str]) -> GraphEdge:
    return GraphEdge(
        source_id=caller_id, target_id=callee_id, repo_id=repo_id,
        type="CALLS", label="calls",
        confidence=confidence, origin="inferred",
        detected_by="call_graph_resolver", match_type="name_resolution",
        evidence=evidence[:5],
    )


def create_exposes_api_edge(repo_id: str, source_id: str, endpoint_id: str,
                            evidence: list[str]) -> GraphEdge:
    return GraphEdge(
        source_id=source_id, target_id=endpoint_id, repo_id=repo_id,
        type="EXPOSES_API", label="exposes API",
        detected_by="endpoint_extractor", match_type="annotation",
        evidence=evidence[:5],
    )


def create_depends_on_edge(repo_id: str, file_id: str, dep_id: str,
                           evidence: list[str]) -> GraphEdge:
    return GraphEdge(
        source_id=file_id, target_id=dep_id, repo_id=repo_id,
        type="DEPENDS_ON", label="depends on",
        detected_by="dependency_parser", match_type="manifest",
        evidence=evidence[:5],
    )
