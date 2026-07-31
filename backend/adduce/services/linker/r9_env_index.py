"""R9's broadcast half: build the env-value index before the join (I10).

Env-var indirection needs two things that belong to different phases, and
until now both ran in one resolver:

1. **Index** every resolved config definition by (scope, var name). This reads
   `cfgdef` claims and nothing else, and produces a side table bounded by
   config — the shape architecture §4 calls broadcast state.
2. **Join** code read-sites against that index, which is `r9_env.py`.

Running (1) inside the join phase broke invariant I10. R6 reads
`ctx.env_values` and R9 wrote it, so the two resolvers had to run in one
process in a fixed order — the engine even documented the ordering as
deliberate. That works single-threaded and fails the moment REDUCE is
partitioned: R9 in the shard holding one key populates values that R6, in the
shard holding another, never sees. No error, no counter — just edges that
stop appearing, which is the failure mode this project treats as the worst
available.

Splitting it costs nothing at runtime and buys shardability: the index is
built once, before any partitioning, and replicated like every other
broadcast table.

Counters keep the `r9.` prefix. They are the same declines about the same
claims, computed earlier; renaming them would break continuity in every
dashboard and comparison for no gain.
"""

import logging

from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, EnvValue, LinkContext, ResolverOutput,
)

logger = logging.getLogger(__name__)

# Network classes join hosts (R9); enum-ish values join by hmac (R6 topics).
# Everything else — ports, bools, secrets — resolves nothing, so indexing it
# would grow a broadcast table with entries no resolver can ever use.
_NETWORK_CLASSES = ("url", "hostname")


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    """Populate `ctx.env_values`. Emits no edges: this is a side table.

    A broadcast resolver returning an empty output is not a no-op — what it
    contributes is state, and the join phases that read it would find nothing
    without this having run.
    """
    definitions = _index_definitions(index)
    _resolve_references(ctx, index, definitions)
    return ResolverOutput()


def _index_definitions(index: ClaimIndex) -> dict:
    """Every cfgdef claim keyed by (scope, object, key) for reference lookup."""
    by_object: dict[tuple[str, str, str], ClaimRecord] = {}
    for claim in index.provides("cfgdef"):
        source = claim.attrs.get("source", "")
        if source not in ("k8s_configmap", "k8s_secret"):
            continue
        scope, _, _rest = claim.key.partition(":")
        obj = str(claim.attrs.get("object") or "")
        key = str(claim.attrs.get("config_key") or "")
        if obj and key:
            by_object[(scope, obj, key)] = claim
    return by_object


def _index_helm_values(index: ClaimIndex) -> dict:
    """helm_values cfgdefs by (repo, dotted key), for reference chasing."""
    by_key: dict[tuple[str, str], ClaimRecord] = {}
    for claim in index.provides("cfgdef"):
        if claim.attrs.get("source") != "helm_values":
            continue
        key = str(claim.attrs.get("config_key") or "")
        if key:
            by_key[(claim.repo_id, key)] = claim
    return by_key


def _chase_helm_ref(ctx: LinkContext, claim: ClaimRecord, attrs: dict,
                    helm_values: dict) -> dict | None:
    """Follow `{{ .Values.x }}` one more layer down, or say why not.

    The chart and its values file live in the same repository — a chart
    renders only its own values — so the lookup never crosses repos.
    Returns the values-file attrs to price the binding with, None to keep
    the attrs already in hand.
    """
    ref = str(attrs.get("helm_ref") or "")
    if not ref:
        if attrs.get("helm_composite"):
            # `http://{{ .Values.host }}:{{ .Values.port }}` — resolving it
            # would mean rendering the template, and a hand-rendered value
            # is an invented one. Counted, never spliced.
            ctx.count("r9.helm_composite_template")
        return None
    target = helm_values.get((claim.repo_id, ref))
    if target is None:
        ctx.count("r9.helm_ref_unresolved")
        return None
    ctx.count("r9.helm_ref_resolved")
    return target.attrs


def _resolve_references(ctx: LinkContext, index: ClaimIndex,
                        definitions: dict) -> None:
    """Turn each env binding into a concrete value where possible."""
    helm_values = _index_helm_values(index)
    for claim in index.provides("cfgdef"):
        source = claim.attrs.get("source", "")
        scope, _, var_name = claim.key.partition(":")

        if source == "k8s_env" and not claim.attrs.get("unresolved"):
            # A literal that is itself a pure Helm reference points one
            # layer further down: values → env → code.
            attrs = _chase_helm_ref(ctx, claim, claim.attrs, helm_values) \
                or claim.attrs
            _record_value(ctx, claim, scope, var_name, attrs,
                          origin="k8s_env")
            continue

        if source == "k8s_env" and claim.attrs.get("unresolved"):
            if claim.attrs.get("ref_kind") == "secret":
                # A secret's value is never in the graph, so it can never
                # yield a host. Counted, not joined.
                ctx.count("r9.secret_ref")
                continue
            ref_name = str(claim.attrs.get("ref_name") or "")
            ref_key = str(claim.attrs.get("ref_key") or "")
            target = definitions.get((scope, ref_name, ref_key))
            if target is None:
                ctx.count("r9.unresolved_ref")
                continue
            ctx.count("r9.resolved_ref")
            # Value comes from the ConfigMap; the consumer is the workload
            # that references it, so attribution stays on the referencing
            # claim. When the ConfigMap value is itself `{{ .Values.x }}`,
            # follow it to the values file — the full E2 chain:
            # values → ConfigMap → env → code.
            attrs = _chase_helm_ref(ctx, claim, target.attrs, helm_values) \
                or target.attrs
            _record_value(ctx, claim, scope, var_name, attrs,
                          origin="k8s_configmap")
            continue

        if source in ("helm_values", "compose_env"):
            _record_value(ctx, claim, scope, var_name, claim.attrs,
                          origin=source)


def _record_value(ctx: LinkContext, claim: ClaimRecord, scope: str,
                  var_name: str, attrs: dict, origin: str) -> None:
    value_class = str(attrs.get("value_class") or "")
    if value_class not in _NETWORK_CLASSES and value_class != "enum-ish":
        return
    ctx.record_env_value(EnvValue(
        name=var_name,
        scope=scope,
        value_class=value_class,
        value_host=str(attrs.get("value_host") or ""),
        value_hmac=str(attrs.get("value_hmac") or ""),
        value_port=int(attrs.get("value_port") or 0),
        value_scheme=str(attrs.get("value_scheme") or ""),
        origin=origin,
        evidence=list(claim.evidence or []),
        repo_id=claim.repo_id,
        env_scope=str(claim.attrs.get("env_scope") or ""),
        # Always from the *referencing* claim, never the ConfigMap: the
        # ConfigMap is shared, the workload that mounts it is the reader.
        consumer_service=str(claim.attrs.get("service") or ""),
    ))
    ctx.count("r9.values_indexed")
