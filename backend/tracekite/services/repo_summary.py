"""Map stored Repo node properties into the public summary contract."""

from tracekite.models.api_models import RepoSummary
from tracekite.services.graph_properties import parse_json, to_native_dt


def repo_summary(props: dict) -> RepoSummary:
    coverage = parse_json(props.get("parse_coverage_totals"))
    return RepoSummary(
        id=props.get("id") or "",
        name=props.get("name") or "",
        owner=props.get("owner") or "",
        repo=props.get("repo") or "",
        github_url=props.get("github_url") or "",
        branch=props.get("branch") or "main",
        last_ingested_at=to_native_dt(props.get("last_ingested_at")),
        ingestion_status=props.get("ingestion_status") or "unknown",
        lifecycle_state=props.get("lifecycle_state"),
        head_commit_sha=props.get("head_commit_sha"),
        source=props.get("source"),
        node_count=props.get("node_count") or 0,
        edge_count=props.get("edge_count") or 0,
        parse_coverage=coverage or None,
        claims_by_kind=parse_json(props.get("claims_by_kind")) or None,
        linked_at=to_native_dt(props.get("linked_at")),
    )
