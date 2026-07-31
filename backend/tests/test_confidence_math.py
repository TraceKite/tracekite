"""Intervals and how they compound.

The number under test is the honest half of every confidence this project
serves: 1.000 measured once and 1.000 measured 189 times must produce
visibly different intervals, and a six-hop chain must not inherit its
strongest link's confidence.
"""

import pytest

from adduce.services.linker.confidence_math import (
    path_confidence, wilson_interval,
)


class TestWilson:
    def test_one_success_in_one_trial_is_barely_a_claim(self):
        lo, hi = wilson_interval(1, 1)
        assert lo == pytest.approx(0.2065, abs=1e-4)
        assert hi == 1.0

    def test_the_flagship_number_is_a_tight_claim(self):
        """189 TP / 0 FP: the goal's precision statement, as an interval."""
        lo, hi = wilson_interval(189, 189)
        assert lo == pytest.approx(0.9801, abs=1e-4)
        assert hi == 1.0

    def test_zero_successes_bounds_from_above(self):
        lo, hi = wilson_interval(0, 1)
        assert lo == 0.0
        assert hi == pytest.approx(0.7935, abs=1e-4)

    def test_no_trials_bounds_nothing(self):
        """No data claims nothing; a narrower answer would be an invented
        measurement."""
        assert wilson_interval(0, 0) == (0.0, 1.0)

    def test_more_support_narrows_the_interval(self):
        widths = [wilson_interval(n, n)[1] - wilson_interval(n, n)[0]
                  for n in (1, 3, 10, 100)]
        assert widths == sorted(widths, reverse=True)

    def test_impossible_counts_raise(self):
        with pytest.raises(ValueError):
            wilson_interval(2, 1)


class TestPathConfidence:
    def test_six_hops_at_point_nine_is_not_a_point_nine_path(self):
        """The exit criterion, in one number."""
        result = path_confidence([0.9] * 6)
        assert result["compounded"] == pytest.approx(0.5314, abs=1e-4)
        assert result["weakest_hop"] == 0.9
        assert result["hops"] == 6

    def test_intervals_multiply_hop_by_hop(self):
        result = path_confidence([(0.9, 0.8, 1.0), (0.9, 0.8, 1.0)])
        assert result["compounded"] == pytest.approx(0.81)
        assert result["lo"] == pytest.approx(0.64)
        assert result["hi"] == 1.0

    def test_the_weakest_hop_is_named_beside_the_product(self):
        """Different questions: the product says how much to trust the
        chain, the weakest hop says where to look first."""
        result = path_confidence([0.95, 0.6, 0.95])
        assert result["weakest_hop"] == 0.6
        assert result["compounded"] == pytest.approx(0.5415)

    def test_a_single_hop_compounds_to_itself(self):
        result = path_confidence([0.85])
        assert result["compounded"] == 0.85
        assert result["lo"] == 0.85 and result["hi"] == 0.85

    def test_zero_hops_is_not_a_confident_path(self):
        """Confidence 1.0 for the empty chain would bless every question
        about a path that does not exist."""
        assert path_confidence([])["compounded"] == 0.0
