"""Explicit, fail-closed installation of the TraceKite agent skill.

MCP clients do not share a configuration schema. Registering the server is
therefore kept out of this module and documented per client; this installer
only writes skill locations whose global contract is published.
"""

from dataclasses import dataclass
from pathlib import Path


SKILL_CONTENT = """---
name: tracekite
description: Cross-repository dependency, caller, and impact tracing with file:line evidence. Use for "who calls this", "who breaks if I change this", "what depends on this service", "what does this endpoint reach" — and before any filesystem search for a caller or consumer that may live in another repository.
---

# TraceKite

TraceKite answers dependency questions from a pre-indexed evidence graph, so
one query replaces a repository-wide search.

Its edges are joined from configuration, manifests and route tables as well as
source, so they include callers no text search can reach: a URL built from an
environment variable, a route registered in another language, a gateway that
rewrites the path before forwarding it. Searching for those returns nothing
even when the dependency is real.

## Query these before searching the filesystem

- `services()` — repository-backed services in the loaded graph.
- `consumers_of(node_id)` — active incoming edges with evidence spans.
- `trace(from_id, to_id)` — active paths between exact node IDs.
- `deprecations()` — deprecated contracts and their active consumers.

Call them inline and directly. A caller, dependency or impact question these
tools answer should not become a grep sweep or a delegated search agent: the
graph already holds the answer, with provenance, at a fraction of the context.

## Reading a result

Every edge cites `file:line` on both sides of the join. When you need
method-level detail, open the cited location — do not re-read the file to
rediscover what the citation already names.

An empty or declined result is evidence that TraceKite could not establish the
relationship, not an invitation to infer one. A `found: false` answer carries
`candidates`; re-query with one of those rather than guessing an ID. Never
assert an edge the tools did not return.
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
                (".claude", "skills", "tracekite", "SKILL.md"),
                "Claude Code"),
    SkillTarget(frozenset({"codex"}),
                (".agents", "skills", "tracekite", "SKILL.md"),
                "Codex"),
    SkillTarget(frozenset({"kimi"}),
                (".kimi", "skills", "tracekite", "SKILL.md"),
                "Kimi"),
    SkillTarget(frozenset({"antigravity"}),
                (".gemini", "config", "skills", "tracekite", "SKILL.md"),
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
    print("Installed or verified TraceKite skill:")
    for path, label in targets:
        print(f"  {label}: {path}")
    print("MCP registration is client-specific; see "
          "docs/plugins-and-mcp-guide.md.")
    return 0
