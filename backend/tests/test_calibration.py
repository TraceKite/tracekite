"""M11 calibration harness: labeled estates -> per-tier P/R rows.

The estates are constructed truth, so a false positive here is a REAL resolver
bug, not a fixture problem — failure messages therefore name the estate and
edge. write_measured must never disturb the flat tier table ctx.conf() reads.
"""

import os
import shutil
import subprocess
import sys

import pytest
import yaml

from adduce.services.calibration import build_estates, run_calibration
from adduce.services.calibration_io import (
    MEASURED_MARKER, coverage_gaps, write_measured,
)
from adduce.services.linker.base import config_dir

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(config_dir(), "confidence.yml")

# Tiers the harness must at minimum produce measured rows for.
CORE_TIERS = ("r5.declared", "r5.exact", "r7.hint_exact", "r6.literal",
              "r6.declared", "r3.publishes", "r12.catalog",
              "r2.selector_match")


@pytest.fixture(scope="module")
def results() -> dict:
    return run_calibration()


def _rows(results):
    for section in sorted(k for k in results if not k.startswith("_")):
        for tier, row in sorted(results[section].items()):
            yield f"{section}.{tier}", row


class TestRunCalibration:
    def test_core_tiers_have_rows(self, results):
        have = {key for key, _ in _rows(results)}
        missing = [tier for tier in CORE_TIERS if tier not in have]
        assert not missing, (
            f"No measured row for {missing}; estates produced rows for "
            f"{sorted(have)}")

    def test_every_measured_precision_is_one(self, results):
        # Fixtures are constructed truth — an FP is a real resolver bug, so
        # the failure must say which estate emitted which forbidden edge.
        forbidden = results["_diagnostics"]["forbidden"]
        bad = {key: row for key, row in _rows(results)
               if row["precision"] != 1.0}
        assert not bad, (
            f"Resolver produced forbidden edges (precision<1.0 on {bad}). "
            f"Offending estate+edge: {forbidden}")

    def test_no_expected_edge_is_missing(self, results):
        # Recall over constructed truth must be perfect too; a miss means the
        # estate or the resolver regressed. Name the estate and expectation.
        missing = results["_diagnostics"]["missing"]
        assert not missing, f"Expected edges not produced: {missing}"
        for key, row in _rows(results):
            assert row["recall"] == 1.0, (key, row)

    def test_rows_carry_support_and_fp(self, results):
        for key, row in _rows(results):
            assert set(row) == {"precision", "precision_lo", "precision_hi",
                                "recall", "support", "fp"}, key
            # F1: the interval is the honest half of the point estimate,
            # and it must actually bound it.
            assert row["precision_lo"] <= row["precision"] \
                <= row["precision_hi"], key
            assert row["support"] >= 1, f"{key} has no expectations"
            assert row["fp"] == 0, (key, row)

    def test_every_expectation_names_its_tier(self):
        for estate in build_estates():
            for spec in estate.expect + estate.forbid:
                assert "tier" in spec and "." in spec["tier"], (
                    estate.name, spec)


class TestWriteMeasured:
    @pytest.fixture()
    def tmp_config(self, tmp_path):
        target = tmp_path / "confidence.yml"
        shutil.copyfile(CONFIG_PATH, target)
        return str(target)

    def test_round_trips_and_preserves_flat_tiers(self, results, tmp_config):
        before = yaml.safe_load(open(tmp_config, encoding="utf-8"))
        write_measured(results, tmp_config)
        text = open(tmp_config, encoding="utf-8").read()
        after = yaml.safe_load(text)

        # The generated block parses and carries the rows.
        assert MEASURED_MARKER in text
        assert after["measured"]["corpus"] == "fixtures-v1"
        rows = after["measured"]["rows"]
        assert rows["r5.declared"]["precision"] == 1.0
        assert rows["r2.selector_match"]["support"] >= 1

        # Flat tiers (and everything else ctx.conf reads) are untouched.
        for key, value in before.items():
            if key in ("measured", "derived"):
                continue    # the generated tail; regenerated every run
            assert after[key] == value, f"write_measured altered {key!r}"
        # Comments above the marker survive byte-for-byte.
        assert text.split(MEASURED_MARKER)[0].startswith(
            "# Confidence registry")

    def test_rewrite_replaces_block_idempotently(self, results, tmp_config):
        write_measured(results, tmp_config)
        write_measured(results, tmp_config, corpus="fixtures-v2")
        text = open(tmp_config, encoding="utf-8").read()
        assert text.count(MEASURED_MARKER) == 1
        assert text.count("\nmeasured:") == 1
        assert yaml.safe_load(text)["measured"]["corpus"] == "fixtures-v2"


