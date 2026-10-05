from neo4j.exceptions import ClientError

from tracekite.db.neo4j_batch_writer import Neo4jBatchWriter


class _Result:
    def __init__(self, count):
        self._count = count

    def single(self):
        return {"c": self._count}


class _TimeoutSession:
    def __init__(self, max_rows):
        self.max_rows = max_rows
        self.attempts = []

    def run(self, _query, *, rows, **_params):
        self.attempts.append(len(rows))
        if len(rows) > self.max_rows:
            error = ClientError("transaction timed out")
            error._neo4j_code = (
                "Neo.ClientError.Transaction."
                "TransactionTimedOutClientConfiguration"
            )
            raise error
        return _Result(len(rows))


def test_timeout_batches_split_until_they_fit():
    session = _TimeoutSession(max_rows=2)

    written = Neo4jBatchWriter(session, "query").write(
        [{"id": value} for value in range(5)], batch_size=5)

    assert written == 5
    assert session.attempts == [5, 2, 3, 1, 2]


def test_non_timeout_error_is_not_retried():
    session = _TimeoutSession(max_rows=0)
    original_run = session.run

    def fail(_query, *, rows, **params):
        session.attempts.append(len(rows))
        raise ClientError("not a transaction timeout")

    session.run = fail
    try:
        Neo4jBatchWriter(session, "query").write([{"id": 1}], 1)
    except ClientError:
        pass
    else:
        raise AssertionError("non-timeout Neo4j errors must propagate")

    assert session.attempts == [1]
    session.run = original_run
