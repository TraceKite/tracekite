"""The distribution owns a namespace nobody else will claim.

The wheel used to install a top-level package called `app`. `app` is the
conventional package name for FastAPI, Flask and Django projects — which
is exactly the audience `pip install evigraph-core` exists for — so an
integrating host's own `app/` shadowed the library entirely: cwd precedes
site-packages, and `from app.services...` raised ModuleNotFoundError. Two
installed distributions both owning `app/` merged silently in
site-packages instead, one `__init__.py` overwriting the other.

Nothing caught it because A9's exit criterion is about dependencies, not
about the namespace. These tests are that missing criterion, asserted
against the source layout and the build hook's own package setting so they
run without a build step.
"""

import ast
import pathlib
import tomllib

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
PYPROJECT = REPO / "packaging" / "evigraph-core" / "pyproject.toml"

# Names a host is likely to own. `app` is the one that actually bit.
SQUATTED = {"app", "src", "lib", "core", "server", "api", "main", "config",
            "utils", "models", "db", "services", "tests"}


def _spec() -> dict:
    with open(PYPROJECT, "rb") as handle:
        return tomllib.load(handle)


def _shipped_packages() -> set[str]:
    """Top-level import packages the wheel would create."""
    build = (_spec().get("tool", {}).get("hatch", {}).get("build", {}))
    force = build.get("targets", {}).get("wheel", {}).get(
        "force-include", {})
    packages = {str(dest).split("/")[0] for dest in force.values()}
    custom = build.get("hooks", {}).get("custom", {})
    if custom.get("package"):
        packages.add(custom["package"])
    return packages


class TestNamespace:
    def test_the_source_package_is_named_for_the_project(self):
        assert (BACKEND / "evigraph" / "__init__.py").exists()
        assert not (BACKEND / "app").exists(), (
            "backend/app is back; the wheel would claim the `app` namespace "
            "and shadow every host that has its own")

    def test_no_shipped_package_squats_a_name_a_host_may_own(self):
        offenders = sorted(_shipped_packages() & SQUATTED)
        assert not offenders, (
            f"the wheel would install top-level {offenders}, which collides "
            f"with the host application it is meant to be embedded in")

    def test_the_wheel_ships_exactly_one_top_level_package(self):
        assert _shipped_packages() == {"evigraph"}, _shipped_packages()

    def test_the_console_script_points_into_that_package(self):
        scripts = _spec()["project"].get("scripts") or {}
        assert scripts.get("evigraph", "").startswith("evigraph."), scripts


class TestNoStaleSelfReference:
    def test_no_module_imports_the_old_package_name(self):
        """A missed import would only fail once installed, because a source
        checkout has no `app` on sys.path to catch it either way."""
        offenders = []
        for path in sorted(BACKEND.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"),
                             filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module \
                        and not node.level:
                    names = [node.module]
                for name in names:
                    if name == "app" or name.startswith("app."):
                        offenders.append(
                            f"{path.relative_to(REPO)}:{node.lineno}: {name}")
        assert not offenders, offenders

    def test_the_container_entrypoint_targets_the_renamed_package(self):
        dockerfile = (BACKEND / "Dockerfile").read_text()
        assert "evigraph.main:app" in dockerfile
        assert "backend/evigraph" in dockerfile
        assert "COPY backend/app " not in dockerfile


class TestDocumentedImportsResolve:
    """The README's example is the first code anyone runs. It broke silently
    during the rename — prose was updated, the code fence was not — and a
    quickstart that raises ImportError is the worst first impression the
    project can make."""

    def test_every_import_in_the_readme_exists(self):
        import importlib
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        modules = set()
        for line in readme.splitlines():
            line = line.strip()
            if line.startswith("from evigraph") and " import " in line:
                modules.add(line.split()[1])
            elif line.startswith("import evigraph"):
                modules.add(line.split()[1])
        assert modules, "no evigraph imports found in the README at all"
        for name in sorted(modules):
            importlib.import_module(name)      # raises if the path moved

    def test_the_readme_shows_no_pre_rename_imports(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for stale in ("from app import", "from app.", "python -m app.cli"):
            assert stale not in readme, f"README still shows {stale!r}"


class TestImageRunsWhatTestsRan:
    """The image installs the lockfile the tests resolved.

    It used to install `backend/requirements.txt` on `python:3.12-slim`
    while the suite ran Python 3.14 with newer pydantic and fastapi — two
    different runtimes, neither of which tested the other. That gap let two
    annotation-only imports pass 2063 tests and crash the container on boot.
    """

    def _dockerfile(self) -> str:
        return (BACKEND / "Dockerfile").read_text(encoding="utf-8")

    def test_dependencies_come_from_the_lockfile(self):
        text = self._dockerfile()
        assert "uv sync" in text and "--frozen" in text, (
            "the image must install uv.lock frozen, or it can resolve "
            "versions CI never tested")
        assert "pip install --no-cache-dir -r requirements.txt" not in text

    def test_requirements_txt_stays_deleted(self):
        assert not (BACKEND / "requirements.txt").exists(), (
            "backend/requirements.txt is back; it pinned a pydantic with no "
            "wheel for the declared requires-python and is what forced the "
            "container onto a different Python from the tests")

    def test_the_base_image_satisfies_requires_python(self):
        import re
        with open(REPO / "pyproject.toml", "rb") as handle:
            floor = tomllib.load(handle)["project"]["requires-python"]
        wanted = tuple(int(x) for x in re.findall(r"\d+", floor)[:2])
        found = re.search(r"FROM python:(\d+)\.(\d+)", self._dockerfile())
        assert found, "cannot determine the base image's Python"
        actual = (int(found.group(1)), int(found.group(2)))
        assert actual >= wanted, (
            f"image python {actual} is below requires-python {floor}")


class TestReadmeDocumentsTheCli:
    """A subcommand nobody documents is one nobody finds. The README listed
    2 of 17 before this — the CLI is the library's whole surface for anyone
    who does not embed it, so drift here is the difference between a usable
    open-source tool and a private one."""

    def _subcommands(self) -> set[str]:
        import argparse
        from evigraph.cli import build_parser
        for action in build_parser()._actions:
            if isinstance(action, argparse._SubParsersAction):
                return set(action.choices)
        raise AssertionError("no subparsers on the CLI")

    def test_every_subcommand_appears_in_the_readme(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        missing = sorted(c for c in self._subcommands()
                         if f"evigraph {c}" not in readme)
        assert not missing, (
            f"undocumented subcommand(s): {missing} — add them to the CLI "
            f"section of the README")

    def test_the_readme_documents_no_command_that_does_not_exist(self):
        import re
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        claimed = set(re.findall(r"`evigraph ([a-z][a-z-]+)", readme))
        unknown = sorted(claimed - self._subcommands())
        assert not unknown, f"README documents non-existent command(s): {unknown}"
