"""Agent installation is explicit, complete, and never overwrites user data."""

import json
import tomllib
from pathlib import Path

import pytest

from adduce.agent_setup import (
    SKILL_CONTENT,
    SkillConflictError,
    install_skills,
)

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "adduce"


def test_codex_and_kimi_use_their_published_skill_locations(tmp_path):
    installed = install_skills(["codex", "kimi"], home=tmp_path)

    assert installed == [
        (tmp_path / ".agents/skills/adduce/SKILL.md", "Codex"),
        (tmp_path / ".kimi/skills/adduce/SKILL.md", "Kimi"),
    ]
    assert all(path.read_text(encoding="utf-8") == SKILL_CONTENT
               for path, _label in installed)


def test_existing_matching_skill_is_verified_without_rewrite(tmp_path):
    path = tmp_path / ".claude/skills/adduce/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(SKILL_CONTENT, encoding="utf-8")
    before = path.stat().st_mtime_ns

    install_skills(["claude"], home=tmp_path)

    assert path.stat().st_mtime_ns == before


def test_conflict_preflight_prevents_partial_install(tmp_path):
    conflict = tmp_path / ".claude/skills/adduce/SKILL.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("user-owned", encoding="utf-8")

    with pytest.raises(SkillConflictError, match="refusing to overwrite"):
        install_skills(["all"], home=tmp_path)

    assert conflict.read_text(encoding="utf-8") == "user-owned"
    assert not (tmp_path / ".agents/skills/adduce/SKILL.md").exists()


def test_only_published_client_locations_are_selected(tmp_path):
    paths = {Path(path).relative_to(tmp_path)
             for path, _label in install_skills(["all"], home=tmp_path)}

    assert paths == {
        Path(".claude/skills/adduce/SKILL.md"),
        Path(".agents/skills/adduce/SKILL.md"),
        Path(".kimi/skills/adduce/SKILL.md"),
        Path(".gemini/config/skills/adduce/SKILL.md"),
    }


def test_cross_client_plugin_contains_the_published_skill_and_mcp_server():
    codex = json.loads(
        (PLUGIN / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    claude = json.loads(
        (PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    kimi = json.loads(
        (PLUGIN / "kimi.plugin.json").read_text(encoding="utf-8"))

    assert (PLUGIN / "skills/adduce/SKILL.md").read_text(
        encoding="utf-8") == SKILL_CONTENT
    assert codex["mcpServers"]["adduce"]["args"] == ["mcp"]
    assert claude["mcpServers"]["adduce"]["args"] == ["mcp"]
    assert kimi["mcpServers"]["adduce"]["args"] == ["mcp"]


def test_plugin_and_package_versions_are_released_together():
    application = tomllib.loads((REPO / "pyproject.toml").read_text())
    core = tomllib.loads(
        (REPO / "packaging/adduce-core/pyproject.toml").read_text())
    versions = {
        json.loads(path.read_text(encoding="utf-8"))["version"]
        for path in (
            PLUGIN / ".codex-plugin/plugin.json",
            PLUGIN / ".claude-plugin/plugin.json",
            PLUGIN / "kimi.plugin.json",
        )
    }

    assert versions == {
        application["project"]["version"], core["project"]["version"]}
