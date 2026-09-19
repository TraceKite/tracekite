#!/usr/bin/env python3
"""Smoke-test an installed tracekite-core distribution without test deps."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def _run(command: list[str], *, cwd: Path, env=None, input_text=None):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _require_success(result, label: str) -> None:
    if result.returncode:
        raise SystemExit(
            f"{label} failed ({result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _check_help(executable: str, root: Path) -> None:
    result = _run([executable, "--help"], cwd=root)
    _require_success(result, "tracekite --help")
    if "link" not in result.stdout or "mcp" not in result.stdout:
        raise SystemExit("tracekite --help omitted required core commands")


def _check_optional_ingest(executable: str, root: Path) -> None:
    result = _run([
        executable,
        "ingest",
        "https://github.com/TraceKite/tracekite",
        "--server",
        "http://127.0.0.1:9",
        "--no-wait",
    ], cwd=root)
    if result.returncode != 2 or "requires httpx" not in result.stderr:
        raise SystemExit(
            "core-only ingest did not decline with the server-extra hint\n"
            f"exit: {result.returncode}\nstderr:\n{result.stderr}"
        )
    if "Traceback" in result.stderr:
        raise SystemExit("core-only ingest printed a traceback")


def _check_link(executable: str, root: Path, env: dict[str, str]) -> None:
    result = _run([
        executable,
        "link",
        str(root / "corpus/orders-service"),
        str(root / "corpus/billing-service"),
        "--now",
        "2026-01-01T00:00:00+00:00",
    ], cwd=root, env=env)
    _require_success(result, "tracekite link")
    payload = json.loads(result.stdout)
    edges = payload.get("edges", [])
    if not edges or any(not edge.get("evidence") for edge in edges):
        raise SystemExit("link smoke produced no edges or an uncited edge")


def _check_mcp(executable: str, root: Path, env: dict[str, str]) -> None:
    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "services", "arguments": {}},
        },
    ]
    result = _run(
        [executable, "mcp", str(root / "corpus/orders-service")],
        cwd=root,
        env=env,
        input_text="\n".join(json.dumps(frame) for frame in frames) + "\n",
    )
    _require_success(result, "tracekite mcp")
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    services = json.loads(replies[1]["result"]["content"][0]["text"])
    if not services.get("services"):
        raise SystemExit("MCP smoke returned no services")


def _check_skill_install(executable: str, root: Path,
                         env: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory(prefix="tracekite-release-home-") as home:
        isolated_env = {**env, "HOME": home}
        result = _run(
            [executable, "install-skill", "--client", "codex"],
            cwd=root,
            env=isolated_env,
        )
        _require_success(result, "tracekite install-skill")
        skill = Path(home) / ".agents/skills/tracekite/SKILL.md"
        if not skill.is_file() or "name: tracekite" not in skill.read_text():
            raise SystemExit("skill installer did not write the expected file")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracekite", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    root = args.repo_root.resolve()
    executable = str(Path(args.tracekite).resolve())
    env = {**os.environ, "GRAPH_HMAC_KEY": "release-smoke"}

    _check_help(executable, root)
    _check_optional_ingest(executable, root)
    _check_link(executable, root, env)
    _check_mcp(executable, root, env)
    _check_skill_install(executable, root, env)
    print("tracekite-core distribution smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
