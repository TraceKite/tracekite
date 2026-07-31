"""E3: suggestions surfaced, nothing auto-applied.

The property under test is the boundary: the same unmatched hint that
produces a suggestion must produce NO edge — before, during, and after
suggesting — until an operator signs the alias into the table themselves.
A suggestion that changed the graph would be a guessed edge with a
paper trail.
"""

from adduce.services.linker.alias_suggestions import suggest_aliases
from adduce.services.linker.base import ClaimRecord
from adduce.services.linker.engine import link

NOW = "2026-01-01T00:00:00+00:00"


def claim(kind, direction, key, repo="repo_a", hint=None, attrs=None,
          evidence=None, enode=None, hint_source="host"):
    return ClaimRecord(
        id=f"claim:{repo}:{kind}:{direction}:{key}", repo_id=repo, kind=kind,
        direction=direction, key=key, service_hint=hint,
        hint_source=hint_source, matchable=True, attrs=attrs or {},
        evidence=evidence or [f"{repo}/svc/config.py:7"],
        evidence_node_id=enode, evidence_node_type="",
    )


def estate(consumer_hint="users-svc"):
    """Provider `users` exists; a consumer names `consumer_hint`."""
    return [
        claim("svcname", "provides", "proj:web", repo="repo_web",
              attrs={"source": "compose", "build_context": "."},
              evidence=["repo_web/docker-compose.yml:3"]),
        claim("svcname", "provides", "proj:users", repo="repo_users",
              attrs={"source": "compose", "build_context": "."},
              evidence=["repo_users/docker-compose.yml:3"]),
        claim("http", "provides", "GET:/v1/users", repo="repo_users",
              evidence=["repo_users/src/api.py:5"], enode="node:endpoint"),
        claim("http", "consumes", "httpcall:GET:/v1/users", repo="repo_web",
              hint=consumer_hint, enode="node:callsite",
              evidence=["repo_web/src/api.ts:41"]),
        claim("svcname", "consumes", f"discovery:{consumer_hint}",
              repo="repo_web", hint=consumer_hint,
              evidence=["repo_web/src/api.ts:41"]),
    ]


def calls_service_edges(result):
    return [e for e in result.edges if e.type == "CALLS_SERVICE"]


class TestSuggestions:
    def test_unmatched_hint_is_suggested_with_rule_and_evidence(self):
        claims = estate()
        result = link(claims, now=NOW, aliases={}, promotions=[])
        report = suggest_aliases(claims, result.services, {})
        [suggestion] = report["suggestions"]
        assert suggestion["alias"] == "users-svc"
        assert {"service": "users", "rule": "suffix"} in \
            suggestion["candidates"]
        assert "repo_web/src/api.ts:41" in suggestion["evidence"]
        assert "users:" in suggestion["yaml"]

    def test_nothing_is_auto_applied(self):
        # The whole exit criterion in one test: no edge before, a
        # suggestion in the middle that changes nothing, an edge only
        # after the OPERATOR writes the alias. ONE aliases dict is shared
        # across the flow, exactly as the CLI shares load_aliases() —
        # a suggester that wrote its guesses into the table it was given
        # would silently apply them to the next link.
        aliases: dict = {}
        claims = estate()
        before = link(claims, now=NOW, aliases=aliases, promotions=[])
        assert calls_service_edges(before) == []

        report = suggest_aliases(claims, before.services, aliases)
        assert report["suggestions"], "the decline surfaced nothing"
        assert aliases == {}, "suggesting mutated the operator table"

        again = link(claims, now=NOW, aliases=aliases, promotions=[])
        identity = lambda r: [(e.source_id, e.type, e.target_id, e.status,
                               e.confidence) for e in r.edges]  # noqa: E731
        assert identity(again) == identity(before)

        signed = link(claims, now=NOW, aliases={"users": ["users-svc"]},
                      promotions=[])
        assert len(calls_service_edges(signed)) == 1

    def test_hint_covered_by_existing_alias_is_not_resuggested(self):
        claims = estate()
        aliases = {"users": ["users-svc"]}
        result = link(claims, now=NOW, aliases=aliases, promotions=[])
        report = suggest_aliases(claims, result.services, aliases)
        assert report["suggestions"] == []
        assert report["declined"]["already_known"] >= 1

    def test_vendor_host_is_classified_not_suggested(self):
        claims = estate(consumer_hint="api.stripe.com")
        result = link(claims, now=NOW, aliases={}, promotions=[])
        report = suggest_aliases(claims, result.services, {})
        assert report["suggestions"] == []
        # Two claims carry the hint (the call and its discovery lookup);
        # declines count claim sites, suggestions group by name.
        assert report["declined"]["external_vendor"] == 2

    def test_nothing_close_declines_no_candidate(self):
        claims = estate(consumer_hint="warehouse")
        result = link(claims, now=NOW, aliases={}, promotions=[])
        report = suggest_aliases(claims, result.services, {})
        assert report["suggestions"] == []
        assert report["declined"]["no_candidate"] == 1

    def test_one_transform_never_two(self):
        # "users-svc-api" is two suffixes from "users": suggesting it
        # would be a guess, not a spelling.
        claims = estate(consumer_hint="users-svc-api")
        result = link(claims, now=NOW, aliases={}, promotions=[])
        report = suggest_aliases(claims, result.services, {})
        assert report["suggestions"] == []
        assert report["declined"]["no_candidate"] == 1
