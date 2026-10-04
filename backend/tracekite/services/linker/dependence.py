"""Which edges mean their source depends on their target.

"Who depends on X" is asked through MCP `consumers_of` and `history
--consumers-of`. Two kinds of in-edge are not dependence: a claim's
RESOLVED_TO, bookkeeping that duplicates the file- or service-level edge
beside it, and DECLARES_CONTRACT / DECLARES_TOPIC, which are the target's
own definition. Counting them, one gRPC operation in opentelemetry-demo
reported sixteen dependents where four files call it and four implement it.
"""

NOT_DEPENDENCE = frozenset({"RESOLVED_TO", "DECLARES_CONTRACT", "DECLARES_TOPIC"})


def is_dependence(edge) -> bool:
    return edge.type not in NOT_DEPENDENCE
