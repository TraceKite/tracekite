"""Shared test configuration: deterministic env before app imports."""

import os

os.environ.setdefault("GRAPH_HMAC_KEY", "test-hmac-key-not-a-secret")
os.environ.setdefault("API_TOKEN", "test-api-token")

import pytest  # noqa: E402

from tracekite.config import settings  # noqa: E402

settings.graph_hmac_key = settings.graph_hmac_key or "test-hmac-key-not-a-secret"
settings.api_token = settings.api_token or "test-api-token"

AUTH_HEADERS = {"Authorization": f"Bearer {settings.api_token}"}


def neo4j_available() -> bool:
    """Whether the integration tier can run.

    These are the M0 gate: the all-mocked suite validated query *text* while
    production deletion 500'd. Skipping them silently reproduces exactly that
    blind spot, so CI sets REQUIRE_NEO4J=1 and a missing database becomes a
    failure instead of 13 quiet skips.
    """
    try:
        from tracekite.db.neo4j_client import check_neo4j_health
        ok = bool(settings.neo4j_password) and check_neo4j_health()
    except Exception:
        ok = False
    if not ok and os.environ.get("REQUIRE_NEO4J") == "1":
        raise RuntimeError(
            "REQUIRE_NEO4J=1 but Neo4j is unreachable. Start it with "
            "`docker compose up -d neo4j` and export NEO4J_URI/NEO4J_PASSWORD."
        )
    return ok


@pytest.fixture(scope="session")
def auth_headers() -> dict:
    return dict(AUTH_HEADERS)
