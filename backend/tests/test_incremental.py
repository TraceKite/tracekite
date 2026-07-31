"""Claim-level invalidation produces the full link's answer.

The contract is equivalence, and the test substrate is the calibration
estates — constructed truth covering every resolver family. Each estate is
mutated one claim at a time (dropped, edited, added) and `relink()` must
produce exactly the edges and rendezvous `link()` produces from scratch.
An incremental result that drifts from the full one is worse than a slow
link: it is a graph whose content depends on the order changes arrived.
"""

import dataclasses

import pytest

from adduce.services.calibration import build_estates
from adduce.services.linker.engine import link
from adduce.services.linker.incremental import changed_kinds, relink

NOW = "2026-01-01T00:00:00+00:00"


def edge_view(edges):
    return sorted((e.type, e.source_id, e.target_id, e.status,
                   round(float(e.confidence), 6),
                   tuple(sorted(e.evidence or [])))
                  for e in edges)


def spec_view(specs):
    return sorted((s.label, s.node_id,
                   tuple(sorted((k, str(v)) for k, v in s.props.items())))
                  for s in specs)


def full(claims, run_id="linkrun_full"):
    return link(claims, run_id=run_id, confidence={}, aliases={},
                promotions=[], now=NOW)


def incremental(claims, prior_claims, prior, run_id="linkrun_incr"):
    return relink(claims, prior_claims, prior, run_id=run_id, now=NOW,
                  confidence={}, aliases={}, promotions=[])


def mutations(claims):
    """Three ways one claim can change, plus the no-op."""
    if not claims:
        return
    dropped = claims[1:]
    yield "drop_first", dropped

    edited = [dataclasses.replace(
        claims[0], evidence=[e.rsplit(":", 1)[0] + ":999"
                             for e in claims[0].evidence])] + claims[1:]
    yield "edit_evidence", edited

    added = claims + [dataclasses.replace(
        claims[0], id=claims[0].id + "_new", key=claims[0].key + "-new")]
    yield "add_claim", added

    yield "no_change", list(claims)


ESTATES = build_estates()


@pytest.mark.parametrize("estate", ESTATES, ids=lambda e: e.name)
def test_every_mutation_matches_the_full_link(estate):
    prior_claims = list(estate.claims)
    prior = full(prior_claims, run_id="linkrun_prior")
    for label, mutated in mutations(prior_claims):
        expected = full(mutated)
        got = incremental(mutated, prior_claims, prior)
        assert edge_view(got.edges) == edge_view(expected.edges), (
            f"{estate.name}/{label}: incremental edges diverged from the "
            "full link — the graph now depends on the order changes arrived")
        assert spec_view(got.rendezvous) == spec_view(expected.rendezvous), (
            f"{estate.name}/{label}: rendezvous diverged")


class TestOnlyTouchedPartitionsReResolve:
    """The exit criterion, asserted on the counters the run itself emits."""

    def _mixed_claims(self):
        """Two resolver families in one estate, so a change in one leaves
        the other's partition untouched."""
        http = next(e for e in ESTATES if e.name == "http_hint_tiers")
        agents = next(e for e in ESTATES if e.name == "agents_r11")
        return list(http.claims) + list(agents.claims)

    def test_an_unchanged_estate_re_resolves_no_claims(self):
        claims = self._mixed_claims()
        prior = full(claims, run_id="linkrun_prior")
        got = incremental(list(claims), claims, prior)
        # The service-call fusion clique (r5, r9) reruns every time by
        # design; this estate holds none of their claims, so the rerun is
        # over nothing — which is the honest zero.
        assert got.counters["incremental.resolvers_rerun"] == 2
        assert got.counters["incremental.claims_reresolved"] == 0
        assert got.counters["incremental.edges_kept"] > 0
        assert edge_view(got.edges) == edge_view(full(claims).edges)

    def test_an_http_change_does_not_re_resolve_the_agents(self):
        claims = self._mixed_claims()
        prior = full(claims, run_id="linkrun_prior")
        dropped = next(c for c in claims if c.kind == "http")
        mutated = [c for c in claims if c.id != dropped.id]
        got = incremental(mutated, claims, prior)

        assert edge_view(got.edges) == edge_view(full(mutated).edges)
        assert got.counters["incremental.claims_reresolved"] \
            == sum(1 for c in mutated if c.kind == "http")
        assert got.counters["incremental.edges_kept"] > 0, (
            "the agents partition was re-resolved for an http change")

    def test_a_broadcast_change_falls_back_to_full_and_says_so(self):
        estate = next(e for e in ESTATES if e.name == "compose_topology")
        prior_claims = list(estate.claims)
        prior = full(prior_claims, run_id="linkrun_prior")
        # Dropping a svcname claim moves the service tables every partition
        # reads; keeping anything would assert edges from stale evidence.
        mutated = [c for c in prior_claims if c.kind != "svcname"] \
            + [c for c in prior_claims if c.kind == "svcname"][1:]
        got = incremental(mutated, prior_claims, prior)
        assert got.counters.get("incremental.broadcast_changed") == 1
        assert got.counters["incremental.edges_kept"] == 0
        assert edge_view(got.edges) == edge_view(full(mutated).edges)

    def test_a_registered_host_resolver_forces_full(self):
        """A host resolver's input kinds are unknown here; keeping anything
        would guess at what it reads. Guessing wrong keeps a stale edge."""
        from adduce.services.linker.engine import (
            clear_registered_resolvers, register_resolver,
        )
        from adduce.services.linker.values import ResolverOutput

        class Hosted:
            def resolve(self, index, ctx):
                return ResolverOutput()

        estate = ESTATES[0]
        prior = full(estate.claims, run_id="linkrun_prior")
        register_resolver("r_host", Hosted(), phase="join")
        try:
            got = incremental(list(estate.claims), estate.claims, prior)
        finally:
            clear_registered_resolvers()
        assert got.counters.get("incremental.registered_resolver") == 1
        assert got.counters["incremental.edges_kept"] == 0


class TestChangedKinds:
    def test_an_edit_dirties_its_kind(self):
        estate = ESTATES[0]
        edited = [dataclasses.replace(estate.claims[0], attrs={"x": 1})] \
            + list(estate.claims[1:])
        assert estate.claims[0].kind in changed_kinds(estate.claims, edited)

    def test_a_kind_change_dirties_both(self):
        estate = ESTATES[0]
        moved = [dataclasses.replace(estate.claims[0], kind="dataset")] \
            + list(estate.claims[1:])
        dirty = changed_kinds(estate.claims, moved)
        assert estate.claims[0].kind in dirty and "dataset" in dirty

    def test_identical_estates_dirty_nothing(self):
        estate = ESTATES[0]
        assert changed_kinds(estate.claims, list(estate.claims)) == set()
