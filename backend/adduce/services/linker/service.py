"""The application's link driver: store in, `engine.link()`, store out.

Everything that computes a fact about the graph lives in `engine.py` and is
callable without a database. This file only moves data across the store
boundary and keeps the LinkRun ledger.

New-writes-first / delete-old-after: edges for this run are written, then any
linker edge from a previous run is removed, then orphan rendezvous/Service
nodes are GC'd. LinkRun is the ledger.
"""

import logging
import uuid

from adduce.services.linker.engine import link
from adduce.services.linker.ports import LinkerStore

logger = logging.getLogger(__name__)


class LinkerService:
    """Drives one link run against an injected store.

    The store is a constructor argument rather than a module import so this
    class never names a backend: the server picks Neo4j, a test passes a fake,
    and an embedding host supplies its own (architecture §2).
    """

    def __init__(self, store: LinkerStore, on_run=None):
        self._store = store
        # Called with (run_id, counters, timings) when a run finishes. Injected
        # the same way the store is, and for the same reason: publishing a
        # measurement is I/O, and this class must stay callable by a host that
        # has no exporter, no metrics SDK and no opinion about either.
        self._on_run = on_run

    def link_full(self, mode: str = "full") -> dict:
        run_id = f"linkrun_{uuid.uuid4().hex[:12]}"
        self._store.create_link_run(run_id, mode=mode)
        try:
            counters, timings = self._run(run_id)
        except Exception as exc:
            self._store.finish_link_run(run_id, "failed", {},
                                        error=str(exc)[:500])
            raise
        self._store.finish_link_run(run_id, "done", counters)
        if self._on_run is not None:
            # After the ledger is closed, and never in the failure path's way:
            # an exporter that raises must not turn a completed run into a
            # failed one, so it is called where nothing depends on it.
            try:
                self._on_run(run_id, counters, timings)
            except Exception:                                 # noqa: BLE001
                logger.warning("run observer failed for %s", run_id,
                               exc_info=True)
        return {"link_run_id": run_id, **counters}

    def link_delta(self) -> dict:
        """Incremental relink: skip entirely when no repo's claim
        set changed since its last link.

        Resolution is global — R0 clustering can shift when any repo changes —
        so a changed estate still recomputes everything in memory. The saving
        is real anyway: the fingerprint gate turns the common no-op case into
        one cheap query, and the MERGE write path only touches changed
        relationships plus preserves `first_seen_at`.
        """
        changed = self._changed_repos()
        if not changed:
            return {"skipped": True, "reason": "no repo's claims changed",
                    "repos_changed": 0}
        result = self.link_full(mode="delta")
        self._store_fingerprints()
        result["repos_changed"] = len(changed)
        return result

    def _changed_repos(self) -> list[str]:
        """Which repos' claim sets differ from what the last link recorded.

        The comparison stays here and only the two reads go to the store: what
        counts as changed is the linker's decision, not the backend's.
        """
        current = self._store.claim_fingerprints()
        stored = self._store.stored_fingerprints()
        return sorted(repo for repo, fp in current.items()
                      if stored.get(repo) != fp)

    def _store_fingerprints(self) -> None:
        self._store.store_fingerprints(self._store.claim_fingerprints())

    def _run(self, run_id: str) -> tuple[dict, object]:
        result = link(self._store.load_claims(), run_id=run_id)

        self._store.write_rendezvous_nodes(result.rendezvous)
        self._store.write_service_nodes(result.services)
        written = self._store.write_linker_edges(result.edges)
        deleted = self._store.delete_stale_linker_edges(run_id)
        orphans = self._store.gc_orphan_rendezvous()
        self._store.stamp_repos_linked(result.repo_ids, run_id)

        # I7: a repo excluded from the link is named, not merely missing.
        # Without this an estate with a broken repo is indistinguishable from
        # a smaller estate, and the absent edges look like poor recall.
        excluded = self._store.unlinkable_repos()
        counters = dict(result.counters)
        if excluded:
            logger.warning("Link run %s excluded %d repo(s): %s", run_id,
                           len(excluded),
                           ", ".join(f"{k}={v}" for k, v in
                                     sorted(excluded.items())))
        counters.update({
            "repos_excluded": len(excluded),
            "repos_excluded_detail": dict(sorted(excluded.items())),
            "rendezvous_written": len(result.rendezvous),
            "services_written": len(result.services),
            "edges_written": sum(written.values()),
            "edges_by_type": written,
            "stale_edges_deleted": deleted,
            "orphans_gcd": orphans,
        })
        return counters, result.timings
