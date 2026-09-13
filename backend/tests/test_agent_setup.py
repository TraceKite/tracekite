"""Agent installation is explicit, complete, and never overwrites user data."""

import json
import tomllib
from pathlib import Path

import pytest
import yaml

from tracekite.agent_setup import (
    TARGETS,
    SKILL_CONTENT,
    SkillConflictError,
    install_skills,
)
from tracekite.mcp_server import TOOLS

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "tracekite"


def test_codex_and_kimi_use_their_published_skill_locations(tmp_path):
    installed = install_skills(["codex", "kimi"], home=tmp_path)

    assert installed == [
        (tmp_path / ".agents/skills/tracekite/SKILL.md", "Codex"),
        (tmp_path / ".kimi/skills/tracekite/SKILL.md", "Kimi"),
    ]
    assert all(path.read_text(encoding="utf-8") == SKILL_CONTENT
               for path, _label in installed)


def test_existing_matching_skill_is_verified_without_rewrite(tmp_path):
    path = tmp_path / ".claude/skills/tracekite/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(SKILL_CONTENT, encoding="utf-8")
    before = path.stat().st_mtime_ns

    install_skills(["claude"], home=tmp_path)

    assert path.stat().st_mtime_ns == before


def test_conflict_preflight_prevents_partial_install(tmp_path):
    conflict = tmp_path / ".claude/skills/tracekite/SKILL.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("user-owned", encoding="utf-8")

    with pytest.raises(SkillConflictError, match="refusing to overwrite"):
        install_skills(["all"], home=tmp_path)

    assert conflict.read_text(encoding="utf-8") == "user-owned"
    assert not (tmp_path / ".agents/skills/tracekite/SKILL.md").exists()


def test_only_published_client_locations_are_selected(tmp_path):
    paths = {Path(path).relative_to(tmp_path)
             for path, _label in install_skills(["all"], home=tmp_path)}

    assert paths == {
        Path(".claude/skills/tracekite/SKILL.md"),
        Path(".agents/skills/tracekite/SKILL.md"),
        Path(".kimi/skills/tracekite/SKILL.md"),
        Path(".gemini/config/skills/tracekite/SKILL.md"),
    }


def test_cross_client_plugin_contains_the_published_skill_and_mcp_server():
    codex = json.loads(
        (PLUGIN / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    claude = json.loads(
        (PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    kimi = json.loads(
        (PLUGIN / "kimi.plugin.json").read_text(encoding="utf-8"))

    assert (PLUGIN / "skills/tracekite/SKILL.md").read_text(
        encoding="utf-8") == SKILL_CONTENT
    assert codex["mcpServers"]["tracekite"]["args"] == ["mcp"]
    assert claude["mcpServers"]["tracekite"]["args"] == ["mcp"]
    assert kimi["mcpServers"]["tracekite"]["args"] == ["mcp"]


def test_plugin_and_package_versions_are_released_together():
    application = tomllib.loads((REPO / "pyproject.toml").read_text())
    core = tomllib.loads(
        (REPO / "packaging/tracekite-core/pyproject.toml").read_text())
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


def _skill_frontmatter() -> dict:
    """The YAML header every client parses to decide whether to load us."""
    _, _, rest = SKILL_CONTENT.partition("---\n")
    header, sep, _body = rest.partition("\n---\n")
    assert sep, "skill has no closing frontmatter fence"
    return yaml.safe_load(header)


def test_skill_frontmatter_loads_under_the_name_every_client_installs():
    front = _skill_frontmatter()

    installed_dirs = {target.relative_path[-2] for target in TARGETS}
    assert installed_dirs == {front["name"]}
    assert front["description"].strip()


def test_skill_documents_every_tool_the_mcp_server_serves():
    """A tool the skill omits is a tool the agent never learns to call."""
    _, _, body = SKILL_CONTENT.partition("\n---\n")

    for name in sorted(tool["name"] for tool in TOOLS):
        assert f"`{name}(" in body, f"skill does not document {name}"


def test_skill_routes_agents_to_the_graph_before_a_filesystem_search():
    """The routing rule is the fix; a pure tool listing does not fire."""
    body = SKILL_CONTENT.partition("\n---\n")[2].lower()

    assert "before searching the filesystem" in body
    assert "candidates" in body
