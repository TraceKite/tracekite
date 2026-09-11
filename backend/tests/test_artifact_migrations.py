"""Reading an artifact written by an older engine.

An artifact outlives the code that wrote it, so "refuse anything not exactly
current" is too strict and "read anything" is far too loose. The SemVer policy
already decides: minor is additive with known defaults, major changed meaning.
"""

import pytest

from evigraph.db.artifact_migrations import (
    MIGRATIONS, UnmigratableArtifact, can_read, migrate, register_migration,
)
from evigraph.wire import WIRE_VERSION


class TestPolicy:
    def test_the_current_version_reads(self):
        readable, reason = can_read(WIRE_VERSION)
        assert readable, reason

    def test_a_different_major_is_refused_with_a_reason(self):
        """A field removed or renamed cannot be filled in honestly."""
        readable, reason = can_read("0.9.0")
        assert not readable
        assert "major" in reason

    def test_a_newer_version_is_refused(self):
        """This engine does not know what was added and would read it as
        absent — which looks like data rather than ignorance."""
        readable, reason = can_read("1.99.0")
        assert not readable
        assert "newer" in reason

    def test_an_unparseable_version_is_refused_not_guessed(self):
        readable, reason = can_read("not-a-version")
        assert not readable and "unreadable" in reason

    def test_an_older_minor_without_a_migration_is_refused(self):
        """Passing an unknown shape through is how a compaction ends up
        mixing two contracts and reporting neither."""
        MIGRATIONS.pop((1, 0), None)
        readable, reason = can_read("1.0.0") if WIRE_VERSION != "1.0.0" \
            else (True, "")
        if WIRE_VERSION != "1.0.0":
            assert not readable and "no declared migration" in reason


class TestMigrating:
    def test_a_declared_migration_is_applied(self):
        """Simulates a 1.0 -> 1.1 bump that added a field with a default."""
        from evigraph.db import artifact_migrations as m

        original = m.WIRE_VERSION
        try:
            m.WIRE_VERSION = "1.1.0"

            @register_migration(1, 0)
            def _add_field(meta):
                return {**meta, "new_field": "default"}

            out = migrate({"wire_version": "1.0.0", "repo_id": "r"})
            assert out["new_field"] == "default"
            assert out["wire_version"] == "1.1.0"
            assert out["repo_id"] == "r", "existing values must survive"
        finally:
            m.WIRE_VERSION = original
            MIGRATIONS.pop((1, 0), None)

    def test_migrating_an_unreadable_artifact_raises(self):
        """Rather than returning half-migrated metadata, which is worse than
        none because it looks readable."""
        with pytest.raises(UnmigratableArtifact):
            migrate({"wire_version": "0.1.0"})
