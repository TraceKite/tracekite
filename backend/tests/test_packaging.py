"""`tracekite-core` declares what it actually needs, and nothing heavy.

The distribution's dependency list is not hand-maintained: it is the measured
import closure of the core and parsers layers. This fails when the two drift,
because a dependency list that is merely aspirational is how "no heavy deps"
quietly stops being true — someone adds an import, the list says otherwise,
and a host discovers it at install time.

Building and installing the wheel is verified separately (it needs a network
and a scratch venv); what is enforced here is the claim the wheel makes.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_layers  # noqa: E402

PYPROJECT = (Path(__file__).resolve().parent.parent.parent
             / "packaging" / "tracekite-core" / "pyproject.toml")
CLI_PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"

# Never in the core distribution. A host already running a graph database must
# not be made to install a second one; a host with no web server must not
# acquire one.
HEAVY = {"neo4j", "fastapi", "starlette", "uvicorn", "pydantic-settings",
         "pydantic_settings"}

# Import name -> distribution name, where they differ.
DISTRIBUTION_OF = {"yaml": "pyyaml", "tree_sitter": "tree-sitter"}


def _declared() -> set[str]:
    text = PYPROJECT.read_text()
    block = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    return {re.split(r"[><=!\[]", line.strip().strip('",'))[0].strip().lower()
            for line in block.splitlines() if line.strip().startswith('"')}


def _guarded(tree) -> set[str]:
    """Imports wrapped in `try: ... except ImportError`.

    These are optional by construction — the code degrades and says so, as
    the tree-sitter HTML and CSS grammars do. Requiring them would force
    every host to install grammars it may never parse.
    """
    optional = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches_import = any(
            (h.type is not None
             and "ImportError" in ast.dump(h.type)) or h.type is None
            for h in node.handlers)
        if not catches_import:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Import):
                optional.update(a.name.split(".")[0] for a in inner.names)
            elif isinstance(inner, ast.ImportFrom) and inner.module:
                optional.add(inner.module.split(".")[0])
    return optional


def _imported() -> set[str]:
    """Third-party modules the core and parsers layers require unguarded."""
    found = set()
    for path in sorted(check_layers.APP.rglob("*.py")):
        if ("__pycache__" in path.parts
                or check_layers.is_package_marker(path)):
            continue
        if check_layers.layer_of(check_layers.module_name(path)) not in (
                "core", "parsers"):
            continue
        tree = ast.parse(path.read_text())
        optional = _guarded(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names
                             if a.name.split(".")[0] not in optional)
            elif isinstance(node, ast.ImportFrom) and node.module \
                    and not node.level:
                if node.module.split(".")[0] not in optional:
                    found.add(node.module.split(".")[0])
    stdlib = set(sys.stdlib_module_names)
    return {DISTRIBUTION_OF.get(m, m).replace("_", "-").lower()
            for m in found if m not in stdlib and m != "tracekite"}


class TestCoreDistribution:
    def test_declares_no_heavy_dependency(self):
        assert not (_declared() & HEAVY), _declared() & HEAVY

    def test_core_imports_nothing_heavy(self):
        """The list could be honest and the code still wrong; check both."""
        assert not (_imported() & HEAVY), _imported() & HEAVY

    def test_every_import_is_declared(self):
        """An undeclared import is an ImportError for whoever installs it."""
        missing = _imported() - _declared()
        assert not missing, f"imported but not declared: {sorted(missing)}"

    def test_the_server_extra_carries_what_core_refuses(self):
        """The application's heavy deps live in an extra, so one repository
        serves both surfaces without a second copy of the engine."""
        text = PYPROJECT.read_text()
        extra = text.split("server = [", 1)[1].split("]", 1)[0]
        assert "fastapi" in extra and "uvicorn" in extra
        assert "neo4j" in text.split("neo4j = [", 1)[1].split("]", 1)[0]

    def test_optional_grammars_are_offered_as_an_extra(self):
        """HTML and CSS parsing degrade gracefully when their grammars are
        absent, so they are opt-in rather than a cost every host pays."""
        text = PYPROJECT.read_text()
        extra = text.split("languages = [", 1)[1].split("]", 1)[0]
        assert "tree-sitter-html" in extra and "tree-sitter-css" in extra

    def test_control_plane_ships_with_the_engine(self):
        """`link()` refuses to run without calibrated confidences rather than
        invent defaults, so a wheel without `config/` can scan but never
        link — which is a broken library, loudly."""
        text = PYPROJECT.read_text()
        hook = (PYPROJECT.parent / "hatch_build.py").read_text()

        assert 'path = "hatch_build.py"' in text
        assert 'package = "tracekite"' in text
        assert '_control_plane' in hook

    def test_distribution_carries_the_repository_license_verbatim(self):
        packaged = (PYPROJECT.parent / "LICENSE").read_text()
        repository = (PYPROJECT.parents[2] / "LICENSE").read_text()

        assert packaged == repository


class TestCliDistribution:
    def test_cli_wheel_ships_code_and_control_plane(self):
        text = CLI_PYPROJECT.read_text()

        assert 'tracekite = "tracekite.cli:main"' in text
        assert 'packages = ["backend/tracekite"]' in text
        assert '"config" = "tracekite/_control_plane"' in text
