"""HTTP routes declared in Ruby: Rails routing DSL and Sinatra.

Precision-first, like every extractor here: only string-literal paths are
taken, and the two DSLs are recognised by where and how they appear, not by
the verb words alone — `get` is one of the most common method names in Ruby,
and matching it loose would mint phantom endpoints out of ordinary code.

* **Rails** routes are read only from `config/routes.rb` (and
  `config/routes/*.rb`), because that is where the DSL is legal. `namespace`
  and `scope` prefixes are tracked with a do/end depth walk. `resources`
  expands to the five canonical routes Rails actually registers — that is
  the DSL's documented meaning, not an inference — filtered by
  `only:`/`except:`.
* **Sinatra** verbs may appear in any Ruby file but must look like Sinatra:
  a leading-slash literal path followed by a block (`do` or `{`) on the
  same line.

Param syntax normalises to brace templates: `:id` -> `{id}`, `*splat` ->
`{splat}`, matching what every other route extractor emits so the join key
space is one space.
"""

import re
from dataclasses import dataclass, field

_RAILS_FILES = re.compile(r"(^|/)config/routes(/[\w.-]+)?\.rb$")

_VERB = re.compile(
    r"^\s*(get|post|put|patch|delete)\s+['\"]([^'\"]+)['\"](.*)$")
_RESOURCES = re.compile(r"^\s*resources\s+:(\w+)(.*)$")
_NAMESPACE = re.compile(
    r"^\s*(?:namespace\s+:(\w+)|scope\s+['\"]([^'\"]+)['\"].*?)\s+do\b")
_ONLY = re.compile(r"only:\s*(?:\[([^\]]*)\]|:(\w+))")
_EXCEPT = re.compile(r"except:\s*(?:\[([^\]]*)\]|:(\w+))")
_SYMBOL = re.compile(r":(\w+)")
_PARAM = re.compile(r":(\w+)")
_SPLAT = re.compile(r"\*(\w+)")
_TO = re.compile(r"to:\s*['\"]([\w/#]+)['\"]")
_DO_TOKEN = re.compile(r"\bdo\b(?:\s*\|[^|]*\|)?\s*(?:#.*)?$")
_END_TOKEN = re.compile(r"^\s*end\b")

_SINATRA = re.compile(
    r"^\s*(get|post|put|patch|delete)\s+(['\"])(/[^'\"]*)\2"
    r"[^#\n]*(?:\bdo\b|\{)")

# What `resources :name` registers, per the Rails router's own table.
_RESOURCE_ACTIONS = (
    ("index", "GET", ""), ("create", "POST", ""),
    ("show", "GET", "/{id}"), ("update", "PATCH", "/{id}"),
    ("destroy", "DELETE", "/{id}"),
)


@dataclass
class RubyRoute:
    """One statically-declared HTTP route registration."""
    method: str
    path: str
    framework: str        # rails | sinatra
    line: int
    handler_name: str = ""
    attrs: dict = field(default_factory=dict)


def _template(path: str) -> str:
    return _SPLAT.sub(r"{\1}", _PARAM.sub(r"{\1}", path))


def _joined(prefix: str, path: str) -> str:
    path = path if path.startswith("/") else "/" + path
    return (prefix + path).replace("//", "/") or "/"


def _actions_for(rest: str) -> list[tuple[str, str, str]]:
    """The resource actions after only:/except:, or all five."""
    if only := _ONLY.search(rest):
        wanted = set(_SYMBOL.findall(only.group(1) or "")) \
            | ({only.group(2)} if only.group(2) else set())
        return [a for a in _RESOURCE_ACTIONS if a[0] in wanted]
    if exc := _EXCEPT.search(rest):
        dropped = set(_SYMBOL.findall(exc.group(1) or "")) \
            | ({exc.group(2)} if exc.group(2) else set())
        return [a for a in _RESOURCE_ACTIONS if a[0] not in dropped]
    return list(_RESOURCE_ACTIONS)


def _rails_routes(content: str) -> list[RubyRoute]:
    routes: list[RubyRoute] = []
    # (prefix, the do/end depth it was opened at). A bare `end` closes the
    # innermost frame opened at the depth it returns to.
    stack: list[tuple[str, int]] = []
    depth = 0

    for number, line in enumerate(content.splitlines(), start=1):
        if _END_TOKEN.match(line):
            depth -= 1
            while stack and stack[-1][1] > depth:
                stack.pop()
            continue

        prefix = stack[-1][0] if stack else ""
        if ns := _NAMESPACE.match(line):
            part = ns.group(1) or ns.group(2)
            stack.append((_joined(prefix, part), depth + 1))
        elif res := _RESOURCES.match(line):
            name, rest = res.group(1), res.group(2)
            base = _joined(prefix, name)
            for action, method, suffix in _actions_for(rest):
                routes.append(RubyRoute(
                    method, base + suffix, "rails", number,
                    handler_name=f"{name}#{action}"))
            if _DO_TOKEN.search(rest):
                # Nested resources gain the parent's member scope, exactly
                # as Rails nests them.
                stack.append((f"{base}/{{{name.rstrip('s')}_id}}", depth + 1))
        elif verb := _VERB.match(line):
            target = _TO.search(verb.group(3) or "")
            routes.append(RubyRoute(
                verb.group(1).upper(),
                _template(_joined(prefix, verb.group(2))),
                "rails", number,
                handler_name=target.group(1) if target else ""))

        if _DO_TOKEN.search(line):
            depth += 1
    return routes


def extract_rb_routes(file_path: str, content: str) -> list[RubyRoute]:
    """Every statically-declared route in one Ruby file.

    Returns an empty list for files it does not recognise — an extractor
    never raises for unrecognised input.
    """
    if _RAILS_FILES.search(file_path):
        return _rails_routes(content)
    return [RubyRoute(m.group(1).upper(), _template(m.group(3)),
                      "sinatra", content.count("\n", 0, m.start()) + 1)
            for m in _SINATRA.finditer(content)]
