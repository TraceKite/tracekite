"""Which resolvers run, in which phase, in which order.

Extracted from `engine.py`: the engine is the pipeline, this is the roster.
They change for different reasons — a new resolver edits this file and nothing
else, while a change to how the phases work edits the engine and leaves the
roster alone.

Order is *declared* here rather than being wherever a name happens to sit.
Until E6 a host could add a resolver but not say where it belonged, so
registering meant "last" — the one position an extension usually cannot use,
because anything that contributes state has to run before the resolvers that
read it.
"""

from evigraph.services.linker import (
    r0_alias, r1_compose, r2_k8s, r3_library, r4_gateway, r5_grpc, r6_topic,
    r7_http, r8_graphql, r9_env, r9_env_index, r10_dataset, r11_agent,
    r12_owner, r13_webhook, r14_operation,
)

# Resolvers run in two groups with NORMALIZE between them (architecture §4).
#
# BROADCAST_RESOLVERS contribute the small side tables every later phase reads:
# r2_k8s's cluster-DNS spellings and selector bindings are aliases R0 must see
# before it clusters names, and r4_gateway builds the route table NORMALIZE
# rewrites paths through. r2 emits no Service-level edges directly — those are
# queued and materialized after R0.
BROADCAST_RESOLVERS = (
    ("r2_k8s", r2_k8s),
    ("r0_alias", r0_alias),
    ("r1_compose", r1_compose),
    ("r3_library", r3_library),
    ("r4_gateway", r4_gateway),
    # The env-value index. Broadcast because R6 and R9 both read it: a table
    # written during the join is only visible to the shard that wrote it
    # (I10). Depends on nothing else here — it reads cfgdef claims only — so
    # its position within the group is free.
    ("r9_env_index", r9_env_index),
)

# JOIN_RESOLVERS run against frozen keys. Nothing here may rewrite a rendezvous
# key — that is invariant I9, and it is what lets these be partitioned by key.
JOIN_RESOLVERS = (
    ("r5_grpc", r5_grpc),
    ("r7_http", r7_http),
    ("r8_graphql", r8_graphql),
    ("r9_env", r9_env),
    ("r6_topic", r6_topic),
    ("r13_webhook", r13_webhook),
    ("r14_operation", r14_operation),
    ("r10_dataset", r10_dataset),
    ("r11_agent", r11_agent),
    # r12 runs last: Service-level OWNED_BY needs every Service minted.
    ("r12_owner", r12_owner),
)

RESOLVERS = BROADCAST_RESOLVERS + JOIN_RESOLVERS

# Precedence, declared rather than positional.
#
# The shipped resolvers' order is meaningful — r12 needs every Service minted,
# r6 needs the env index — and until now that order was wherever a name sat in
# a tuple. A host could add a resolver but not say where it belonged, so
# registration meant "last", which is the one position an extension usually
# cannot use.
#
# Spaced by ten so a host has somewhere to stand between any two.
SHIPPED_PRECEDENCE = {
    name: (index + 1) * 10
    for index, (name, _module) in enumerate(BROADCAST_RESOLVERS + JOIN_RESOLVERS)
}

# Resolvers a host registered at runtime. Held apart from the built-in
# tuples so `RESOLVERS` stays the shipped set and a host extension is always
# identifiable as one.
_REGISTERED_BROADCAST: list[tuple[int, str, object]] = []
_REGISTERED_JOIN: list[tuple[int, str, object]] = []

# Registrations with no stated precedence run after everything shipped, in the
# order they were registered. Counting up keeps that order stable rather than
# leaving it to a sort over equal keys.
_APPENDED = 10_000


def register_resolver(name: str, module, *, phase: str = "join",
                      precedence: int | None = None) -> None:
    """Add a join rule without forking, at a chosen precedence.

    `phase` is not a formality. A BROADCAST resolver may write the side tables
    later phases read; a JOIN resolver runs against frozen keys and may not
    alter one — that is invariant I9, and it is what lets the join be
    partitioned at all. LinkContext raises if a JOIN resolver rewrites a key,
    so a host that picks the wrong phase finds out loudly rather than losing
    edges to a shard that was never told about them.

    `precedence` places the resolver among the shipped ones — see
    `SHIPPED_PRECEDENCE` for what to slot between. Omitted, it runs last,
    which is right for an observer and wrong for anything later resolvers must
    see.

    Decline discipline is enforced by naming, not by trust: a registered
    resolver's counters are namespaced under its own name, so its declines are
    attributable and an operator can see which extension is dropping what.
    """
    global _APPENDED
    if phase not in ("broadcast", "join"):
        raise ValueError(f"phase must be 'broadcast' or 'join', got {phase!r}")
    if not hasattr(module, "resolve"):
        raise TypeError(
            f"resolver {name!r} has no resolve(index, ctx); it would be "
            "skipped silently at link time, which is the one thing a "
            "registration must not allow")
    if any(name == existing for _p, existing, _m in
           _REGISTERED_BROADCAST + _REGISTERED_JOIN):
        raise ValueError(
            f"resolver {name!r} is already registered; two resolvers under "
            "one name make their counters indistinguishable")

    if precedence is None:
        _APPENDED += 1
        precedence = _APPENDED
    target = (_REGISTERED_BROADCAST if phase == "broadcast"
              else _REGISTERED_JOIN)
    target.append((precedence, name, module))


def resolver_order(phase: str) -> list[tuple[str, object]]:
    """The declared order for one phase, shipped and registered together.

    Sorted on (precedence, name): a host that registers at the same precedence
    as another gets a stable order rather than one that depends on which
    import ran first — which is the whole of what E6 removes.
    """
    shipped = BROADCAST_RESOLVERS if phase == "broadcast" else JOIN_RESOLVERS
    registered = (_REGISTERED_BROADCAST if phase == "broadcast"
                  else _REGISTERED_JOIN)
    entries = [(SHIPPED_PRECEDENCE[name], name, module)
               for name, module in shipped] + list(registered)
    return [(name, module) for _p, name, module in sorted(entries)]


def declared_order() -> list[dict]:
    """Every resolver, its phase and its precedence — queryable."""
    out = []
    for phase in ("broadcast", "join"):
        for name, _module in resolver_order(phase):
            out.append({"name": name, "phase": phase,
                        "precedence": SHIPPED_PRECEDENCE.get(name)
                        or _precedence_of(name, phase),
                        "shipped": name in SHIPPED_PRECEDENCE})
    return out


def _precedence_of(name: str, phase: str) -> int:
    registered = (_REGISTERED_BROADCAST if phase == "broadcast"
                  else _REGISTERED_JOIN)
    return next(p for p, n, _m in registered if n == name)


def registered_resolvers() -> dict[str, list[str]]:
    """What a host has registered, so a run can report who took part."""
    return {"broadcast": [n for _p, n, _m in _REGISTERED_BROADCAST],
            "join": [n for _p, n, _m in _REGISTERED_JOIN]}


def clear_registered_resolvers() -> None:
    """Drop host registrations. For tests; the app never calls this."""
    _REGISTERED_BROADCAST.clear()
    _REGISTERED_JOIN.clear()
