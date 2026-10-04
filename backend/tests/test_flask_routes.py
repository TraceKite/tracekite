"""Flask routes are extracted with literal blueprint prefix semantics."""

from tracekite import engine_config
from tracekite.services.flask_route_extractor import extract_flask_routes
from tracekite.services.scan import scan


def _keys(source: str) -> set[tuple[str, str, str]]:
    routes, declined = extract_flask_routes(source)
    assert declined == 0
    return {(route.method, route.path, route.framework) for route in routes}


def test_application_route_and_shortcuts():
    source = '''
from flask import Flask
app = Flask(__name__)

@app.route("/orders", methods=["GET", "POST"])
def orders(): pass

@app.delete("/orders/<order_id>")
def remove(order_id): pass
'''

    assert _keys(source) == {
        ("GET", "/orders", "flask"),
        ("POST", "/orders", "flask"),
        ("DELETE", "/orders/<order_id>", "flask"),
    }


def test_blueprint_default_prefix():
    source = '''
from flask import Flask, Blueprint
app = Flask(__name__)
bp = Blueprint("users", __name__, url_prefix="/api")
app.register_blueprint(bp)

@bp.route("/users")
def users(): pass
'''

    assert _keys(source) == {("GET", "/api/users", "flask")}


def test_blueprint_without_a_visible_registration_is_declined():
    source = '''
from flask import Blueprint
bp = Blueprint("users", __name__, url_prefix="/api")

@bp.route("/users")
def users(): pass
'''

    routes, declined = extract_flask_routes(source)

    assert routes == []
    assert declined == 1


def test_registration_prefix_overrides_blueprint_default():
    source = '''
from flask import Flask, Blueprint
app = Flask(__name__)
bp = Blueprint("users", __name__, url_prefix="/api")
app.register_blueprint(bp, url_prefix="/v2")

@bp.route("/users")
def users(): pass
'''

    assert _keys(source) == {("GET", "/v2/users", "flask")}


def test_nested_blueprint_prefixes_compose():
    source = '''
import flask as f
app = f.Flask(__name__)
parent = f.Blueprint("api", __name__, url_prefix="/api")
child = f.Blueprint("v1", __name__, url_prefix="/v1")
parent.register_blueprint(child)
app.register_blueprint(parent)

@child.get("/users")
def users(): pass
'''

    assert _keys(source) == {("GET", "/api/v1/users", "flask")}


def test_dynamic_path_prefix_and_methods_are_declined():
    source = '''
from flask import Flask, Blueprint
app = Flask(__name__)
bp = Blueprint("users", __name__, url_prefix=PREFIX)

@app.route(PATH)
def dynamic_path(): pass

@app.route("/dynamic", methods=METHODS)
def dynamic_methods(): pass

@bp.route("/users")
def dynamic_prefix(): pass
'''

    routes, declined = extract_flask_routes(source)

    assert routes == []
    assert declined == 3


def test_scan_relabels_flask_shortcut_and_emits_blueprint_contract(tmp_path):
    engine_config.configure(graph_hmac_key="flask-routes-test")
    (tmp_path / "app.py").write_text('''
from flask import Flask, Blueprint
app = Flask(__name__)
bp = Blueprint("api", __name__, url_prefix="/api")
app.register_blueprint(bp)

@app.get("/health")
def health(): return "ok"

@bp.route("/users", methods=["POST"])
def users(): return "ok"
''')

    sink = scan(str(tmp_path), repo_id="flask-app")
    endpoints = [node for node in sink.nodes if node.type == "ApiEndpoint"]
    found = {(node.extra_props["http_method"],
              node.extra_props["path_template"],
              node.extra_props["framework"]) for node in endpoints}

    assert found == {
        ("GET", "/health", "flask"),
        ("POST", "/api/users", "flask"),
    }
