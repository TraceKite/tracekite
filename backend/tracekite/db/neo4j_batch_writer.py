"""Bounded Neo4j writes with an adaptive timeout fallback."""

import logging

from neo4j.exceptions import Neo4jError

logger = logging.getLogger(__name__)

_TRANSACTION_TIMEOUT = (
    "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration"
)


class Neo4jBatchWriter:
    """Write rows atomically, splitting only batches Neo4j times out."""

    def __init__(self, session, query: str, **params) -> None:
        self._session = session
        self._query = query
        self._params = params

    def write(self, rows: list[dict], batch_size: int) -> int:
        total = 0
        for start in range(0, len(rows), batch_size):
            total += self._write_chunk(rows[start:start + batch_size])
        return total

    def _write_chunk(self, rows: list[dict]) -> int:
        try:
            result = self._session.run(
                self._query, rows=rows, **self._params)
            return result.single()["c"]
        except Neo4jError as exc:
            if exc.code != _TRANSACTION_TIMEOUT or len(rows) < 2:
                raise
            midpoint = len(rows) // 2
            logger.warning(
                "Neo4j timed out writing %d rows; retrying as %d and %d",
                len(rows), midpoint, len(rows) - midpoint)
            return (self._write_chunk(rows[:midpoint])
                    + self._write_chunk(rows[midpoint:]))
