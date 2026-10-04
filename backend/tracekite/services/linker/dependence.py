"""Which edges mean their source depends on their target.

"Who depends on X" is asked through MCP ``consumers_of`` and
``history --consumers-of``. Provider and bookkeeping edges are not dependence. Counting
them, one gRPC operation in opentelemetry-demo reported sixteen dependents
where four files call it and four implement it.
Unknown edge types decline by default. A blacklist silently starts calling a
new provider or bookkeeping edge a consumer before anyone reviews its meaning.
"""

DEPENDENCE_TYPES = frozenset({
    "BUILT_FROM", "CALLS_SERVICE", "CONSUMES_FROM", "DEPENDS_ON",
    "DEPENDS_ON_REPO", "EXPOSES", "INVOKES", "PUBLISHES_TO", "READS_FROM",
    "REGISTERS_WEBHOOK", "ROUTES_TO", "UI_CALLS", "WRITES_TO",
})


def is_dependence(edge) -> bool:
    return edge.type in DEPENDENCE_TYPES
