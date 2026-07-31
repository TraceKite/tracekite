"""Lifecycle hooks and declared resolver order.

Both are the extensibility surface A7 opened: a host can add a resolver, and
now it can say where the resolver runs and watch what the shipped ones do.
The failure mode for each is silence — a hook that never fires, a resolver
registered into a position that cannot see what it needs — so the tests are
mostly about what is *reported*.
"""

import pytest

from adduce.services.linker import hooks
from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput,
)
from adduce.services.linker.engine import (
    SHIPPED_PRECEDENCE, clear_registered_resolvers, declared_order,
    link, register_resolver, resolver_order, run_resolvers,
)


def claim(cid, repo, key, hint):
    return ClaimRecord(
        id=cid, repo_id=repo, kind="svcname", direction="provides", key=key,
        service_hint=hint, hint_source="compose", matchable=True,
        evidence=["docker-compose.yml:1"], attrs={},
        evidence_node_id=None, evidence_node_type="File")


CLAIMS = [claim("c1", "repo_a", "compose:billing", "billing"),
          claim("c2", "repo_b", "compose:orders", "orders")]


def run():
    return link(CLAIMS, run_id="linkrun_hooks", confidence={}, aliases={},
                promotions=[], now="2026-01-01T00:00:00+00:00")


@pytest.fixture(autouse=True)
def clean():
    clear_registered_resolvers()
    hooks.clear_hooks()
    yield
    clear_registered_resolvers()
    hooks.clear_hooks()


class Recorder:
    def __init__(self):
        self.before, self.after, self.declines = [], [], []

    def pre_resolve(self, name, index, ctx):
        self.before.append(name)

    def post_resolve(self, name, output, ctx):
        self.after.append((name, len(output.edges)))

    def on_decline(self, counter, n, ctx):
        self.declines.append((counter, n))


class TestHooksFire:
    def test_every_resolver_is_announced_and_reported(self):
        recorder = Recorder()
        hooks.register_hook(recorder)
        run()
        assert recorder.before
        assert [n for n in recorder.before] == [n for n, _ in recorder.after]

    def test_declines_reach_the_host(self):
        recorder = Recorder()
        hooks.register_hook(recorder)
        run()
        assert recorder.declines
        assert any(name.startswith("r0.") or name == "claims_loaded"
                   for name, _n in recorder.declines)

    def test_a_hook_with_no_known_method_is_refused(self):
        """Registering something that can never be called is the silent
        no-op a registration must not allow."""
        with pytest.raises(TypeError, match="implements none"):
            hooks.register_hook(object())

    def test_a_failing_hook_does_not_fail_the_run(self, caplog):
        class Broken:
            def pre_resolve(self, name, index, ctx):
                raise RuntimeError("host bug")

        hooks.register_hook(Broken())
        assert run().edges is not None
        assert any("hook" in r.getMessage() for r in caplog.records)


class TestHooksCanVeto:
    def _suppressing_hook(self):
        class Suppress:
            def post_resolve(self, name, output, ctx):
                if not output.edges:
                    return None
                trimmed = ResolverOutput()
                trimmed.rendezvous = output.rendezvous
                trimmed.services = output.services
                trimmed.edges = output.edges[:-1]
                return trimmed
        return Suppress()

    def test_a_hook_can_remove_an_edge(self):
        """A8's exit criterion: the hook fires and the edge is gone."""
        before = len(run().edges)
        hooks.register_hook(self._suppressing_hook())
        after = run()
        assert len(after.edges) < before

    def test_suppression_is_counted_not_silent(self):
        """An edge that vanished with no record is indistinguishable from one
        that was never found."""
        hooks.register_hook(self._suppressing_hook())
        assert run().counters.get("hook.suppressed_edges", 0) > 0

    def test_a_hook_may_not_invent_an_edge(self):
        """Edges carry file:line on both sides because a resolver put them
        there. One arriving from a host has nothing behind it."""
        class Inventor:
            def post_resolve(self, name, output, ctx):
                bigger = ResolverOutput()
                bigger.rendezvous = output.rendezvous
                bigger.services = output.services
                bigger.edges = list(output.edges) + ["not-an-edge"]
                return bigger

        hooks.register_hook(Inventor())
        result = run()
        assert result.counters.get("hook.rejected_additions", 0) > 0
        assert all(not isinstance(e, str) for e in result.edges)

    def test_counting_inside_a_hook_does_not_recurse(self):
        """`on_decline` fires from `ctx.count`, and suppression counts."""
        class Counter:
            def on_decline(self, counter, n, ctx):
                ctx.count("host.saw_a_decline")

        hooks.register_hook(Counter())
        assert run().counters["host.saw_a_decline"] > 0


class FakeResolver:
    def resolve(self, index, ctx):
        ctx.count("fake.ran")
        return ResolverOutput()


class TestDeclaredOrder:
    def test_the_shipped_order_is_unchanged_by_being_declared(self):
        """E6 makes the order explicit; it must not make it different."""
        assert [n for n, _m in resolver_order("broadcast")] == [
            "r2_k8s", "r0_alias", "r1_compose", "r3_library", "r4_gateway",
            "r9_env_index"]
        assert [n for n, _m in resolver_order("join")] == [
            "r5_grpc", "r7_http", "r8_graphql", "r9_env", "r6_topic",
            "r13_webhook", "r14_operation", "r10_dataset", "r11_agent",
            "r12_owner"]

    def test_a_host_can_run_before_a_shipped_resolver(self):
        """The capability E6 adds. Registration used to mean 'last', which is
        the one position a resolver contributing state cannot use."""
        register_resolver("r_early", FakeResolver(), phase="join",
                          precedence=SHIPPED_PRECEDENCE["r7_http"] - 1)
        order = [n for n, _m in resolver_order("join")]
        assert order.index("r_early") < order.index("r7_http")

    def test_registration_without_a_precedence_runs_last(self):
        register_resolver("r_late", FakeResolver(), phase="join")
        assert [n for n, _m in resolver_order("join")][-1] == "r_late"

    def test_equal_precedence_is_ordered_by_name_not_import(self):
        """Two hosts registering at the same precedence must not depend on
        which import ran first — that is exactly what E6 removes."""
        register_resolver("r_zebra", FakeResolver(), phase="join",
                          precedence=500)
        register_resolver("r_alpha", FakeResolver(), phase="join",
                          precedence=500)
        order = [n for n, _m in resolver_order("join")]
        assert order.index("r_alpha") < order.index("r_zebra")

    def test_the_order_is_queryable_with_its_precedence(self):
        register_resolver("r_extra", FakeResolver(), phase="join",
                          precedence=75)
        rows = {row["name"]: row for row in declared_order()}
        assert rows["r_extra"] == {"name": "r_extra", "phase": "join",
                                   "precedence": 75, "shipped": False}
        assert rows["r7_http"]["shipped"] is True
        assert rows["r2_k8s"]["phase"] == "broadcast"

    def test_a_registered_resolver_actually_runs_in_its_slot(self):
        register_resolver("r_slotted", FakeResolver(), phase="broadcast",
                          precedence=5)
        ctx = LinkContext("linkrun_order", {}, {})
        run_resolvers(ClaimIndex(CLAIMS), ctx)
        assert ctx.counters["fake.ran"] == 1
        assert ctx.counters["registered.r_slotted"] == 1
