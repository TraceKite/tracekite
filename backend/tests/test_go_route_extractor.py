"""Go HTTP route extraction.

net/http (incl. Go 1.22 method patterns), echo, chi, fiber, gorilla/mux, gin.
Precision-first: dynamic paths decline instead of guessing.
"""

from evigraph.services.go_route_extractor import extract_go_routes


def _line(src: str, needle: str) -> int:
    return src[: src.index(needle)].count("\n") + 1


def _one(routes, method, path):
    found = [r for r in routes if r.method == method and r.path == path]
    assert len(found) == 1, (method, path, [(r.method, r.path) for r in routes])
    return found[0]


GO_NET_HTTP = '''package main

import (
	"fmt"
	"net/http"
)

func healthHandler(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintln(w, "ok")
}

func main() {
	http.HandleFunc("/healthz", healthHandler)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/pets/{id}", getPet)
	mux.HandleFunc("POST /api/pets", createPet)
	mux.Handle("/metrics", metricsHandler())
	mux.HandleFunc("admin.example.com/console", adminConsole)
	mux.HandleFunc("/{$}", rootHandler)

	http.ListenAndServe(":8080", mux)
}
'''


class TestNetHttp:
    def test_default_servemux_handlefunc(self):
        routes = extract_go_routes("main.go", GO_NET_HTTP)
        route = _one(routes, "ANY", "/healthz")
        assert route.framework == "net/http"
        assert route.handler_name == "healthHandler"
        assert route.line == _line(GO_NET_HTTP, 'http.HandleFunc("/healthz"')

    def test_go122_method_patterns_split_method_from_path(self):
        routes = extract_go_routes("main.go", GO_NET_HTTP)
        assert _one(routes, "GET", "/api/pets/{id}").handler_name == "getPet"
        assert _one(routes, "POST", "/api/pets").framework == "net/http"

    def test_plain_pattern_is_any_method(self):
        routes = extract_go_routes("main.go", GO_NET_HTTP)
        assert _one(routes, "ANY", "/metrics").handler_name == ""

    def test_host_prefixed_pattern_keeps_path_and_records_host(self):
        routes = extract_go_routes("main.go", GO_NET_HTTP)
        assert _one(routes, "ANY", "/console").attrs == {"host": "admin.example.com"}

    def test_exact_root_marker_normalizes_to_slash(self):
        assert _one(extract_go_routes("main.go", GO_NET_HTTP), "ANY", "/")


GO_ECHO = '''package main

import (
	"fmt"

	"github.com/labstack/echo/v4"
)

func main() {
	e := echo.New()

	e.GET("/users/:id", getUser)
	e.Any("/ping", pingHandler)

	g := e.Group("/api/v1")
	g.POST("/pets", createPet)

	admin := g.Group("/admin")
	admin.DELETE("/pets/:petID", deletePet)

	e.GET(dynamicPath, listUsers)
	e.GET("/files/"+bucket, listFiles)
	e.GET(fmt.Sprintf("/v%d/users", version), versioned)

	e.Logger.Fatal(e.Start(":1323"))
}
'''


class TestEcho:
    def test_verb_with_colon_param_normalized_to_braces(self):
        routes = extract_go_routes("main.go", GO_ECHO)
        route = _one(routes, "GET", "/users/{id}")
        assert route.framework == "echo"
        assert route.handler_name == "getUser"

    def test_any_verb(self):
        assert _one(extract_go_routes("main.go", GO_ECHO), "ANY", "/ping")

    def test_group_prefix_applied(self):
        assert _one(extract_go_routes("main.go", GO_ECHO), "POST", "/api/v1/pets")

    def test_nested_group_composes_prefixes(self):
        routes = extract_go_routes("main.go", GO_ECHO)
        route = _one(routes, "DELETE", "/api/v1/admin/pets/{petID}")
        assert route.line == _line(GO_ECHO, 'admin.DELETE(')

    def test_dynamic_paths_are_skipped(self):
        # variable, "+"-concat, and fmt.Sprintf paths all decline
        assert len(extract_go_routes("main.go", GO_ECHO)) == 4


