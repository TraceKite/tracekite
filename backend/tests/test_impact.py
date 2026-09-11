"""PR mode: which consumers a change breaks.

The roadmap's highest-value task and the goal's closing sentence — "it answers,
on every pull request, which consumers a change breaks, with a file and line
for each". So the tests are about the two ways that answer can be wrong:
naming somebody who did not break, and naming somebody without saying where.
"""

from tracekite.models.graph_models import GraphEdge
from tracekite.services.linker.impact import as_comment, impact


def edge(source, target, *, evidence=("src/billing_client.py:14",),
         source_repo="orders", target_repo="billing", status="active"):
    e = GraphEdge(source_id=source, target_id=target, repo_id=source_repo,
                  type="CALLS_SERVICE", evidence=list(evidence),
                  detected_by="resolver.http@1")
    e.status = status
    e.source_repo_id = source_repo
    e.target_repo_id = target_repo
    return e


CALL = edge("orders-service", "billing-service")


class TestBreaks:
    def test_a_removed_edge_is_a_break_with_its_citation(self):
        result = impact([CALL], [], changed_repos={"billing"})
        assert len(result.breaks) == 1
        found = result.breaks[0]
        assert found.consumer == "orders-service"
        assert found.lost == "billing-service"
        assert found.evidence == ("src/billing_client.py:14",)
        assert found.caused_by_this_change is True

    def test_a_consumer_that_changed_its_own_code_is_not_breakage(self):
        """Reporting it would train reviewers to dismiss the check, which
        costs more than the finding is worth."""
        result = impact([CALL], [], changed_repos={"orders"})
        assert len(result.breaks) == 1
        assert result.breaks[0].caused_by_this_change is False
        assert result.blocking == []

    def test_an_edge_that_vanished_with_neither_side_changing_is_not_a_break(
            self):
        """That is a regression in TraceKite, not in the branch, and serving it
        as somebody's fault is worse than not reporting it."""
        result = impact([CALL], [], changed_repos={"unrelated"})
        assert result.breaks == []
        assert len(result.unexplained) == 1
        assert result.counters["impact.unexplained"] == 1

    def test_an_uncitable_loss_is_counted_not_reported(self):
        """An edge with no file:line should never have been emitted (I6), and
        a break nobody can open is not a work item."""
        result = impact([edge("a", "b", evidence=())], [],
                        changed_repos={"billing"})
        assert result.breaks == []
        assert result.counters["impact.uncitable"] == 1

    def test_nothing_removed_means_no_breaks(self):
        result = impact([CALL], [CALL], changed_repos={"billing"})
        assert result.breaks == [] and result.counters["impact.unchanged"] == 1

    def test_added_edges_are_reported_too(self):
        result = impact([], [CALL], changed_repos={"billing"})
        assert result.added == [{
            "consumer": "orders-service", "gained": "billing-service",
            "type": "CALLS_SERVICE",
            "evidence": ["src/billing_client.py:14"]}]

    def test_a_candidate_edge_appearing_is_not_a_new_connection(self):
        """Candidates are excluded from default answers, so announcing one as
        gained claims a connection the tool would not show."""
        result = impact([], [edge("a", "b", status="candidate")],
                        changed_repos={"billing"})
        assert result.added == []


class TestWithoutAttribution:
    """Called with no `changed_repos`, every loss is reported and none is
    attributed — degraded, and visibly so."""

    def test_every_loss_is_reported(self):
        result = impact([CALL], [])
        assert len(result.breaks) == 1
        assert result.breaks[0].caused_by_this_change is True

    def test_nothing_is_filed_as_unexplained(self):
        """Without knowing what changed, "neither side changed" is not a
        conclusion available to make."""
        assert impact([CALL], []).unexplained == []


