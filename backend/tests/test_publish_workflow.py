"""The publishing Action stays wired to the real CLI.

A workflow cannot run inside the test suite, but its lies can be caught
before CI ever sees them: a step invoking a command that no longer
exists, an artifact upload pointing at nothing, or the head-sha plumbing
quietly dropped — each would publish garbage on every merge while the
YAML still looked plausible.
"""

import os
import subprocess
import sys

import yaml

WORKFLOW = os.path.join(os.path.dirname(__file__), "..", "..",
                        ".github", "workflows", "publish-artifact.yml")
BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class TestWorkflowShape:
    def test_it_is_callable_and_runs_on_merge(self):
        doc = _workflow()
        triggers = doc.get("on") or doc.get(True)
        assert "workflow_call" in triggers
        assert triggers["push"]["branches"] == ["main"]

    def test_the_scan_step_feeds_the_upload(self):
        [job] = _workflow()["jobs"].values()
        run_steps = [s for s in job["steps"] if "adduce.cli artifact" in
                     str(s.get("run", ""))]
        assert run_steps, "no step invokes the artifact command"
        assert "--head-sha \"$GITHUB_SHA\"" in run_steps[0]["run"], (
            "the commit anchor is what makes temporal queries possible; "
            "dropping it publishes artifacts no history can use")
        uploads = [s for s in job["steps"]
                   if "upload-artifact" in str(s.get("uses", ""))]
        assert uploads[0]["with"]["path"] == \
            "${{ steps.scan.outputs.path }}"


class TestTheCommandItInvokes:
    def test_artifact_command_is_deterministic_and_idempotent(self, tmp_path):
        """The workflow's whole contract: same tree, same file. Run the
        REAL command twice; the second run must reuse, not re-mint."""
        corpus = os.path.join(BACKEND, "..", "corpus", "orders-service")

        def run():
            return subprocess.run(
                [sys.executable, "-m", "adduce.cli", "artifact", corpus,
                 "--out", str(tmp_path), "--repo-id", "orders",
                 "--head-sha", "abc123"],
                cwd=BACKEND, capture_output=True, text=True, timeout=300)

        first, second = run(), run()
        assert first.returncode == 0, first.stderr
        assert first.stdout == second.stdout
        assert "reused" in second.stderr
        assert os.path.exists(first.stdout.strip())
