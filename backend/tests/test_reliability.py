"""E5: constants derived from labels, not chosen — and the derivation bites.

The property under test is the learning DIRECTION: clean evidence leaves a
design prior standing (recorded as prior, visibly unproven), while a single
labelled false positive drags the tier's evidence ceiling below the served
constant and the derivation demands the constant follow it down. Volume of
clean labels never inflates a number.
"""

from evigraph.services.linker.reliability import (
    derive_constants, derived_block_lines, pool_labels,
)

SERVED = {"r7": {"hint_exact": 0.95, "exposes": 0.98},
          "r5": {"declared": 0.98}}

MEASURED = [
    {"tier": "r7.hint_exact", "support": 3, "recall": 1.0, "fp": 0},
    {"tier": "r7.exposes", "support": 2, "recall": 1.0, "fp": 0},
    {"tier": "r5.declared", "support": 2, "recall": 1.0, "fp": 0},
]

NO_LABELS = {"tp": [], "fp": [], "unusable": []}


def _row(derivation, tier):
    return next(r for r in derivation["rows"] if r["tier"] == tier)


class TestPooling:
    def test_measured_rows_pool_per_tier_and_per_resolver(self):
        pools = pool_labels(MEASURED, NO_LABELS)
        assert pools["tier"]["r7.hint_exact"] == {"tp": 3, "fp": 0}
        assert pools["resolver"]["r7"] == {"tp": 5, "fp": 0}
        assert pools["global"] == {"tp": 7, "fp": 0}

    def test_tiered_review_label_sharpens_its_tier(self):
        labels = {**NO_LABELS, "fp": [{"tier": "r7.hint_exact"}]}
        pools = pool_labels(MEASURED, labels)
        assert pools["tier"]["r7.hint_exact"] == {"tp": 3, "fp": 1}
        assert pools["resolver"]["r7"]["fp"] == 1

    def test_unattributed_label_pools_globally_only(self):
        labels = {**NO_LABELS, "fp": [{"tier": ""}]}
        pools = pool_labels(MEASURED, labels)
        assert pools["unattributed"] == {"tp": 0, "fp": 1}
        assert pools["global"]["fp"] == 1
        # No tier and no resolver was indicted by it.
        assert all(p["fp"] == 0 for p in pools["tier"].values())
        assert all(p["fp"] == 0 for p in pools["resolver"].values())

    def test_malformed_tier_string_is_unattributed_not_fatal(self):
        labels = {**NO_LABELS, "fp": [{"tier": "not-a-tier"}]}
        pools = pool_labels(MEASURED, labels)
        assert pools["unattributed"]["fp"] == 1


class TestDerivation:
    def test_clean_evidence_leaves_priors_standing_and_says_so(self):
        derivation = derive_constants(SERVED, MEASURED, NO_LABELS)
        for row in derivation["rows"]:
            assert row["derived"] == row["served"]
            assert row["basis"] == "prior"

    def test_an_fp_label_drags_the_constant_down_when_it_contradicts(self):
        labels = {**NO_LABELS, "fp": [{"tier": "r7.exposes"}]}
        derivation = derive_constants(SERVED, MEASURED, labels)
        row = _row(derivation, "r7.exposes")
        # wilson_hi(2 tp, 1 fp) = 0.9385 < 0.98: the ceiling binds.
        assert row["derived"] < row["served"]
        assert row["basis"] == "tier_evidence"

    def test_a_ceiling_is_a_measurement_not_a_punishment(self):
        # 1 FP in 4 trials gives wilson_hi 0.9544 — it does NOT contradict
        # a served 0.95 at 95% confidence, so the prior stands. The
        # derivation only moves a constant the labels actually refute.
        labels = {**NO_LABELS, "fp": [{"tier": "r7.hint_exact"}]}
        derivation = derive_constants(SERVED, MEASURED, labels)
        row = _row(derivation, "r7.hint_exact")
        assert row["derived"] == row["served"] == 0.95
        assert row["basis"] == "prior"

    def test_resolver_fp_caps_sibling_tiers(self):
        # The FP is on hint_exact, but r7's pooled evidence also bounds
        # exposes: a resolver caught wrong anywhere is suspect everywhere.
        labels = {**NO_LABELS,
                  "fp": [{"tier": "r7.hint_exact"}] * 3}
        derivation = derive_constants(SERVED, MEASURED, labels)
        sibling = _row(derivation, "r7.exposes")
        assert sibling["derived"] < sibling["served"]
        assert sibling["basis"] == "resolver_evidence"
        # r5 shares no evidence with r7 and is untouched.
        assert _row(derivation, "r5.declared")["basis"] == "prior"

    def test_clean_volume_never_inflates_a_constant(self):
        labels = {**NO_LABELS,
                  "tp": [{"tier": "r7.hint_exact"}] * 500}
        derivation = derive_constants(SERVED, MEASURED, labels)
        assert _row(derivation, "r7.hint_exact")["derived"] == 0.95

    def test_block_lines_parse_and_carry_the_verdict(self):
        import yaml
        labels = {**NO_LABELS, "fp": [{"tier": ""}]}
        derivation = derive_constants(SERVED, MEASURED, labels)
        block = yaml.safe_load("\n".join(derived_block_lines(derivation)))
        assert block["derived"]["unattributed_labels"] == {"tp": 0, "fp": 1}
        assert block["derived"]["rows"]["r7.hint_exact"]["basis"] == "prior"
