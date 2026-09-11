"""R3 library resolver: join package coordinates at Library rendezvous nodes.

The rendezvous key is a version-free purl, so "the library" is one node and
per-consumer versions live on the DEPENDS_ON edges — version skew is a query
over one node's in-edges, not a reconciliation problem. Precision comes from
an explicit internal boundary: a coordinate links only when an ingested repo
publishes it (the strong join) or the control-plane file claims its namespace
(the declared boundary). Everything else is external and counted, because a
graph where every repo depends on `lodash` answers no blast-radius question.

Go modules get one extra join: a module path IS a repo URL, so an unpublished
`github.com/acme/lib` consumed by another repo still binds to the ingested
repo with that URL. VCS dependencies bind the same way.

Edges: Repo -PUBLISHES-> Library, Repo -DEPENDS_ON-> Library, and
Repo -DEPENDS_ON_REPO-> Repo for resolved go-module/git dependencies.
"""

import logging
from collections import defaultdict

from tracekite.services.claims import is_internal_lib
from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    linker_edge, load_internal_namespaces,
)
from tracekite.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.library@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    namespaces = load_internal_namespaces()

    published: dict[str, list[ClaimRecord]] = defaultdict(list)
    for claim in index.provides("lib"):
        published[claim.key].append(claim)

    consumed: dict[str, list[ClaimRecord]] = defaultdict(list)
    for claim in index.consumes("lib"):
        consumed[claim.key].append(claim)

    seen: set[str] = set()
    for key, publishers in sorted(published.items()):
        node_id = _rendezvous(ctx, out, seen, key, internal=True)
        for claim in publishers:
            ctx.count("r3.published")
            _edge(ctx, out, claim, "PUBLISHES", node_id, key,
                  ctx.conf("r3", "publishes"), "publish_identity")

    for key, consumers in sorted(consumed.items()):
        is_published = key in published
        internal = is_published or is_internal_lib(key, namespaces)
        repo_binding = None if is_published else _repo_for_module(ctx, key, consumers)
        if not internal and repo_binding is None:
            ctx.count("r3.external_skipped", len(consumers))
            continue

        node_id = _rendezvous(ctx, out, seen, key, internal=True)
        publisher_repos = sorted({c.repo_id for c in published.get(key, [])})
        versions: set[str] = set()
        for claim in consumers:
            tier = ("lockfile_resolved" if claim.attrs.get("resolved")
                    else "manifest_declared")
            match_type = ("published" if is_published else
                          "go_module_path" if repo_binding else
                          "internal_namespace")
            _edge(ctx, out, claim, "DEPENDS_ON", node_id, key,
                  ctx.conf("r3", tier), match_type,
                  target_repo=(publisher_repos[0]
                               if len(publisher_repos) == 1 else
                               repo_binding or ""),
                  extra={"version": str(claim.attrs.get("version") or ""),
                         "scope": str(claim.attrs.get("scope") or ""),
                         "resolved": bool(claim.attrs.get("resolved"))})
            ctx.count("r3.depends")
            if version := str(claim.attrs.get("version") or ""):
                versions.add(version)

        if len(versions) > 1:
            # Skew is a fact worth surfacing, not an error.
            ctx.count("r3.version_skew")

        target_repo = (publisher_repos[0] if len(publisher_repos) == 1
                       else repo_binding)
        if target_repo:
            for repo in sorted({c.repo_id for c in consumers} - {target_repo}):
                out.edges.append(linker_edge(
                    ctx, RESOLVER_ID, "DEPENDS_ON_REPO", repo, target_repo,
                    source_label="Repo", target_label="Repo",
                    confidence=ctx.conf("r3", "publishes"),
                    match_type="library", evidence=[], claim_key=key,
                    source_repo=repo, target_repo=target_repo,
                    extra={"via": ["library"]},
                ))


    return out


def _rendezvous(ctx: LinkContext, out: ResolverOutput, seen: set[str],
                key: str, internal: bool) -> str:
    node_id = rid.library_id(key)
    if node_id not in seen:
        seen.add(node_id)
        ecosystem = key[4:].partition("/")[0]
        out.rendezvous.append(RendezvousSpec("Library", node_id, {
            "key": key,
            "name": key[4:].partition("/")[2] or key,
            "ecosystem": ecosystem,
            "internal": internal,
        }))
        ctx.count("r3.libraries")
    return node_id


def _edge(ctx: LinkContext, out: ResolverOutput, claim: ClaimRecord,
          edge_type: str, node_id: str, key: str, confidence: float,
          match_type: str, target_repo: str = "",
          extra: dict | None = None) -> None:
    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, node_id,
        source_label="ContractClaim", target_label="Library",
        confidence=confidence, match_type=match_type,
        evidence=claim.evidence, claim_key=key,
        source_repo=claim.repo_id, origin="matched",
    ))
    out.edges.append(linker_edge(
        ctx, RESOLVER_ID, edge_type, claim.repo_id, node_id,
        source_label="Repo", target_label="Library",
        confidence=confidence, match_type=match_type,
        evidence=claim.evidence, claim_key=key,
        source_repo=claim.repo_id, target_repo=target_repo,
        extra=dict(extra or {}, via=["package"]),
    ))


def _repo_for_module(ctx: LinkContext, key: str,
                     consumers: list[ClaimRecord]) -> str | None:
    """`pkg:golang/github.com/acme/lib` -> the ingested repo at that URL, and
    VCS dependencies -> the ingested repo they point at."""
    if key.startswith("pkg:golang/"):
        module = key[len("pkg:golang/"):]
        parts = module.split("/")
        if len(parts) >= 3:
            repo_id = ctx.repo_id_for_url(f"https://{'/'.join(parts[:3])}")
            if repo_id:
                ctx.count("r3.go_module_bound")
                return repo_id
    for claim in consumers:
        git_url = str(claim.attrs.get("git_url") or "")
        if git_url:
            repo_id = ctx.repo_id_for_url(git_url)
            if repo_id:
                ctx.count("r3.git_dep_bound")
                return repo_id
    return None
