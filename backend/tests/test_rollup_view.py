"""The aggregate view folds honestly.

A group box is a summary someone will trust without opening it, so every
fold rule is a place to lie: a mean confidence would hide a weak edge
among strong ones, a dropped intra-group call would make the busiest
domain look quiet, and scattering unowned services would erase the finding
that nobody owns them.
"""

import pytest

from adduce.services.linker.rollup_view import (
    aggregate_service_map, domain_of,
)

SERVICES = [
    {"id": "s1", "name": "billing-api"},
    {"id": "s2", "name": "billing-worker"},
    {"id": "s3", "name": "orders-api"},
    {"id": "s4", "name": "auth"},
]


def edge(source, target, confidence=0.9, type_="CALLS_SERVICE"):
    return {"source": source, "target": target, "confidence": confidence,
            "type": type_}


class TestDomainGrouping:
    def test_shared_prefixes_fold_into_one_box(self):
        result = aggregate_service_map(SERVICES, [])
        assert [g["id"] for g in result["groups"]] == [
            "auth", "billing", "orders"]
        billing = result["groups"][1]
        assert billing["services"] == ["billing-api", "billing-worker"]
        assert billing["size"] == 2

    def test_cross_group_edges_roll_up_with_weight(self):
        result = aggregate_service_map(SERVICES, [
            edge("s1", "s3"), edge("s2", "s3")])
        assert result["edges"] == [{
            "source": "billing", "target": "orders", "weight": 2,
            "min_confidence": 0.9, "types": ["CALLS_SERVICE"]}]

    def test_group_confidence_is_the_minimum_not_the_mean(self):
        """An aggregate is only as trustworthy as its least trustworthy
        member; a mean lets one weak edge hide inside strong neighbours."""
        # Weak edge FIRST: a fold that keeps the last-seen value instead
        # of the minimum reports 0.95 here and hides the 0.62.
        result = aggregate_service_map(SERVICES, [
            edge("s2", "s3", 0.62), edge("s1", "s3", 0.95)])
        assert result["edges"][0]["min_confidence"] == 0.62

    def test_intra_group_calls_are_counted_not_dropped(self):
        """A group that looks quiet from outside may be the busiest thing
        in the estate."""
        result = aggregate_service_map(SERVICES, [edge("s1", "s2")])
        billing = next(g for g in result["groups"] if g["id"] == "billing")
        assert billing["internal_edges"] == 1
        assert result["edges"] == []

    def test_an_edge_to_a_non_service_is_counted_not_misfiled(self):
        result = aggregate_service_map(SERVICES, [
            edge("s1", "global:Topic:orders")])
        assert result["non_service_edges"] == 1
        assert result["edges"] == []


class TestTeamGrouping:
    def test_ownership_groups_and_the_unowned_are_named(self):
        result = aggregate_service_map(
            SERVICES, [], by="team",
            ownership={"s1": "payments", "s2": "payments"})
        assert [g["id"] for g in result["groups"]] == [
            "(unowned)", "payments"]
        unowned = result["groups"][0]
        assert unowned["services"] == ["auth", "orders-api"]

    def test_no_ownership_at_all_is_one_honest_box(self):
        """An estate that declared no owners renders as exactly that — not
        an error, and not a guess."""
        result = aggregate_service_map(SERVICES, [], by="team",
                                       ownership=None)
        assert [g["id"] for g in result["groups"]] == ["(unowned)"]

    def test_an_unknown_grouping_raises(self):
        with pytest.raises(ValueError):
            aggregate_service_map(SERVICES, [], by="vibes")


class TestDomainOf:
    def test_prefix_rules(self):
        assert domain_of("billing-api") == "billing"
        assert domain_of("auth") == "auth"
        assert domain_of("") == "(unnamed)"


class TestScale:
    def test_a_thousand_services_become_dozens_of_boxes(self):
        """The exit criterion: navigable without per-service rendering."""
        services = [{"id": f"s{i}", "name": f"domain{i % 40}-svc-{i}"}
                    for i in range(1000)]
        edges = [edge(f"s{i}", f"s{(i * 7 + 1) % 1000}")
                 for i in range(1000)]
        result = aggregate_service_map(services, edges)
        assert len(result["groups"]) == 40
        assert sum(g["size"] for g in result["groups"]) == 1000
        rolled = sum(e["weight"] for e in result["edges"]) \
            + sum(g["internal_edges"] for g in result["groups"])
        assert rolled == 1000, "an edge was dropped on the way up"
