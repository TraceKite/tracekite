"""Tests for precision-first C# ASP.NET Core Minimal API extraction."""

from adduce.services.csharp_route_extractor import (
    extract_csharp_routes,
    extract_csharp_routes_with_declines,
)


def test_extracts_literal_verbs_and_constraints():
    content = """
var app = WebApplication.Create();
app.MapGet("/v1/pets", () => "pets");
app.MapPost("/v1/orders", (Order order) => order);
app.MapPut("/v1/orders/{id:int}", (int id) => id);
app.MapDelete("/v1/orders/{id:guid}", (Guid id) => id);
app.MapPatch("/v1/orders/{id}", () => "ok");
"""
    routes = extract_csharp_routes("Program.cs", content)

    assert [(route.method, route.path) for route in routes] == [
        ("GET", "/v1/pets"),
        ("POST", "/v1/orders"),
        ("PUT", "/v1/orders/{id}"),
        ("DELETE", "/v1/orders/{id}"),
        ("PATCH", "/v1/orders/{id}"),
    ]
    assert routes[0].line == 3


def test_independent_groups_do_not_leak_prefixes():
    content = """
var app = WebApplication.Create();
var api = app.MapGroup("/api");
var admin = app.MapGroup("/admin");
api.MapGet("/users", () => "users");
admin.MapGet("/audit", () => "audit");
app.MapGet("/health", () => "ok");
"""
    routes = extract_csharp_routes("Program.cs", content)

    assert [route.path for route in routes] == [
        "/api/users", "/admin/audit", "/health"]


def test_nested_groups_compose_their_own_prefixes():
    content = """
var app = WebApplication.Create();
var api = app.MapGroup("/api");
var v1 = api.MapGroup("/v1");
v1.MapGet("/users", () => "users");
"""
    routes = extract_csharp_routes("Program.cs", content)

    assert [route.path for route in routes] == ["/api/v1/users"]


def test_chained_group_route_is_resolved():
    routes = extract_csharp_routes(
        "Program.cs",
        'var app = WebApplication.Create();\n'
        'app.MapGroup("/api").MapGet("/users", () => "users");',
    )

    assert [(route.method, route.path) for route in routes] == [
        ("GET", "/api/users")]


def test_computed_paths_and_group_prefixes_are_declined():
    content = """
var app = WebApplication.Create();
var dynamic = app.MapGroup(prefix);
dynamic.MapGet("/users", () => "users");
app.MapGet(routePath, () => "computed");
app.MapGroup(groupPath).MapPost("/orders", () => "computed");
"""
    routes, declined = extract_csharp_routes_with_declines(
        "Program.cs", content)

    assert routes == []
    assert declined == 3


def test_comments_do_not_emit_routes_or_declines():
    content = """
// app.MapGet("/commented", () => "no");
/* var api = app.MapGroup(prefix);
api.MapGet("/also-commented", () => "no"); */
var app = WebApplication.Create();
app.MapGet("/live", () => "yes");
"""
    routes, declined = extract_csharp_routes_with_declines(
        "Program.cs", content)

    assert [route.path for route in routes] == ["/live"]
    assert declined == 0


def test_unknown_route_receiver_is_declined_instead_of_assumed_root():
    routes, declined = extract_csharp_routes_with_declines(
        "Routes.cs", 'routes.MapGet("/users", () => "users");')

    assert routes == []
    assert declined == 1


def test_typed_group_assignment_keeps_its_prefix():
    content = """
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
RouteGroupBuilder api = app.MapGroup("/api");
api.MapGet("/users", () => "users");
"""

    routes, declined = extract_csharp_routes_with_declines(
        "Program.cs", content)

    assert [route.path for route in routes] == ["/api/users"]
    assert declined == 0


def test_no_routes_is_empty():
    assert extract_csharp_routes(
        "Program.cs", 'Console.WriteLine("Hello World");') == []
