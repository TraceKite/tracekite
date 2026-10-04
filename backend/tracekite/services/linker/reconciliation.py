"""Declared contracts against observed ones, both sides cited.

A spec and the code drift in two directions and they are different
findings: **declared-not-observed** is a promise nobody keeps (a consumer
built against the spec will 404), **observed-not-declared** is an endpoint
consumers cannot discover honestly (they will call it anyway, undocumented
coupling). Reporting only one direction would hide the other behind a
green check.

Pure over claims — no store, no server — and matched on the positional
template so `/owners/{ownerId}` in a spec meets `/owners/{id}` in code:
the parameter's NAME is documentation, the position is the contract.
gRPC and topics reconcile through the same function because their claims
already carry both sides (proto vs implementation, declared vs literal).
"""

from tracekite.services.linker.grpc_names import (
    operation_service_names, stub_service_name,
)
from tracekite.utils.canonical import canonicalize_path_template


def _positional(key: str) -> tuple[str, str]:
    method, _, template = key.partition(":")
    return method, canonicalize_path_template(template)


def _cite(claim) -> dict:
    return {"key": claim.key, "evidence": list(claim.evidence or []),
            "repo": claim.repo_id}


def reconcile_http(claims: list) -> dict:
    """OpenAPI declarations vs routes the code actually registers."""
    declared: dict[tuple, list] = {}
    observed: dict[tuple, list] = {}
    for claim in claims:
        if claim.kind != "http" or claim.direction != "provides":
            continue
        if claim.attrs.get("source") == "openapi":
            declared.setdefault(_positional(claim.key), []).append(claim)
        elif claim.matchable:
            observed.setdefault(_positional(claim.key), []).append(claim)

    return {
        "matched": [
            {"operation": f"{m} {t}",
             "declared": [_cite(c) for c in declared[(m, t)]],
             "observed": [_cite(c) for c in observed[(m, t)]]}
            for m, t in sorted(declared.keys() & observed.keys())],
        "declared_not_observed": [
            {"operation": f"{m} {t}",
             "declared": [_cite(c) for c in declared[(m, t)]]}
            for m, t in sorted(declared.keys() - observed.keys())],
        "observed_not_declared": [
            {"operation": f"{m} {t}",
             "observed": [_cite(c) for c in observed[(m, t)]]}
            for m, t in sorted(observed.keys() - declared.keys())],
    }


def reconcile_grpc(claims: list) -> dict:
    """Proto operations vs the server implementations that serve them.

    An implementation names only its service, so it keeps every operation
    that service declares — the binding R5 makes. Compared key for key, the
    two shapes never met and every operation of a fully served proto read as
    a promise nobody keeps.
    """
    declared = {c.key for c in claims if c.matchable
                and c.kind == "grpcop" and c.direction == "provides"}
    served = {stub_service_name(c): c.key for c in claims if c.matchable
              and c.kind == "grpcstub" and c.direction == "provides"}
    matched = {key for key in declared
               if served.keys() & set(operation_service_names(key))}
    named = {name for key in declared for name in operation_service_names(key)}
    return {
        "declared_not_observed": sorted(declared - matched),
        "observed_not_declared": sorted({key for name, key in served.items()
                                         if name not in named}),
        "matched": len(matched),
    }


def reconcile(claims: list) -> dict:
    """The full report. Sections exist even when empty — an absent section
    is indistinguishable from one never computed. Only matchable claims
    count: a dynamic topic has no name to reconcile, and printed as `""`."""
    topic_declared = {c.key for c in claims if c.kind == "topic"
                      and c.matchable and c.attrs.get("declared")}
    topic_observed = {c.key for c in claims if c.kind == "topic"
                      and c.matchable and not c.attrs.get("declared")}
    return {
        "http": reconcile_http(claims),
        "grpc": reconcile_grpc(claims),
        "topics": {
            "declared_not_observed": sorted(topic_declared - topic_observed),
            "observed_not_declared": sorted(topic_observed - topic_declared),
            "matched": len(topic_declared & topic_observed),
        },
    }
