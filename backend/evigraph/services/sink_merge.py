"""Fold chunk sinks back into one repository's sink.

A sharded scan parses a repository's files in slices, each slice into its
own `IngestSink`, in its own process. This puts them back together so the
result is indistinguishable from the serial scan — which is not a nicety:
artifacts are content-addressed, and a merge that reordered a node or
double-counted a file would give the same repository two digests depending
on how many workers scanned it, breaking reuse and every diff.

Ordering discipline: chunks are contiguous slices of the ordered file list,
merged in slice order, so the concatenated nodes and edges are the exact
sequence the serial loop would have appended.
"""

from evigraph.services.ingest_source import IngestSink

# Every numeric coverage field is summed; `tier` is ordered and upgraded.
# Derived from the shape `IngestSink.lang()` initialises rather than listed
# by hand, so a new counter field cannot be silently dropped by the merge.
_TIER_FIELD = "tier"


def merge_chunk(target: IngestSink, chunk: IngestSink) -> None:
    """Fold one chunk's output into the target, in order.

    `add_node` re-checks identity, so a node minted by two chunks — nothing
    produces one today, but the artifact's primary key makes duplicates a
    corruption, not a wart — collapses instead of doubling.
    """
    for node in chunk.nodes:
        target.add_node(node)
    target.edges.extend(chunk.edges)
    target.parse_context.update(chunk.parse_context)

    for kind, count in chunk.claims.items():
        target.claims[kind] = target.claims.get(kind, 0) + count
    for reason, count in chunk.capped.items():
        target.capped[reason] = target.capped.get(reason, 0) + count

    for language, counters in chunk.coverage.items():
        merged = target.lang(language)
        for field, value in counters.items():
            if field == _TIER_FIELD:
                target.upgrade_tier(language, value)
            else:
                merged[field] = merged.get(field, 0) + value


def merge_chunks(structure: IngestSink, chunks: list[IngestSink]) -> IngestSink:
    """Structure first, then every chunk in slice order."""
    for chunk in chunks:
        merge_chunk(structure, chunk)
    return structure
