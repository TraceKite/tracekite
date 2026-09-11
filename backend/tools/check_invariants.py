"""Enforce the two invariants only static analysis can catch.

I3, I5, I6, I7 are behavioural and have tests. I8 has a scaling fixture. I1,
I2 and I9 are pinned by the determinism, layering and NORMALIZE tests. That
left two with nothing enforcing them, and both fail *silently* — which is the
reason they are worth a tool rather than a code review:

* **I4, key discipline.** One canonicaliser produces rendezvous keys. A second
  one does not raise; it produces keys in a slightly different format, and the
  claims that use it simply never meet their counterparts. Recall drops and
  nothing says why.
* **I4, id discipline.** The same argument applies to the rendezvous node id
  the key is turned into. Twenty construction sites across ten resolvers and
  two routes had drifted into existence, and two of them were exact
  duplicates: a route rebuilt the format its resolver owned. A reader that
  spells an id differently from the writer finds nothing — an empty answer
  rather than an error, which is the worst way for this to fail.
* **I10, shard independence.** No phase may require two shards to talk. A join
  resolver reading a table another join resolver wrote works perfectly on one
  machine and loses edges the moment REDUCE is partitioned — in whichever
  shard happens not to hold the writer's key.

Run:  python backend/tools/check_invariants.py [--list]
Exit: 0 clean, 1 violations found.
"""

import argparse
import ast
import pathlib
import sys

# Run as a script, `backend/` is not on the path and neither `tools` nor `app`
# imports. Added before the sibling import rather than inside main(), because
# by then the module-level import has already failed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools.ctx_access import BACKEND, resolver_access        # noqa: E402

# Where a rendezvous key may legitimately be canonicalised. Adding to this set
# is the deliberate act I4 asks for: two canonicalisers that disagree by one
# character produce keys that never meet, so the second one must be a decision
# somebody made on purpose rather than a helper that appeared.
DECLARED_CANONICALISERS = {
    # The canonicaliser: path templates, HTTP methods, package URLs.
    "evigraph/utils/canonical.py",
    # `positional()` — narrower than the canonicaliser and idempotent on its
    # output, which `test_invariants.py` pins rather than assumes.
    "evigraph/services/linker/base.py",
}

# The one module that may spell a rendezvous node id. Labelled estates state
# expected ids as literals — those are assertions about output, not a second
# implementation, so the calibration corpus is exempt.
DECLARED_ID_BUILDERS = {
    "evigraph/utils/rendezvous_ids.py",
    "evigraph/services/calibration.py",
    "evigraph/services/calibration_estates.py",
}


def check_shard_independence(join: dict | None = None) -> list[str]:
    """I10: a join resolver may not read a table another join resolver wrote.

    Keyed access is fine — the shard that owns the key owns the entry. Reading
    the table whole is the violation, because that asks for entries produced
    under keys this shard does not hold.

    `join` is injectable so the rule can be tested against a synthetic pair
    without arranging a real violation in the shipped resolver set.
    """
    if join is None:
        _broadcast, join = resolver_access()
    violations = []
    for writer, (writes, _) in sorted(join.items()):
        for table in sorted(writes):
            for reader, (_, whole) in sorted(join.items()):
                if reader != writer and table in whole:
                    violations.append(
                        f"I10: {reader} reads all of ctx.{table}, which "
                        f"{writer} writes during the join. Both run in the "
                        f"join phase, so under a partitioned REDUCE the "
                        f"reader's shard never sees the writer's entries and "
                        f"the edges vanish without an error. Move the write "
                        f"into BROADCAST or NORMALIZE.")
    return violations


def check_key_discipline() -> list[str]:
    """I4: rendezvous keys come from one canonicaliser.

    A canonicaliser is recognised by what it does — collapse a route parameter
    to `{}`, or build a `pkg:` URL. Reading such a key is not canonicalising
    it, so `startswith("pkg:")` is left alone.
    """
    violations = []
    for path in sorted((BACKEND / "evigraph").rglob("*.py")):
        rel = path.relative_to(BACKEND.parent).as_posix().replace(
            "backend/", "")
        if rel in DECLARED_CANONICALISERS:
            continue
        if not rel.startswith("evigraph/services/linker/"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if _collapses_a_parameter(node):
                violations.append(
                    f"I4: {rel}:{node.lineno} collapses a route parameter to "
                    f"'{{}}' — that is key canonicalisation, and a second "
                    f"implementation of it produces keys that never meet "
                    f"their counterparts. Call evigraph.utils.canonical instead, "
                    f"or add this file to DECLARED_CANONICALISERS on "
                    f"purpose.")
            if _builds_a_purl(node):
                violations.append(
                    f"I4: {rel}:{node.lineno} builds a package URL from "
                    f"parts; build_purl is the one that ships, and two "
                    f"spellings of the same dependency never join.")
    return violations


def check_id_discipline() -> list[str]:
    """I4, second half: rendezvous node ids come from one module.

    A `global:`-prefixed literal anywhere else is a second speller. Matched on
    the literal text rather than on imports, because the failure mode is
    someone writing the format out by hand — exactly what an import check
    would miss.
    """
    violations = []
    for path in sorted(BACKEND.rglob("evigraph/**/*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel in DECLARED_ID_BUILDERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            value = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
            elif isinstance(node, ast.JoinedStr):
                value = "".join(v.value for v in node.values
                                if isinstance(v, ast.Constant)
                                and isinstance(v.value, str))
            if value and value.startswith("global:"):
                violations.append(
                    f"{rel}:{node.lineno} builds a rendezvous id "
                    f"({value[:40]!r}) — that format belongs to "
                    f"evigraph/utils/rendezvous_ids.py; a second speller finds "
                    f"nothing and reports it as an empty answer")
    return violations


def _collapses_a_parameter(node) -> bool:
    """`re.sub(p, "{}", s)` or `compiled.sub("{}", s)`.

    Both spellings, because the replacement sits at a different index in each
    and checking only one is how a check passes over the thing it was written
    to find. Nobody passes "{}" as a *pattern*, so looking in both positions
    costs no precision.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else \
        getattr(func, "id", "")
    if name != "sub":
        return False
    return any(isinstance(arg, ast.Constant) and arg.value == "{}"
               for arg in node.args[:2])


def _builds_a_purl(node) -> bool:
    """An f-string starting `pkg:` — construction, not `startswith("pkg:")`."""
    if not isinstance(node, ast.JoinedStr) or not node.values:
        return False
    head = node.values[0]
    return isinstance(head, ast.Constant) and \
        str(head.value).startswith("pkg:")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true",
                        help="print each resolver's side-table access")
    args = parser.parse_args()

    if args.list:
        broadcast, join = resolver_access()
        for label, group in (("broadcast", broadcast), ("join", join)):
            print(f"\n{label}")
            for name, (writes, whole) in sorted(group.items()):
                print(f"  {name}")
                print(f"    writes: {sorted(writes) or '-'}")
                print(f"    reads whole: {sorted(whole) or '-'}")
        print()

    violations = (check_shard_independence() + check_key_discipline()
                  + check_id_discipline())
    if violations:
        print(f"{len(violations)} INVARIANT VIOLATION(S):\n")
        for line in violations:
            print(f"  {line}\n")
        return 1
    print("invariants hold: one canonicaliser, one id speller, "
          "no cross-shard reads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
