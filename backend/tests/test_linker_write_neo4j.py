"""A failed linker write names the row that failed, against the live Neo4j."""

import pytest

from tracekite.db.neo4j_client import get_session
from tracekite.services import graph_writer
from tracekite.services.graph_writer import WriteReconciliationError
from tracekite.services.linker.base import LinkContext, linker_edge, load_confidence
from tests.conftest import neo4j_available

pytestmark = pytest.mark.skipif(not neo4j_available(),
                                reason="Neo4j is not reachable")

CLAIM = "testint-linkwrite:ContractClaim:1"
NAME = "global:SvcName:discovery:testint-linkwrite-api"
SERVICE = "global:Service:testint-linkwrite-server"


@pytest.fixture(autouse=True)
def nodes():
    with get_session() as session:
        session.run("MERGE (:GraphNode:ContractClaim {id: $c}) "
                    "MERGE (:ServiceName:Rendezvous {id: $n}) "
                    "MERGE (:Service {id: $s})", c=CLAIM, n=NAME, s=SERVICE)
    yield
    with get_session() as session:
        session.run("MATCH (n) WHERE n.id IN [$c, $n, $s] DETACH DELETE n",
                    c=CLAIM, n=NAME, s=SERVICE)


def _resolved(target, label):
    ctx = LinkContext("linkrun_testint", load_confidence(), {})
    return linker_edge(ctx, "resolver.test@1", "RESOLVED_TO", CLAIM, target,
                       source_label="ContractClaim", target_label=label,
                       confidence=0.9, match_type="test", evidence=["x.yaml:1"])


def test_the_reported_row_is_the_one_that_failed():
    # Diagnosed under GraphNode, the rendezvous target that WAS written read
    # as missing, and the mislabelled row behind it went unnamed.
    with pytest.raises(WriteReconciliationError) as raised:
        graph_writer.write_linker_edges([_resolved(NAME, "ServiceName"),
                                         _resolved(SERVICE, "ServiceName")])

    assert [(s["target"], s["missing_target"]) for s in raised.value.samples] \
        == [(SERVICE, True)]


def test_each_target_written_under_its_own_label():
    written = graph_writer.write_linker_edges([_resolved(NAME, "ServiceName"),
                                               _resolved(SERVICE, "Service")])

    assert written == {"RESOLVED_TO": 2}
