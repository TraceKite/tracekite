"""Node/JS/TS HTTP route extraction.

Plain Express verb calls are the legacy parser's job; this module must emit
nothing for them (only mount-prefixed re-emissions with attrs.mounted).
"""

from adduce.services.js_route_extractor import JsRoute, extract_js_routes


def _find(routes, method, path, framework=None):
    for r in routes:
        if r.method == method and r.path == path and (
                framework is None or r.framework == framework):
            return r
    return None


# --- NestJS ----------------------------------------------------------------

NEST = """\
import { Controller, Get, Post, Put, Delete, Patch, Head, Options } from '@nestjs/common';

@Controller('owners')
export class OwnersController {
  @Get()
  findAll(): Owner[] { return []; }

  @Get(':id')
  findOne(@Param('id') id: string) { return null; }

  @Post('adopt')
  @HttpCode(201)
  async adopt(@Body() dto: AdoptDto) { return dto; }

  @Delete(':id')
  remove(id: string) {}

  @Patch(':id/name')
  rename() {}

  @Head('ping')
  ping() {}

  @Options('cors')
  cors() {}
}

@Controller()
export class RootController {
  @Get()
  index() { return 'ok'; }

  @Put('settings')
  update() {}
}

@Controller({ path: 'vets', version: '2' })
export class VetsController {
  @Get('specialties')
  specialties() {}
}
"""


class TestNestJs:
    def test_controller_prefix_and_methods(self):
        routes = extract_js_routes("src/owners/owners.controller.ts", NEST)
        nest = [r for r in routes if r.framework == "nestjs"]
        assert len(nest) == 10

        root = _find(nest, "GET", "/owners")
        assert root is not None and root.handler_name == "findAll"
        assert root.line == 5

        one = _find(nest, "GET", "/owners/{id}")
        assert one is not None and one.handler_name == "findOne"

        adopt = _find(nest, "POST", "/owners/adopt")
        assert adopt is not None and adopt.handler_name == "adopt"

        assert _find(nest, "DELETE", "/owners/{id}") is not None
        assert _find(nest, "PATCH", "/owners/{id}/name") is not None
        assert _find(nest, "HEAD", "/owners/ping") is not None
        assert _find(nest, "OPTIONS", "/owners/cors") is not None

    def test_empty_controller_prefix(self):
        routes = extract_js_routes("app.controller.ts", NEST)
        idx = _find(routes, "GET", "/", "nestjs")
        assert idx is not None and idx.handler_name == "index"
        assert _find(routes, "PUT", "/settings", "nestjs") is not None

    def test_object_controller_with_version(self):
        routes = extract_js_routes("vets.controller.ts", NEST)
        spec = _find(routes, "GET", "/vets/specialties", "nestjs")
        assert spec is not None
        assert spec.attrs == {"version": "2"}

    def test_non_literal_decorator_path_declined(self):
        src = (
            "@Controller('x')\n"
            "class C {\n"
            "  @Get(ROUTES.OWNER)\n"
            "  dyn() {}\n"
            "  @Get('ok')\n"
            "  ok() {}\n"
            "}\n"
        )
        routes = extract_js_routes("c.ts", src)
        assert [r.path for r in routes] == ["/x/ok"]


# --- Fastify ---------------------------------------------------------------

FASTIFY = """\
const fastify = require('fastify')({ logger: true });

fastify.get('/health', async () => ({ ok: true }));
fastify.post('/pets', { schema }, createPet);
fastify.route({
  method: 'GET',
  url: '/pets/:petId',
  handler: getPet,
});
fastify.route({ method: ['POST', 'HEAD'], url: '/bulk', handler: bulk });

fastify.register(async (instance) => {
  instance.get('/list', listOwners);
  instance.post('/', createOwner);
}, { prefix: '/owners' });

async function vetRoutes(app, opts) {
  app.get('/vets', listVets);
}
fastify.register(vetRoutes, { prefix: '/v1' });

fastify.register(require('./routes/external'), { prefix: '/ext' });

fastify.listen({ port: 3000 });
"""


