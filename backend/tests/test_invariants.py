"""Architecture §6 invariants, enforced rather than documented.

"Violating any of these is a defect, not a trade-off." A rule that only exists
in prose degrades silently — the whole reason A11 exists for the layering
rule. These do the same for the invariants that are mechanically checkable.

Covered here: I3 (locality), I5 (decline discipline), I6 (evidence
completeness), I7 (run immutability). I8 has its own file because it needs a
scaling fixture; I9 is pinned by the NORMALIZE tests; I1 by the determinism
tests; I2 by the layering and purity checks.

I4 (one canonicaliser) and I10 (shard independence) are structural claims
about how resolvers are written rather than properties of one run's output, so
they are checked by `backend/tools/check_invariants.py` and driven from here.
"""

import pytest

from evigraph import engine_config
from evigraph.db.memory_store import InMemoryLinkerStore
from evigraph.services.linker.engine import link
from evigraph.services.scan import scan

import os

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE = os.path.join(FIXTURES, "callgraph-sample")
PLANTED = os.path.join(FIXTURES, "planted-secret")
RUN_ID = "linkrun_invariants"


@pytest.fixture(scope="module")
def linked():
    engine_config.configure(graph_hmac_key="invariants-test-key")
    store = InMemoryLinkerStore([scan(SAMPLE, "repo_a"), scan(PLANTED, "repo_b")])
    result = link(store.load_claims(), run_id=RUN_ID,
                  now="2026-01-01T00:00:00+00:00")
    assert result.edges, "fixtures must produce edges for these to mean anything"
    return store, result


class TestI3Locality:
    """A claim is derived from exactly one repository."""

    def test_a_scan_attributes_every_claim_to_the_repo_scanned(self):
        engine_config.configure(graph_hmac_key="invariants-test-key")
        store = InMemoryLinkerStore([scan(SAMPLE, "only_this_repo")])
        claims = store.load_claims()
        assert claims
        assert {c.repo_id for c in claims} == {"only_this_repo"}

    def test_no_claim_is_attributed_to_nothing(self, linked):
        store, _ = linked
        assert all(c.repo_id for c in store.load_claims())

    def test_scanning_two_repos_keeps_their_claims_apart(self, linked):
        """MAP shards by file; a claim carrying the wrong repo would be
        resolved against the wrong source and dead-link its evidence."""
        store, _ = linked
        assert {c.repo_id for c in store.load_claims()} <= {"repo_a", "repo_b"}


class TestI5DeclineDiscipline:
    """Every unresolved claim increments a named counter."""

    def test_declines_are_counted(self, linked):
        _, result = linked
        assert result.counters, "a run that declined nothing and said nothing"

    def test_every_counter_is_named_not_anonymous(self, linked):
        _, result = linked
        for name in result.counters:
            assert name and not name.isdigit(), name


class TestI6EvidenceCompleteness:
    """Every edge cites file and line."""

    def test_no_edge_lacks_evidence(self, linked):
        _, result = linked
        missing = [(e.type, e.source_id) for e in result.edges if not e.evidence]
        assert not missing, missing

    def test_evidence_is_file_and_line_not_a_bare_path(self, linked):
        _, result = linked
        for edge in result.edges:
            for citation in edge.evidence:
                assert ":" in citation, (edge.type, citation)


class TestI7RunImmutability:
    """Every edge is attributed to exactly one run."""

    def test_every_edge_carries_the_run_that_made_it(self, linked):
        _, result = linked
        orphans = [e.type for e in result.edges if not e.link_run_id]
        assert not orphans, (
            f"edges with no run: {set(orphans)} — an edge nobody can attribute "
            "to a run cannot be superseded or rolled back")

    def test_all_edges_belong_to_this_run_and_no_other(self, linked):
        _, result = linked
        assert {e.link_run_id for e in result.edges} == {RUN_ID}

    def test_a_second_run_stamps_its_own_id(self):
        """Two runs must be distinguishable, or delete-old-after cannot tell
        which edges are stale."""
        engine_config.configure(graph_hmac_key="invariants-test-key")
        store = InMemoryLinkerStore([scan(SAMPLE, "repo_a")])
        first = link(store.load_claims(), run_id="run_one", now="2026-01-01T00:00:00+00:00")
        second = link(store.load_claims(), run_id="run_two", now="2026-01-01T00:00:00+00:00")
        assert {e.link_run_id for e in first.edges} == {"run_one"}
        assert {e.link_run_id for e in second.edges} == {"run_two"}


