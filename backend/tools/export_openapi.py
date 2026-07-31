"""Write the API's own OpenAPI document to `lib/api-spec/openapi.yaml`.

That file used to be scaffolding that LOOKED like a contract: it declared
one path, `/healthz`, which is not among the routes the backend serves —
the real one is `/health` — and nothing imports the client orval
generates from it. AGENTS.md lists reading it as a way to get a
confident wrong answer about the API.

The fix is not to delete it but to make it true. FastAPI already knows
the routes, so the document is generated from the app and checked in;
`tests/test_openapi_spec.py` fails when the two disagree, which is what
stops it drifting back into fiction.

The title is pinned to "Api" because `lib/api-spec/orval.config.ts`
derives its generated import paths from it — its own transformer forces
the same value, and this keeps the checked-in file consistent with what
orval would produce.

Run: python backend/tools/export_openapi.py [--check]
Exit: 0 written/matching, 1 when --check finds a difference.
"""

import argparse
import os
import sys

import yaml

# Settled before importing the app: `adduce.config` reads the environment at
# import time and refuses to boot without these.
os.environ.setdefault("GRAPH_HMAC_KEY", "openapi-export")
os.environ.setdefault("API_TOKEN", "openapi-export")

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

SPEC_PATH = os.path.join(os.path.dirname(BACKEND), "lib", "api-spec",
                         "openapi.yaml")

_HEADER = (
    "# GENERATED from the FastAPI app by backend/tools/export_openapi.py.\n"
    "# Do not hand-edit: `tests/test_openapi_spec.py` fails when this file\n"
    "# and the routes disagree. Regenerate instead.\n"
    "#\n"
    "# The title is pinned to \"Api\" because orval.config.ts derives its\n"
    "# generated import paths from it.\n"
)


def build_spec() -> dict:
    """The app's own document, with the title orval expects."""
    from adduce.main import app

    spec = app.openapi()
    spec = yaml.safe_load(yaml.safe_dump(spec))   # plain types, stable order
    spec.setdefault("info", {})["title"] = "Api"
    return spec


def render(spec: dict) -> str:
    return _HEADER + yaml.safe_dump(spec, sort_keys=True, width=100,
                                    default_flow_style=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the checked-in file is stale")
    args = parser.parse_args(argv)

    rendered = render(build_spec())
    if args.check:
        try:
            with open(SPEC_PATH, "r", encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            current = ""
        if current != rendered:
            print(f"{SPEC_PATH} is stale — regenerate with "
                  f"`python backend/tools/export_openapi.py`", file=sys.stderr)
            return 1
        print("openapi.yaml matches the routes")
        return 0

    with open(SPEC_PATH, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    paths = len(build_spec().get("paths") or {})
    print(f"wrote {SPEC_PATH} ({paths} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
