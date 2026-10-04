"""F5: stale evidence downgrades confidence, never deletes.

The asymmetry is the design: `stale` needs positive proof (file gone,
line past EOF, the claim's own token absent around the cited line);
anything unverifiable is counted and left alone — wrongly aging a good
edge is the same sin as inventing one.
"""

from tracekite.models.graph_models import GraphEdge
from tracekite.services.claims import ContractClaim
from tracekite.services.evidence_reverify import (
    claim_token, downgrade_stale, reverify,
)

FILES = {
    "src/api.py": "import x\n@app.get('/v1/users')\ndef users(): ...\n",
    "compose.yml": "services:\n  users:\n    image: users:1\n",
}


def reader(files=None):
    table = FILES if files is None else files
    return lambda path: table.get(path)


def http_claim(evidence):
    return ContractClaim(repo_id="r", kind="http", direction="provides",
                         key="GET:/v1/users", evidence=[evidence])


def edge(evidence, confidence=0.95):
    return GraphEdge(source_id="a", target_id="b", repo_id="",
                     type="CALLS_SERVICE", confidence=confidence,
                     status="active", evidence=[evidence],
                     created_by="linker")


class TestVerdicts:
    def test_cited_line_still_says_it(self):
        report = reverify([http_claim("src/api.py:2")], reader())
        assert report["counts"] == {"ok": 1, "stale": 0, "unverifiable": 0}

    def test_drift_within_radius_still_counts(self):
        # The decorator moved from line 2 to 3 lines away: the citation
        # aged but the fact holds; aging it would be a false positive.
        report = reverify([http_claim("src/api.py:1")], reader())
        assert report["counts"]["ok"] == 1

    def test_missing_file_is_stale(self):
        report = reverify([http_claim("gone/api.py:2")], reader())
        assert report["stale"] == {"gone/api.py:2": "stale_file"}

    def test_line_past_eof_is_stale(self):
        report = reverify([http_claim("src/api.py:99")], reader())
        assert report["stale"] == {"src/api.py:99": "stale_line"}

    def test_rewritten_line_is_stale(self):
        files = {"src/api.py": "import x\n# nothing here now\npass\n"}
        report = reverify([http_claim("src/api.py:2")], reader(files))
        assert report["stale"] == {"src/api.py:2": "stale_line"}

    def test_no_token_means_unverifiable_never_stale(self):
        claim = ContractClaim(repo_id="r", kind="owner",
                              direction="provides", key="team:payments",
                              evidence=["CODEOWNERS:1"])
        assert claim_token("owner", "team:payments") is None
        report = reverify([claim], reader({}))
        assert report["counts"]["unverifiable"] == 1
        assert report["stale"] == {}


class TestDowngrade:
    CONF = {"stale_evidence_factor": 0.7, "floor": 0.6}

    def test_below_floor_becomes_candidate_never_deleted(self):
        edges = [edge("gone.py:1", confidence=0.7),
                 edge("fine.py:1", confidence=0.7)]
        out = downgrade_stale(edges, {"gone.py:1": "stale_file"}, self.CONF)
        assert len(edges) == 2, "reverification must never remove an edge"
        rotten, fine = edges
        assert rotten.status == "candidate" and rotten.confidence == 0.49
        assert rotten.extra_props["stale_evidence"] == ["gone.py:1"]
        assert fine.status == "active" and fine.confidence == 0.7
        assert len(out["downgraded"]) == 1

    def test_above_floor_stays_active_but_carries_the_flag(self):
        e = edge("gone.py:1", confidence=0.95)
        downgrade_stale([e], {"gone.py:1": "stale_file"}, self.CONF)
        assert e.status == "active" and e.confidence == 0.665
        assert e.extra_props["stale_evidence"] == ["gone.py:1"]


class TestSourceSaysItItsOwnWay:
    """An unchanged tree must verify. Comparing normalised keys verbatim
    aged 14 of 27 checkable citations on gothinkster's realworld API and 98
    on medusa, scanned and checked at the same commit."""

    def _verdicts(self, kind, key, evidence, files, attrs=None):
        claim = ContractClaim(repo_id="r", kind=kind, direction="provides",
                              key=key, evidence=[evidence], attrs=attrs or {})
        return reverify([claim], reader(files))

    def test_a_parameterised_route_matches_its_own_spelling(self):
        files = {"routes.ts": "router.delete('/articles/:slug/comments/:id', h);\n"}
        report = self._verdicts("http", "DELETE:/articles/{}/comments/{}",
                                "routes.ts:1", files)
        assert report["counts"]["ok"] == 1

    def test_a_lowercased_key_matches_mixed_case_source(self):
        files = {"compose.yml": "services:\n  x:\n    y: 1\n  frontendTests:\n"}
        report = self._verdicts("svcname", "demo:frontendtests",
                                "compose.yml:4", files)
        assert report["counts"]["ok"] == 1

    def test_a_quoted_sql_identifier_matches_its_key(self):
        files = {"q.sql": "\n\nselect 1\nfrom \"public\".\"order_line_item\"\n"}
        report = self._verdicts("db", "table:public.order_line_item",
                                "q.sql:4", files)
        assert report["counts"]["ok"] == 1

    def test_a_file_routed_path_is_checked_against_the_file_path(self):
        files = {"pages/api/products/[id]/index.ts": "export default handler;\n"}
        report = self._verdicts("http", "ANY:/api/products/{}",
                                "pages/api/products/[id]/index.ts:1", files,
                                attrs={"framework": "nextjs-pages"})
        assert report["counts"]["ok"] == 1

    def test_line_one_is_a_file_level_citation(self):
        files = {"m.sql": "-- migration\n\n\n\n\nCREATE TABLE \"Comment\" (id int);\n"}
        report = self._verdicts("db", "table:comment", "m.sql:1", files)
        assert report["counts"]["ok"] == 1

    def test_a_route_that_is_really_gone_is_still_stale(self):
        files = {"routes.ts": "router.delete('/articles/:slug', h);\n"}
        report = self._verdicts("http", "DELETE:/articles/{}/comments/{}",
                                "routes.ts:1", files)
        assert report["stale"] == {"routes.ts:1": "stale_line"}
