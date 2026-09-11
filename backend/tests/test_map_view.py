"""The service map is assembled in core, so both surfaces agree.

Two decisions used to live inside the `/api/v2/service-map` handler and
one inside the rollup handler, which meant `pip install tracekite` and
`docker compose up` could render the same estate differently. They are
pinned here because that is the point of moving them — not that the code
relocated, but that there is now one answer.
"""

from tracekite.services.linker.map_view import assemble_service_map, node_kind
from tracekite.services.linker.rollup_view import ownership_from_rows


def node(nid, name=None, **extra):
    return {"id": nid, "name": name or nid, **extra}


def edge(source, target, etype="CALLS_SERVICE", **extra):
    return {"source": source, "target": target, "type": etype, **extra}


class TestNodeKind:
    def test_repo_beats_the_default(self):
        assert node_kind(["GraphNode", "Repo"]) == "repo"

    def test_unresolved_service_name_is_a_dead_end(self):
        assert node_kind(["ServiceName"]) == "service_name"

    def test_anything_else_is_a_plain_node(self):
        assert node_kind(["HttpContract"]) == "node"
        assert node_kind([]) == "node"
        assert node_kind(None) == "node"


class TestAssembly:
    def test_services_from_the_node_query_are_services(self):
        out = assemble_service_map(
            [node("global:Service:orders", "orders", is_gateway=False,
                  repo_ids=["r1"])], [], 0)
        [n] = out["nodes"]
        assert n["kind"] == "service" and n["repo_ids"] == ["r1"]

    def test_a_node_only_an_edge_mentions_is_still_drawn(self):
        """Otherwise the edge dangles: the map would draw an arrow to
        nothing, which reads as a missing service rather than an
        unresolved name."""
        out = assemble_service_map(
            [node("global:Service:web", "web")],
            [edge("global:Service:web", "global:SvcName:prod:ghost",
                  target_labels=["ServiceName"], target_name="ghost",
                  target_scope="prod", source_labels=["Service"],
                  source_name="web", source_scope=None)], 1)
        kinds = {n["id"]: n for n in out["nodes"]}
        assert kinds["global:SvcName:prod:ghost"]["dead_end"] is True
        assert len(out["edges"]) == 1

    def test_totals_report_the_estate_not_the_page(self):
        out = assemble_service_map([node("a")], [
            edge("a", "b", target_labels=[], target_name="b",
                 target_scope=None, source_labels=[], source_name="a",
                 source_scope=None)], total_edges=4000)
        assert out["totals"]["edges"] == 4000
        assert out["truncated"] is True

    def test_untruncated_when_the_page_holds_everything(self):
        out = assemble_service_map([node("a")], [], total_edges=0)
        assert out["truncated"] is False

    def test_evidence_is_capped_per_edge(self):
        out = assemble_service_map([], [
            edge("a", "b", target_labels=[], target_name="b",
                 target_scope=None, source_labels=[], source_name="a",
                 source_scope=None,
                 evidence=["a:1", "b:2", "c:3", "d:4", "e:5"])], 1)
        assert out["edges"][0]["evidence"] == ["a:1", "b:2", "c:3"]


class TestOwnershipTieBreak:
    def test_first_in_sorted_order_wins(self):
        rows = [{"service": "s1", "team": "alpha"},
                {"service": "s1", "team": "beta"},
                {"service": "s2", "team": "gamma"}]
        assert ownership_from_rows(rows) == {"s1": "alpha", "s2": "gamma"}

    def test_the_same_rows_always_give_the_same_owner(self):
        """Arbitrary is fine; per-surface is not. A library host and the app
        must tell one ownership story about one estate."""
        rows = [{"service": "s", "team": "a"}, {"service": "s", "team": "b"}]
        assert ownership_from_rows(rows) == ownership_from_rows(list(rows))
