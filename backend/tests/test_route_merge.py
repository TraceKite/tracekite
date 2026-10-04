"""One endpoint per real route when two readers report it, at its true method."""

import pytest

from tracekite import engine_config
from tracekite.services.scan import scan


@pytest.fixture(autouse=True)
def _key():
    engine_config.configure(graph_hmac_key="route-merge-test")


def _endpoints(tmp_path, files):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    sink = scan(str(tmp_path), "repo")
    return sorted((n.extra_props["http_method"], n.extra_props["path_template"],
                   n.extra_props["framework"])
                  for n in sink.nodes if n.type == "ApiEndpoint"), sink


CHI = '''package main

import "github.com/go-chi/chi/v5"

func main() {
	r := chi.NewRouter()
	r.Route("/admin", func(r chi.Router) {
		r.Delete("/users/{id}", deleteUser)
	})
}
'''

EXPRESS = '''const express = require('express');
const app = express();
const router = express.Router();
router.get('/items/:id', getItem);
app.use('/api', router);
'''

FASTIFY = '''import Fastify from 'fastify';
const server = Fastify();
server.post('/orders/:id', createOrder);
'''

GO_STDLIB = '''package main

import "net/http"

func main() {
	http.HandleFunc("/legacy", legacy)
	http.HandleFunc("POST /orders", createOrder)
}
'''

NEXT_POST_ONLY = '''import type { NextApiRequest, NextApiResponse } from 'next';

const handler = async ({ method }: NextApiRequest, res: NextApiResponse) => {
  switch (method) {
    case 'POST':
      return res.status(200).json({});
    default:
      return res.status(405);
  }
};

export default handler;
'''


class TestPrefixedRoutesLeaveNoPhantom:
    def test_a_chi_route_group(self, tmp_path):
        # Was also `DELETE /users/{}`: the raw `/admin/users/{id}` never
        # matched the canonical `/users/{}`, so the half-parsed row stayed.
        endpoints, _ = _endpoints(tmp_path, {"main.go": CHI})
        assert endpoints == [("DELETE", "/admin/users/{}", "chi")]

    def test_an_express_mount(self, tmp_path):
        endpoints, _ = _endpoints(tmp_path, {"app.js": EXPRESS})
        assert endpoints == [("GET", "/api/items/{}", "express")]


def test_the_framework_reader_names_the_framework(tmp_path):
    # Was `express`: the generic pattern's guess won the duplicate.
    endpoints, _ = _endpoints(tmp_path, {"server.ts": FASTIFY})
    assert endpoints == [("POST", "/orders/{}", "fastify")]


class TestUnconstrainedRoutesStayAny:
    def test_a_next_pages_handler_is_any_not_get(self, tmp_path):
        # It serves only POST; it was recorded as GET.
        endpoints, sink = _endpoints(
            tmp_path, {"pages/api/checkout.ts": NEXT_POST_ONLY})
        assert endpoints == [("ANY", "/api/checkout", "nextjs-pages")]
        keys = [n.extra_props["key"] for n in sink.nodes
                if n.type == "ContractClaim" and n.extra_props["kind"] == "http"]
        assert keys == ["ANY:/api/checkout"]

    def test_go_handlefunc_and_method_patterns(self, tmp_path):
        # Was also `GET /legacy`, and `GET /POST /orders` — the method
        # read as part of the path.
        endpoints, _ = _endpoints(tmp_path, {"main.go": GO_STDLIB})
        assert endpoints == [("ANY", "/legacy", "net/http"),
                             ("POST", "/orders", "net/http")]
