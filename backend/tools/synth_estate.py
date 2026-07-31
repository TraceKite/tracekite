"""Generate a synthetic estate with known ground truth.

The 1,000-repo figures in the roadmap are extrapolated from six real
repositories, and B12's exit criterion — link time scales inversely with
workers — is unmeasurable on the fixture corpus: 288 files parse in 0.62s,
so pool startup dominates whatever the workers do. This manufactures an
estate big enough to measure, with three properties the corpus cannot fake:

* **Ground truth by construction.** Every service call is planted, so the
  manifest lists exactly which CALLS_SERVICE edges must exist. At a thousand
  repositories that is what turns "it ran" into a recall number — and any
  active call edge *outside* the manifest is a false positive at scale.
* **A hot rendezvous key.** One provider is called by a configurable share
  of the estate. REDUCE partitions by key, so this is the shard no worker
  count can shrink — the exact shape B13 must detect and split.
* **Monorepos.** The real estate keeps 81% of its nodes in one repository;
  repo-granular MAP idles workers on it. `--monorepos` reproduces that for
  B15.

The shapes are copied from `corpus/` because those are proven through the
real parsers: a compose env var carries the host, a Python client reads it,
a Go file registers the route. No generated file names another service —
the edge exists only because three artifacts agree on a rendezvous key,
which is the join this tool exists to exercise.

Deterministic: same seed, same estate, byte for byte. Anything else would
make two measurements incomparable and the recall check unrepeatable.

Run: python backend/tools/synth_estate.py --repos 100 --out /tmp/estate
"""

import argparse
import json
import os
import random
import sys


def _env_key(service: str) -> str:
    return service.replace("-", "_").upper() + "_URL"


def _compose(service: str, targets: list[str]) -> str:
    lines = ["services:", f"  {service}:", "    build: .",
             "    ports:", '      - "8080:8080"']
    if targets:
        lines.append("    environment:")
        lines += [f"      {_env_key(t)}: http://{t}:8080" for t in targets]
        lines.append("    depends_on:")
        lines += [f"      - {t}" for t in targets]
    return "\n".join(lines) + "\n"


def _routes_go(service: str) -> str:
    return f'''package internal

import "net/http"

// The estate's consumers reach this route only through configuration.
func Register(mux *http.ServeMux) {{
\tmux.HandleFunc("GET /v1/{service}/items/{{id}}", handleItems)
}}

func handleItems(w http.ResponseWriter, r *http.Request) {{}}
'''


def _client_py(target: str) -> str:
    # The attribute is named for the service it points at, as real clients
    # are. A repo calling several services reads several *_URL keys from one
    # directory, and this name is the only signal that says which of them a
    # given call site uses.
    var = target.replace("-", "_")
    return f'''"""Calls {target} over HTTP; the host arrives from configuration."""
import os

import httpx


class Client:
    def __init__(self):
        self._{var}_url = os.environ["{_env_key(target)}"]

    async def items(self, item_id: str):
        return await httpx.AsyncClient().get(
            f"{{self._{var}_url}}/v1/{target}/items/{{item_id}}")
'''


def _padding_py(index: int, functions: int) -> str:
    """Parse work with no claims in it: plausible code, nothing to join."""
    parts = [f'"""Internal helpers, batch {index}."""\n']
    for n in range(functions):
        parts.append(f'''

def compute_metric_{index:03d}_{n:02d}(values, weight={n + 1}):
    total = 0
    for value in values:
        if value is None:
            continue
        total += value * weight + {index}
    return total
''')
    return "".join(parts)


def plan_estate(repos: int, *, calls_per_service: int, hot_share: float,
                monorepos: int, mono_services: int, seed: int) -> dict:
    """Decide every service and every call before writing a byte.

    The plan *is* the ground truth: `calls` is exactly the set of
    CALLS_SERVICE edges the linked estate must contain, and the hot provider
    is named so a skew measurement knows what it is looking at.
    """
    rng = random.Random(seed)
    standalone = [f"svc-{i:04d}" for i in range(repos)]
    mono: dict[str, list[str]] = {
        f"mono-{m:04d}": [f"mono-{m:04d}-svc-{s:02d}"
                          for s in range(mono_services)]
        for m in range(monorepos)}
    services = standalone + [s for group in mono.values() for s in group]

    hot = services[0]
    calls: set[tuple[str, str]] = set()
    for service in services:
        others = [s for s in services if s != service]
        for target in rng.sample(others, min(calls_per_service, len(others))):
            calls.add((service, target))
        if service != hot and rng.random() < hot_share:
            calls.add((service, hot))

    return {
        "services": services,
        "repos": {**{s: [s] for s in standalone}, **mono},
        "calls": sorted(calls),
        "hot_provider": hot,
        "hot_consumers": sorted(c for c, t in calls if t == hot),
        "seed": seed,
    }


