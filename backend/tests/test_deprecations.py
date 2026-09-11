"""Deprecated contracts list their live consumers.

The two answers a deprecation raises, both tested from the declining side:
a consumer the tool is not sure about must not block a deletion, and a
contract with nobody calling it must say so out loud rather than by
omission.
"""

from evigraph.models.graph_models import GraphEdge
from evigraph.services.linker.deprecations import deprecation_report
from evigraph.services.linker.values import RendezvousSpec


def contract(node_id="global:Http:billing:GET:/v1/legacy/{}",
             deprecated=True, **props):
    base = {"method": "GET", "path_template": "/v1/legacy/{id}",
            "repo_ids": ["billing-service"]}
    if deprecated:
        base["deprecated"] = True
    return RendezvousSpec("HttpContract", node_id, {**base, **props})


def invoke(source, target, *, status="active",
           evidence=("src/legacy_client.py:9",), repo="orders-service"):
    e = GraphEdge(source_id=source, target_id=target, repo_id=repo,
                  type="INVOKES", evidence=list(evidence),
                  detected_by="resolver.http@1")
    e.status = status
    e.source_repo_id = repo
    return e


LEGACY = "global:Http:billing:GET:/v1/legacy/{}"


class TestDeprecationReport:
    def test_a_live_consumer_is_listed_with_its_line(self):
        report = deprecation_report(
            [invoke("orders-service:File:abc", LEGACY)], [contract()])
        assert len(report) == 1
        entry = report[0]
        assert entry["contract"] == LEGACY
        assert entry["safe_to_remove"] is False
        assert entry["live_consumers"] == [{
            "consumer": "orders-service:File:abc",
            "repo": "orders-service",
            "evidence": ["src/legacy_client.py:9"]}]

    def test_no_consumers_is_stated_not_implied(self):
        """The answer that permits deletion, present rather than absent."""
        report = deprecation_report([], [contract()])
        assert report == [{
            "contract": LEGACY, "method": "GET",
            "path": "/v1/legacy/{id}", "providers": ["billing-service"],
            "live_consumers": [], "safe_to_remove": True}]

    def test_a_candidate_consumer_does_not_block_deletion(self):
        """A candidate edge is excluded from default answers everywhere;
        listing it here would block a removal on evidence the tool itself
        declined to assert."""
        report = deprecation_report(
            [invoke("orders-service:File:abc", LEGACY, status="candidate")],
            [contract()])
        assert report[0]["safe_to_remove"] is True

    def test_a_non_deprecated_contract_is_not_in_the_report(self):
        report = deprecation_report(
            [invoke("x", "global:Http:billing:GET:/v1/current")],
            [contract("global:Http:billing:GET:/v1/current",
                      deprecated=False)])
        assert report == []

    def test_consumers_of_other_contracts_do_not_leak_in(self):
        report = deprecation_report(
            [invoke("x", "global:Http:billing:GET:/v1/other")], [contract()])
        assert report[0]["live_consumers"] == []

    def test_output_is_sorted_for_diffing(self):
        """The report is diffed between runs to watch migrations progress;
        an order that shifted would read as change where none happened."""
        report = deprecation_report(
            [invoke("z:File:1", LEGACY, repo="zeta"),
             invoke("a:File:1", LEGACY, repo="alpha")],
            [contract("global:Http:b:GET:/v1/two"), contract()])
        assert [r["contract"] for r in report] == [
            "global:Http:b:GET:/v1/two", LEGACY]
        assert [c["repo"] for c in report[1]["live_consumers"]] == [
            "alpha", "zeta"]


class TestEndToEnd:
    def test_a_deprecated_annotation_reaches_the_report(self, tmp_path):
        """Source annotation to report, through the real pipeline: a JVM
        handler marked @Deprecated, called from another repo."""
        from evigraph import engine_config
        from evigraph.db.memory_store import InMemoryLinkerStore
        from evigraph.services.linker.engine import link
        from evigraph.services.scan import scan

        provider = tmp_path / "billing-service"
        (provider / "src").mkdir(parents=True)
        (provider / "docker-compose.yml").write_text(
            'services:\n  billing-service:\n    build: .\n    ports:\n'
            '      - "8080:8080"\n')
        (provider / "src" / "LegacyController.java").write_text(
            'import org.springframework.web.bind.annotation.*;\n\n'
            '@RestController\npublic class LegacyController {\n'
            '    @Deprecated\n'
            '    @GetMapping("/v1/legacy/{id}")\n'
            '    public String legacy(@PathVariable String id) {\n'
            '        return id;\n    }\n}\n')

        consumer = tmp_path / "orders-service"
        (consumer / "src").mkdir(parents=True)
        (consumer / "docker-compose.yml").write_text(
            "services:\n  orders-service:\n    build: .\n    environment:\n"
            "      BILLING_URL: http://billing-service:8080\n")
        (consumer / "src" / "billing_client.py").write_text(
            'import os\n\nimport httpx\n\n\nclass Client:\n'
            '    def __init__(self):\n'
            '        self._base = os.environ["BILLING_URL"]\n\n'
            '    async def legacy(self, item_id):\n'
            '        return await httpx.AsyncClient().get(\n'
            '            f"{self._base}/v1/legacy/{item_id}")\n')

        engine_config.configure(graph_hmac_key="deprecations-test")
        sinks = [scan(str(provider), "billing-service"),
                 scan(str(consumer), "orders-service")]
        result = link(InMemoryLinkerStore(sinks).load_claims(),
                      run_id="linkrun_dep",
                      now="2026-01-01T00:00:00+00:00")

        from evigraph.services.linker.deprecations import deprecation_report
        report = deprecation_report(result.edges, result.rendezvous)
        assert len(report) == 1, [
            (s.node_id, s.props.get("deprecated"))
            for s in result.rendezvous if s.label == "HttpContract"]
        assert "legacy" in report[0]["contract"]
        assert report[0]["safe_to_remove"] is False
        assert any("billing_client.py" in cite
                   for consumer_entry in report[0]["live_consumers"]
                   for cite in consumer_entry["evidence"])
