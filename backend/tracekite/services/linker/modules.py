"""The module boundary: what owns behaviour, as opposed to what stores code.

Lived in `routes/links.py` until now, which put a fact about the graph in the
server layer — "the server may orchestrate; it may not compute". A library
host calling `link()` could not ask which module a path belongs to without
importing FastAPI, so it would have written its own copy and drifted.

C9 promotes this further, from helper to a first-class node. That is not done:
the boundary is computed here and consumed by callers, but no `Module` node is
minted yet.
"""

# `projects/` is one estate's convention, not a rule. A container directory
# holds sibling modules; the module is the directory *inside* it.
MODULE_CONTAINERS = frozenset({
    "projects", "services", "apps", "packages", "modules",
    "libs", "components", "cmd", "src",
})

# Directories that DESCRIBE deployment rather than own behaviour. A service
# whose only evidence is a manifest in `deploy/` does not belong to a module
# called "deploy" — that edge reads as code ownership and is not one, so the
# live graph carried `Module:deploy`, `Module:docker` and `Module:k8s`
# alongside genuine modules named for the code they hold. Declining is
# the same rule as declining an edge: a module we cannot name is better than
# one named after the folder the YAML happens to live in.
# Necessarily incomplete — a convention nobody registered will slip through,
# which is why the decline is counted (`r0.module_unknown`) rather than
# assumed complete. `chart` singular was the one this list missed on its
# first run against the live estate.
INFRASTRUCTURE_DIRS = frozenset({
    "deploy", "deployment", "deployments", "docker", "dockerfiles",
    "k8s", "kubernetes", "kube", "manifests", "manifest",
    "chart", "charts", "helm", "helmfile", "kustomize", "overlays",
    "infra", "infrastructure", "terraform", "tf", "ansible", "ops",
    "argocd", "flux", "skaffold", "compose",
    "ci", "build", "scripts", "config", "configs", "etc", "env",
    "environments", ".github", ".gitlab", ".circleci",
})


def module_of(path: str | None) -> str:
    """The module a file belongs to, from its path.

    A repository is how code is STORED; a module is what owns behaviour. In a
    monorepo the interesting boundary is the second: `projects/foyer` calling
    `projects/capability-registry` is a service crossing a boundary, even
    though both sit in one repository and would look internal if repo id were
    the test.
    """
    parts = [p for p in (path or "").split("/") if p]
    if len(parts) < 2:
        # A file at the repository root belongs to no module. Returning its
        # own name was harmless while this only labelled a display row; as a
        # node identity it mints `Module:config.properties`, which is a file
        # wearing a module's label.
        return ""
    if parts[0] in MODULE_CONTAINERS and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    if parts[0].lower() in INFRASTRUCTURE_DIRS:
        # A deployment descriptor says where a service RUNS, not who owns it.
        return ""
    return parts[0]
