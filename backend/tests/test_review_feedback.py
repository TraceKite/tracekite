"""Reviews refine, never block.

Both halves of the exit criterion, from the failing side: a corrupt
decisions file must not fail the graph (counted, because silently
ignoring an operator's decisions would be worse than failing), and every
decision becomes a labelled example without the reviewer knowing they
were labelling.
"""

from adduce.services.linker.base import ClaimRecord
from adduce.services.linker.engine import link
from adduce.services.linker.review_labels import review_labels


def claim(cid, repo, key, hint):
    return ClaimRecord(
        id=cid, repo_id=repo, kind="svcname", direction="provides", key=key,
        service_hint=hint, hint_source="compose", matchable=True,
        evidence=["docker-compose.yml:1"], attrs={},
        evidence_node_id=None, evidence_node_type="File")


CLAIMS = [claim("c1", "repo_a", "compose:billing", "billing"),
          claim("c2", "repo_b", "compose:orders", "orders")]


class TestNeverBlock:
    def test_a_corrupt_decisions_file_is_counted_not_fatal(self, tmp_path,
                                                           monkeypatch):
        """The graph outranks the review tooling: a bad promotions.yml
        yields a complete link run with the failure on the record."""
        from adduce import engine_config

        (tmp_path / "promotions.yml").write_text("{{{ not yaml")
        monkeypatch.setenv("KG_CONFIG_DIR", str(tmp_path))
        engine_config.reset()
        engine_config.configure(graph_hmac_key="f6-test",
                                config_dir=str(tmp_path))
        try:
            result = link(CLAIMS, run_id="linkrun_f6", confidence={},
                          aliases={}, now="2026-01-01T00:00:00+00:00")
        finally:
            engine_config.reset()
            engine_config.configure(graph_hmac_key="f6-test")
        assert result.edges, "the corrupt file cost the run its edges"
        assert result.counters.get("promotions_unreadable") == 1

    def test_a_rejection_is_a_status_never_a_deletion(self):
        """The reviewed edge stays queryable as rejected: deleting it
        would erase the very decision the review recorded."""
        result = link(CLAIMS, run_id="linkrun_rej", confidence={},
                      aliases={}, now="2026-01-01T00:00:00+00:00",
                      promotions=[{"source": e.source_id, "type": e.type,
                                   "target": e.target_id,
                                   "decision": "reject"}
                                  for e in link(
                                      CLAIMS, run_id="pre", confidence={},
                                      aliases={}, promotions=[],
                                      now="2026-01-01T00:00:00+00:00").edges])
        rejected = [e for e in result.edges if e.status == "rejected"]
        assert rejected, "rejections vanished instead of being recorded"
        assert result.counters.get("edges_rejected", 0) >= 1


class TestLabelsBack:
    def test_decisions_become_labelled_examples(self):
        labels = review_labels([
            {"source": "a", "type": "CALLS_SERVICE", "target": "b",
             "decision": "promote", "note": "verified in prod"},
            {"source": "c", "type": "CALLS_SERVICE", "target": "d",
             "decision": "reject"},
        ])
        assert [l["source"] for l in labels["tp"]] == ["a"]
        assert [l["source"] for l in labels["fp"]] == ["c"]
        assert labels["unusable"] == []

    def test_a_malformed_decision_is_surfaced_not_dropped(self):
        """A label nobody can use is a finding about the review tooling."""
        labels = review_labels([{"source": "x", "decision": "maybe"}])
        assert labels["unusable"][0]["decision"] == "maybe"
