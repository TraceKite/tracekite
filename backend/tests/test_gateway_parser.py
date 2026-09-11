"""Gateway route-table parsing."""

from tracekite.parsers.gateway_parser import (
    parse_envoy_config, parse_js_proxies, parse_kong_config,
    parse_next_config, parse_nginx_conf, parse_traefik_file,
    parse_traefik_labels, sniff_gateway_file,
)

NGINX = r"""
upstream backend {
    server orders:8080;
    server orders-canary:8080 backup;
}

server {
    listen 80;
    server_name api.shop.example www.shop.example;

    location /api/ {
        proxy_pass http://backend/;
        proxy_set_header Host $host;
    }

    location ~* ^/legacy/(.*)$ {
        rewrite ^/legacy/(.*)$ /$1 break;
        proxy_pass http://billing:9000;
    }

    location /static/ {
        root /var/www;
    }

    location = /healthz {
        return 200 "ok";
    }

    location /payments {
        proxy_pass http://payments.internal:8443/v1/;
    }

    location /dyn/ {
        proxy_pass http://$backend_host;
    }
}
"""

ENVOY = """
static_resources:
  listeners:
    - name: main
      address:
        socket_address: { address: 0.0.0.0, port_value: 8080 }
      filter_chains:
        - filters:
            - name: envoy.filters.network.http_connection_manager
              typed_config:
                "@type": type.googleapis.com/envoy.http_connection_manager.v3.HttpConnectionManager
                stat_prefix: ingress_http
                route_config:
                  name: local_route
                  virtual_hosts:
                    - name: shop
                      domains: ["shop.example.com", "*"]
                      routes:
                        - match: { prefix: "/api/orders" }
                          route:
                            cluster: orders_cluster
                            prefix_rewrite: "/orders"
                        - match:
                            safe_regex:
                              regex: "^/v2/items/.*$"
                          route:
                            cluster: catalog_cluster
                        - match: { prefix: "/checkout" }
                          route:
                            weighted_clusters:
                              clusters:
                                - name: checkout_v1
                                  weight: 90
                                - name: checkout_v2
                                  weight: 10
  clusters:
    - name: orders_cluster
      load_assignment:
        endpoints:
          - lb_endpoints:
              - endpoint:
                  address:
                    socket_address: { address: orders.internal, port_value: 8080 }
    - name: catalog_cluster
      load_assignment:
        endpoints:
          - lb_endpoints:
              - endpoint:
                  address:
                    socket_address: { address: catalog.internal, port_value: 9000 }
"""

KONG = r"""
_format_version: "3.0"
services:
  - name: orders-service
    url: http://orders.internal:8081/v1
    routes:
      - name: orders-route
        paths: ["/orders", "/api/orders"]
        hosts: ["api.shop.example"]
        methods: ["GET", "POST"]
  - name: billing-service
    host: billing.internal
    port: 9090
    routes:
      - name: billing-route
        paths: ["/billing"]
        strip_path: false
  - name: legacy-service
    url: http://legacy.internal
    routes:
      - name: legacy-regex
        paths: ['~/lgc/\d+']
"""

TRAEFIK = """
http:
  routers:
    api:
      rule: "Host(`shop.example.com`) && PathPrefix(`/api`)"
      service: orders
      middlewares:
        - api-strip
    dashboard:
      rule: "PathPrefix(`/dash`)"
      service: dash@docker
  services:
    orders:
      loadBalancer:
        servers:
          - url: "http://orders.internal:8080"
  middlewares:
    api-strip:
      stripPrefix:
        prefixes:
          - /api
"""

TRAEFIK_LABELS = [
    "traefik.enable=true",
    "traefik.http.routers.myapp.rule=Host(`app.example.com`) && PathPrefix(`/api`)",
    "traefik.http.routers.myapp.middlewares=myapp-strip",
    "traefik.http.middlewares.myapp-strip.stripprefix.prefixes=/api",
    "traefik.http.services.myapp.loadbalancer.server.port=3000",
]

