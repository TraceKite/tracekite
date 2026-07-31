"""I8: broadcast side tables stay O(services + rules), never O(claims).

One of the two load-bearing invariants. Every resolver that needs global
context reads a side table — `service_by_name`, `rewrite_routes`,
`env_values` — and those tables are *replicated to every worker* when the
join is sharded. Bounded by services and rules they are a few megabytes at a
thousand repositories. Proportional to claims, they are not, and the estate
stops sharding: the moment one goes claim-proportional, Phase 2 becomes
unbuildable and nothing says so at the time.

The test holds the topology fixed and multiplies the claims. A table that
grows with the second number and not the first has broken the invariant.
"""

import pytest

from adduce.services.linker.base import ClaimIndex, ClaimRecord, LinkContext
from adduce.services.linker.engine import run_resolvers

# Queues, not side tables: drained into edges within the run rather than
# broadcast to workers, so claim-proportional is correct for them.
QUEUES = {"pending_calls", "pending_gitops"}
# Bounded by the number of distinct counter names, not by their values.
NOT_A_TABLE = {"counters", "confidence", "known_repos"}
# NORMALIZE output is one entry per call site and shards like MAP — it is
# per-claim data, never broadcast, so claim-proportional is correct for it.
# Named explicitly because it happens to be empty in this fixture, and a
# silently-passing exclusion is worth no more than a silently-passing test.
PER_CLAIM = {"_normalized_calls"}


def claim(cid, repo, kind, direction, key, **kw):
    return ClaimRecord(
        id=cid, repo_id=repo, kind=kind, direction=direction, key=key,
        service_hint=kw.get("hint"), hint_source=kw.get("src", "none"),
        matchable=True, evidence=[kw.get("ev", "f.yml:1")], attrs={},
        evidence_node_id=kw.get("node", f"n{cid}"), evidence_node_type="File")


def estate(http_claims: int):
    """Two services and one endpoint, with `http_claims` call sites on it.

    Only the claim count varies. Services, routes and config are identical
    between runs, so any table that grows is growing with claims.
    """
    claims = [
        claim("s1", "repo_a", "svcname", "provides", "compose:billing",
              hint="billing", src="compose"),
        claim("s2", "repo_b", "svcname", "provides", "compose:orders",
              hint="orders", src="compose"),
        claim("r1", "repo_a", "route", "provides", "GET /v1/invoices",
              hint="billing", src="compose"),
    ]
    claims += [
        claim(f"h{i}", "repo_b", "http", "consumes", "GET /v1/invoices",
              hint="orders", src="compose", ev=f"src/client{i}.py:{i}")
        for i in range(http_claims)
    ]
    return claims


def table_sizes(claims) -> dict[str, int]:
    ctx = LinkContext("linkrun_i8", {}, {})
    ctx.known_repos = {"repo_a", "repo_b"}
    run_resolvers(ClaimIndex(claims), ctx)
    return {
        name: len(value)
        for name, value in vars(ctx).items()
        if isinstance(value, (dict, set, list))
        and name not in QUEUES and name not in NOT_A_TABLE
        and name not in PER_CLAIM
    }


class TestSideTablesAreNotClaimProportional:
    @pytest.fixture(scope="class")
    def measured(self):
        return table_sizes(estate(10)), table_sizes(estate(200))

    def test_no_table_grows_with_claim_count(self, measured):
        small, large = measured
        grew = {name: (small[name], large[name])
                for name in small if large[name] > small[name]}
        assert not grew, (
            f"side table(s) grew with claim count, breaking I8: {grew}. "
            "A table replicated to every worker must be bounded by services "
            "and rules, or the estate cannot be sharded.")

    def test_the_measurement_covers_the_real_tables(self, measured):
        """Guard the guard: if the tables were renamed away, every assertion
        above would pass over an empty dict."""
        small, _ = measured
        assert {"service_by_name", "rewrite_routes",
                "env_values"} <= set(small), sorted(small)

    def test_claims_really_did_scale(self):
        """And the input actually differed, or nothing was tested."""
        assert len(estate(200)) > len(estate(10)) * 5
