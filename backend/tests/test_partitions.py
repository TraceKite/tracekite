"""The skew guard: hot keys detected and split, no single-worker tail.

The property under test is the exit criterion itself: with a key holding
half the estate, four workers must not degenerate into one worker doing
half the work. Correctness of the split rests on the join being a product —
every (provider, consumer) pair of a split key must still meet in exactly
one sub-shard, which is what the coverage tests pin.
"""

from evigraph.services.linker.base import ClaimRecord
from evigraph.services.linker.partitions import (
    REPLICATION_CAP, Plan, hot_key_sizes, plan,
)


def claim(cid, key, direction="consumes", matchable=True):
    return ClaimRecord(
        id=cid, repo_id=f"repo_{cid}", kind="http", direction=direction,
        key=key, service_hint=None, hint_source="none", matchable=matchable,
        evidence=[f"src/{cid}.py:1"], attrs={}, evidence_node_id=None,
        evidence_node_type="")


def hot_estate(consumers=200, cold_keys=200):
    """One provider with `consumers` callers, plus uniform background."""
    claims = [claim("p0", "hot", direction="provides")]
    claims += [claim(f"c{i:04d}", "hot") for i in range(consumers)]
    claims += [claim(f"k{i:04d}", f"cold-{i}") for i in range(cold_keys)]
    return claims


class TestDetection:
    def test_a_key_over_the_fair_share_is_hot(self):
        sizes = hot_key_sizes(hot_estate(), workers=4)
        assert list(sizes) == ["hot"]
        assert sizes["hot"] == 201

    def test_a_uniform_estate_has_no_hot_keys(self):
        claims = [claim(f"c{i}", f"key-{i % 50}") for i in range(200)]
        assert hot_key_sizes(claims, workers=4) == {}

    def test_unmatchable_claims_do_not_count(self):
        claims = [claim(f"c{i}", "k", matchable=False) for i in range(50)]
        assert hot_key_sizes(claims, workers=4) == {}

    def test_every_link_run_reports_skew(self):
        """Detection is live in the engine, not only in tools: a production
        estate must be able to say its own shard-limiting key exists."""
        from evigraph.services.linker.engine import link

        result = link(hot_estate(consumers=40, cold_keys=2),
                      run_id="linkrun_skew", confidence={}, aliases={},
                      promotions=[], now="2026-01-01T00:00:00+00:00")
        assert result.counters["skew.hot_keys"] == 1
        assert result.counters["skew.largest_hot_key_claims"] == 41
        # Zero is reported as zero, not as absence.
        quiet = link([claim("c1", "a"), claim("c2", "b")],
                     run_id="linkrun_quiet", confidence={}, aliases={},
                     promotions=[], now="2026-01-01T00:00:00+00:00")
        assert quiet.counters["skew.hot_keys"] == 0


class TestNoSingleWorkerTail:
    def test_the_hot_key_is_split_and_the_tail_is_gone(self):
        """The exit criterion. Unsplit, the hot key's 201 claims of 401
        total give 4 workers a tail_ratio of ~2.0 — one worker does half
        the estate. Split, no partition may exceed a fair share by much."""
        result = plan(hot_estate(), workers=4)
        assert "hot" in result.hot_keys
        naive_tail = 201 / (result.total_claims / 4)
        assert naive_tail > 1.9
        assert result.tail_ratio < 1.3, (
            f"tail_ratio {result.tail_ratio}: a worker still carries a "
            "disproportionate shard")

    def test_a_uniform_estate_packs_evenly_without_splitting(self):
        claims = [claim(f"c{i}", f"key-{i % 40}") for i in range(200)]
        result = plan(claims, workers=4)
        assert result.hot_keys == []
        assert result.tail_ratio < 1.2

    def test_one_worker_never_splits(self):
        result = plan(hot_estate(), workers=1)
        assert result.hot_keys == []
        assert len(result.partitions) == 1


class TestSplitCorrectness:
    def _shards_of(self, result: Plan, key: str):
        return [s for p in result.partitions for s in p if s.key == key]

    def test_every_pair_of_a_split_key_meets_exactly_once(self):
        """The join is providers x consumers. Each consumer chunk carries
        the full provider side, so a pair meets in the one sub-shard
        holding that consumer — never zero times, never twice."""
        result = plan(hot_estate(), workers=4)
        shards = self._shards_of(result, "hot")
        assert len(shards) > 1

        consumers = [cid for s in shards for cid in s.claim_ids
                     if cid != "p0"]
        assert sorted(consumers) == [f"c{i:04d}" for i in range(200)]
        assert len(set(consumers)) == len(consumers), "a consumer met twice"
        for shard in shards:
            assert "p0" in shard.claim_ids + shard.replicated_ids, (
                "a consumer chunk lost the provider side: those pairs "
                "silently never meet — the exact failure I9/B13 exist "
                "to prevent")

    def test_cold_keys_are_never_split(self):
        result = plan(hot_estate(), workers=4)
        for key in ("cold-0", "cold-1"):
            assert len(self._shards_of(result, key)) == 1

    def test_a_key_with_both_sides_huge_declines_and_is_named(self):
        """Replicating hundreds of claims per sub-shard costs more than the
        skew it removes. Packed whole and NAMED — a quiet tail is the
        failure mode this module exists against."""
        big = REPLICATION_CAP + 10
        claims = ([claim(f"p{i:03d}", "wide", direction="provides")
                   for i in range(big)]
                  + [claim(f"c{i:03d}", "wide") for i in range(big)]
                  + [claim(f"k{i}", f"cold-{i}") for i in range(20)])
        result = plan(claims, workers=4)
        assert result.unsplittable == ["wide"]
        assert len(self._shards_of(result, "wide")) == 1

    def test_the_plan_is_deterministic(self):
        first, second = plan(hot_estate(), 4), plan(hot_estate(), 4)
        assert [[(s.key, s.claim_ids, s.replicated_ids) for s in p]
                for p in first.partitions] \
            == [[(s.key, s.claim_ids, s.replicated_ids) for s in p]
                for p in second.partitions]

    def test_an_empty_estate_plans_nothing(self):
        result = plan([], workers=4)
        assert result.partitions == [] and result.tail_ratio == 0.0
