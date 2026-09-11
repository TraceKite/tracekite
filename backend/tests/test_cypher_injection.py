"""A relationship type is the one caller string Cypher cannot bind.

`neo4j_graph_store._rel_pattern` interpolates it, because Cypher treats a
relationship type as syntax rather than a value and offers no parameter for
it. The SQLite store answers the same `QuerySpec` with `?` placeholders and
is safe without trying; the Neo4j one is safe only because it refuses
anything that is not a bare identifier.

Nothing reaches it from a request today — `/api/repos/{id}/graph` hands its
`edge_types` to `graph_reader`, which binds `$edge_types` — so this pins the
guard before the store is wired up as the read path and the gap goes live.

Deliberately not in `test_neo4j_graph_store.py`: that module skips wholesale
without a database, and a guard against injection that silently does not run
is worse than none.
"""

import pytest

from evigraph.db.neo4j_graph_store import _rel_pattern


class TestRealTypesPass:
    def test_one_type(self):
        assert _rel_pattern(["CALLS_SERVICE"]) == ":CALLS_SERVICE"

    def test_several_types(self):
        assert _rel_pattern(["CALLS_SERVICE", "ROUTES_TO"]) == \
            ":CALLS_SERVICE|ROUTES_TO"

    def test_no_types_means_no_predicate(self):
        assert _rel_pattern(None) == ""
        assert _rel_pattern([]) == ""

    def test_a_type_invented_later_still_works(self):
        """Refused by grammar, not by a list of known types, so adding an
        edge type does not mean editing this guard."""
        assert _rel_pattern(["SOME_TYPE_ADDED_LATER"]) == \
            ":SOME_TYPE_ADDED_LATER"


class TestAnythingElseIsRefused:
    @pytest.mark.parametrize("payload", [
        "FOO]->() DETACH DELETE n //",   # close the pattern, then destroy
        "A|B",                            # a second type past the join
        "CALLS SERVICE",                  # a space is not an identifier
        "*",
        "A'",
        "A`B",
        "1STARTS_WITH_DIGIT",
        "",
    ])
    def test_refused(self, payload):
        with pytest.raises(ValueError):
            _rel_pattern([payload])

    def test_one_bad_type_refuses_the_whole_pattern(self):
        """Fail closed: a valid type beside an invalid one must not let the
        query through with the bad one merely dropped."""
        with pytest.raises(ValueError):
            _rel_pattern(["CALLS_SERVICE", "X]->() DELETE n //"])
