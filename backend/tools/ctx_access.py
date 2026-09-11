"""Which `ctx` side tables each resolver writes, and how it reads them.

Extracted from `check_invariants.py`: reading the AST is a different job from
deciding what the reading means, and only one of the two has anything to say
about invariants. The distinction this module exists to make is *whole* versus
*keyed* access — `ctx.env_values.items()` needs entries other shards produced,
`ctx.contract_repos[node_id]` needs only the one the owning shard already has.
"""

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parent.parent
LINKER = BACKEND / "evigraph" / "services" / "linker"

# Reading one entry is shard-local: the partition that owns the key owns the
# entry. Reading the whole table is not — it asks for entries other shards
# produced, which is exactly what I10 forbids.
KEYED_ACCESS = {"get", "setdefault", "pop"}

MUTATORS = {"append", "add", "extend", "update"}


class CtxAccess(ast.NodeVisitor):
    """Which `ctx` side tables a module writes, and how it reads them.

    The distinction that matters is *whole* versus *keyed*. Every access is
    assumed whole-table until something proves it is a lookup, because that is
    the direction that fails safe: a missed keyed access reports a violation
    somebody investigates, a missed whole read reports nothing and ships.
    """

    def __init__(self):
        self.writes: set[str] = set()
        self.keyed: set[str] = set()
        self.whole: set[str] = set()
        self.calls: set[str] = set()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _is_ctx(node.value):
            if isinstance(node.ctx, ast.Store):
                self.writes.add(node.attr)
            else:
                self.whole.add(node.attr)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        table = _ctx_table(node.value)
        if table is None:
            self.generic_visit(node)
            return
        self.keyed.add(table)
        if isinstance(node.ctx, ast.Store):
            self.writes.add(table)
        # Descend into the slice only. Visiting `node.value` would record the
        # attribute again as a whole-table read and undo the distinction this
        # method exists to make.
        self.visit(node.slice)

    def visit_Compare(self, node: ast.Compare) -> None:
        for op, comparator in zip(node.ops, node.comparators):
            # `key in ctx.table` is a lookup, not a scan.
            if isinstance(op, (ast.In, ast.NotIn)):
                table = _ctx_table(comparator)
                if table is not None:
                    self.keyed.add(table)
                    self.visit(node.left)
                    return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and _is_ctx(func.value):
            # A LinkContext method. What it writes is resolved from the class.
            self.calls.add(func.attr)
            self._visit_args(node)
            return

        table = _ctx_table(func.value) if isinstance(func, ast.Attribute) \
            else None
        if table is not None and func.attr in KEYED_ACCESS | MUTATORS:
            self.keyed.add(table)
            if func.attr in MUTATORS:
                self.writes.add(table)
            self._visit_args(node)
            return

        # `ctx.table[key].add(...)` — a keyed write into an entry. Shard-local
        # by construction: the partition owning the key owns the entry.
        if isinstance(func, ast.Attribute) and func.attr in MUTATORS:
            inner = func.value
            if isinstance(inner, ast.Subscript):
                nested = _ctx_table(inner.value)
                if nested is not None:
                    self.keyed.add(nested)
                    self.writes.add(nested)
                    self.visit(inner.slice)
                    self._visit_args(node)
                    return
        self.generic_visit(node)

    def _visit_args(self, node: ast.Call) -> None:
        for child in list(node.args) + [k.value for k in node.keywords]:
            self.visit(child)


def _is_ctx(node) -> bool:
    return isinstance(node, ast.Name) and node.id == "ctx"


def _ctx_table(node) -> str | None:
    """`ctx.<name>` -> "<name>", else None."""
    if isinstance(node, ast.Attribute) and _is_ctx(node.value):
        return node.attr
    return None


def method_writes() -> dict[str, set[str]]:
    """Which side tables each LinkContext method writes.

    Derived from the class rather than listed here: a new writer method would
    otherwise be invisible to this check, and the invariant it breaks is one
    nobody notices until an estate is sharded.
    """
    tree = ast.parse((LINKER / "base.py").read_text())
    out: dict[str, set[str]] = {}
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef) or cls.name != "LinkContext":
            continue
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            written = set()
            for node in ast.walk(fn):
                target = None
                if isinstance(node, ast.Attribute) and \
                        isinstance(node.ctx, ast.Store):
                    target = node
                elif isinstance(node, ast.Subscript) and \
                        isinstance(node.ctx, ast.Store) and \
                        isinstance(node.value, ast.Attribute):
                    target = node.value
                elif isinstance(node, ast.Call) and \
                        isinstance(node.func, ast.Attribute) and \
                        node.func.attr in {"append", "add", "extend"} and \
                        isinstance(node.func.value, ast.Attribute):
                    target = node.func.value
                if target is not None and isinstance(target.value, ast.Name) \
                        and target.value.id == "self":
                    written.add(target.attr)
            out[fn.name] = written
    return out


def resolver_access() -> tuple[dict, dict]:
    """(broadcast, join) -> {name: (writes, whole_reads)}.

    Method and property names are dropped: `ctx.canon(...)` reads like an
    attribute to the AST but is behaviour, not a table, and listing it as one
    would bury the four names that matter under a dozen that never can.
    """
    from evigraph.services.linker.engine import BROADCAST_RESOLVERS, JOIN_RESOLVERS

    writes_by_method = method_writes()
    not_a_table = set(writes_by_method) | _properties()

    def analyse(group):
        out = {}
        for name, module in group:
            path = pathlib.Path(module.__file__)
            visitor = CtxAccess()
            visitor.visit(ast.parse(path.read_text()))
            writes = set(visitor.writes)
            for call in visitor.calls:
                writes |= writes_by_method.get(call, set())
            out[name] = (writes - not_a_table, visitor.whole - not_a_table)
        return out

    return analyse(BROADCAST_RESOLVERS), analyse(JOIN_RESOLVERS)


def _properties() -> set[str]:
    """LinkContext's properties — attribute syntax, method semantics."""
    tree = ast.parse((LINKER / "base.py").read_text())
    names = set()
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "LinkContext":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and any(
                        getattr(d, "id", "") == "property" or
                        getattr(d, "attr", "") == "setter"
                        for d in fn.decorator_list):
                    names.add(fn.name)
    return names
