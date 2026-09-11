"""The admission rule `claims.py` promises: registry row, emitter, resolver.

`services/claims.py` says adding a kind costs "one registry row + an emitting
parser + a consuming resolver (CI admission test enforces all three)". Nothing
enforced it. The cost of that gap is already recorded: `services/absence.py`
kept a second hand-written list of kinds that drifted from `ACTIVE_KINDS` in
both directions, and half its vocabulary named kinds no emitter produces —
absence reported forever for things that could never be found.

Checked statically rather than by scanning fixtures. A runtime check would
only prove the *corpus* exercises a kind, so a kind with a real emitter and no
fixture would fail and a reviewer would 'fix' it by writing a fixture. What
admission asks is whether the code exists, which is a question about source.

The kind is sometimes an expression rather than a literal — `r10_dataset.py`
loops over `("dataset", "db")`, `emit_data_site_claims` picks with a ternary —
so both collectors resolve simple tuple and conditional forms. Anything more
indirect than that is deliberately not resolved: a kind reached by a computed
name is not something a reader can check either.
"""

import ast
import pathlib

import pytest

from tracekite.services.claims import ACTIVE_KINDS, RESERVED_KINDS

_SERVICES = pathlib.Path(__file__).resolve().parents[1] / "tracekite" / "services"

# `calibration.py` also builds ContractClaims, and is excluded on purpose: it
# manufactures labelled estates to measure resolvers. Counting it would let a
# kind satisfy admission on the strength of its own test harness, which is the
# fiction this file exists to catch.
EMITTER_FILES = sorted(_SERVICES.glob("ingest_*.py"))
RESOLVER_FILES = sorted((_SERVICES / "linker").glob("*.py"))

# Index accessors a resolver reads claims through (`linker/base.py`).
_ACCESSORS = frozenset({"kind", "provides", "consumes", "for_key"})

# `image` is emitted by three sites in `ingest_claims.py` and registered to R0,
# but no resolver reads it: BUILT_FROM is derived from `declared` claims and
# build context instead, and the only mentions of images under `linker/` are
# prose. The claims are still evidenced nodes a query can reach — the same way
# `graph_writer.py` notes config ownership is answered from ContractClaim nodes
# directly — so this is a hole in the registry's resolver column rather than
# dead data. Named so that a *new* unconsumed kind still fails this file.
KINDS_WITHOUT_A_RESOLVER = frozenset({"image"})


def _literals(node: ast.AST) -> set[str]:
    """Every string a kind expression can evaluate to, or nothing."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _literals(node.body) | _literals(node.orelse)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return set().union(set(), *(_literals(e) for e in node.elts))
    return set()


def _emitted_kinds() -> dict[str, set[str]]:
    """kind -> files constructing a ContractClaim with it."""
    emitted: dict[str, set[str]] = {}
    for path in EMITTER_FILES:
        tree = ast.parse(path.read_text())
        assigned: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, set()).update(
                            _literals(node.value))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "ContractClaim"):
                continue
            for keyword in node.keywords:
                if keyword.arg != "kind":
                    continue
                values = _literals(keyword.value)
                if not values and isinstance(keyword.value, ast.Name):
                    values = assigned.get(keyword.value.id, set())
                for value in values:
                    emitted.setdefault(value, set()).add(path.name)
    return emitted


def _consumed_kinds() -> dict[str, set[str]]:
    """kind -> resolver files reading it off the claim index."""
    consumed: dict[str, set[str]] = {}
    for path in RESOLVER_FILES:
        tree = ast.parse(path.read_text())
        loop_bound: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                if values := _literals(node.iter):
                    loop_bound.setdefault(node.target.id, set()).update(values)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _ACCESSORS and node.args):
                continue
            values = _literals(node.args[0])
            if not values and isinstance(node.args[0], ast.Name):
                values = loop_bound.get(node.args[0].id, set())
            for value in values:
                consumed.setdefault(value, set()).add(path.name)
    return consumed


class TestTheSourcesAreWhereWeThinkTheyAre:
    """Static analysis that found no files would pass every test below."""

    @pytest.mark.parametrize("files", [EMITTER_FILES, RESOLVER_FILES])
    def test_the_scanned_set_is_not_empty(self, files):
        assert files, "no source found: the layout moved and this file is blind"

    def test_a_known_emitter_and_resolver_are_in_scope(self):
        assert "ingest_claims.py" in {p.name for p in EMITTER_FILES}
        assert "r7_http.py" in {p.name for p in RESOLVER_FILES}


class TestEveryRegisteredKindIsEmitted:
    """A row with no emitter is vocabulary that can never be found."""

    def test_every_active_kind_has_an_emitter(self):
        orphans = sorted(set(ACTIVE_KINDS) - set(_emitted_kinds()))
        assert not orphans, (
            f"registered but never emitted: {orphans}. Either add the parser "
            f"that claims it, or drop the row — a kind nothing produces is "
            f"reported absent from every repository forever.")

    def test_no_emitter_invents_an_unregistered_kind(self):
        """`ContractClaim.__post_init__` raises on these, so an unregistered
        kind is a crash at ingest rather than a bad edge. Caught here to name
        the file instead of waiting for a repository that reaches the line."""
        known = set(ACTIVE_KINDS) | set(RESERVED_KINDS)
        stray = {k: sorted(v) for k, v in _emitted_kinds().items()
                 if k not in known}
        assert not stray, f"emitted but not in ACTIVE_KINDS: {stray}"

    def test_reserved_kinds_are_not_emitted(self):
        """Reserved means registered and deliberately unclaimed. One that is
        emitted is an active kind whose row was never promoted."""
        promoted = sorted(set(RESERVED_KINDS) & set(_emitted_kinds()))
        assert not promoted, (
            f"reserved but emitted: {promoted}. Move the row into "
            f"ACTIVE_KINDS with its resolver id so the kind is admitted "
            f"properly, rather than reaching the graph through the guard's "
            f"reserved escape hatch.")


class TestEveryRegisteredKindIsConsumed:
    """The third column: a claim nothing reads produces no edge."""

    def test_every_active_kind_has_a_consuming_resolver(self):
        consumed = set(_consumed_kinds())
        orphans = sorted(set(ACTIVE_KINDS) - consumed - KINDS_WITHOUT_A_RESOLVER)
        assert not orphans, (
            f"emitted but no resolver reads it: {orphans}. These become "
            f"evidenced claim nodes that never join, so the kind costs storage "
            f"and yields no edge.")

    def test_the_exemption_still_describes_reality(self):
        """A named exemption that quietly became consumed is a stale comment
        claiming a hole that closed."""
        consumed = set(_consumed_kinds())
        stale = sorted(KINDS_WITHOUT_A_RESOLVER & consumed)
        assert not stale, (
            f"{stale} now has a resolver — remove it from "
            f"KINDS_WITHOUT_A_RESOLVER so the check tightens again.")

    def test_no_resolver_reads_a_kind_that_is_not_registered(self):
        known = set(ACTIVE_KINDS) | set(RESERVED_KINDS)
        stray = {k: sorted(v) for k, v in _consumed_kinds().items()
                 if k not in known}
        assert not stray, (
            f"resolver reads a kind no emitter can produce: {stray}. The "
            f"lookup returns nothing and the resolver silently does no work.")
