"""The benchmark emits comparable numbers.

What makes two commits' benchmarks comparable is pinned: the workload is
seeded (same estate both times), the report normalises per 100k LOC, and
every stage measures in its own process — getrusage's high-water mark
never goes down, so one process would charge the link with the scan's
peak.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tools.benchmark import benchmark, count_loc  # noqa: E402


class TestBenchmark:
    def test_the_report_is_schema_complete(self):
        report = benchmark(repos=4, seed=7)
        assert report["estate"]["loc"] > 0
        for stage in ("scan", "link"):
            assert report[stage]["seconds"] >= 0
            assert report[stage]["peak_kib"] > 0
        for key in ("scan_seconds", "link_seconds",
                    "scan_peak_mib", "link_peak_mib"):
            assert report["per_100k_loc"][key] >= 0

    def test_the_workload_is_identical_across_runs(self):
        """Two commits must measure the same estate, or the numbers
        compare machines and noise instead of code."""
        first = benchmark(repos=4, seed=7)
        second = benchmark(repos=4, seed=7)
        assert first["estate"]["loc"] == second["estate"]["loc"]
        assert first["scan"]["artifacts"] == second["scan"]["artifacts"]
        assert first["link"]["claims"] == second["link"]["claims"]
        assert first["link"]["edges"] == second["link"]["edges"]

    def test_loc_counts_lines_not_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
        (tmp_path / "b.py").write_text("z = 3\n")
        assert count_loc(str(tmp_path)) == 3
