"""The layering rule is enforced here, not just documented.

`architecture.md` §2 fixes the dependency direction, and a rule that degrades
silently is worth nothing. This runs the import-graph check as part of the
suite, so a violating import fails the same command that gates a PR.

Kept as a test rather than only a CI step on purpose: the check must fail for
whoever introduces the import, on their machine, before it reaches review.
"""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import check_layers  # noqa: E402


def _format(violations) -> str:
    return "\n".join(
        f"  [{src_layer}] {src} imports "
        f"{'UP to' if kind == 'upward' else 'SIBLING'} [{dst_layer}] {dst}"
        for src, src_layer, dst, dst_layer, kind in violations)


class TestLayering:
    def test_arrows_point_down_only(self):
        """core imports nothing above it; parsers and store may import core;
        neither may import the other; server may import anything."""
        violations, _ = check_layers.scan()
        assert not violations, (
            f"{len(violations)} layering violation(s):\n{_format(violations)}\n\n"
            "Either invert the dependency, or move the value the importer "
            "needs into a config type the lower layer owns "
            "(engine_config / db.store_config). Do not add the import.")

    def test_every_module_has_a_layer(self):
        """An unranked module is a hole in the rule: it would be free to
        import anything until someone noticed."""
        _, unassigned = check_layers.scan()
        assert not unassigned, (
            "module(s) with no layer — add them to LAYERS in "
            f"backend/tools/check_layers.py:\n  " + "\n  ".join(unassigned))

    def test_core_is_importable_without_the_server_or_a_driver(self):
        """The Phase 1 gate in miniature: core must not drag in fastapi or the
        neo4j driver by importing it. Checked on the import graph rather than
        by importing, so it holds even when both happen to be installed."""
        offenders = {}
        for path in sorted((check_layers.APP).rglob("*.py")):
            if "__pycache__" in path.parts or check_layers.is_package_marker(path):
                continue
            name = check_layers.module_name(path)
            if check_layers.layer_of(name) != "core":
                continue
            heavy = {m for m in _third_party_imports(path)
                     if m in {"fastapi", "neo4j", "starlette", "uvicorn",
                              "pydantic_settings"}}
            if heavy:
                offenders[name] = sorted(heavy)
        assert not offenders, f"core modules importing heavy deps: {offenders}"


def _third_party_imports(path) -> set[str]:
    import ast
    tree = ast.parse(path.read_text(), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module.split(".")[0])
    return found
