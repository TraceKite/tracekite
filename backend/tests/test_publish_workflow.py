"""Publishing Actions stay wired to real artifacts and installed behavior.

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
PYPI_WORKFLOW = os.path.join(os.path.dirname(__file__), "..", "..",
                             ".github", "workflows", "publish-pypi.yml")
CI_WORKFLOW = os.path.join(os.path.dirname(__file__), "..", "..",
                           ".github", "workflows", "ci.yml")
BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _pypi_workflow() -> dict:
    with open(PYPI_WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _ci_workflow() -> dict:
    with open(CI_WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class TestWorkflowShape:
    def test_it_is_callable_and_runs_on_merge(self):
        doc = _workflow()
        triggers = doc.get("on") or doc.get(True)
        assert "workflow_call" in triggers
        assert triggers["push"]["branches"] == ["main"]

    def test_the_scan_step_feeds_the_upload(self):
        [job] = _workflow()["jobs"].values()
        run_steps = [s for s in job["steps"] if "tracekite.cli artifact" in
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
                [sys.executable, "-m", "tracekite.cli", "artifact", corpus,
                 "--out", str(tmp_path), "--repo-id", "orders",
                 "--head-sha", "abc123"],
                cwd=BACKEND, capture_output=True, text=True, timeout=300)

        first, second = run(), run()
        assert first.returncode == 0, first.stderr
        assert first.stdout == second.stdout
        assert "reused" in second.stderr
        assert os.path.exists(first.stdout.strip())


class TestPyPIWorkflow:
    def test_only_an_intentional_release_triggers_publication(self):
        doc = _pypi_workflow()
        triggers = doc.get("on") or doc.get(True)

        assert triggers == {"release": {"types": ["published"]}}

    def test_build_validates_version_metadata_and_installed_behavior(self):
        steps = _pypi_workflow()["jobs"]["build"]["steps"]
        commands = "\n".join(str(step.get("run", "")) for step in steps)

        assert "GITHUB_REF_NAME" in commands
        assert "uv build --project packaging/tracekite-core" in commands
        assert "twine check dist/*" in commands
        assert ".test-env/bin/tracekite link" in commands
        assert '".test-env/bin/tracekite", "mcp"' in commands

    def test_oidc_permission_is_scoped_to_the_protected_publish_job(self):
        doc = _pypi_workflow()
        publish = doc["jobs"]["publish"]

        assert doc["permissions"] == {"contents": "read"}
        assert "permissions" not in doc["jobs"]["build"]
        assert publish["permissions"] == {"id-token": "write"}
        assert publish["environment"] == {
            "name": "pypi", "url": "https://pypi.org/p/tracekite-core"}


def test_container_import_gate_attaches_the_python_script_to_stdin():
    steps = _ci_workflow()["jobs"]["container"]["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)

    assert "docker run --rm -i tracekite-backend:ci python -" in commands
