"""WebFlux functional + Ktor route extraction."""

from evigraph.services.jvm_route_extractor import extract_jvm_routes


def _line(src: str, needle: str) -> int:
    return src[: src.index(needle)].count("\n") + 1


def _one(routes, method, path):
    found = [r for r in routes if r.method == method and r.path == path]
    assert len(found) == 1, (method, path, [(r.method, r.path) for r in routes])
    return found[0]


WEBFLUX_JAVA = '''package org.petclinic.owner;

import static org.springframework.web.reactive.function.server.RequestPredicates.GET;
import static org.springframework.web.reactive.function.server.RequestPredicates.POST;
import static org.springframework.web.reactive.function.server.RequestPredicates.PUT;
import static org.springframework.web.reactive.function.server.RequestPredicates.path;
import static org.springframework.web.reactive.function.server.RouterFunctions.nest;
import static org.springframework.web.reactive.function.server.RouterFunctions.route;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.server.RouterFunction;
import org.springframework.web.reactive.function.server.ServerResponse;

@Configuration
public class OwnerRouterConfig {

    @Bean
    public RouterFunction<ServerResponse> ownerRoutes(OwnerHandler handler) {
        return route(GET("/owners/{ownerId}"), handler::getOwner)
                .andRoute(POST("/owners"), handler::createOwner);
    }

    @Bean
    public RouterFunction<ServerResponse> petRoutes(PetHandler petHandler) {
        return nest(path("/api"),
                route(GET("/pets"), petHandler::list)
                        .andRoute(PUT("/pets/{petId}"), petHandler::update));
    }
}
'''


class TestWebFluxJavaPredicates:
    def test_route_with_request_predicate(self):
        routes = extract_jvm_routes("OwnerRouterConfig.java", WEBFLUX_JAVA)
        route = _one(routes, "GET", "/owners/{ownerId}")
        assert route.framework == "webflux-fn"
        assert route.handler_name == "handler::getOwner"
        assert route.line == _line(WEBFLUX_JAVA, 'GET("/owners/{ownerId}")')

    def test_chained_and_route(self):
        routes = extract_jvm_routes("OwnerRouterConfig.java", WEBFLUX_JAVA)
        assert _one(routes, "POST", "/owners").handler_name == "handler::createOwner"

    def test_nest_applies_path_prefix_inside_span(self):
        routes = extract_jvm_routes("OwnerRouterConfig.java", WEBFLUX_JAVA)
        assert _one(routes, "GET", "/api/pets").handler_name == "petHandler::list"
        assert _one(routes, "PUT", "/api/pets/{petId}")


WEBFLUX_BUILDER = '''package org.petclinic.products;

import static org.springframework.web.reactive.function.server.RequestPredicates.accept;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.web.reactive.function.server.RequestPredicates;
import org.springframework.web.reactive.function.server.RouterFunction;
import org.springframework.web.reactive.function.server.RouterFunctions;
import org.springframework.web.reactive.function.server.ServerResponse;

@Configuration
public class ProductRouterConfig {

    @Bean
    public RouterFunction<ServerResponse> productRoutes(ProductHandler handler) {
        return RouterFunctions.route()
                .GET("/products", handler::all)
                .GET("/products/{id}", accept(MediaType.APPLICATION_JSON), handler::byId)
                .POST("/products", handler::create)
                .nest(RequestPredicates.path("/v1"), builder -> builder
                        .DELETE("/products/{id}", handler::purge))
                .build();
    }
}
'''


class TestWebFluxBuilder:
    def test_builder_verbs(self):
        routes = extract_jvm_routes("ProductRouterConfig.java", WEBFLUX_BUILDER)
        assert _one(routes, "GET", "/products").handler_name == "handler::all"
        assert _one(routes, "POST", "/products").handler_name == "handler::create"

    def test_extra_predicate_arg_keeps_path_drops_handler(self):
        routes = extract_jvm_routes("ProductRouterConfig.java", WEBFLUX_BUILDER)
        get_by_id = [r for r in routes
                     if r.method == "GET" and r.path == "/products/{id}"]
        assert len(get_by_id) == 1
        assert get_by_id[0].handler_name == ""

    def test_builder_nest_prefixes_lambda_body(self):
        routes = extract_jvm_routes("ProductRouterConfig.java", WEBFLUX_BUILDER)
        assert _one(routes, "DELETE", "/v1/products/{id}").handler_name == "handler::purge"


WEBFLUX_KOTLIN = '''package org.petclinic.reservations

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.web.reactive.function.server.coRouter

@Configuration
class ReservationRouterConfig(private val handler: ReservationHandler) {

    @Bean
    fun reservationRoutes() = coRouter {
        GET("/reservations", handler::list)
        POST("/reservations", handler::create)
        "/api".nest {
            GET("/pets", handler::pets)
            "/v2".nest {
                DELETE("/pets/{petId}", handler::removePet)
            }
        }
        GET("/rooms/$roomId", handler::room)
    }
}
'''