class TestCoverageGaps:
    def test_unreachable_tiers_are_listed_not_faked(self, results):
        gaps = coverage_gaps(results, CONFIG_PATH)
        # Every unreachable tier found during calibration was removed from
        # the table (r1.links, r2.dns_alias, r9.env_resolved_multi,
        # r0.built_from_config) — a priced-but-unreachable tier is the
        # schema fiction Invariant 7 forbids, so the gap list must be empty.
        assert gaps == []

    def test_no_measured_tier_is_reported_as_gap(self, results):
        gaps = set(coverage_gaps(results, CONFIG_PATH))
        measured = {key for key, _ in _rows(results)}
        assert not gaps & measured

    def test_gap_entries_are_flat_tier_names(self, results):
        table = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8"))
        for gap in coverage_gaps(results, CONFIG_PATH):
            section, _, tier = gap.partition(".")
            assert isinstance(table[section][tier], float), gap


class TestCli:
    def test_dry_run_exits_zero_and_prints_table(self):
        env = dict(os.environ)
        env.pop("GRAPH_HMAC_KEY", None)  # the CLI must set its own default
        proc = subprocess.run(
            [sys.executable, "-m", "tools.calibrate", "--dry-run"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
            timeout=300)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "r5.declared" in proc.stdout
        # F3 makes an unmeasured tier a build failure, so a zero exit now
        # certifies full coverage, not merely a printed table.
        assert "All served tiers have measured rows." in proc.stdout
        assert "--dry-run: not writing" in proc.stdout

    def test_an_unlabelled_tier_fails_the_build(self, tmp_path):
        """F3's exit criterion. A tier served without a labelled estate
        behind it is a number nobody measured; the gate turns "the rule
        everyone knows" into one a deadline cannot skip. Simulated by
        serving a tier no corpus labels."""
        import shutil

        config_dir = tmp_path / "config"
        shutil.copytree(os.path.join(BACKEND_DIR, "..", "config"),
                        config_dir)
        conf = config_dir / "confidence.yml"
        conf.write_text(open(conf, encoding="utf-8").read()
                        + "\nr99:\n  imaginary_tier: 0.9\n")

        env = dict(os.environ)
        env["KG_CONFIG_DIR"] = str(config_dir)
        proc = subprocess.run(
            [sys.executable, "-m", "tools.calibrate", "--dry-run"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
            timeout=300)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "UNLABELLED TIER(S) SERVED" in proc.stderr
        assert "r99.imaginary_tier" in proc.stderr

    def test_a_labelled_fp_forces_the_constant_down(self, tmp_path):
        """E5's exit criterion from the failing side: a reviewer rejects an
        r7.exposes edge, the tier's evidence ceiling drops below its served
        0.98, and calibrate refuses until the constant follows the labels.
        A human can no longer keep a number the evidence contradicts."""
        import shutil

        config_dir = tmp_path / "config"
        shutil.copytree(os.path.join(BACKEND_DIR, "..", "config"),
                        config_dir)
        (config_dir / "promotions.yml").write_text(
            "promotions:\n"
            "- {source: svc-a, type: CALLS_SERVICE, target: svc-b,\n"
            "   decision: reject, tier: r7.exposes, note: wrong host}\n")

        env = dict(os.environ)
        env["KG_CONFIG_DIR"] = str(config_dir)
        proc = subprocess.run(
            [sys.executable, "-m", "tools.calibrate", "--dry-run"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
            timeout=300)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "CONSTANTS ABOVE EVIDENCE CEILING" in proc.stderr
        assert "r7.exposes" in proc.stderr
        assert "lower the constant to the derived value" in proc.stderr

    def test_dry_run_does_not_touch_the_config(self):
        before = open(CONFIG_PATH, encoding="utf-8").read()
        subprocess.run(
            [sys.executable, "-m", "tools.calibrate", "--dry-run"],
            cwd=BACKEND_DIR, capture_output=True, text=True, timeout=300)
        assert open(CONFIG_PATH, encoding="utf-8").read() == before
