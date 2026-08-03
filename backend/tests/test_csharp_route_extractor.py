"""Tests for C# ASP.NET Core Minimal API route extraction."""

from adduce.services.csharp_route_extractor import extract_csharp_routes


def test_extract_csharp_minimal_api_verbs():
    content = """
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

app.MapGet("/v1/pets", () => "pets");
app.MapPost("/v1/orders", (Order order) => order);
app.MapPut("/v1/orders/{id}", (int id) => id);
app.MapDelete("/v1/orders/{id}", (int id) => id);

app.Run();
"""
    routes = extract_csharp_routes("Program.cs", content)
    assert len(routes) == 4

    assert routes[0].method == "GET"
    assert routes[0].path == "/v1/pets"
    assert routes[0].line == 5

    assert routes[1].method == "POST"
    assert routes[1].path == "/v1/orders"

    assert routes[2].method == "PUT"
    assert routes[2].path == "/v1/orders/{id}"

    assert routes[3].method == "DELETE"
    assert routes[3].path == "/v1/orders/{id}"


def test_extract_csharp_parameter_type_constraints():
    content = """
app.MapGet("/pets/{id:int}", (int id) => "pet");
app.MapDelete("/orders/{id:guid}", (Guid id) => "order");
"""
    routes = extract_csharp_routes("Program.cs", content)
    assert len(routes) == 2
    assert routes[0].path == "/pets/{id}"
    assert routes[1].path == "/orders/{id}"


def test_extract_csharp_map_group():
    content = """
var app = WebApplication.Create();
var api = app.MapGroup("/api/v1");

api.MapGet("/users", () => "users");
"""
    routes = extract_csharp_routes("Program.cs", content)
    assert len(routes) == 1
    assert routes[0].method == "GET"
    assert routes[0].path == "/api/v1/users"


def test_extract_csharp_no_routes_empty():
    routes = extract_csharp_routes("Program.cs", "Console.WriteLine(\"Hello World\");")
    assert routes == []
