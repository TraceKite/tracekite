"""Flask application and blueprint routes from Python syntax.

Only literal paths, methods and prefixes become routes. A registration option
overrides a blueprint's constructor default, matching Flask's own contract.
Dynamic values are counted as declines rather than guessed.
Blueprint routes require a registration visible in the same file.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class FlaskRoute:
    method: str
    path: str
    handler_name: str
    line: int
    framework: str = "flask"


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal(value: ast.AST | None) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _keyword(call: ast.Call, name: str) -> tuple[bool, str | None]:
    for keyword in call.keywords:
        if keyword.arg == name:
            return True, _literal(keyword.value)
    return False, None


def _join_path(prefix: str, path: str) -> str:
    left = "/" + prefix.strip("/") if prefix.strip("/") else ""
    right = "/" + path.strip("/") if path.strip("/") else "/"
    return (left + right).replace("//", "/") or "/"


def _flask_symbols(tree: ast.AST) -> tuple[set[str], set[str]]:
    flask_names, blueprint_names = {"Flask"}, {"Blueprint"}
    modules = {"flask"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "flask":
            for alias in node.names:
                if alias.name == "Flask":
                    flask_names.add(alias.asname or alias.name)
                elif alias.name == "Blueprint":
                    blueprint_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "flask":
                    modules.add(alias.asname or alias.name)
    flask_names.update(f"{module}.Flask" for module in modules)
    blueprint_names.update(f"{module}.Blueprint" for module in modules)
    return flask_names, blueprint_names


def _bindings(tree: ast.AST, flask_names: set[str], blueprint_names: set[str]):
    apps, blueprints = set(), {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        called = _call_name(value.func)
        if called in flask_names:
            apps.update(names)
        elif called in blueprint_names:
            present, prefix = _keyword(value, "url_prefix")
            for name in names:
                blueprints[name] = prefix if present else ""
    return apps, blueprints


def _registrations(tree: ast.AST, apps: set[str], blueprints: dict[str, str | None]):
    registrations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "register_blueprint" or not node.args:
            continue
        parent, child = _call_name(node.func.value), _call_name(node.args[0])
        if parent not in apps | set(blueprints) or child not in blueprints:
            continue
        present, override = _keyword(node, "url_prefix")
        registrations.append((parent, child,
                              override if present else blueprints[child]))
    return registrations


def _mounts(apps: set[str], blueprints: dict[str, str | None], registrations):
    mounts: dict[str, set[str]] = {app: {""} for app in apps}
    unresolved = list(registrations)
    while unresolved:
        changed = False
        remaining = []
        for parent, child, prefix in unresolved:
            if parent not in mounts or prefix is None:
                remaining.append((parent, child, prefix))
                continue
            before = len(mounts.get(child, set()))
            mounts.setdefault(child, set()).update(
                _join_path(base, prefix) for base in mounts[parent])
            changed = changed or len(mounts[child]) > before
        if not changed:
            break
        unresolved = remaining
    return mounts


def _methods(decorator: ast.Call, verb: str) -> list[str] | None:
    if verb != "route":
        return [verb.upper()]
    for keyword in decorator.keywords:
        if keyword.arg != "methods":
            continue
        if not isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
            return None
        values = [_literal(item) for item in keyword.value.elts]
        if not values or any(value is None for value in values):
            return None
        return [value.upper() for value in values if value]
    return ["GET"]


def extract_flask_routes(content: str) -> tuple[list[FlaskRoute], int]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return [], 0
    flask_names, blueprint_names = _flask_symbols(tree)
    apps, blueprints = _bindings(tree, flask_names, blueprint_names)
    if not apps and not blueprints:
        return [], 0
    mounts = _mounts(apps, blueprints,
                     _registrations(tree, apps, blueprints))
    routes, declined = [], 0
    function_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    for function in (node for node in ast.walk(tree)
                     if isinstance(node, function_types)):
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            called = _call_name(decorator.func)
            receiver, separator, verb = called.rpartition(".")
            if not separator or verb not in {
                    "route", "get", "post", "put", "delete", "patch",
                    "head", "options"}:
                continue
            if receiver not in apps | set(blueprints):
                continue
            path = _literal(decorator.args[0])
            methods = _methods(decorator, verb)
            prefixes = mounts.get(receiver, set())
            if path is None or methods is None or not prefixes:
                declined += 1
                continue
            for prefix in sorted(prefixes):
                for method in methods:
                    routes.append(FlaskRoute(
                        method, _join_path(prefix, path), function.name,
                        decorator.lineno))
    unique = {(route.method, route.path, route.handler_name, route.line): route
              for route in routes}
    return [unique[key] for key in sorted(unique)], declined
