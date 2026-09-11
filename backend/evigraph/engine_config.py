"""Runtime values core needs, owned by core (architecture §2).

Core cannot import the server's `Settings`: that would make the engine depend
on pydantic-settings, on environment variables, and on there being a server in
the process at all — none of which a host embedding `link()` has.

So core declares the few values it needs as a frozen dataclass with working
defaults, and whoever runs the engine pushes real ones down. The application
does that from `evigraph/config.py`; a library host calls `configure()` itself, or
calls nothing and takes the defaults.

Stdlib only, by design — this module is on the path to `evigraph-core`, which
A9 requires to install without neo4j or fastapi.
"""

import os
from dataclasses import dataclass, replace

_HERE = os.path.dirname(os.path.abspath(__file__))

# Installed as a wheel, the control plane ships inside the package. Running
# from a clone, it is the workspace-root `config/` beside `backend/`. Both are
# resolved relative to this file, so no absolute path is ever baked in.
_PACKAGED_CONFIG_DIR = os.path.join(_HERE, "_control_plane")
_REPO_CONFIG_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "config"))
_DEFAULT_CONFIG_DIR = (_PACKAGED_CONFIG_DIR
                       if os.path.isdir(_PACKAGED_CONFIG_DIR)
                       else _REPO_CONFIG_DIR)


@dataclass(frozen=True)
class EngineConfig:
    """Every environment-derived value core reads. Keep it this short.

    A field here is a value the engine cannot compute for itself. Anything an
    operator tunes belongs in `config/*.yml` instead, where it is versioned
    with the estate rather than with the process.
    """

    # Operator control plane: confidence.yml, service_aliases.yml, ...
    config_dir: str = _DEFAULT_CONFIG_DIR
    # Where repositories are cloned.
    workspace_dir: str = "/tmp/repos"
    # Salt for the HMACs that redact config values before they reach a claim.
    graph_hmac_key: str = ""
    # Per-file parse budget. A pathological file can wedge tree-sitter
    # indefinitely; without a cap one file stalls a whole repository's scan.
    parse_timeout_s: int = 30
    parse_file_cap_bytes: int = 512 * 1024
    # Whole-repo ceilings. A generated monorepo or a vendored tree can other-
    # wise turn one scan into an unbounded job. Both are reported when they
    # bite: a cap that silently truncates is indistinguishable from a
    # repository that simply had less in it.
    max_files_per_repo: int = 50_000
    max_claims_per_repo: int = 200_000


_active = EngineConfig()


def get_config() -> EngineConfig:
    """The active config. Read at call time, never cached by callers — the
    server sets real values after core modules are already imported."""
    return _active


def configure(**values) -> None:
    """Replace the active config with `values` applied over it.

    Empty and None values are dropped rather than written: an unset
    environment variable must fall back to the default, not blank the field.
    """
    global _active
    supplied = {k: v for k, v in values.items() if v not in (None, "")}
    unknown = set(supplied) - {f for f in EngineConfig.__dataclass_fields__}
    if unknown:
        raise TypeError(f"unknown EngineConfig field(s): {sorted(unknown)}")
    _active = replace(_active, **supplied)


def reset() -> None:
    """Restore defaults. For tests that need a known starting point."""
    global _active
    _active = EngineConfig()
