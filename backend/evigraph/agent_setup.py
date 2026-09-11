"""Explicit, fail-closed installation of the Evigraph agent skill.

MCP clients do not share a configuration schema. Registering the server is
therefore kept out of this module and documented per client; this installer
only writes skill locations whose global contract is published.
"""

from dataclasses import dataclass
from pathlib import Path


SKILL_CONTENT = """---
name: evigraph
description: Cross-repository dependency tracing with file:line evidence.
---

# Evigraph

Use the Evigraph MCP tools for cross-repository caller, dependency, and impact
questions:

- `services()` lists repository-backed services in the loaded graph.
- `consumers_of(node_id)` returns active incoming edges with evidence spans.
- `trace(from_id, to_id)` returns active paths between exact node IDs.
- `deprecations()` reports deprecated contracts and their active consumers.

Treat an empty or declined result as evidence that Evigraph could not establish
the relationship. Never infer an edge that the tools did not return. Open the
cited source location when method-level implementation detail is required.
"""


class SkillConflictError(RuntimeError):
    """An existing skill differs, so overwriting it would destroy user data."""


@dataclass(frozen=True)
class SkillTarget:
    clients: frozenset[str]
    relative_path: tuple[str, ...]
    label: str


TARGETS = (
    SkillTarget(frozenset({"claude"}),
                (".claude", "skills", "evigraph", "SKILL.md"),
                "Claude Code"),
    SkillTarget(frozenset({"codex"}),
                (".agents", "skills", "evigraph", "SKILL.md"),
                "Codex"),
    SkillTarget(frozenset({"kimi"}),
                (".kimi", "skills", "evigraph", "SKILL.md"),
                "Kimi"),
    SkillTarget(frozenset({"antigravity"}),
                (".gemini", "config", "skills", "evigraph", "SKILL.md"),
                "Antigravity"),
)
SUPPORTED_CLIENTS = frozenset(c for target in TARGETS for c in target.clients)


def _selected_targets(clients: list[str] | None) -> list[SkillTarget]:
    selected = set(clients or ["all"])
    unknown = selected - SUPPORTED_CLIENTS - {"all"}
    if unknown:
        raise ValueError(f"unsupported client(s): {sorted(unknown)}")
    if "all" in selected:
        return list(TARGETS)
    return [target for target in TARGETS if target.clients & selected]


def install_skills(clients: list[str] | None = None,
                   home: Path | None = None) -> list[tuple[Path, str]]:
    """Install selected skills without modifying or replacing existing data."""
    root = home or Path.home()
    targets = [(root.joinpath(*target.relative_path), target.label)
               for target in _selected_targets(clients)]

    conflicts = [path for path, _label in targets
                 if path.exists() and path.read_text(encoding="utf-8") !=
                 SKILL_CONTENT]
    if conflicts:
        rendered = ", ".join(str(path) for path in conflicts)
        raise SkillConflictError(
            f"refusing to overwrite existing skill file(s): {rendered}")

    for path, _label in targets:
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SKILL_CONTENT, encoding="utf-8")
    return targets


def cmd_install_skill(args) -> int:
    targets = install_skills(getattr(args, "client", None))
    print("Installed or verified Evigraph skill:")
    for path, label in targets:
        print(f"  {label}: {path}")
    print("MCP registration is client-specific; see "
          "docs/plugins-and-mcp-guide.md.")
    return 0