class TestFastify:
    def test_verb_calls(self):
        routes = extract_js_routes("server.js", FASTIFY)
        health = _find(routes, "GET", "/health", "fastify")
        assert health is not None and health.line == 3
        assert _find(routes, "POST", "/pets", "fastify") is not None

    def test_route_object_single_and_array(self):
        routes = extract_js_routes("server.js", FASTIFY)
        pet = _find(routes, "GET", "/pets/{petId}", "fastify")
        assert pet is not None and pet.handler_name == "getPet"
        assert pet.line == 5
        assert _find(routes, "POST", "/bulk", "fastify") is not None
        assert _find(routes, "HEAD", "/bulk", "fastify") is not None

    def test_register_inline_arrow_with_prefix(self):
        routes = extract_js_routes("server.js", FASTIFY)
        assert _find(routes, "GET", "/owners/list", "fastify") is not None
        assert _find(routes, "POST", "/owners", "fastify") is not None

    def test_register_same_file_identifier_with_prefix(self):
        routes = extract_js_routes("server.js", FASTIFY)
        vets = _find(routes, "GET", "/v1/vets", "fastify")
        assert vets is not None and vets.handler_name == "listVets"
        # The unprefixed body route must not leak out separately.
        assert _find(routes, "GET", "/vets") is None

    def test_cross_file_register_declined(self):
        routes = extract_js_routes("server.js", FASTIFY)
        assert not any(r.path.startswith("/ext") for r in routes)

    def test_total_and_no_duplicates(self):
        routes = extract_js_routes("server.js", FASTIFY)
        fast = [r for r in routes if r.framework == "fastify"]
        assert len(fast) == 8
        assert len({(r.method, r.path) for r in fast}) == 8


# --- Koa -------------------------------------------------------------------

KOA = """\
const Router = require('@koa/router');
const router = new Router({ prefix: '/api' });

router.get('/owners', listOwners);
router.post('/owners', createOwner);
router.del('/owners/:id', removeOwner);

const plain = new Router();
plain.get('/health', health);
plain.prefix('/internal');
"""


class TestKoa:
    def test_constructor_prefix_applied(self):
        routes = extract_js_routes("routes.js", KOA)
        owners = _find(routes, "GET", "/api/owners", "koa-router")
        assert owners is not None and owners.handler_name == "listOwners"
        assert owners.line == 4
        assert _find(routes, "POST", "/api/owners", "koa-router") is not None

    def test_del_alias_and_param(self):
        routes = extract_js_routes("routes.js", KOA)
        assert _find(routes, "DELETE", "/api/owners/{id}",
                     "koa-router") is not None

    def test_prefix_method_call(self):
        routes = extract_js_routes("routes.js", KOA)
        assert _find(routes, "GET", "/internal/health",
                     "koa-router") is not None

    def test_new_router_without_koa_import_ignored(self):
        src = "const r = new Router();\nr.get('/x', h);\n"
        assert extract_js_routes("other.js", src) == []


# --- Hapi ------------------------------------------------------------------

HAPI = """\
const Hapi = require('@hapi/hapi');
const server = Hapi.server({ port: 3000 });

server.route({
  method: 'GET',
  path: '/owners/{ownerId}',
  handler: getOwner,
});

server.route({ method: ['POST', 'PUT'], path: '/owners', handler: upsert });
server.route({ method: '*', path: '/{any*}', handler: catchAll });
"""


class TestHapi:
    def test_single_route(self):
        routes = extract_js_routes("server.js", HAPI)
        one = _find(routes, "GET", "/owners/{ownerId}", "hapi")
        assert one is not None and one.handler_name == "getOwner"

    def test_method_array(self):
        routes = extract_js_routes("server.js", HAPI)
        assert _find(routes, "POST", "/owners", "hapi") is not None
        assert _find(routes, "PUT", "/owners", "hapi") is not None

    def test_star_method_is_any_and_param_modifier(self):
        routes = extract_js_routes("server.js", HAPI)
        catch = _find(routes, "ANY", "/{any}", "hapi")
        assert catch is not None and catch.handler_name == "catchAll"


# --- AdonisJS --------------------------------------------------------------

ADONIS_V5 = """\
import Route from '@ioc:Adonis/Core/Route'

Route.get('/', 'HomeController.index')
Route.post('/login', 'AuthController.login')

Route.group(() => {
  Route.get('/owners', 'OwnersController.index')
  Route.put('/owners/:id', 'OwnersController.update')
}).prefix('/api/v1').middleware(['auth'])
"""

ADONIS_V6 = """\
import router from '@adonisjs/core/services/router'
const UsersController = () => import('#controllers/users_controller')

router.get('/users', [UsersController, 'index'])
router.delete('/users/:id', [UsersController, 'destroy'])
"""