def _write_service(root: str, service: str, targets: list[str],
                   pad_files: int, pad_functions: int) -> int:
    os.makedirs(os.path.join(root, "internal"), exist_ok=True)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    files = {
        "docker-compose.yml": _compose(service, targets),
        os.path.join("internal", "routes.go"): _routes_go(service),
        **{os.path.join("src", f"{t}_client.py"): _client_py(t)
           for t in targets},
        **{os.path.join("src", f"lib_{n:03d}.py"):
           _padding_py(n, pad_functions) for n in range(pad_files)},
    }
    for name, content in files.items():
        with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
            fh.write(content)
    return len(files)


def write_estate(plan: dict, out_dir: str, *, pad_files: int,
                 pad_functions: int) -> dict:
    """Write the estate and its manifest. Returns the manifest."""
    targets_of: dict[str, list[str]] = {s: [] for s in plan["services"]}
    for consumer, target in plan["calls"]:
        targets_of[consumer].append(target)

    files = 0
    for repo, members in sorted(plan["repos"].items()):
        for service in members:
            # A monorepo nests each service in its own directory, exactly as
            # the real one does; a standalone repo is the service.
            root = (os.path.join(out_dir, repo) if len(members) == 1
                    else os.path.join(out_dir, repo, "services", service))
            files += _write_service(root, service, sorted(targets_of[service]),
                                    pad_files, pad_functions)

    # No absolute paths in the manifest: the estate must be byte-identical
    # wherever it is generated, or two measurements of "the same" estate are
    # not of the same thing. Callers know where they put it.
    manifest = {**plan, "files": files,
                "pad_files": pad_files, "pad_functions": pad_functions}
    with open(os.path.join(out_dir, "manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return manifest


def generate(out_dir: str, *, repos: int, calls_per_service: int = 3,
             hot_share: float = 0.3, monorepos: int = 0,
             mono_services: int = 20, pad_files: int = 20,
             pad_functions: int = 8, seed: int = 7) -> dict:
    plan = plan_estate(repos, calls_per_service=calls_per_service,
                       hot_share=hot_share, monorepos=monorepos,
                       mono_services=mono_services, seed=seed)
    return write_estate(plan, out_dir, pad_files=pad_files,
                        pad_functions=pad_functions)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", type=int, default=100,
                        help="standalone single-service repositories")
    parser.add_argument("--out", required=True)
    parser.add_argument("--calls-per-service", type=int, default=3)
    parser.add_argument("--hot-share", type=float, default=0.3,
                        help="share of services that also call the hot one")
    parser.add_argument("--monorepos", type=int, default=0)
    parser.add_argument("--mono-services", type=int, default=20)
    parser.add_argument("--pad-files", type=int, default=20)
    parser.add_argument("--pad-functions", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    if os.path.exists(args.out) and os.listdir(args.out):
        # Refuse rather than merge: an estate half-written over an older one
        # has ground truth that matches neither, and every measurement made
        # on it is quietly wrong.
        print(f"refusing to write into non-empty {args.out}", file=sys.stderr)
        return 1

    manifest = generate(
        args.out, repos=args.repos, calls_per_service=args.calls_per_service,
        hot_share=args.hot_share, monorepos=args.monorepos,
        mono_services=args.mono_services, pad_files=args.pad_files,
        pad_functions=args.pad_functions, seed=args.seed)
    print(f"{len(manifest['repos'])} repos, {len(manifest['services'])} "
          f"services, {len(manifest['calls'])} planted calls "
          f"({len(manifest['hot_consumers'])} on the hot provider), "
          f"{manifest['files']} files -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
