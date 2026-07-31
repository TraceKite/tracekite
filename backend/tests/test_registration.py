"""A host extends the engine without forking it.

Every estate wires services together differently, and the parsers and
resolvers that ship here reflect the systems the authors happened to have. A
host with an in-house framework must be able to add one — otherwise the only
route is a fork, and a forked engine stops receiving fixes.

The registration must not weaken anything. A registered resolver runs in a
declared phase, and its declines are attributable to it by name: an extension
that dropped claims anonymously would be indistinguishable from the engine
finding nothing, which is the failure this project treats as worst.
"""

import pytest

from adduce.parsers.parser_registry import (
    clear_registered_parsers, get_parser_for_file, register_parser,
    registered_parsers,
)
from adduce.services.linker.base import ClaimIndex, ClaimRecord, LinkContext
from adduce.services.linker.engine import (
    clear_registered_resolvers, register_resolver, registered_resolvers,
    run_resolvers,
)


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registered_parsers()
    clear_registered_resolvers()
    yield
    clear_registered_parsers()
    clear_registered_resolvers()


class ThirdPartyParser:
    """What a host would write for an in-house framework."""

    def __init__(self):
        self.seen = []

    def parse(self, path, content):
        self.seen.append(path)
        return {"handled_by": "third-party"}


class TestParserRegistration:
    def test_a_third_party_parser_is_used(self):
        parser = ThirdPartyParser()
        register_parser(parser, [".inhouse"])
        assert get_parser_for_file("src/thing.inhouse") is parser

    def test_extensions_normalise(self):
        parser = ThirdPartyParser()
        register_parser(parser, ["INHOUSE"])
        assert get_parser_for_file("a.inhouse") is parser

    def test_registration_beats_a_builtin_for_the_same_extension(self):
        """A host that went to the trouble means it."""
        builtin = get_parser_for_file("a.py")
        assert builtin is not None
        parser = ThirdPartyParser()
        register_parser(parser, [".py"])
        assert get_parser_for_file("a.py") is parser

    def test_builtins_still_serve_everything_else(self):
        register_parser(ThirdPartyParser(), [".inhouse"])
        assert get_parser_for_file("a.py") is not None

    def test_a_parser_without_parse_is_refused_at_registration(self):
        """Not at the first file, which is far from the mistake."""
        with pytest.raises(TypeError, match="no parse"):
            register_parser(object(), [".x"])

    def test_a_parser_for_no_extension_is_refused(self):
        with pytest.raises(ValueError, match="never run"):
            register_parser(ThirdPartyParser(), [])

    def test_registrations_are_reportable(self):
        register_parser(ThirdPartyParser(), [".inhouse"])
        assert registered_parsers()


class ThirdPartyResolver:
    """A join rule a host would add. Declines, and says so."""

    RESOLVER_ID = "resolver.inhouse@1"

    def __init__(self):
        self.ran = False

    def resolve(self, index, ctx):
        from adduce.services.linker.base import ResolverOutput

        self.ran = True
        for claim in index.kind("svcname"):
            # Declining is the interesting path: it must be counted, or the
            # extension is silently dropping claims.
            ctx.count("inhouse.unmatched")
        return ResolverOutput()


def claim(cid, key, hint):
    return ClaimRecord(
        id=cid, repo_id="r1", kind="svcname", direction="provides", key=key,
        service_hint=hint, hint_source="compose", matchable=True,
        evidence=["a.yml:1"], attrs={}, evidence_node_id=f"n{cid}",
        evidence_node_type="File")


class TestResolverRegistration:
    def _run(self):
        ctx = LinkContext("linkrun_reg", {}, {})
        ctx.known_repos = {"r1"}
        run_resolvers(ClaimIndex([claim("c1", "compose:billing", "billing")]),
                      ctx)
        return ctx

    def test_a_registered_resolver_runs(self):
        resolver = ThirdPartyResolver()
        register_resolver("inhouse", resolver)
        self._run()
        assert resolver.ran is True

    def test_its_declines_are_counted(self):
        """A7's exit: registered, and declines counted."""
        register_resolver("inhouse", ThirdPartyResolver())
        ctx = self._run()
        assert ctx.counters.get("inhouse.unmatched", 0) >= 1, ctx.counters

    def test_the_run_names_which_extensions_took_part(self):
        """A graph built with host extensions must not be mistaken for one
        built by the shipped resolvers alone."""
        register_resolver("inhouse", ThirdPartyResolver())
        ctx = self._run()
        assert ctx.counters.get("registered.inhouse", 0) >= 1

    def test_broadcast_and_join_are_separate_phases(self):
        register_resolver("early", ThirdPartyResolver(), phase="broadcast")
        register_resolver("late", ThirdPartyResolver(), phase="join")
        assert registered_resolvers() == {"broadcast": ["early"],
                                          "join": ["late"]}

    def test_an_unknown_phase_is_refused(self):
        with pytest.raises(ValueError, match="broadcast"):
            register_resolver("x", ThirdPartyResolver(), phase="whenever")

    def test_a_resolver_without_resolve_is_refused(self):
        """It would be skipped silently at link time — the one thing a
        registration must not allow."""
        with pytest.raises(TypeError, match="no resolve"):
            register_resolver("x", object())

    def test_a_duplicate_name_is_refused(self):
        """Two resolvers under one name make their counters
        indistinguishable, which defeats the point of naming them."""
        register_resolver("inhouse", ThirdPartyResolver())
        with pytest.raises(ValueError, match="already registered"):
            register_resolver("inhouse", ThirdPartyResolver())

    def test_builtin_resolvers_still_run(self):
        register_resolver("inhouse", ThirdPartyResolver())
        ctx = self._run()
        assert ctx.counters.get("r0.services", 0) >= 1, ctx.counters