GO_CHI = '''package main

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

func main() {
	r := chi.NewRouter()
	r.Use(middleware.Logger)

	r.Get("/healthz", healthCheck)

	r.Route("/api/v1", func(r chi.Router) {
		r.Get("/pets", listPets)
		r.Post("/pets", createPet)
		r.Route("/owners", func(r chi.Router) {
			r.Get("/{ownerID}", getOwner)
			r.Delete("/{ownerID:[0-9]+}", deleteOwner)
		})
	})

	r.Mount("/admin", adminRouter())

	http.ListenAndServe(":3000", r)
}
'''


class TestChi:
    def test_top_level_capitalized_verb(self):
        route = _one(extract_go_routes("main.go", GO_CHI), "GET", "/healthz")
        assert route.framework == "chi"

    def test_route_closure_applies_prefix(self):
        routes = extract_go_routes("main.go", GO_CHI)
        assert _one(routes, "GET", "/api/v1/pets").handler_name == "listPets"
        assert _one(routes, "POST", "/api/v1/pets")

    def test_nested_route_closures_compose(self):
        routes = extract_go_routes("main.go", GO_CHI)
        route = _one(routes, "GET", "/api/v1/owners/{ownerID}")
        assert route.line == _line(GO_CHI, 'r.Get("/{ownerID}"')

    def test_regex_constraint_normalized(self):
        assert _one(extract_go_routes("main.go", GO_CHI),
                    "DELETE", "/api/v1/owners/{ownerID}")

    def test_mount_is_cross_router_and_skipped(self):
        assert all("/admin" not in r.path
                   for r in extract_go_routes("main.go", GO_CHI))

    def test_typed_helper_param_binds_router(self):
        source = ('package main\n\nimport "github.com/go-chi/chi/v5"\n\n'
                  'func petRoutes(r chi.Router) {\n'
                  '\tr.Get("/pets", listPets)\n}\n')
        route = _one(extract_go_routes("routes.go", source), "GET", "/pets")
        assert route.framework == "chi"


GO_FIBER = '''package main

import "github.com/gofiber/fiber/v2"

func main() {
	app := fiber.New(fiber.Config{AppName: "petstore"})

	app.Get("/livez", livenessProbe)
	app.All("/echo", echoBack)

	api := app.Group("/v1")
	api.Post("/pets", createPet)
	api.Get("/pets/:petID?", getPet)

	app.Listen(":8080")
}
'''


class TestFiber:
    def test_capitalized_verbs_and_framework(self):
        route = _one(extract_go_routes("main.go", GO_FIBER), "GET", "/livez")
        assert route.framework == "fiber"

    def test_all_maps_to_any(self):
        assert _one(extract_go_routes("main.go", GO_FIBER), "ANY", "/echo")

    def test_group_prefix_and_optional_param(self):
        routes = extract_go_routes("main.go", GO_FIBER)
        assert _one(routes, "POST", "/v1/pets")
        assert _one(routes, "GET", "/v1/pets/{petID}")


GO_GORILLA = '''package main

import (
	"net/http"

	"github.com/gorilla/mux"
)

func main() {
	r := mux.NewRouter()

	r.HandleFunc("/pets", listPets).Methods("GET")
	r.HandleFunc("/pets", createPet).Methods("POST", "PUT")
	r.HandleFunc("/status", statusHandler)

	api := r.PathPrefix("/api").Subrouter()
	api.HandleFunc("/owners/{ownerID:[0-9]+}", getOwner).Methods(http.MethodGet)
	api.Handle("/ws", websocketHandler{}).Methods("GET").Host("ws.example.com")

	http.Handle("/debug", debugHandler)

	http.ListenAndServe(":8000", r)
}
'''


