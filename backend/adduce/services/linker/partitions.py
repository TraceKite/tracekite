"""REDUCE partitions with a skew guard on hot rendezvous keys.

REDUCE partitions by key, so the largest key bounds the smallest possible
wall-clock: one contract with 800 consumers serialises its shard no matter
how many workers exist. This plans the partitions so that cannot happen —
a hot key is *split*, its consumers chunked across sub-shards with the
(small) provider side replicated to each, exactly the way broadcast tables
are already replicated.

Operator's decision (2026-07-29): built ahead of the parallel REDUCE that
will consume it. The join measures 0.19s at 16.5K claims, so no pool is
attached today; the plan is exercised live by claim-level invalidation,
reported by `estate_probe`, and its no-tail property is pinned here
so the pool, when a measurement justifies one, inherits a guard that
already works.

The split is safe because keys are final before the join (I9) and no join
resolver reads another's tables (I10, enforced): the join for key K is
providers(K) x consumers(K), so any partition holding all of one side and
a chunk of the other computes exactly its chunk of the product.
"""

from dataclasses import dataclass, field

# A key whose smaller side exceeds this is not split: replicating hundreds
# of claims to every sub-shard costs more than the skew it removes. Counted
# in the plan rather than silently packed, so a pathological key is a
# visible finding, not a quiet tail.
REPLICATION_CAP = 64


@dataclass(frozen=True)
class Shard:
    """One unit of REDUCE work: a key (or a slice of one)."""

    key: str
    claim_ids: tuple[str, ...]
    # Claims present in other shards of the same key — the replicated side
    # of a split. Deliberate duplication, and counted as such.
    replicated_ids: tuple[str, ...] = ()

    @property
    def weight(self) -> int:
        return len(self.claim_ids) + len(self.replicated_ids)


@dataclass
class Plan:
    """Partitions for `workers`, plus what the guard did and declined."""

    partitions: list[list[Shard]] = field(default_factory=list)
    hot_keys: list[str] = field(default_factory=list)
    unsplittable: list[str] = field(default_factory=list)
    total_claims: int = 0
    replicated_claims: int = 0

    @property
    def tail_ratio(self) -> float:
        """Largest partition over the perfect share — 1.0 is ideal.

        The number the exit criterion is about: without the guard, a key
        holding half the claims gives four workers a tail_ratio of 2.0 —
        one worker does half the estate while three idle.
        """
        if not self.partitions or not self.total_claims:
            return 0.0
        largest = max(sum(s.weight for s in p) for p in self.partitions)
        return largest / (self.total_claims / len(self.partitions))


def hot_key_sizes(claims, workers: int) -> dict[str, int]:
    """Every key too big for one worker's fair share of the estate."""
    sizes: dict[str, int] = {}
    for claim in claims:
        if getattr(claim, "matchable", True) and claim.key:
            sizes[claim.key] = sizes.get(claim.key, 0) + 1
    if not sizes or workers <= 1:
        return {}
    fair = max(1, len(claims) // workers)
    return {key: count for key, count in sorted(sizes.items())
            if count > fair}


def plan(claims, workers: int) -> Plan:
    """Partition matchable claims by key, splitting the hot ones.

    Deterministic: same claims, same worker count, same plan — a plan that
    shifted between runs would make every incremental reuse a cache
    miss and every measurement incomparable.
    """
    by_key: dict[str, list] = {}
    for claim in claims:
        if getattr(claim, "matchable", True) and claim.key:
            by_key.setdefault(claim.key, []).append(claim)

    result = Plan(total_claims=sum(len(v) for v in by_key.values()))
    if not by_key or workers <= 0:
        return result

    fair = max(1, result.total_claims // max(workers, 1))
    shards: list[Shard] = []
    for key in sorted(by_key):
        group = sorted(by_key[key], key=lambda c: c.id)
        if len(group) <= fair or workers == 1:
            shards.append(Shard(key, tuple(c.id for c in group)))
            continue

        result.hot_keys.append(key)
        provides = [c for c in group if c.direction == "provides"]
        consumes = [c for c in group if c.direction != "provides"]
        # Chunk the larger side; replicate the smaller. The join is a
        # product, so every (provider, consumer) pair still meets exactly
        # once — in the one sub-shard holding that chunk.
        small, large = sorted((provides, consumes), key=len)
        if len(small) > REPLICATION_CAP:
            # Splitting would replicate more than it saves. Packed whole,
            # named, and visible — a quiet tail is the failure mode.
            result.unsplittable.append(key)
            shards.append(Shard(key, tuple(c.id for c in group)))
            continue

        chunk_size = max(1, fair - len(small))
        replicated = tuple(c.id for c in small)
        for start in range(0, len(large), chunk_size):
            chunk = large[start:start + chunk_size]
            shards.append(Shard(key, tuple(c.id for c in chunk), replicated))
            result.replicated_claims += len(small) if start else 0

    # LPT: heaviest shard into the lightest partition. Ties on key so the
    # packing cannot depend on dict order.
    result.partitions = [[] for _ in range(workers)]
    loads = [0] * workers
    for shard in sorted(shards, key=lambda s: (-s.weight, s.key,
                                               s.claim_ids)):
        target = loads.index(min(loads))
        result.partitions[target].append(shard)
        loads[target] += shard.weight
    result.partitions = [p for p in result.partitions if p]
    return result
