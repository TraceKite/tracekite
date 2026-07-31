"""The CLI is the library surface with a face on it.

Run as a subprocess, because the contract being tested is the process one:
JSON on stdout and nothing else, so `adduce link ... | jq` works.
"""

import json
import os
import subprocess
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(BACKEND, "tests", "fixtures")
SAMPLE = os.path.join(FIXTURES, "callgraph-sample")
PLANTED = os.path.join(FIXTURES, "planted-secret")
FIXED_NOW = "2026-01-01T00:00:00+00:00"


def run(*args):
    proc = subprocess.run(
        [sys.executable, "-m", "adduce.cli", *args],
        cwd=BACKEND, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


class TestScan:
    def test_stdout_is_only_json(self):
        payload = json.loads(run("scan", SAMPLE).stdout)
        assert payload["repo_id"] == "callgraph-sample"
        assert payload["nodes"] > 0 and payload["claims"]

    def test_repo_id_can_be_overridden(self):
        payload = json.loads(run("scan", SAMPLE, "--repo-id", "custom").stdout)
        assert payload["repo_id"] == "custom"


class TestLink:
    def test_links_two_repositories(self):
        payload = json.loads(
            run("link", SAMPLE, PLANTED, "--now", FIXED_NOW).stdout)
        assert payload["claims_loaded"] > 0
        assert payload["repos"] == ["callgraph-sample", "planted-secret"]
        assert payload["edges"], "two real repos should produce edges"

    def test_every_edge_carries_evidence_and_confidence(self):
        """An edge without a file:line is exactly what this tool refuses to
        emit — the CLI must not be the one surface that drops it."""
        payload = json.loads(
            run("link", SAMPLE, PLANTED, "--now", FIXED_NOW).stdout)
        for edge in payload["edges"]:
            assert edge["evidence"], edge
            assert 0.0 < edge["confidence"] <= 1.0, edge

    def test_counters_are_reported_not_swallowed(self):
        """Declines are data. A run that reports edges but no counters has
        hidden every question it declined to answer."""
        payload = json.loads(
            run("link", SAMPLE, PLANTED, "--now", FIXED_NOW).stdout)
        assert payload["counters"], payload

    def test_same_inputs_and_now_give_byte_identical_output(self):
        """The floor B6 builds on: without this, CI diffing is unbuildable."""
        first = run("link", SAMPLE, PLANTED, "--now", FIXED_NOW).stdout
        second = run("link", SAMPLE, PLANTED, "--now", FIXED_NOW).stdout
        assert first == second

    def test_no_secret_reaches_the_output(self):
        proc = run("link", SAMPLE, PLANTED, "--now", FIXED_NOW)
        assert "PLANTEDSECRET" not in proc.stdout + proc.stderr


class TestExplain:
    def test_explains_a_real_edge(self):
        linked = json.loads(
            run("link", SAMPLE, PLANTED, "--now", FIXED_NOW).stdout)
        edge = linked["edges"][0]
        payload = json.loads(
            run("explain", SAMPLE, PLANTED, "--now", FIXED_NOW,
                "--edge", edge["source"], edge["target"]).stdout)
        assert payload["found"] is True
        assert payload["edges"][0]["evidence"]

    def test_missing_edge_declines_rather_than_inventing(self):
        payload = json.loads(
            run("explain", SAMPLE, PLANTED, "--edge", "nope", "alsonope").stdout)
        assert payload["found"] is False


class TestPublishedContract:
    """A4 + J1: the schema is emitted and versioned, and output validates."""

    def test_schema_is_emitted_and_versioned(self):
        payload = json.loads(run("schema").stdout)
        assert payload["wire_version"].count(".") == 2, payload["wire_version"]
        assert set(payload["schemas"]) >= {
            "ScanReport", "LinkReport", "ExplainReport", "EdgeRecord"}

    def test_evidence_and_counters_are_required_by_the_contract(self):
        """Not incidental: an edge without a file:line, or a report that
        omits its declines, is the failure this project refuses to ship."""
        schemas = json.loads(run("schema").stdout)["schemas"]
        assert "evidence" in schemas["EdgeRecord"]["required"]
        assert "counters" in schemas["LinkReport"]["required"]

    def test_link_output_validates_against_the_published_model(self):
        from adduce.wire import LinkReport

        payload = json.loads(
            run("link", SAMPLE, PLANTED, "--now", FIXED_NOW).stdout)
        report = LinkReport(**payload)
        assert report.wire_version == payload["wire_version"]
        assert all(e.evidence for e in report.edges)

    def test_scan_output_validates_against_the_published_model(self):
        from adduce.wire import ScanReport

        assert ScanReport(**json.loads(run("scan", SAMPLE).stdout))

    def test_every_payload_carries_its_wire_version(self):
        """A consumer that cannot tell which contract it is reading has no
        way to fail safely when the contract changes."""
        for args in (("scan", SAMPLE),
                     ("link", SAMPLE, "--now", FIXED_NOW),
                     ("explain", SAMPLE, "--edge", "a", "b")):
            assert "wire_version" in json.loads(run(*args).stdout), args


class TestFullDerivation:
    """Every edge explains claims, resolver, transforms, evidence.

    An edge that cannot account for itself should never have been emitted.
    Confidence without a derivation is a number nobody can check, which is
    the thing this tool exists not to produce.
    """

    def _edges(self):
        from adduce.cli_explain import _derivation
        from adduce import engine_config
        from adduce.db.memory_store import InMemoryLinkerStore
        from adduce.services.linker.engine import link
        from adduce.services.scan import scan

        engine_config.configure(graph_hmac_key="e7-test-key")
        store = InMemoryLinkerStore([scan(SAMPLE, "a"), scan(PLANTED, "b")])
        result = link(store.load_claims(), now=FIXED_NOW)
        assert result.edges, "fixture must produce edges to explain"
        return [_derivation(e) for e in result.edges]

    def test_every_edge_names_its_resolver(self):
        for d in self._edges():
            assert d["resolver"], d
            assert "@" in d["resolver"], (
                f"resolver must be versioned so a re-run is attributable: {d}")

    def test_every_joined_edge_names_the_key_its_claims_met_on(self):
        """Only join edges have one. A structural edge like `HAS_ALIAS` *is*
        the rendezvous — R0 clusters names rather than joining two claims —
        so demanding a key of it would be demanding the wrong thing."""
        for d in self._edges():
            if d["origin"] == "inferred":
                continue
            assert d["rendezvous_key"], d

    def test_structural_edges_still_name_resolver_and_evidence(self):
        """Being unjoined is not an excuse to be unexplainable."""
        structural = [d for d in self._edges() if d["origin"] == "inferred"]
        for d in structural:
            assert d["resolver"] and d["evidence"], d

    def test_every_edge_cites_evidence(self):
        for d in self._edges():
            assert d["evidence"], d
            assert all(":" in e for e in d["evidence"]), (
                f"evidence must be file:line, not a bare path: {d}")

    def test_every_edge_reports_its_transforms(self):
        """Present even when empty: 'no rewriting happened' is an answer, and
        an absent field is not distinguishable from an unrecorded one."""
        for d in self._edges():
            assert "transforms" in d
            assert set(d["transforms"]) == {
                "match_type", "via", "env_scope", "path_prefix"}, d

    def test_every_edge_states_how_it_came_to_exist(self):
        """Three kinds, and the distinction is the point: `declared` means
        somebody wrote it down, `matched` means two claims met on a key, and
        `inferred` means we clustered it. A reader who cannot tell which is
        being shown cannot judge how much to trust it."""
        for d in self._edges():
            assert d["origin"] in ("declared", "matched", "inferred"), d


CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "corpus")