class TestGorilla:
    def test_methods_chain_yields_one_route_per_method(self):
        routes = extract_go_routes("main.go", GO_GORILLA)
        assert _one(routes, "GET", "/pets").handler_name == "listPets"
        assert _one(routes, "POST", "/pets").line == _one(
            routes, "PUT", "/pets").line

    def test_without_methods_is_any(self):
        route = _one(extract_go_routes("main.go", GO_GORILLA), "ANY", "/status")
        assert route.framework == "gorilla"

    def test_subrouter_prefix_and_constraint_and_method_constant(self):
        routes = extract_go_routes("main.go", GO_GORILLA)
        route = _one(routes, "GET", "/api/owners/{ownerID}")
        assert route.handler_name == "getOwner"

    def test_host_chain_recorded(self):
        routes = extract_go_routes("main.go", GO_GORILLA)
        assert _one(routes, "GET", "/api/ws").attrs == {"host": "ws.example.com"}

    def test_default_servemux_in_gorilla_file_stays_net_http(self):
        routes = extract_go_routes("main.go", GO_GORILLA)
        assert _one(routes, "ANY", "/debug").framework == "net/http"

    def test_constraint_with_nested_braces_normalizes(self):
        source = ('package main\n\nimport "github.com/gorilla/mux"\n\n'
                  'func main() {\n'
                  '\tr := mux.NewRouter()\n'
                  '\tr.HandleFunc("/d/{id:[0-9]{4}}", byYear).Methods("GET")\n'
                  '}\n')
        assert _one(extract_go_routes("main.go", source), "GET", "/d/{id}")


GO_GIN = '''package main

import "github.com/gin-gonic/gin"

func setupRouter() *gin.Engine {
	r := gin.Default()
	r.GET("/ping", pong)

	v1 := r.Group("/v1")
	v1.POST("/pets", createPet)

	admin := v1.Group("/admin")
	admin.DELETE("/pets/:id", removePet)
	return r
}
'''


class TestGin:
    def test_uppercase_verbs_resolve_to_gin_not_echo(self):
        route = _one(extract_go_routes("router.go", GO_GIN), "GET", "/ping")
        assert route.framework == "gin"

    def test_group_and_nested_group(self):
        routes = extract_go_routes("router.go", GO_GIN)
        assert _one(routes, "POST", "/v1/pets")
        assert _one(routes, "DELETE", "/v1/admin/pets/{id}")


class TestRobustness:
    def test_non_go_file_returns_nothing(self):
        assert extract_go_routes("app.py", 'e.GET("/x", h)') == []

    def test_empty_content(self):
        assert extract_go_routes("main.go", "") == []

    def test_malformed_source_does_not_raise(self):
        broken = 'package main\n\nfunc main() {\n\tr := chi.NewRouter()\n\tr.Get("/unclosed'
        assert extract_go_routes("broken.go", broken) == []

    def test_ambiguous_frameworks_decline(self):
        # echo and gin share the r.GET(...) shape; an unbound receiver with
        # both imported cannot be attributed, so nothing is guessed.
        source = ('package main\n\nimport (\n'
                  '\t"github.com/gin-gonic/gin"\n'
                  '\t"github.com/labstack/echo/v4"\n)\n\n'
                  'func register(r muxlike) {\n'
                  '\tr.GET("/ambiguous", handleIt)\n}\n')
        assert extract_go_routes("routes.go", source) == []

    def test_single_framework_fallback_and_comments_ignored(self):
        source = ('package main\n\nimport "github.com/labstack/echo/v4"\n\n'
                  'func register(e routerish) {\n'
                  '\t// e.GET("/commented", skipMe)\n'
                  '\te.GET("/ok", handleOK)\n}\n')
        routes = extract_go_routes("routes.go", source)
        assert [(r.method, r.path, r.framework) for r in routes] == [
            ("GET", "/ok", "echo")]