class TestAdonis:
    def test_v5_top_level_routes(self):
        routes = extract_js_routes("start/routes.ts", ADONIS_V5)
        home = _find(routes, "GET", "/", "adonis")
        assert home is not None and home.handler_name == "HomeController.index"
        assert _find(routes, "POST", "/login", "adonis") is not None

    def test_group_prefix_applied_to_body_only(self):
        routes = extract_js_routes("start/routes.ts", ADONIS_V5)
        assert _find(routes, "GET", "/api/v1/owners", "adonis") is not None
        assert _find(routes, "PUT", "/api/v1/owners/{id}",
                     "adonis") is not None
        # Group-body routes must not also appear unprefixed.
        assert _find(routes, "GET", "/owners", "adonis") is None

    def test_v6_router_and_tuple_handler(self):
        routes = extract_js_routes("start/routes.ts", ADONIS_V6)
        users = _find(routes, "GET", "/users", "adonis")
        assert users is not None
        assert users.handler_name == "UsersController.index"
        assert _find(routes, "DELETE", "/users/{id}", "adonis") is not None

    def test_use_route_variant_and_any(self):
        src = ("const Route = use('Route')\n"
               "Route.any('/webhooks', 'WebhookController.handle')\n")
        routes = extract_js_routes("routes.js", src)
        hook = _find(routes, "ANY", "/webhooks", "adonis")
        assert hook is not None

    def test_no_adonis_marker_declines(self):
        src = "router.get('/users', h)\n"
        assert extract_js_routes("start/routes.ts", src) == []


# --- Next.js app router ----------------------------------------------------

NEXT_APP = """\
import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  return NextResponse.json([]);
}

export const POST = async (request: Request) => {
  return NextResponse.json({}, { status: 201 });
};
"""


class TestNextJsAppRouter:
    def test_path_from_file_path(self):
        routes = extract_js_routes(
            "frontend/src/app/api/owners/[ownerId]/route.ts", NEXT_APP)
        get = _find(routes, "GET", "/api/owners/{ownerId}", "nextjs-app")
        assert get is not None and get.handler_name == "GET"
        assert get.line == 3
        post = _find(routes, "POST", "/api/owners/{ownerId}", "nextjs-app")
        assert post is not None and post.handler_name == "POST"
        assert len(routes) == 2

    def test_route_groups_and_parallel_segments_dropped(self):
        routes = extract_js_routes(
            "web/app/(marketing)/api/@analytics/users/[...slug]/route.ts",
            "export function DELETE(req) {}\n")
        assert _find(routes, "DELETE", "/api/users/{slug}",
                     "nextjs-app") is not None

    def test_optional_catch_all(self):
        routes = extract_js_routes(
            "app/api/docs/[[...parts]]/route.ts",
            "export const HEAD = () => new Response();\n")
        assert _find(routes, "HEAD", "/api/docs/{parts}",
                     "nextjs-app") is not None

    def test_non_route_filename_ignored(self):
        routes = extract_js_routes("src/app/api/owners/handlers.ts", NEXT_APP)
        assert not any(r.framework == "nextjs-app" for r in routes)


# --- Next.js pages router --------------------------------------------------

NEXT_PAGES = """\
export default async function handler(req, res) {
  res.status(200).json({ ok: true });
}
"""


class TestNextJsPagesRouter:
    def test_default_export_is_any(self):
        routes = extract_js_routes("web/pages/api/owners/[id].ts", NEXT_PAGES)
        assert len(routes) == 1
        r = routes[0]
        assert (r.method, r.path, r.framework) == \
            ("ANY", "/api/owners/{id}", "nextjs-pages")
        assert r.handler_name == "handler"

    def test_index_maps_to_directory_path(self):
        routes = extract_js_routes("web/src/pages/api/index.ts", NEXT_PAGES)
        assert _find(routes, "ANY", "/api", "nextjs-pages") is not None

    def test_catch_all_segment(self):
        routes = extract_js_routes("site/pages/api/[...path].ts", NEXT_PAGES)
        assert _find(routes, "ANY", "/api/{path}", "nextjs-pages") is not None

    def test_no_default_export_declines(self):
        src = "export function helper() {}\n"
        assert extract_js_routes("web/pages/api/owners.ts", src) == []


# --- Remix -----------------------------------------------------------------

REMIX = """\
import { json } from '@remix-run/node';

export async function loader({ params }) {
  return json(await getOwner(params.ownerId));
}

export const action = async ({ request }) => {
  return redirect('/owners');
};
"""

