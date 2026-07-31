"""Webhook producer and consumer joined.

A registration is code in one repo promising another repo's endpoint will
be called later — coupling with no call site at delivery time. The joins
here are strict on purpose, and the declines carry the argument: `url=`
appears in every HTTP call ever written, and a callback whose receiver
declares no matching route might be a typo with a timer on it.
"""

from adduce import engine_config
from adduce.db.memory_store import InMemoryLinkerStore
from adduce.services.http_call_extractor import extract_webhook_registrations
from adduce.services.linker.engine import link
from adduce.services.scan import scan

NOW = "2026-01-01T00:00:00+00:00"


class TestExtractor:
    def test_a_registration_yields_url_and_deliverer(self):
        [(line, url, deliverer)] = extract_webhook_registrations(
            "stripe.WebhookEndpoint.create(\n"
            '    url="https://ours.internal/hooks/stripe",\n)')
        assert line == 2
        assert url == "https://ours.internal/hooks/stripe"
        assert deliverer == "stripe"

    def test_a_url_kwarg_without_hook_context_is_not_a_registration(self):
        """`url=` appears in every HTTP call ever written."""
        assert extract_webhook_registrations(
            'requests.post("http://x/api", json={"url": "https://a/b"})') \
            == []

    def test_callback_url_counts_as_context_by_itself(self):
        [(_, url, _)] = extract_webhook_registrations(
            'client.subscriptions.add(callback_url="https://r/cb")')
        assert url == "https://r/cb"


class TestJoin:
    def test_a_registered_callback_joins_the_receivers_route(self, tmp_path):
        """The exit criterion, through the real pipeline: the registrar's
        service gains REGISTERS_WEBHOOK to the receiver's contract, with
        the registration line cited."""
        engine_config.configure(graph_hmac_key="webhook-e2e")
        ours = tmp_path / "ours"
        (ours / "src").mkdir(parents=True)
        (ours / "docker-compose.yml").write_text(
            'services:\n  ours:\n    build: .\n    ports:\n'
            '      - "8080:8080"\n')
        (ours / "src" / "hooks.py").write_text(
            "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n"
            '@app.post("/hooks/stripe")\n'
            "def stripe_hook():\n    return {}\n")
        (ours / "src" / "setup_billing.py").write_text(
            "import stripe\n\n\n"
            "def register():\n"
            "    stripe.WebhookEndpoint.create(\n"
            '        url="http://ours:8080/hooks/stripe",\n    )\n')

        store = InMemoryLinkerStore([scan(str(ours), "ours")])
        result = link(store.load_claims(), run_id="linkrun_d3", now=NOW)

        hooks = [e for e in result.edges
                 if e.type == "REGISTERS_WEBHOOK" and e.status == "active"]
        assert hooks, result.counters
        assert "hooks/stripe" in hooks[0].target_id
        assert hooks[0].extra_props.get("deliverer") == "stripe"
        assert any("setup_billing.py" in cite for cite in hooks[0].evidence)
        assert result.counters.get("r13.registered") == 1

    def test_a_callback_to_an_undeclared_route_declines(self, tmp_path):
        """The receiver never declared the path: asserting the delivery
        contract would invent an edge with a timer on it."""
        engine_config.configure(graph_hmac_key="webhook-decline")
        ours = tmp_path / "ours"
        (ours / "src").mkdir(parents=True)
        (ours / "docker-compose.yml").write_text(
            "services:\n  ours:\n    build: .\n")
        (ours / "src" / "setup.py").write_text(
            "import stripe\n\n"
            "stripe.WebhookEndpoint.create(\n"
            '    url="http://ours:8080/hooks/ghost",\n)\n')
        store = InMemoryLinkerStore([scan(str(ours), "ours")])
        result = link(store.load_claims(), run_id="linkrun_ghost", now=NOW)
        assert not [e for e in result.edges
                    if e.type == "REGISTERS_WEBHOOK"]
        assert result.counters.get("r13.receiver_unmatched") == 1