class TestMeasuredInExplain:
    """F1: the interval is served next to every priced confidence."""

    def _edges(self):
        from adduce import engine_config
        from adduce.db.memory_store import InMemoryLinkerStore
        from adduce.services.linker.engine import link
        from adduce.services.scan import scan

        engine_config.configure(graph_hmac_key="explain-measured-test")
        sinks = [scan(os.path.join(CORPUS, "orders-service"), "orders-service"),
                 scan(os.path.join(CORPUS, "billing-service"),
                      "billing-service")]
        return link(InMemoryLinkerStore(sinks).load_claims(),
                    run_id="linkrun_f1",
                    now="2026-01-01T00:00:00+00:00").edges

    def test_a_priced_edge_carries_its_interval(self):
        from adduce.cli_explain import _measured_row

        invokes = [e for e in self._edges() if e.type == "INVOKES"]
        assert invokes
        row = _measured_row(invokes[0])
        assert row["tier"].startswith("r7.")
        assert row["precision"] == 1.0
        lo, hi = row["interval"]
        assert 0 < lo < 1 and hi == 1.0, (
            "the interval is the honest half: support this small must show "
            "a wide bound, not a bare 1.000")

    def test_an_unpriced_edge_says_why_not_nothing(self):
        from adduce.cli_explain import _measured_row

        rollups = [e for e in self._edges()
                   if e.detected_by.startswith("rollup.")]
        assert rollups
        row = _measured_row(rollups[0])
        assert row["tier"] is None and "not a priced tier" in row["why"]
