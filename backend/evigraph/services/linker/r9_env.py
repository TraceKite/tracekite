"""R9 environment indirection: join code read-sites to config values.

Env-var indirection is the #1 documented false-negative cause across every
published dependency-extraction tool: ``fetch(process.env.ORDERS_URL)`` names
no service, so a purely syntactic extractor sees nothing. The value lives in a
Deployment, a ConfigMap, a Helm values file or a compose file — a different
repo from the code, which is exactly why this has to be a linker pass and not
a parser feature.

Building the index of those values is broadcast work and lives in
`r9_env_index.py`; this file is the join. The split is invariant I10: R6 also
reads `ctx.env_values`, and a table written during the join can only be read
by a resolver running in the same shard.

Every edge carries ``env_scope``, so a value that only holds in staging is
never presented as a production fact.
"""

import logging

from evigraph.services.linker.base import (
    ClaimIndex, ClaimRecord, EnvValue, LinkContext, ResolverOutput,
)

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.env@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    _join_read_sites(ctx, index)
    return out


def _join_read_sites(ctx: LinkContext, index: ClaimIndex) -> None:
    """Step 3: code reads ORDERS_URL; a manifest says what ORDERS_URL is."""
    by_name: dict[str, list[EnvValue]] = {}
    for value in ctx.env_values.values():
        by_name.setdefault(value.name, []).append(value)

    for claim in index.consumes("cfgread"):
        var_name = str(claim.attrs.get("env_name") or "")
        if not var_name:
            continue
        candidates = by_name.get(var_name, [])
        if not candidates:
            ctx.count("r9.read_unresolved")
            if claim.attrs.get("endpoint_like"):
                # Worth surfacing: an unresolved *_URL is a missing edge, an
                # unresolved RETRY_COUNT is not.
                ctx.count("r9.read_unresolved_endpoint")
            continue

        # Prefer definitions from the repo that also holds the code: in a
        # monorepo the manifest next to the source is the authoritative one.
        same_repo = [v for v in candidates if v.repo_id == claim.repo_id]
        candidates = same_repo or candidates

        hosts = {v.value_host for v in candidates if v.value_host}
        if len(hosts) > 1:
            # The same variable names different targets per environment.
            # Emitting one would assert a fact that holds in only one of them.
            ctx.count("r9.ambiguous_across_envs")
            continue
        if not hosts:
            continue

        consumers = {v.consumer_service for v in candidates if v.consumer_service}
        if len(consumers) > 1:
            # Injected into several workloads; which one contains this code is
            # a guess, and a wrong source attributes the call to the wrong team.
            ctx.count("r9.ambiguous_consumer")
            continue

        value = candidates[0]
        target = ctx.canon(_bare_host(value.value_host))
        source = ctx.canon(consumers.pop() if consumers
                           else _consumer_service(ctx, claim))
        if not target or not source or source == target:
            ctx.count("r9.self_or_unknown")
            continue

        ctx.count("r9.env_resolved_calls")
        ctx.record_service_call(
            source, target, RESOLVER_ID,
            ctx.conf("r9", "env_resolved"),
            (claim.evidence or []) + value.evidence,
            claim.repo_id, via="env_indirection", env_scope=value.env_scope,
        )


def _consumer_service(ctx: LinkContext, claim: ClaimRecord) -> str:
    """Which service performs this read — the module owning the reading file."""
    path = claim.primary_path
    return ctx.module_service_name(claim.repo_id, path) or ""


def _bare_host(host: str) -> str:
    host = (host or "").lower()
    for suffix in (".svc.cluster.local", ".svc"):
        if host.endswith(suffix):
            host = host[: -len(suffix)]
            break
    return host.split(".")[0]