class TestComment:
    def test_the_comment_names_the_consumer_and_the_line(self):
        text = as_comment(impact([CALL], [], changed_repos={"billing"}))
        assert "orders" in text
        assert "src/billing_client.py:14" in text

    def test_one_deleted_route_is_one_finding_not_three(self):
        """The same loss surfaces as a Service rollup, a name-level edge and
        a File-to-contract edge — three node ids, one line to fix. Listing
        them separately reads as three breaks and makes the comment
        untrustworthy."""
        granularities = [
            edge("global:Service:orders", "global:Service:billing"),
            edge("orders-service", "billing-service"),
            edge("orders-service:File:abc", "global:Http:billing:GET:/v1/x"),
        ]
        text = as_comment(impact(granularities, [],
                                 changed_repos={"billing"}))
        assert text.startswith("**TraceKite**: 1 connection(s) lost")
        assert text.count("src/billing_client.py:14") == 1
        assert "also recorded as" in text

    def test_a_clean_change_says_so_rather_than_staying_silent(self):
        text = as_comment(impact([CALL], [CALL], changed_repos={"billing"}))
        assert "no consumer loses a connection" in text

    def test_truncation_is_stated(self):
        """A comment that silently showed twenty of forty would be read as
        'these are the breaks', and the other twenty would ship."""
        many = [edge(f"consumer-{i}", "billing-service",
                     evidence=(f"src/c{i}.py:1",), source_repo=f"repo-{i}")
                for i in range(25)]
        text = as_comment(impact(many, [], changed_repos={"billing"}), limit=5)
        assert "20 further connection(s) not shown" in text

    def test_an_tracekite_regression_is_named_separately(self):
        result = impact([CALL], [], changed_repos={"unrelated"})
        assert "regression in TraceKite" in as_comment(result)


class TestEndToEnd:
    def test_a_removed_route_breaks_its_caller(self, tmp_path):
        """The corpus, through the real pipeline: billing drops the route
        orders calls, and orders is named with the line that calls it."""
        import os
        import shutil

        from tracekite import engine_config
        from tracekite.db.artifact import write_artifact
        from tracekite.db.artifact_reader import read_artifact
        from tracekite.db.memory_store import InMemoryLinkerStore
        from tracekite.services.linker.engine import link
        from tracekite.services.scan import scan

        engine_config.configure(graph_hmac_key="impact-test-key")
        corpus = os.path.join(os.path.dirname(__file__), "..", "..", "corpus")

        def artifacts_for(billing_src: str, out: str) -> list:
            work = tmp_path / out
            shutil.copytree(os.path.join(corpus, "orders-service"),
                            work / "orders-service")
            shutil.copytree(os.path.join(corpus, "billing-service"),
                            work / "billing-service")
            routes = work / "billing-service" / "internal" / "routes.go"
            routes.write_text(billing_src)
            return [
                write_artifact(scan(str(work / name), name), name,
                               str(work / "artifacts")).path
                for name in ("orders-service", "billing-service")]

        original = (open(os.path.join(corpus, "billing-service", "internal",
                                      "routes.go"), encoding="utf-8").read())
        base = artifacts_for(original, "base")
        head = artifacts_for("package internal\n\nfunc Routes() {}\n", "head")

        def graph(paths, run_id):
            store = InMemoryLinkerStore([read_artifact(p) for p in paths])
            return link(store.load_claims(), run_id=run_id,
                        now="2026-01-01T00:00:00+00:00").edges

        result = impact(graph(base, "b"), graph(head, "h"),
                        changed_repos={"billing-service"})
        assert result.blocking, result.as_dict()
        assert any("orders" in b.consumer for b in result.blocking)
        assert all(b.evidence for b in result.blocking)


class TestRisk:
    def test_score_is_confidence_weighted_blast(self):
        """Thirty certain breaks must outscore thirty maybes; one maybe
        must score near zero instead of crying wolf."""
        sure = edge("a-svc", "billing-service", source_repo="repo-a")
        sure.confidence = 0.95
        maybe = edge("b-svc", "billing-service", source_repo="repo-b",
                     evidence=("src/b.py:2",))
        maybe.confidence = 0.62
        result = impact([sure, maybe], [], changed_repos={"billing"})
        assert result.risk() == {"score": 1.57, "blast_repos": 2,
                                 "breaks": 2}

    def test_non_blocking_breaks_do_not_score(self):
        """A consumer that broke itself is not this PR's risk."""
        e = edge("a-svc", "billing-service")
        e.confidence = 0.95
        result = impact([e], [], changed_repos={"orders"})
        assert result.risk() == {"score": 0.0, "blast_repos": 0, "breaks": 0}

    def test_risk_rides_every_report_and_comment(self):
        result = impact([CALL], [], changed_repos={"billing"})
        assert "risk" in result.as_dict()
        assert "Risk:" in as_comment(result)
        clean = impact([CALL], [CALL], changed_repos={"billing"})
        assert "Risk: 0" in as_comment(clean)
