"""Is the engine able to answer correctly right now?

A host embedding `scan()` and `link()` has no `/health` endpoint to ask, and
the failure modes here are quiet ones: an unset HMAC key means redaction
refuses at the first secret, and a missing confidence table means every edge's
score would be a guess. Both surface as an exception deep in a run rather than
at startup, which is exactly when a host can do least about it.

So this is a startup question with a startup answer. `degraded` means the
engine will run but produce a worse graph; `failed` means it will refuse.
Neither is inferred — each check names what it looked at.

Stdlib and the control plane only, so an `evigraph-core` host can call it.
"""

from dataclasses import dataclass, field

OK = "ok"
DEGRADED = "degraded"
FAILED = "failed"

# Worst wins: a single failed check makes the whole report failed.
_RANK = {OK: 0, DEGRADED: 1, FAILED: 2}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class Health:
    status: str = OK
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == OK

    def as_dict(self) -> dict:
        return {"status": self.status,
                "checks": [{"name": c.name, "status": c.status,
                            "detail": c.detail} for c in self.checks]}


def _redaction_check() -> Check:
    from evigraph.engine_config import get_config

    if get_config().graph_hmac_key:
        return Check("redaction_key", OK)
    return Check(
        "redaction_key", FAILED,
        "GRAPH_HMAC_KEY is unset: redaction raises at the first secret-bearing "
        "config value, so a scan will fail part-way rather than at startup")


def _control_plane_check() -> Check:
    """The confidence table is not optional — link() refuses without it."""
    try:
        from evigraph.services.linker.base import config_dir, load_confidence

        table = load_confidence()
    except Exception as exc:                                  # noqa: BLE001
        return Check("control_plane", FAILED,
                     f"{type(exc).__name__}: {str(exc)[:120]}")
    if not table:
        return Check("control_plane", FAILED,
                     f"confidence table is empty at {config_dir()}")
    missing = [k for k in ("floor", "fusion_cap") if k not in table]
    if missing:
        return Check("control_plane", DEGRADED,
                     f"missing {', '.join(missing)}; defaults will be used")
    return Check("control_plane", OK, f"{len(table)} keys")


def _workspace_check() -> Check:
    import os

    from evigraph.engine_config import get_config

    path = get_config().workspace_dir
    if os.path.isdir(path):
        if os.access(path, os.W_OK):
            return Check("workspace", OK, path)
        return Check("workspace", DEGRADED, f"{path} is not writable")

    # Absent is not the same as broken: the workspace is created on the first
    # clone. What matters is whether it *can* be, so the parent decides.
    parent = os.path.dirname(path.rstrip("/")) or "/"
    if os.path.isdir(parent) and os.access(parent, os.W_OK):
        return Check("workspace", OK, f"{path} (will be created)")
    return Check("workspace", DEGRADED,
                 f"{path} cannot be created; cloning a repo will fail, though "
                 "scanning a path in place still works")


def _extensions_check() -> Check:
    """Host registrations are reported, not judged.

    A graph built with extensions is not degraded — but a reader who cannot
    tell extensions were involved cannot account for what they contributed.
    """
    from evigraph.parsers.parser_registry import registered_parsers
    from evigraph.services.linker.engine import registered_resolvers

    resolvers = registered_resolvers()
    total = (len(registered_parsers()) + len(resolvers["broadcast"])
             + len(resolvers["join"]))
    if not total:
        return Check("extensions", OK, "none registered")
    return Check("extensions", OK,
                 f"{len(registered_parsers())} parser(s), "
                 f"{len(resolvers['broadcast']) + len(resolvers['join'])} "
                 "resolver(s) registered by the host")


def health(store=None) -> Health:
    """Whether the engine can answer correctly, and what is wrong if not.

    Pass a `GraphStore` to include a storage check; omit it for a host that
    keeps no storage, where storage being absent is the intended state rather
    than a fault.
    """
    checks = [_redaction_check(), _control_plane_check(), _workspace_check(),
              _extensions_check()]

    if store is not None:
        checks.append(_store_check(store))

    worst = max((c.status for c in checks), key=lambda s: _RANK[s])
    return Health(status=worst, checks=checks)


def _store_check(store) -> Check:
    """A store that cannot be counted cannot be written to either."""
    from evigraph.db.graph_store import Aggregate

    try:
        rows = store.query(Aggregate("node")).rows
    except Exception as exc:                                  # noqa: BLE001
        return Check("store", FAILED,
                     f"{type(store).__name__}: {type(exc).__name__}: "
                     f"{str(exc)[:100]}")
    return Check("store", OK,
                 f"{type(store).__name__}, {rows[0]['count']} nodes")