class TestServerDoesNotCompute:
    """"The server may orchestrate; it may not compute."

    Anything that derives a fact about the graph must live below the store
    layer, or a library host gets a different answer from an app user — or,
    more likely, writes its own copy and drifts. `module_of` sat in
    `routes/links.py` until it was moved.
    """

    def test_module_boundary_is_computable_without_the_server(self):
        from evigraph.services.linker.modules import module_of

        assert module_of("projects/foyer/src/main.py") == "projects/foyer"
        assert module_of("billing/app.py") == "billing"
        assert module_of("") == ""

    def test_the_server_uses_the_core_implementation(self):
        """Not a second copy that agrees today and drifts tomorrow. The
        route no longer touches the primitive at all — it calls the
        crossings assembly, which is where the module-boundary decision
        lives now."""
        from evigraph.services.linker import crossings, modules

        assert crossings.module_of is modules.module_of
        import evigraph.routes.links as links
        assert not hasattr(links, "module_of")

    def test_a_container_directory_is_not_itself_a_module(self):
        """`src/` holds modules; it is not one. Treating it as a module would
        collapse every file in a repo into one boundary."""
        from evigraph.services.linker.modules import module_of

        assert module_of("src/billing/handler.go") == "src/billing"

    def test_a_root_level_file_belongs_to_no_module(self):
        """It has no directory to belong to. Returning its own name mints
        `Module:config.properties` — a file wearing a module's label, which
        is only harmless while nothing queries it."""
        from evigraph.services.linker.modules import module_of

        assert module_of("config.properties") == ""
        assert module_of("README.md") == ""

    def test_a_container_holding_only_a_file_is_not_a_module_path(self):
        from evigraph.services.linker.modules import module_of

        assert module_of("src/main.py") == "src"
        assert module_of("projects/foyer/main.py") == "projects/foyer"


class TestCardinality:
    """Fan-in and fan-out on every contract.

    A contract with forty consumers is not the risk of one with a single
    consumer. Blast radius is the question this tool exists to answer, and it
    is a number — until now the graph could not tell the two apart.
    """

    def _annotated(self, edges, node_ids):
        from evigraph.services.linker.base import RendezvousSpec
        from evigraph.services.linker.engine import annotate_cardinality

        specs = [RendezvousSpec("HttpContract", nid, {}) for nid in node_ids]
        annotate_cardinality(specs, edges)
        return {s.node_id: s.props for s in specs}

    def _edge(self, src, dst, status="active"):
        from evigraph.models.graph_models import GraphEdge

        e = GraphEdge(source_id=src, target_id=dst, repo_id="r",
                      type="CALLS_SERVICE", evidence=["f:1"],
                      detected_by="resolver.test@1")
        e.status = status
        return e

    def test_fan_in_counts_consumers(self, linked=None):
        props = self._annotated(
            [self._edge("a", "c"), self._edge("b", "c")], ["c"])
        assert props["c"]["fan_in"] == 2

    def test_fan_out_counts_the_other_direction(self):
        props = self._annotated(
            [self._edge("c", "x"), self._edge("c", "y")], ["c"])
        assert props["c"]["fan_out"] == 2

    def test_distinct_counterparties_not_edge_count(self):
        """Two resolvers corroborating the same consumer must not report a
        fan-in of two — overstating blast radius is the direction that
        misleads someone deciding whether a change is safe."""
        props = self._annotated(
            [self._edge("a", "c"), self._edge("a", "c")], ["c"])
        assert props["c"]["fan_in"] == 1

    def test_candidates_do_not_inflate_the_number(self):
        """Sub-floor edges are excluded from default answers, so counting
        them here would inflate a figure people act on."""
        props = self._annotated(
            [self._edge("a", "c"), self._edge("b", "c", status="candidate")],
            ["c"])
        assert props["c"]["fan_in"] == 1

    def test_an_unreferenced_contract_reports_zero_not_absent(self):
        """Absent would be indistinguishable from 'not computed'."""
        props = self._annotated([], ["lonely"])
        assert props["lonely"] == {"fan_in": 0, "fan_out": 0}


