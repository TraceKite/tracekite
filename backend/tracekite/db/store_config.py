"""Connection and batching values the store needs, owned by the store.

Same reason as `engine_config`: the store layer must be constructible by a
host that has no `Settings` object and no `.env` file. The server pushes real
values down at startup; a test or an embedding host calls `configure()`.

Kept separate from `engine_config` on purpose — core has no business knowing
a bolt URI exists, and A5 will add SQLite and in-memory backends whose config
does not belong in core either.
"""

from dataclasses import dataclass, replace

# A deployment that never set a password is indistinguishable from one that
# set the vendor default, and both are reachable by anything on the network.
_DEFAULT_PASSWORDS = {"", "password", "neo4j"}


@dataclass(frozen=True)
class StoreConfig:
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    write_batch_size: int = 5000


_active = StoreConfig()


def get_config() -> StoreConfig:
    return _active


def configure(**values) -> None:
    """Replace the active config with `values` applied over it.

    Empty and None values are dropped so an unset environment variable falls
    back to the default rather than blanking the field.
    """
    global _active
    supplied = {k: v for k, v in values.items() if v not in (None, "")}
    unknown = set(supplied) - {f for f in StoreConfig.__dataclass_fields__}
    if unknown:
        raise TypeError(f"unknown StoreConfig field(s): {sorted(unknown)}")
    _active = replace(_active, **supplied)


def reset() -> None:
    """Restore defaults. For tests that need a known starting point."""
    global _active
    _active = StoreConfig()


def require_neo4j_password() -> str:
    """Startup refuses default or unset Neo4j passwords (design §9)."""
    password = _active.neo4j_password
    if password in _DEFAULT_PASSWORDS:
        raise RuntimeError(
            "NEO4J_PASSWORD is unset or a known default; refusing to start")
    return password
