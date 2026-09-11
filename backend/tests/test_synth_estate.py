"""The synthetic estate is trustworthy ground truth.

Every scale measurement and the estate-level precision check stand on this
generator, so its own failure modes get tests first: an estate that differs
between two runs makes measurements incomparable, and a planted call that
does not link makes the recall number a lie about the engine when it is a
bug in the fixture.
"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from evigraph import engine_config  # noqa: E402
from evigraph.db.memory_store import InMemoryLinkerStore  # noqa: E402
from evigraph.services.linker.engine import link  # noqa: E402
from evigraph.services.scan import scan  # noqa: E402
from tools.synth_estate import generate  # noqa: E402


def tree_digest(root: str) -> str:
    """One hash over every file's path and bytes, in sorted order."""
    rolled = hashlib.sha256()
    for dirpath, dirnames, filenames in sorted(os.walk(root)):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rolled.update(os.path.relpath(path, root).encode())
            with open(path, "rb") as fh:
                rolled.update(fh.read())
    return rolled.hexdigest()


@pytest.fixture(scope="module")
def estate(tmp_path_factory):
    out = tmp_path_factory.mktemp("estate")
    manifest = generate(str(out), repos=8, calls_per_service=2,
                        hot_share=0.5, pad_files=1, pad_functions=2, seed=7)
    return str(out), manifest


@pytest.fixture(scope="module")
def linked(estate):
    out, manifest = estate
    engine_config.configure(graph_hmac_key="synth-estate-test")
    sinks = [scan(os.path.join(out, repo), repo)
             for repo in sorted(manifest["repos"])]
    return manifest, link(InMemoryLinkerStore(sinks).load_claims(),
                          run_id="linkrun_synth",
                          now="2026-01-01T00:00:00+00:00")


def service_pairs(result) -> set[tuple[str, str]]:
    name_of = {s.service_id: s.name for s in result.services}
    return {(name_of.get(e.source_id, e.source_id).split(":")[-1],
             name_of.get(e.target_id, e.target_id).split(":")[-1])
            for e in result.edges
            if e.type == "CALLS_SERVICE" and e.status == "active"}


class TestDeterminism:
    def test_same_seed_same_bytes(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        generate(str(a), repos=4, pad_files=1, seed=11)
        generate(str(b), repos=4, pad_files=1, seed=11)
        assert tree_digest(str(a)) == tree_digest(str(b))

    def test_a_different_seed_is_a_different_estate(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        generate(str(a), repos=4, pad_files=1, seed=11)
        generate(str(b), repos=4, pad_files=1, seed=12)
        assert tree_digest(str(a)) != tree_digest(str(b))


class TestGroundTruth:
    def test_every_planted_call_links(self, linked):
        """Recall against construction: a planted call that fails to link is
        either an engine regression or a generator bug, and both must fail
        here rather than skew a thousand-repo measurement."""
        manifest, result = linked
        planted = {tuple(c) for c in map(tuple, manifest["calls"])}
        missing = planted - service_pairs(result)
        assert not missing, sorted(missing)[:10]

    def test_no_call_edge_outside_the_manifest(self, linked):
        """Precision against construction — the estate-scale form of
        189 TP / 0 FP. An unplanted active call edge is a false positive
        manufactured by the engine."""
        manifest, result = linked
        planted = {tuple(c) for c in map(tuple, manifest["calls"])}
        extra = service_pairs(result) - planted
        assert not extra, sorted(extra)[:10]

    def test_the_hot_provider_is_actually_hot(self, estate):
        _out, manifest = estate
        assert len(manifest["hot_consumers"]) >= 3
        assert all((c, manifest["hot_provider"]) in
                   set(map(tuple, manifest["calls"]))
                   for c in manifest["hot_consumers"])

    def test_a_monorepo_nests_its_services(self, tmp_path):
        manifest = generate(str(tmp_path / "m"), repos=2, monorepos=1,
                            mono_services=3, pad_files=0, seed=5)
        mono = [r for r, members in manifest["repos"].items()
                if len(members) > 1]
        assert len(mono) == 1
        for service in manifest["repos"][mono[0]]:
            assert os.path.exists(os.path.join(
                str(tmp_path / "m"), mono[0], "services", service,
                "docker-compose.yml"))
