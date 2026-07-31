"""Every reader of persisted claims uses one field mapping.

`memory_store.claim_record` exists because the mapping from stored
properties to `ClaimRecord` is a decision, and its docstring says so. Two
of the three readers used it; `services/linker_store.py` — the Neo4j
reader production actually runs — kept an inline copy, so it was the one
reader a newly added `ClaimRecord` field would silently leave at its
default. Nothing raises when that happens; the field is just empty
everywhere the graph is served from, which is the failure mode this
project treats as the worst available.

These tests fail on the mechanism rather than on a symptom: a field
`claim_record` does not map, and a reader that builds a `ClaimRecord`
itself.
"""

import ast
import dataclasses
import pathlib

from adduce.db.memory_store import claim_record
from adduce.services.linker.base import ClaimRecord

BACKEND = pathlib.Path(__file__).resolve().parent.parent

# `claim_record` is the mapping; the labelled-estate builders construct
# ClaimRecords as test INPUT, which is authoring data, not reading it.
DECLARED_BUILDERS = {
    "adduce/db/memory_store.py",
    "adduce/services/calibration.py",
    "adduce/services/calibration_estates.py",
}


def _mapped_fields() -> set[str]:
    """Field names `claim_record` actually assigns, read from its source."""
    source = (BACKEND / "adduce/db/memory_store.py").read_text()
    tree = ast.parse(source)
    func = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "claim_record")
    call = next(n for n in ast.walk(func)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "ClaimRecord")
    return {kw.arg for kw in call.keywords if kw.arg}


class TestMappingIsComplete:
    def test_every_claim_field_is_mapped(self):
        declared = {f.name for f in dataclasses.fields(ClaimRecord)}
        missing = sorted(declared - _mapped_fields())
        assert not missing, (
            f"claim_record does not map {missing}; every reader of persisted "
            f"claims would silently default it")

    def test_the_mapping_round_trips_a_full_claim(self):
        record = claim_record(
            "repo:ContractClaim:abc", "repo_a",
            {"kind": "http", "direction": "consumes",
             "key": "httpcall:GET:/v1/x", "service_hint": "orders",
             "hint_source": "host", "matchable": True,
             "evidence": ["src/a.py:7"]},
            {"client": "requests"}, "node:site", "File")
        assert record.kind == "http"
        assert record.service_hint == "orders"
        assert record.matchable is True
        assert record.evidence == ["src/a.py:7"]
        assert record.attrs == {"client": "requests"}
        assert record.evidence_node_id == "node:site"
        assert record.evidence_node_type == "File"


class TestNoReaderBuildsItsOwn:
    def test_readers_route_through_the_shared_mapping(self):
        offenders = []
        for path in sorted(BACKEND.glob("adduce/**/*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel in DECLARED_BUILDERS:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and \
                        getattr(node.func, "id", "") == "ClaimRecord":
                    offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            f"{offenders} build a ClaimRecord directly; call "
            f"memory_store.claim_record so the field mapping stays one "
            f"decision")