NEXT_CONFIG = """
/** @type {import('next').NextConfig} */
const nextConfig = {
  basePath: '/shop',
  async rewrites() {
    return {
      beforeFiles: [
        { source: '/api/:path*', destination: 'https://orders.internal/api/:path*' },
      ],
      afterFiles: [
        { source: '/reports/:id', destination: '/internal/reports/:id' },
        { source: '/search', destination: `${process.env.SEARCH_URL}/q` },
      ],
    }
  },
  async redirects() {
    return [
      { source: '/old-shop', destination: '/shop', permanent: true },
    ]
  },
}
module.exports = nextConfig
"""

VITE_CONFIG = r"""
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8081',
      '/v2': {
        target: 'http://catalog:9000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/v2/, ''),
      },
    },
  },
})
"""

HPM = """
const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function (app) {
  app.use(
    '/auth',
    createProxyMiddleware({
      target: 'http://auth:4000',
      changeOrigin: true,
    })
  );

  app.use(createProxyMiddleware('/api', {
    target: 'http://orders:3000',
    pathRewrite: { '^/api': '' },
  }));

  app.use('/dyn', createProxyMiddleware({
    target: process.env.BACKEND_URL,
  }));
};
"""

WEBPACK = """
module.exports = {
  devServer: {
    port: 3000,
    proxy: [
      {
        context: ['/api', '/auth'],
        target: 'http://backend:8080',
        pathRewrite: { '^/api': '' },
      },
    ],
  },
};
"""


def _by_path(rules):
    return {rule.match_path: rule for rule in rules}


class TestNginx:
    def test_upstream_resolution_skips_backup_and_strips_port(self):
        rule = _by_path(parse_nginx_conf("nginx.conf", NGINX))["/api/"]
        assert rule.target == "orders"
        assert rule.attrs["upstream"] == "backend"

    def test_server_name_becomes_match_host(self):
        rules = parse_nginx_conf("nginx.conf", NGINX)
        assert all(r.match_host == "api.shop.example" for r in rules)

    def test_proxy_pass_with_uri_part_strips_prefix(self):
        # CRITICAL nginx semantic: `proxy_pass http://backend/;` (trailing
        # slash = URI part) replaces the matched prefix before forwarding.
        rule = _by_path(parse_nginx_conf("nginx.conf", NGINX))["/api/"]
        assert rule.strip_prefix is True

    def test_proxy_pass_without_uri_part_keeps_full_path(self):
        conf = "server {\n location /keep/ {\n  proxy_pass http://svc;\n }\n}"
        [rule] = parse_nginx_conf("nginx.conf", conf)
        assert rule.strip_prefix is False
        assert rule.target == "svc"

    def test_proxy_pass_uri_becomes_rewrite_to(self):
        rule = _by_path(parse_nginx_conf("nginx.conf", NGINX))["/payments"]
        assert rule.target == "payments.internal"
        assert rule.attrs["port"] == 8443
        assert rule.strip_prefix is True
        assert rule.rewrite_to == "/v1/"

    def test_regex_location_with_rewrite_directive(self):
        rule = _by_path(parse_nginx_conf("nginx.conf", NGINX))["/legacy/(.*)"]
        assert rule.attrs["regex"] is True
        assert rule.attrs["pattern"] == "^/legacy/(.*)$"
        assert rule.rewrite_to == "/$1"
        assert rule.strip_prefix is True
        assert rule.target == "billing"

    def test_locations_without_proxy_pass_are_skipped(self):
        paths = set(_by_path(parse_nginx_conf("nginx.conf", NGINX)))
        assert "/static/" not in paths      # serves files
        assert "/healthz" not in paths      # return-only

    def test_dynamic_proxy_pass_keeps_rule_without_target(self):
        rule = _by_path(parse_nginx_conf("nginx.conf", NGINX))["/dyn/"]
        assert rule.target == ""
        assert rule.attrs["dynamic"] is True

    def test_lines_and_kind(self):
        rules = parse_nginx_conf("nginx.conf", NGINX)
        assert {r.gateway_kind for r in rules} == {"nginx"}
        assert all(r.line > 0 for r in rules)

    def test_malformed_conf_does_not_raise(self):
        assert parse_nginx_conf("bad.conf", "location { proxy_pass") == []
        assert parse_nginx_conf("empty.conf", "") == []

    def test_nested_locations_emit_once_each(self):
        rules = parse_nginx_conf("nginx.conf", """
server {
    location /api/ {
        proxy_pass http://outer/;
        location /api/inner/ {
            proxy_pass http://inner:9000;
        }
    }
}
""")
        # The nested location's proxy_pass must not be double-counted into
        # the enclosing location: exactly one rule per location.
        assert {r.match_path: r.target for r in rules} == {
            "/api/": "outer", "/api/inner/": "inner"}
        assert _by_path(rules)["/api/inner/"].strip_prefix is False

    def test_bare_location_snippet_without_server_block(self):
        [rule] = parse_nginx_conf(
            "snippet.conf", "location /inc/ {\n  proxy_pass http://inc/;\n}")
        assert rule.match_path == "/inc/"
        assert rule.target == "inc"


