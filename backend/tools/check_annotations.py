"""Every eagerly-evaluated annotation names something that exists.

Development, CI and the container now all run Python 3.14, where PEP 649
defers annotation evaluation — so an annotation naming an unimported type
is never looked up and never raises. `requires-python` is `>=3.13`
though, and 3.13 evaluates class-level and def-level annotations at
import: anyone running the declared floor gets `NameError` before uvicorn
binds a port, on code where every test passed.

That is not hypothetical, and it is why this runs even though the two
runtimes agree today. Splitting `values.py` out of `base.py` left
`ResolverOutput.edges: list[GraphEdge]` without its import, and
`edge_policy.finalize_edges(combined: ResolverOutput)` likewise. Both
passed every test; both crashed the container, which was then on 3.12,
on its first rebuild in 26 hours.

Checked positions are the ones 3.13 evaluates at import:

- module-level `x: T = ...`
- class-body `x: T` (dataclass fields, the common case here)
- `def f(a: T) -> U` at module or class level

Function-local annotations are never evaluated at runtime and are
skipped. Modules opting into `from __future__ import annotations` are
skipped wholesale: every annotation there is already a lazy string.

Run: python backend/tools/check_annotations.py
"""

import ast
import builtins
import os
import sys

ROOTS = ("adduce", "tools")


def _module_bindings(tree: ast.Module) -> set[str]:
    """Names bound at module scope — the scope annotations resolve in."""
    bound = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                bound.update(n.id for n in ast.walk(target)
                             if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            bound.add(node.target.id)
        elif isinstance(node, (ast.Try, ast.If)):
            # Conditional and fallback imports still bind at module scope.
            for inner in ast.walk(node):
                if isinstance(inner, (ast.ClassDef, ast.FunctionDef,
                                      ast.AsyncFunctionDef)):
                    bound.add(inner.name)
                elif isinstance(inner, ast.Assign):
                    for target in inner.targets:
                        bound.update(n.id for n in ast.walk(target)
                                     if isinstance(n, ast.Name))
    return bound


def _names_in(annotation) -> set[str]:
    """Base names an annotation needs, ignoring string forward refs."""
    names = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Constant):
            continue                      # "Foo" is lazy and legal
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                names.add(base.id)
    return names


def _eager_annotations(tree: ast.Module):
    """(lineno, annotation) pairs Python 3.13 evaluates at import time."""
    def from_def(node):
        args = node.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs,
                    args.vararg, args.kwarg):
            if arg is not None and arg.annotation is not None:
                yield arg.lineno, arg.annotation
        if node.returns is not None:
            yield node.lineno, node.returns

    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            yield node.lineno, node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from from_def(node)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and item.annotation:
                    yield item.lineno, item.annotation
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield from from_def(item)


def check_file(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=path)
    if any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
           and any(a.name == "annotations" for a in n.names)
           for n in tree.body):
        return []
    bound = _module_bindings(tree)
    problems = []
    for lineno, annotation in _eager_annotations(tree):
        for name in sorted(_names_in(annotation) - bound):
            problems.append(
                f"{path}:{lineno}: annotation names {name!r}, which is not "
                f"imported or defined at module scope — import-time "
                f"NameError on Python 3.13, the declared floor")
    return problems


def main() -> int:
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    problems = []
    for root_name in ROOTS:
        for dirpath, _dirs, names in os.walk(os.path.join(backend, root_name)):
            if "__pycache__" in dirpath:
                continue
            for name in sorted(names):
                if name.endswith(".py"):
                    problems.extend(check_file(os.path.join(dirpath, name)))
    if problems:
        print(f"{len(problems)} EAGER-ANNOTATION PROBLEM(S) — these boot the "
              f"container into a NameError:\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("annotations resolve: no import-time NameError on Python 3.13+")
    return 0


if __name__ == "__main__":
    sys.exit(main())