LOADER_ONLY = "export const loader = async () => json([]);\n"


class TestRemix:
    def test_loader_and_action(self):
        routes = extract_js_routes(
            "app/routes/owners.$ownerId.edit.tsx", REMIX)
        get = _find(routes, "GET", "/owners/{ownerId}/edit", "remix")
        assert get is not None and get.handler_name == "loader"
        assert get.line == 3 and get.attrs == {}
        post = _find(routes, "POST", "/owners/{ownerId}/edit", "remix")
        assert post is not None and post.handler_name == "action"
        assert post.attrs == {"remix": "action"}

    def test_index_route(self):
        routes = extract_js_routes("app/routes/_index.tsx", LOADER_ONLY)
        assert _find(routes, "GET", "/", "remix") is not None

    def test_pathless_layout_segment_dropped(self):
        routes = extract_js_routes("app/routes/_auth.login.tsx", LOADER_ONLY)
        assert _find(routes, "GET", "/login", "remix") is not None

    def test_pathless_layout_only_declines(self):
        assert extract_js_routes("app/routes/_auth.tsx", LOADER_ONLY) == []

    def test_v2_folder_convention(self):
        routes = extract_js_routes(
            "app/routes/reports.$year/route.tsx", LOADER_ONLY)
        assert _find(routes, "GET", "/reports/{year}", "remix") is not None

    def test_non_route_dir_ignored(self):
        assert extract_js_routes("app/components/owners.tsx", LOADER_ONLY) == []


# --- Express router mounting -----------------------------------------------

EXPRESS_MOUNT = """\
const express = require('express');
const app = express();

const ownersRouter = express.Router();
ownersRouter.get('/', listOwners);
ownersRouter.get('/:ownerId/pets', listPets);
ownersRouter.post('/', createOwner);

app.get('/health', health);
app.use('/api/owners', ownersRouter);
app.use('/legacy', require('./routes/legacy'));

const orphan = express.Router();
orphan.get('/never', nope);

app.listen(3000);
"""


class TestExpressMounts:
    def test_mounted_routes_get_prefix_and_attr(self):
        routes = extract_js_routes("server.js", EXPRESS_MOUNT)
        root = _find(routes, "GET", "/api/owners", "express")
        assert root is not None and root.handler_name == "listOwners"
        assert root.attrs == {"mounted": True}
        assert root.line == 5
        pets = _find(routes, "GET", "/api/owners/{ownerId}/pets", "express")
        assert pets is not None and pets.attrs == {"mounted": True}
        assert _find(routes, "POST", "/api/owners", "express") is not None

    def test_plain_express_calls_not_reextracted(self):
        routes = extract_js_routes("server.js", EXPRESS_MOUNT)
        assert _find(routes, "GET", "/health") is None

    def test_cross_file_mount_declined(self):
        routes = extract_js_routes("server.js", EXPRESS_MOUNT)
        assert not any("/legacy" in r.path for r in routes)

    def test_unmounted_router_not_emitted(self):
        routes = extract_js_routes("server.js", EXPRESS_MOUNT)
        assert _find(routes, "GET", "/never") is None
        assert len(routes) == 3


# --- robustness ------------------------------------------------------------


class TestRobustness:
    def test_malformed_does_not_raise(self):
        garbage = "const x = {{{ ((( '@Controller(' fastify.register("
        assert isinstance(extract_js_routes("junk.ts", garbage), list)

    def test_unbalanced_nest_decorator(self):
        src = "@Controller('a'\nexport class X {"
        assert extract_js_routes("x.ts", src) == []

    def test_template_literal_with_interpolation_skipped(self):
        src = ("const fastify = require('fastify')();\n"
               "const v = 'v9';\n"
               "fastify.get(`/dyn/${v}`, h);\n"
               "fastify.get(`/static`, h);\n")
        routes = extract_js_routes("s.js", src)
        assert [r.path for r in routes] == ["/static"]

    def test_variable_path_skipped(self):
        src = ("const fastify = require('fastify')();\n"
               "fastify.get(PATH, h);\n")
        assert extract_js_routes("s.js", src) == []

    def test_non_js_extension_returns_empty(self):
        assert extract_js_routes("README.md", "app.get('/x', h)") == []

    def test_empty_content(self):
        assert extract_js_routes("a.ts", "") == []

    def test_dataclass_shape(self):
        r = JsRoute(method="GET", path="/x", framework="fastify", line=1)
        assert r.handler_name == "" and r.attrs == {}
