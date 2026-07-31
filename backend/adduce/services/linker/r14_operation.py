"""R14: one logical operation across transports.

Estates migrate protocols; the graph should show one operation. Two
AUTHORED equivalences tie transports together, and only those two:

- The proto's own `option (google.api.http)` declares that an rpc is
  also served over HTTP. The SAME_OPERATION edge cites the .proto line
  that says so, and lands only when exactly one HttpContract matches the
  declared method and template.
- An event schema names the rpc's output: an Avro subject's fully
  qualified record name equals `package.OutputType` of exactly one rpc.
  Both names are authored (the .avsc declares namespace+name, the .proto
  declares package+message); the join is string equality of qualified
  names, and any fan-out — one schema, two rpcs — declines.

Name similarity ties nothing. "OwnerService looks like /v1/owners" is a
guess, and a wrong SAME_OPERATION merges two operations' blast radii.
"""

from adduce.services.linker.base import (
    ClaimIndex, LinkContext, ResolverOutput, linker_edge, positional,
)
from adduce.services.linker.r7_http import contract_lookup
from adduce.utils import rendezvous_ids as rid

RESOLVER_ID = "resolver.operation@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    rpcs = [c for c in index.provides("grpcop") if c.matchable]
    _join_http_bindings(ctx, index, rpcs, out)
    _join_event_schemas(ctx, index, rpcs, out)
    return out


def _join_http_bindings(ctx, index, rpcs, out) -> None:
    contracts = contract_lookup(index, ctx)
    for claim in rpcs:
        method = str(claim.attrs.get("http_method") or "")
        template = str(claim.attrs.get("http_template") or "")
        if not method or not template:
            continue
        matches = contracts.get((method, positional(template)), [])
        distinct = sorted({contract_id for contract_id, _, _ in matches})
        if not distinct:
            ctx.count("r14.http_binding_unmatched")
            continue
        if len(distinct) > 1:
            # Two HttpContracts under one declared binding is genuine
            # ambiguity: a wrong SAME_OPERATION merges two blast radii.
            ctx.count("r14.http_binding_ambiguous")
            continue
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "SAME_OPERATION",
            rid.grpc_operation_id(claim.key), distinct[0],
            source_label="ContractOperation", target_label="HttpContract",
            confidence=ctx.conf("r14", "http_binding"),
            match_type="http_binding", evidence=claim.evidence,
            claim_key=claim.key, source_repo=claim.repo_id,
            origin="declared", extra={"via": ["google.api.http"]},
        ))
        ctx.count("r14.http_binding")


def _join_event_schemas(ctx, index, rpcs, out) -> None:
    # package.OutputType -> rpcs producing it; fan-out declines below.
    by_output: dict[str, list] = {}
    for claim in rpcs:
        package = str(claim.attrs.get("package") or "")
        output = str(claim.attrs.get("output_type") or "")
        if package and output and "." not in output:
            by_output.setdefault(f"{package}.{output}", []).append(claim)

    for claim in index.kind("topic"):
        if not claim.matchable or claim.attrs.get("source") != "avro":
            continue
        schema = str(claim.attrs.get("schema") or "")
        producers = by_output.get(schema, [])
        if not producers:
            continue                       # a topic with no rpc is normal
        if len(producers) > 1:
            ctx.count("r14.event_schema_ambiguous")
            continue
        [rpc] = producers
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "SAME_OPERATION",
            rid.grpc_operation_id(rpc.key), rid.topic_id(claim.key),
            source_label="ContractOperation", target_label="Topic",
            confidence=ctx.conf("r14", "event_schema"),
            match_type="event_schema",
            evidence=list(rpc.evidence or []) + list(claim.evidence or []),
            claim_key=rpc.key, source_repo=rpc.repo_id,
            origin="declared", extra={"via": ["schema_name"],
                                       "schema": schema},
        ))
        ctx.count("r14.event_schema")