class TestEnvoy:
    def test_prefix_route_resolves_cluster_endpoint(self):
        rule = _by_path(parse_envoy_config("envoy.yaml", ENVOY))["/api/orders"]
        assert rule.target == "orders.internal"
        assert rule.attrs["cluster"] == "orders_cluster"
        assert rule.match_host == "shop.example.com"

    def test_prefix_rewrite_sets_strip_and_rewrite(self):
        rule = _by_path(parse_envoy_config("envoy.yaml", ENVOY))["/api/orders"]
        assert rule.strip_prefix is True
        assert rule.rewrite_to == "/orders"

    def test_safe_regex_match(self):
        rule = _by_path(parse_envoy_config("envoy.yaml", ENVOY))["/v2/items/.*"]
        assert rule.attrs["regex"] is True
        assert rule.attrs["pattern"] == "^/v2/items/.*$"
        assert rule.target == "catalog.internal"

    def test_weighted_clusters_emit_one_rule_each(self):
        rules = [r for r in parse_envoy_config("envoy.yaml", ENVOY)
                 if r.match_path == "/checkout"]
        weights = {r.attrs["cluster"]: r.weight for r in rules}
        assert weights == {"checkout_v1": 90, "checkout_v2": 10}
        # No cluster definition: fall back to the cluster name as target.
        assert {r.target for r in rules} == {"checkout_v1", "checkout_v2"}

    def test_malformed_yaml_does_not_raise(self):
        assert parse_envoy_config("envoy.yaml", "{{{ not yaml") == []
        assert parse_envoy_config("envoy.yaml", "- just\n- a list") == []


class TestKong:
    def test_one_rule_per_path_with_service_url_target(self):
        rules = parse_kong_config("kong.yml", KONG)
        by_path = _by_path(rules)
        assert by_path["/orders"].target == "orders.internal"
        assert by_path["/api/orders"].target == "orders.internal"
        assert by_path["/orders"].attrs["port"] == 8081
        assert by_path["/orders"].attrs["service_path"] == "/v1"
        assert by_path["/orders"].match_host == "api.shop.example"
        assert by_path["/orders"].attrs["methods"] == ["GET", "POST"]

    def test_strip_path_defaults_true(self):
        # Kong strips the matched path by default — an absent strip_path key
        # MUST become strip_prefix=True.
        assert _by_path(parse_kong_config("kong.yml", KONG))[
            "/orders"].strip_prefix is True

    def test_explicit_strip_path_false_respected(self):
        rule = _by_path(parse_kong_config("kong.yml", KONG))["/billing"]
        assert rule.strip_prefix is False
        assert rule.target == "billing.internal"
        assert rule.attrs["port"] == 9090

    def test_kong3_tilde_marks_regex_path(self):
        rule = _by_path(parse_kong_config("kong.yml", KONG))[r"/lgc/\d+"]
        assert rule.attrs["regex"] is True
        assert rule.target == "legacy.internal"

    def test_malformed_kong_does_not_raise(self):
        assert parse_kong_config("kong.yml", "services: notalist") == []
        assert parse_kong_config("kong.yml", ":::") == []


