"""Seeded secrets must not survive into a claim, an artifact, or a log.

`test_ingest_pipeline.test_planted_secrets_never_reach_graph` already pins the
scan's nodes and edges. This covers what it does not, and what B4 makes
dangerous: once a link run's output is written to a file and published by CI,
a leaked secret leaves the machine. So the whole *link* output is checked, and
so are the logs both halves emit.

The fixture plants values marked `PLANTEDSECRET…` in an application.yml and a
config.properties — a password, an API key, an AWS key, and one embedded in a
connection URL, which is the shape that most often escapes a naive redactor.
"""

import io
import json
import logging
import os

from tracekite import engine_config
from tracekite.db.memory_store import InMemoryLinkerStore
from tracekite.services.linker.service import LinkerService
from tracekite.services.scan import scan

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PLANTED = os.path.join(FIXTURES, "planted-secret")
MARKER = "PLANTEDSECRET"


def _serialise(*objects) -> str:
    """Everything an artifact could carry, flattened to one searchable blob."""
    return json.dumps([vars(o) if hasattr(o, "__dict__") else o
                       for o in objects], default=str)


class TestSecretsNeverLeaveTheMachine:
    def _scan(self):
        engine_config.configure(graph_hmac_key="s1-containment-test-key")
        return scan(PLANTED, "secrepo", owner="sec", repo_name="planted")

    def test_fixture_actually_contains_secrets(self):
        """Guard the guard: if the fixture stopped carrying secrets, every
        assertion below would pass while proving nothing."""
        found = []
        for name in os.listdir(PLANTED):
            with open(os.path.join(PLANTED, name), encoding="utf-8") as fh:
                found += [ln for ln in fh if MARKER in ln]
        assert len(found) >= 4, f"fixture no longer seeds secrets: {found}"

    def test_link_output_carries_no_secret(self):
        """The link result is what B4 publishes as an artifact."""
        store = InMemoryLinkerStore([self._scan()])
        counters = LinkerService(store).link_full()

        blob = _serialise(*store.edges, *store.rendezvous, *store.services)
        blob += json.dumps(counters, default=str)
        blob += json.dumps(store.link_runs, default=str)
        assert MARKER not in blob

    def test_claims_carry_no_secret(self):
        """A claim's key is a rendezvous value other repos match on — a secret
        reaching one would be published and joined against."""
        claims = InMemoryLinkerStore([self._scan()]).load_claims()
        assert claims, "planted fixture must still produce claims"
        assert MARKER not in _serialise(*claims)

    def test_secret_bearing_config_is_redacted_not_dropped(self):
        """Redaction must keep the fact and lose the value: dropping the
        config entirely would be a silent decline, and the graph would stop
        recording that a secret is wired in at all."""
        sink = self._scan()
        configs = [n for n in sink.nodes if n.type == "Config"]
        secrets = [n for n in configs
                   if n.extra_props.get("value_class") == "secret"]
        assert secrets, "secrets must be recorded as redacted, not discarded"
        assert all(n.extra_props.get("value_hmac") for n in secrets), \
            "a redacted secret still needs its keyed digest to be joinable"

    def test_logs_carry_no_secret(self):
        """Logs are the leak nobody diffs. Captured across scan *and* link,
        because either half could format a value into a message."""
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            store = InMemoryLinkerStore([self._scan()])
            LinkerService(store).link_full()
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)

        assert MARKER not in stream.getvalue()