class TestI4KeyDiscipline:
    """Rendezvous keys come from one canonicaliser.

    A second one does not raise. It produces keys in a slightly different
    format, the claims that use it never meet their counterparts, and recall
    drops with nothing to point at.
    """

    TEMPLATES = ["/users/{id}", "/users/:id", "/users/<int:id>", "/v1/a/{}/b",
                 "/", "/orders/{orderId}/items/{itemId}", "/static/*"]

    def test_positional_agrees_with_the_canonicaliser(self):
        """`base.positional` is the second declared implementation, and it is
        only safe because it is a no-op on canonical input. Pinned rather than
        assumed: the day the two disagree, keys minted through one stop
        matching keys minted through the other."""
        from evigraph.services.linker.base import positional
        from evigraph.utils.canonical import canonicalize_path_template

        for template in self.TEMPLATES:
            canonical = canonicalize_path_template(template)
            assert positional(canonical) == canonical, template

    def test_a_second_parameter_collapser_is_reported(self):
        import ast

        from tools.check_invariants import _collapses_a_parameter

        for source in ('re.sub(r"<[^>]*>", "{}", t)', '_P.sub("{}", t)'):
            node = ast.parse(source).body[0].value
            assert _collapses_a_parameter(node), source

    def test_reading_a_key_is_not_writing_one(self):
        """R3 slices `pkg:golang/...` apart to find a repo. Flagging that
        would make the check unusable and teach people to silence it."""
        import ast

        from tools.check_invariants import _builds_a_purl, _collapses_a_parameter

        for source in ('key.startswith("pkg:")', 'key[len("pkg:golang/"):]',
                       're.sub(r"\\s+", " ", t)'):
            node = ast.parse(source).body[0].value
            assert not _collapses_a_parameter(node), source
            assert not _builds_a_purl(node), source


class TestI10ShardIndependence:
    """No phase may require two shards to communicate."""

    def test_the_shipped_resolvers_hold(self):
        from tools.check_invariants import check_shard_independence

        assert check_shard_independence() == []

    def test_a_join_written_table_read_whole_is_reported(self):
        """The arrangement this repo had until the env index moved into
        BROADCAST: one join resolver writes a table, another reads all of
        it. Correct on one machine, silently lossy on two."""
        from tools.check_invariants import check_shard_independence

        violations = check_shard_independence({
            "r_writer": ({"env_values"}, set()),
            "r_reader": (set(), {"env_values"}),
        })
        assert len(violations) == 1
        assert "r_reader" in violations[0] and "env_values" in violations[0]

    def test_a_keyed_read_of_the_same_table_is_not_a_violation(self):
        """`ctx.contract_repos[node_id]` is shard-local by construction: the
        partition owning the key owns the entry. Flagging it would condemn
        the pattern every contract resolver correctly uses."""
        from tools.check_invariants import check_shard_independence

        assert check_shard_independence({
            "r_writer": ({"contract_repos"}, set()),
            "r_reader": (set(), set()),
        }) == []

    def test_a_broadcast_written_table_may_be_read_whole(self):
        """Broadcast tables are replicated to every worker; iterating one is
        what they are for. Only join-phase writes are the problem."""
        from tools.check_invariants import check_shard_independence

        assert check_shard_independence({
            "r_reader": (set(), {"env_values"}),
        }) == []
