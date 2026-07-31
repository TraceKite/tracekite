"""WebSocket and SSE contracts.

A long-lived channel is invisible to request/response extraction, and an
invisible dependency is the one that pages whoever breaks it. The channel
joins like any GET — the upgrade happens after the connect and changes
nothing about who is depended on — so what these tests pin is that the
CHANNEL survives the trip: extractor to claim to contract to edge.
"""

from adduce import engine_config
from adduce.db.memory_store import InMemoryLinkerStore
from adduce.services.http_call_extractor import extract_http_calls
from adduce.services.linker.engine import link
from adduce.services.scan import scan

NOW = "2026-01-01T00:00:00+00:00"


class TestClients:
    def test_a_websocket_constructor_is_a_channel_consumer(self):
        sites = extract_http_calls(
            "src/live.ts",
            'const ws = new WebSocket("ws://billing-service:8080/v1/live");',
            "typescript")
        [site] = sites
        assert site.attrs["channel"] == "websocket"
        assert site.service_hint == "billing-service"
        assert site.method == "GET"
        assert site.path_template == "/v1/live"

    def test_an_eventsource_is_an_sse_consumer(self):
        [site] = extract_http_calls(
            "src/feed.ts",
            'const es = new EventSource("/api/events");', "typescript")
        assert site.attrs["channel"] == "sse"
        assert site.path_template == "/api/events"

    def test_a_wss_url_names_its_host_like_https(self):
        [site] = extract_http_calls(
            "src/live.ts",
            'new WebSocket("wss://orders-service:9000/stream")',
            "typescript")
        assert site.service_hint == "orders-service"

    def test_a_variable_url_is_declined_not_guessed(self):
        assert extract_http_calls(
            "src/live.ts", "new WebSocket(endpointFromConfig)",
            "typescript") == []


class TestProviders:
    def test_a_fastapi_websocket_route_is_a_channel_contract(self, tmp_path):
        engine_config.configure(graph_hmac_key="channel-test")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text(
            "from fastapi import FastAPI, WebSocket\n\n"
            "app = FastAPI()\n\n\n"
            '@app.websocket("/v1/live")\n'
            "async def live(ws: WebSocket):\n"
            "    await ws.accept()\n")
        sink = scan(str(tmp_path), "repo_ws")
        endpoints = [(n.extra_props.get("http_method"),
                      n.extra_props.get("path_template"),
                      n.extra_props.get("framework"))
                     for n in sink.nodes if n.type == "ApiEndpoint"]
        assert ("GET", "/v1/live", "websocket") in endpoints

    def test_a_jsr356_server_endpoint_is_a_channel_contract(self, tmp_path):
        engine_config.configure(graph_hmac_key="channel-test")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "LiveSocket.java").write_text(
            "import jakarta.websocket.server.ServerEndpoint;\n\n"
            '@ServerEndpoint("/v1/live")\n'
            "public class LiveSocket {\n"
            "    public void onOpen() {}\n"
            "}\n")
        sink = scan(str(tmp_path), "repo_jws")
        endpoints = [(n.extra_props.get("path_template"),
                      n.extra_props.get("framework"))
                     for n in sink.nodes if n.type == "ApiEndpoint"]
        assert ("/v1/live", "websocket") in endpoints


class TestEndToEnd:
    def test_the_channel_survives_to_the_contract_and_the_edge(self, tmp_path):
        """The exit criterion: the contract node says it is a websocket,
        and the consumer's edge says so too — 'depends on a stream' and
        'depends on a request' are different findings."""
        engine_config.configure(graph_hmac_key="channel-e2e")
        api = tmp_path / "api"
        (api / "src").mkdir(parents=True)
        (api / "docker-compose.yml").write_text(
            'services:\n  billing-service:\n    build: .\n    ports:\n'
            '      - "8080:8080"\n')
        (api / "src" / "app.py").write_text(
            "from fastapi import FastAPI, WebSocket\n\n"
            "app = FastAPI()\n\n\n"
            '@app.websocket("/v1/live")\n'
            "async def live(ws: WebSocket):\n"
            "    await ws.accept()\n")

        web = tmp_path / "web"
        (web / "src").mkdir(parents=True)
        (web / "src" / "Live.tsx").write_text(
            'export function Live() {\n'
            '  new WebSocket("ws://billing-service:8080/v1/live");\n'
            '  return null;\n}\n')

        store = InMemoryLinkerStore([scan(str(api), "api"),
                                     scan(str(web), "web")])
        result = link(store.load_claims(), run_id="linkrun_d2", now=NOW)

        contracts = [s for s in result.rendezvous
                     if s.label == "HttpContract"
                     and s.props.get("channel") == "websocket"]
        assert contracts, [s.props for s in result.rendezvous
                           if s.label == "HttpContract"]
        assert result.counters.get("r7.channel_contracts", 0) >= 1

        edges = [e for e in result.edges
                 if e.type == "UI_CALLS" and e.status == "active"
                 and e.extra_props.get("channel") == "websocket"]
        assert edges, [
            (e.type, e.extra_props.get("channel")) for e in result.edges
            if e.type in ("INVOKES", "UI_CALLS")]
        assert any("Live.tsx" in cite for cite in edges[0].evidence)
