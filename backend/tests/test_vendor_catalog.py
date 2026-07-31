"""External hosts are classified, not dropped.

A call to `api.stripe.com` is qualified — the source names a host — but no
internal service answers, so the join declines and the call used to vanish
into `r7.unmatched_qualified`, indistinguishable from a broken internal call.

Classifying is not linking. Every assertion here is about *counters*; nothing
in this feature can emit an edge, which is why it was safe to add to a
resolver at all.
"""

import pytest

from adduce.services.linker.base import ClaimIndex, ClaimRecord, LinkContext
from adduce.services.linker.engine import run_resolvers
from adduce.services.linker.vendors import (
    Vendor, classify, load_vendors, looks_external,
)


@pytest.fixture(scope="module")
def catalog():
    table = load_vendors()
    assert table, "config/vendor_catalog.yml must load, or nothing is tested"
    return table


class TestClassify:
    def test_known_vendor_is_named(self, catalog):
        assert classify("api.stripe.com", catalog).name == "stripe"

    def test_classification_carries_a_category(self, catalog):
        assert classify("api.stripe.com", catalog).category == "payments"

    def test_subdomain_matches_by_suffix(self, catalog):
        assert classify("my-bucket.s3.amazonaws.com", catalog).name == "aws_s3"

    def test_case_and_trailing_slash_do_not_matter(self, catalog):
        assert classify("API.Stripe.com/", catalog).name == "stripe"

    def test_longest_suffix_wins(self):
        table = {"stripe.com": Vendor("short", "x"),
                 "files.stripe.com": Vendor("long", "y")}
        assert classify("files.stripe.com", table).name == "long"

    def test_unknown_host_is_not_guessed_at(self, catalog):
        """Naming it after the nearest vendor would invent a dependency."""
        assert classify("api.some-startup.example", catalog) is None

    def test_empty_inputs_return_nothing(self, catalog):
        assert classify("", catalog) is None
        assert classify("api.stripe.com", {}) is None


class TestLooksExternal:
    @pytest.mark.parametrize("host", [
        "api.stripe.com", "my-bucket.s3.amazonaws.com", "example.com"])
    def test_routable_hosts(self, host):
        assert looks_external(host) is True

    @pytest.mark.parametrize("name", [
        "billing", "order-service", "vets-service",
        "billing.default.svc", "postgres.internal"])
    def test_internal_service_names_are_not_hosts(self, name):
        """The conservative direction. Misreading an internal name as
        external files a genuine missing edge under 'third party' and stops
        anyone from looking for it."""
        assert looks_external(name) is False


def claim(cid, repo, kind, direction, key, **kw):
    return ClaimRecord(
        id=cid, repo_id=repo, kind=kind, direction=direction, key=key,
        service_hint=kw.get("hint"), hint_source=kw.get("src", "none"),
        matchable=True, evidence=[kw.get("ev", "src/client.py:7")], attrs={},
        evidence_node_id=f"n{cid}", evidence_node_type="File")


class TestCountedDuringALinkRun:
    def _counters(self, host):
        claims = [
            claim("s1", "repo_a", "svcname", "provides", "compose:orders",
                  hint="orders", src="compose"),
            # `httpcall:METHOD:template` is the key NORMALIZE parses; the
            # host arrives as the service hint, which is what makes the call
            # qualified and therefore eligible to be classified when it
            # matches nothing internal.
            claim("h1", "repo_a", "http", "consumes",
                  "httpcall:GET:/v1/charges", hint=host, src="host"),
        ]
        ctx = LinkContext("linkrun_c2", {}, {})
        ctx.known_repos = {"repo_a"}
        run_resolvers(ClaimIndex(claims), ctx)
        return dict(ctx.counters)

    def test_a_known_vendor_is_named_in_the_counters(self):
        counters = self._counters("api.stripe.com")
        assert counters.get("r7.vendor.stripe", 0) >= 1, counters
        assert counters.get("r7.external_vendor", 0) >= 1, counters

    def test_an_unknown_external_host_is_counted_separately(self):
        counters = self._counters("api.unknown-vendor.example")
        assert counters.get("r7.external_unknown", 0) >= 1, counters
        assert "r7.external_vendor" not in counters, counters

    def test_no_edge_is_ever_emitted_for_an_external_call(self):
        """The whole safety argument: this runs only where the resolver had
        already declined, so precision cannot move."""
        claims = [
            claim("s1", "repo_a", "svcname", "provides", "compose:orders",
                  hint="orders", src="compose"),
            claim("h1", "repo_a", "http", "consumes",
                  "httpcall:GET:/v1/charges",
                  hint="api.stripe.com", src="host"),
        ]
        ctx = LinkContext("linkrun_c2", {}, {})
        ctx.known_repos = {"repo_a"}
        out = run_resolvers(ClaimIndex(claims), ctx)
        assert not [e for e in out.edges if "stripe" in e.target_id.lower()]