class TestTraefik:
    def test_router_rule_host_path_and_service_target(self):
        rule = _by_path(parse_traefik_file("traefik.yml", TRAEFIK))["/api"]
        assert rule.match_host == "shop.example.com"
        assert rule.target == "orders.internal"
        assert rule.attrs["port"] == 8080
        assert rule.attrs["router"] == "api"

    def test_strip_prefix_middleware_applies(self):
        by_path = _by_path(parse_traefik_file("traefik.yml", TRAEFIK))
        assert by_path["/api"].strip_prefix is True
        assert by_path["/dash"].strip_prefix is False

    def test_cross_provider_service_ref_falls_back_to_name(self):
        rule = _by_path(parse_traefik_file("traefik.yml", TRAEFIK))["/dash"]
        assert rule.target == "dash"

    def test_labels_keep_target_empty_for_orchestrator_binding(self):
        [rule] = parse_traefik_labels(TRAEFIK_LABELS)
        assert rule.target == ""            # bound to the owning compose service
        assert rule.attrs["router"] == "myapp"
        assert rule.match_path == "/api"
        assert rule.match_host == "app.example.com"
        assert rule.strip_prefix is True

    def test_labels_dict_form(self):
        [rule] = parse_traefik_labels(
            {"traefik.http.routers.web.rule": "PathPrefix(`/`)"})
        assert rule.match_path == "/"
        assert rule.strip_prefix is False

    def test_malformed_traefik_does_not_raise(self):
        assert parse_traefik_file("traefik.yml", "http: [not, a, map]") == []
        assert parse_traefik_labels(["no-equals-sign"]) == []


class TestNextConfig:
    def test_rewrite_with_absolute_destination_keeps_host(self):
        rule = _by_path(parse_next_config("next.config.js", NEXT_CONFIG))[
            "/api/{path}"]
        assert rule.gateway_kind == "next-rewrite"
        assert rule.target == "orders.internal"
        assert rule.rewrite_to == "/api/{path}"
        assert rule.attrs["wildcard"] is True

    def test_relative_destination_is_internal(self):
        rule = _by_path(parse_next_config("next.config.js", NEXT_CONFIG))[
            "/reports/{id}"]
        assert rule.target == ""
        assert rule.attrs["internal"] is True
        assert rule.rewrite_to == "/internal/reports/{id}"

    def test_env_templated_destination_declines_target(self):
        rule = _by_path(parse_next_config("next.config.js", NEXT_CONFIG))[
            "/search"]
        assert rule.target == ""
        assert rule.attrs["dynamic"] is True
        assert rule.attrs["env_ref"] == "SEARCH_URL"

    def test_redirects_get_their_own_kind_and_permanent(self):
        rule = _by_path(parse_next_config("next.config.js", NEXT_CONFIG))[
            "/old-shop"]
        assert rule.gateway_kind == "next-redirect"
        assert rule.attrs["permanent"] is True

    def test_base_path_rule(self):
        rules = [r for r in parse_next_config("next.config.js", NEXT_CONFIG)
                 if r.attrs.get("base_path")]
        assert [r.match_path for r in rules] == ["/shop"]
        assert rules[0].gateway_kind == "next-rewrite"

    def test_malformed_next_config_does_not_raise(self):
        assert parse_next_config("next.config.ts", "") == []
        assert parse_next_config("next.config.ts",
                                 "export default { reactStrictMode: true }") == []


