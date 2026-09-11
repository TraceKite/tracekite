"""A loss that is counted must survive being totalled.

Per-language coverage accepts any counter an extractor adds, but the totals
written beside it were built from a hardcoded key list, so every counter
added after that list was written was summed into nothing.

The case that found it: GoogleCloudPlatform/microservices-demo registers
thirteen gorilla/mux routes whose paths are computed, the Go entry recorded
`endpoints_computed_path: 13`, and the totals still read `endpoints: 0`
with no companion — the decline was counted and then discarded one layer
above the only reader who would act on it.
"""

import json
from unittest.mock import MagicMock, patch

from evigraph.services.ingestion_service import _stamp_coverage


def stamp(coverage, claims=None):
    """Return the totals `_stamp_coverage` would write, decoded."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    with patch("evigraph.services.ingestion_service.get_session", return_value=ctx):
        _stamp_coverage("r1", coverage, claims)
    return json.loads(session.run.call_args.kwargs["totals"])


class TestEveryCounterIsTotalled:
    def test_a_counter_no_list_knows_about_still_totals(self):
        totals = stamp({
            "Go": {"files_seen": 29, "files_parsed": 29, "endpoints": 0,
                   "endpoints_computed_path": 13, "tier": "full"},
        })
        assert totals["endpoints_computed_path"] == 13

    def test_counters_sum_across_languages(self):
        totals = stamp({
            "Go": {"files_seen": 29, "endpoints_computed_path": 13},
            "Ruby": {"files_seen": 4, "endpoints_computed_path": 2},
        })
        assert totals["files_seen"] == 33
        assert totals["endpoints_computed_path"] == 15

    def test_the_established_keys_are_unchanged(self):
        totals = stamp({
            "Go": {"files_seen": 10, "files_parsed": 8, "parse_errors": 1,
                   "files_skipped_large": 0, "entities": 40, "endpoints": 3,
                   "imports_unemitted": 12, "tier": "full"},
        }, {"http": 5, "lib": 7})
        assert totals["files_seen"] == 10
        assert totals["files_parsed"] == 8
        assert totals["parse_errors"] == 1
        assert totals["entities"] == 40
        assert totals["endpoints"] == 3
        assert totals["imports_unemitted"] == 12
        assert totals["claims"] == 12
        assert totals["files_unparsed"] == 2


class TestNonCountersAreNotSummed:
    def test_tier_is_a_label_not_a_measurement(self):
        totals = stamp({"Go": {"files_seen": 1, "tier": "full"}})
        assert "tier" not in totals

    def test_a_boolean_is_not_summed_as_one(self):
        """`True + True == 2` would report a flag as a quantity."""
        totals = stamp({"Go": {"files_seen": 1, "degraded": True}})
        assert "degraded" not in totals
