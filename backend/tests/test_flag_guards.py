"""D5: conditional edges carry their condition — and only when the AST
proves it. The expensive mistake is marking a live edge as flag-gated,
so negations, else branches, unnameable flags and unguarded calls all
stay unmarked.
"""

from types import SimpleNamespace

from tracekite.services.flag_guards import annotate_flag_guards, guarded_ranges
from tracekite.services.ingest_claims import emit_source_claims
from tracekite.services.ingest_source import IngestSink

PY_GUARDED = '''import requests

def checkout(flags):
    if flags.is_enabled("checkout-v2"):
        return requests.post("http://payments:8080/v2/charge")
    return requests.post("http://payments:8080/v1/charge")
'''

TS_GUARDED = '''export async function checkout() {
  if (ldClient.variation("checkout-v2")) {
    await fetch("http://payments:8080/v2/charge");
  }
  await fetch("http://payments:8080/v1/charge");
}
'''

PY_NEGATED = '''import requests

def checkout(flags):
    if not flags.is_enabled("legacy-off"):
        return requests.post("http://payments:8080/v1/charge")
'''


def _file(path, language):
    return SimpleNamespace(path=path, language=language)


def http_claims(sink):
    return [(n.extra_props["key"], dict(n.metadata or {})) for n in sink.nodes
            if n.type == "ContractClaim"
            and n.extra_props.get("kind") == "http"]


class TestGuardedRanges:
    def test_python_consequence_range(self):
        [guard] = guarded_ranges(PY_GUARDED, "python")
        assert guard["flag"] == "checkout-v2"
        assert guard["start"] <= 5 <= guard["end"]
        assert not (guard["start"] <= 6 <= guard["end"])

    def test_negated_check_marks_nothing(self):
        assert guarded_ranges(PY_NEGATED, "python") == []

    def test_non_literal_flag_marks_nothing(self):
        code = ('def f(flags, name):\n'
                '    if flags.is_enabled(name):\n'
                '        call()\n')
        assert guarded_ranges(code, "python") == []

    def test_unsupported_language_marks_nothing(self):
        assert guarded_ranges("if isEnabled('x') then call()", "lua") == []


class TestClaimsCarryTheFlag:
    def test_guarded_call_gets_the_flag_and_sibling_does_not(self):
        sink = IngestSink()
        emit_source_claims("r", _file("src/checkout.py", "python"),
                           PY_GUARDED, [], "file:1", sink)
        claims = dict(http_claims(sink))
        assert claims["httpcall:POST:/v2/charge"].get("flag") == "checkout-v2"
        assert "flag" not in claims["httpcall:POST:/v1/charge"]

    def test_typescript_guard(self):
        sink = IngestSink()
        emit_source_claims("r", _file("src/checkout.ts", "typescript"),
                           TS_GUARDED, [], "file:1", sink)
        claims = dict(http_claims(sink))
        # A bare fetch() is a GET; the method is beside the point here.
        assert claims["httpcall:GET:/v2/charge"].get("flag") == "checkout-v2"
        assert "flag" not in claims["httpcall:GET:/v1/charge"]

    def test_file_without_flag_api_never_parses_an_ast(self):
        # The prefilter is the contract: no flag token, no AST cost.
        sites = [SimpleNamespace(line=1, attrs={})]
        out = annotate_flag_guards(sites, "plain code, no flags", "python")
        assert out[0].attrs == {}


class TestEdgeCarriesCondition:
    def test_condition_rides_the_edge(self):
        from tests.test_alias_suggestions import calls_service_edges, claim
        from tracekite.services.linker.engine import link

        estate = [
            claim("svcname", "provides", "proj:web", repo="repo_web",
                  attrs={"source": "compose", "build_context": "."}),
            claim("svcname", "provides", "proj:payments",
                  repo="repo_payments",
                  attrs={"source": "compose", "build_context": "."}),
            claim("http", "provides", "POST:/v2/charge",
                  repo="repo_payments", enode="node:endpoint"),
            claim("http", "consumes", "httpcall:POST:/v2/charge",
                  repo="repo_web", hint="payments", enode="node:callsite",
                  attrs={"flag": "checkout-v2"}),
            claim("svcname", "consumes", "discovery:payments",
                  repo="repo_web", hint="payments"),
        ]
        result = link(estate, now="2026-01-01T00:00:00+00:00", aliases={},
                      promotions=[])
        [invoke] = [e for e in result.edges if e.type == "INVOKES"]
        assert invoke.extra_props["condition"] == "flag:checkout-v2"
        # Conditional is a rider, not a discount: the wiring is real.
        [cs] = calls_service_edges(result)
        assert cs.status == "active"
