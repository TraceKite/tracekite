"""`link()` must run with no server and no database (A3, Phase 1 gate).

Proven by making the imports impossible rather than merely absent: a blocker
on `sys.meta_path` raises for fastapi, neo4j, starlette and uvicorn, so if any
of them were reachable from the engine's import graph this fails loudly. A
test that only checks `sys.modules` would pass while the dependency sat one
lazy import away.

Run in a subprocess because the test suite itself imports FastAPI — inside
this process those modules are already loaded, and nothing could be blocked.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

PROGRAM = textwrap.dedent(
    '''
    import sys, os

    BANNED = {"fastapi", "neo4j", "starlette", "uvicorn", "pydantic_settings"}

    class Blocker:
        def find_module(self, name, path=None):
            return self.find_spec(name, path)

        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BANNED:
                raise ImportError(f"BLOCKED: engine reached for {name}")
            return None

    sys.meta_path.insert(0, Blocker())
    sys.path.insert(0, %r)

    # A library host configures the engine directly. It cannot import
    # tracekite.config — that needs pydantic-settings, which is banned here — and
    # that is the point: core takes its values from a caller, not an
    # environment it had to be running inside a server to read.
    from tracekite import engine_config
    engine_config.configure(graph_hmac_key="engine-purity-test-key")

    from tracekite.services.linker.base import ClaimRecord
    from tracekite.services.linker.engine import link

    def claim(cid, repo, kind, direction, key, **kw):
        return ClaimRecord(
            id=cid, repo_id=repo, kind=kind, direction=direction, key=key,
            service_hint=kw.get("hint"), hint_source=kw.get("src", "none"),
            matchable=True, evidence=[kw.get("ev", "f.yml:1")], attrs={},
            evidence_node_id=kw.get("node"), evidence_node_type="File")

    # svcname keys must be scope-qualified — R0 skips bare names, so a test
    # using them would mint nothing and still "pass" while proving nothing.
    claims = [
        claim("c1", "repo_a", "svcname", "provides", "compose:billing",
              hint="billing", src="compose"),
        claim("c2", "repo_b", "svcname", "provides", "compose:orders",
              hint="orders", src="compose"),
    ]

    result = link(claims, run_id="linkrun_test", confidence={}, aliases={},
                  promotions=[], now="2026-01-01T00:00:00+00:00")

    assert result.counters["claims_loaded"] == 2, result.counters
    assert sorted(result.repo_ids) == ["repo_a", "repo_b"], result.repo_ids
    # The pipeline must actually produce identities, not merely return.
    names = sorted(s.name for s in result.services)
    assert names == ["billing", "orders"], (names, result.counters)
    assert result.rendezvous, "no rendezvous minted"

    # --- the other half: scan() reads real repositories off disk ----------
    from tracekite.db.memory_store import InMemoryLinkerStore
    from tracekite.services.linker.service import LinkerService
    from tracekite.services.scan import scan

    first = scan(%r, "fixrepo", owner="fix", repo_name="callgraph-sample")
    second = scan(%r, "secrepo", owner="sec", repo_name="planted-secret")
    assert first.nodes, "scan produced no nodes"
    assert first.claims, "scan produced no claims"

    # The Phase 1 gate: a host scans two repos and links them, holding the
    # whole estate in memory, with every heavy dependency blocked.
    store = InMemoryLinkerStore([first, second])
    counters = LinkerService(store).link_full()
    assert counters["claims_loaded"] > 0, counters
    assert store.link_runs[0]["status"] == "done", store.link_runs

    loaded = sorted(m for m in sys.modules if m.split(".")[0] in BANNED)
    assert not loaded, f"banned modules present: {loaded}"

    print("PURE_OK", len(result.edges), len(result.services),
          len(first.nodes), counters["claims_loaded"],
          counters["edges_written"])
    '''
) % (str(BACKEND),
     str(BACKEND / "tests" / "fixtures" / "callgraph-sample"),
     str(BACKEND / "tests" / "fixtures" / "planted-secret"))


class TestEngineIsPure:
    def test_link_runs_with_no_server_and_no_database(self):
        proc = subprocess.run([sys.executable, "-c", PROGRAM],
                              capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, (
            "link() could not run without a server or a database:\n"
            + proc.stdout + proc.stderr)
        assert "PURE_OK" in proc.stdout, proc.stdout

    def test_link_is_deterministic_for_fixed_inputs(self):
        """Same claims and same `now` must yield the same counters. B6 needs
        byte-identical artifacts; this is the floor that claim holds to."""
        first = subprocess.run([sys.executable, "-c", PROGRAM],
                               capture_output=True, text=True, timeout=300)
        second = subprocess.run([sys.executable, "-c", PROGRAM],
                                capture_output=True, text=True, timeout=300)
        assert first.stdout == second.stdout, (first.stdout, second.stdout)
