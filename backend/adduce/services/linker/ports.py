"""The storage surface a link run needs, declared by the linker itself.

Core names the interface; the store layer implements it (architecture §2 —
arrows point down only, and core imports nothing from the layers above it). A
link run that depends on this Protocol instead of on Neo4j is what lets the
same engine run against SQLite, an in-memory store, or a host's own storage
when A5 lands, without the linker changing at all.

Keep it narrow. Every method here is storage a link run cannot avoid. Anything
a resolver wants beyond this is reaching past the boundary, and the operation
belongs on this Protocol before it belongs in a resolver.
"""

from typing import Protocol

from adduce.services.linker.base import ClaimRecord


class LinkerStore(Protocol):
    """Every storage operation one link run performs, read and write."""

    # --- reads ------------------------------------------------------------

    def load_claims(self) -> list[ClaimRecord]:
        """Every claim belonging to a repo that finished a write.

        Claims from a partially-written repo must not be returned: linking off
        them yields edges that look resolved and are silently incomplete.
        """

    def unlinkable_repos(self) -> dict[str, str]:
        """Repo id -> lifecycle state, for every repo excluded from the link.

        A repo whose write failed part-way has claims in the graph but an
        unknown fraction of its evidence, so linking off it is unsafe. It is
        therefore skipped — and skipping without saying so makes an estate
        with a broken repo look identical to a smaller estate.
        """

    def claim_fingerprints(self) -> dict[str, str]:
        """Repo id → digest of that repo's current claim ids."""

    def stored_fingerprints(self) -> dict[str, str]:
        """Repo id → the digest recorded at its last link."""

    # --- writes -----------------------------------------------------------

    def store_fingerprints(self, fingerprints: dict[str, str]) -> None: ...

    def create_link_run(self, run_id: str, mode: str) -> None: ...

    def finish_link_run(self, run_id: str, status: str, counters: dict,
                        error: str | None = None) -> None: ...

    def write_rendezvous_nodes(self, specs: list) -> int: ...

    def write_service_nodes(self, specs: list) -> int: ...

    def write_linker_edges(self, edges: list) -> dict[str, int]: ...

    def delete_stale_linker_edges(self, current_run_id: str) -> int: ...

    def stamp_repos_linked(self, repo_ids: list[str], run_id: str) -> None: ...

    def gc_orphan_rendezvous(self) -> int: ...