class TestJsProxies:
    def test_vite_string_shorthand(self):
        rule = _by_path(parse_js_proxies("vite.config.ts", VITE_CONFIG))["/api"]
        assert rule.target == "localhost"
        assert rule.attrs["port"] == 8081
        assert rule.attrs["dev"] is True
        assert rule.strip_prefix is False

    def test_vite_rewrite_arrow_strips_prefix(self):
        rule = _by_path(parse_js_proxies("vite.config.ts", VITE_CONFIG))["/v2"]
        assert rule.target == "catalog"
        assert rule.strip_prefix is True

    def test_hpm_context_as_first_argument(self):
        rule = _by_path(parse_js_proxies("setupProxy.js", HPM))["/api"]
        assert rule.target == "orders"
        assert rule.attrs["port"] == 3000
        assert rule.strip_prefix is True    # pathRewrite {'^/api': ''}
        assert "dev" not in rule.attrs      # dev is a vite/webpack marker

    def test_hpm_context_from_enclosing_app_use(self):
        rule = _by_path(parse_js_proxies("setupProxy.js", HPM))["/auth"]
        assert rule.target == "auth"
        assert rule.attrs["port"] == 4000

    def test_hpm_process_env_target_declines(self):
        rule = _by_path(parse_js_proxies("setupProxy.js", HPM))["/dyn"]
        assert rule.target == ""
        assert rule.attrs["dynamic"] is True
        assert rule.attrs["env_ref"] == "BACKEND_URL"

    def test_webpack_array_form_one_rule_per_context(self):
        by_path = _by_path(parse_js_proxies("webpack.config.js", WEBPACK))
        assert set(by_path) == {"/api", "/auth"}
        assert by_path["/api"].target == "backend"
        assert by_path["/api"].strip_prefix is True
        # ^/api never matches an /auth request, so /auth is not stripped.
        assert by_path["/auth"].strip_prefix is False
        assert by_path["/auth"].attrs["dev"] is True

    def test_malformed_js_does_not_raise(self):
        assert parse_js_proxies("x.js", "const a = {") == []
        assert isinstance(parse_js_proxies("x.js", "createProxyMiddleware("),
                          list)


class TestSniff:
    def test_each_format_recognized(self):
        assert sniff_gateway_file("nginx.conf", NGINX) == "nginx"
        assert sniff_gateway_file("deploy/envoy.yaml", ENVOY) == "envoy"
        assert sniff_gateway_file("kong.yml", KONG) == "kong"
        assert sniff_gateway_file("traefik/dynamic.yml", TRAEFIK) == "traefik"
        assert sniff_gateway_file("next.config.ts", NEXT_CONFIG) == "next"
        assert sniff_gateway_file("vite.config.ts", VITE_CONFIG) == "jsproxy"
        assert sniff_gateway_file("src/setupProxy.js", HPM) == "jsproxy"
        assert sniff_gateway_file("webpack.config.js", WEBPACK) == "jsproxy"

    def test_non_gateway_files_return_empty(self):
        assert sniff_gateway_file("app.py", "print('hi')") == ""
        assert sniff_gateway_file("values.yaml", "replicaCount: 1") == ""
        assert sniff_gateway_file("mime.conf", "types { text/html html; }") == ""
        assert sniff_gateway_file("index.js", "console.log('x')") == ""


# A Traefik file-provider config shipped as Kubernetes manifests is routinely
# multi-document: the route table sits behind one or more `---` separators.
# yaml.safe_load RAISES on the second document, so a single-document read
# discards the whole file and reports no routes at all.
TRAEFIK_MULTIDOC = """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: traefik-dynamic
---
http:
  routers:
    api:
      rule: "PathPrefix(`/api`)"
      service: orders
  services:
    orders:
      loadBalancer:
        servers:
          - url: "http://orders.internal:8080"
"""


class TestMultiDocumentYaml:
    def test_traefik_routes_survive_a_document_separator(self):
        rules = parse_traefik_file("traefik.yml", TRAEFIK_MULTIDOC)
        assert [r.target for r in rules] == ["orders.internal"]
