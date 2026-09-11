"""Neo4j driver lifecycle: singleton driver, sessions, health checks.

The driver enforces a non-default password at startup (design §9) and sets
client-side timeouts; the server enforces db.transaction.timeout=60s.
"""

import logging
from contextlib import contextmanager
from typing import Optional

from neo4j import GraphDatabase, Driver

from evigraph.db.store_config import get_config, require_neo4j_password

logger = logging.getLogger(__name__)

_driver: Optional[Driver] = None


def get_driver() -> Driver:
    """Get or create the Neo4j driver singleton."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            get_config().neo4j_uri,
            auth=(get_config().neo4j_user, require_neo4j_password()),
            connection_timeout=10.0,
            max_transaction_retry_time=15.0,
            max_connection_pool_size=20,
        )
        logger.info("Neo4j driver created for %s", get_config().neo4j_uri)
    return _driver


@contextmanager
def get_session():
    """Yield a Neo4j session bound to the default database."""
    session = get_driver().session()
    try:
        yield session
    finally:
        session.close()


def check_neo4j_health() -> bool:
    """Return True when the database answers a trivial query."""
    try:
        with get_session() as session:
            session.run("RETURN 1").consume()
        return True
    except Exception as exc:
        logger.error("Neo4j health check failed: %s", exc)
        return False


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")