class TestWebFluxKotlin:
    def test_corouter_verbs(self):
        routes = extract_jvm_routes("ReservationRouterConfig.kt", WEBFLUX_KOTLIN)
        assert _one(routes, "GET", "/reservations").handler_name == "handler::list"
        assert _one(routes, "POST", "/reservations")

    def test_string_nest_prefix(self):
        routes = extract_jvm_routes("ReservationRouterConfig.kt", WEBFLUX_KOTLIN)
        assert _one(routes, "GET", "/api/pets")

    def test_nested_nest_composes(self):
        routes = extract_jvm_routes("ReservationRouterConfig.kt", WEBFLUX_KOTLIN)
        assert _one(routes, "DELETE", "/api/v2/pets/{petId}")

    def test_template_path_is_dynamic_and_skipped(self):
        routes = extract_jvm_routes("ReservationRouterConfig.kt", WEBFLUX_KOTLIN)
        assert not any("/rooms" in r.path for r in routes)


KTOR_KOTLIN = '''package com.petclinic.visits

import io.ktor.http.HttpStatusCode
import io.ktor.server.application.*
import io.ktor.server.response.*
import io.ktor.server.routing.*

fun Application.configureRouting(visitService: VisitService) {
    routing {
        get("/health") {
            call.respondText("OK")
        }
        route("/api/v1") {
            get("/visits") {
                call.respond(visitService.all())
            }
            post("/visits") {
                call.respond(HttpStatusCode.Created)
            }
            route("/owners") {
                get("/{ownerId}") {
                    call.respond(visitService.forOwner(call.parameters["ownerId"]))
                }
                delete("/{ownerId?}") {
                    call.respond(HttpStatusCode.NoContent)
                }
            }
        }
        route("/status") {
            get {
                call.respondText("up")
            }
        }
        route("/secure") {
            authenticate {
                get { call.respond(currentUser()) }
            }
        }
        get("/files/$name") { }
    }
}
'''


class TestKtor:
    def test_basic_verb_with_path(self):
        routes = extract_jvm_routes("Routing.kt", KTOR_KOTLIN)
        route = _one(routes, "GET", "/health")
        assert route.framework == "ktor"
        assert route.line == _line(KTOR_KOTLIN, 'get("/health")')

    def test_route_block_prefixes_children(self):
        routes = extract_jvm_routes("Routing.kt", KTOR_KOTLIN)
        assert _one(routes, "GET", "/api/v1/visits")
        assert _one(routes, "POST", "/api/v1/visits")

    def test_nested_route_blocks_compose_and_optional_param(self):
        routes = extract_jvm_routes("Routing.kt", KTOR_KOTLIN)
        assert _one(routes, "GET", "/api/v1/owners/{ownerId}")
        assert _one(routes, "DELETE", "/api/v1/owners/{ownerId}")

    def test_pathless_verb_takes_route_prefix(self):
        assert _one(extract_jvm_routes("Routing.kt", KTOR_KOTLIN), "GET", "/status")

    def test_bare_verb_wrapped_in_other_lambda_is_declined(self):
        # `authenticate { get { } }`: the path shape through an arbitrary
        # wrapper is unknowable, so it is skipped rather than guessed.
        routes = extract_jvm_routes("Routing.kt", KTOR_KOTLIN)
        assert not any(r.path == "/secure" for r in routes)

    def test_template_path_is_dynamic_and_skipped(self):
        routes = extract_jvm_routes("Routing.kt", KTOR_KOTLIN)
        assert not any("/files" in r.path for r in routes)

    def test_route_extension_function_without_routing_block(self):
        source = ('package com.petclinic.vets\n\n'
                  'import io.ktor.server.routing.Route\n'
                  'import io.ktor.server.routing.get\n\n'
                  'fun Route.vetRoutes() {\n'
                  '    get("/vets") {\n'
                  '        call.respond(vetService.all())\n'
                  '    }\n'
                  '}\n')
        assert _one(extract_jvm_routes("VetRoutes.kt", source), "GET", "/vets")


class TestRobustness:
    def test_non_jvm_file_returns_nothing(self):
        assert extract_jvm_routes("routes.py", 'GET("/x")') == []

    def test_no_framework_marker_declines(self):
        source = ('public class Helper {\n'
                  '    static String GET(String p) { return prefix + GET("/x"); }\n'
                  '}\n')
        assert extract_jvm_routes("Helper.java", source) == []

    def test_ktor_dsl_in_java_file_is_not_ktor(self):
        assert extract_jvm_routes(
            "Routes.java", 'routing { get("/x") { } }') == []

    def test_malformed_source_does_not_raise(self):
        assert extract_jvm_routes("Broken.kt", 'routing { get("/x') == []
