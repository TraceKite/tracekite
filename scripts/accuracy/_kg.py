"""Shared plumbing for the accuracy harness.

The harness measures the graph against the source it was built from. Both
directions -- precision (verify_edges.py) and recall (measure_recall.py) --
need the same four things: a Neo4j connection, a way to read files out of the
ingested clone, a repo to point at, and cypher-shell output parsed into rows.
This is that, in one place, so neither script grows its own copy.

Nothing here is specific to any estate. The repo under test comes from argv
or $ADDUCE_REPO, and defaults to every repo the graph knows about, so the
harness runs against whatever you have ingested.
"""
import os
import subprocess
import sys

# Overridable so the harness works against a stack renamed in compose, or one
# run under a project prefix.
NEO4J_CONTAINER = os.environ.get("ADDUCE_NEO4J_CONTAINER", "adduce-neo4j")
BACKEND_CONTAINER = os.environ.get("ADDUCE_BACKEND_CONTAINER", "adduce-backend")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
REPO_ROOT = os.environ.get("ADDUCE_REPO_ROOT", "/app/data/repos")


def _password() -> str:
    """Neo4j password from the environment, falling back to the repo's .env.

    Never hardcode an absolute path to someone's checkout: resolve .env
    relative to this file so a clone anywhere works.
    """
    if os.environ.get("NEO4J_PASSWORD"):
        return os.environ["NEO4J_PASSWORD"]
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
    try:
        with open(env_path) as fh:
            for line in fh:
                if line.startswith("NEO4J_PASSWORD"):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


PW = _password()


def sh(*args: str) -> str:
    """Run a command, return stdout, swallow failure."""
    return subprocess.run(args, capture_output=True, text=True).stdout


def _run_cypher(query: str) -> list[str]:
    out = subprocess.run(
        ["docker", "exec", NEO4J_CONTAINER, "cypher-shell", "-u", NEO4J_USER,
         "-p", PW, "--format", "plain", query],
        capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr[:400], file=sys.stderr)
        return []
    return [ln for ln in out.stdout.strip().split("\n") if ln.strip()]


def cypher(query: str) -> list[dict]:
    """Rows as dicts keyed by the RETURN aliases.

    A NULL comes back from cypher-shell's `plain` format as the literal text
    `NULL`, which is TRUTHY in Python. Left alone it defeats every
    `row.get(x) or fallback` in the callers -- one such case had the harness
    reading files from a repo literally named "NULL" and reporting a third of
    a stratum unverifiable. Matched case-insensitively because the casing is
    a rendering detail nobody should have to remember.
    """
    lines = _run_cypher(query)
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].split(", ")]
    return [{k: ("" if v.upper() == "NULL" else v)
             for k, v in zip(header, _split_row(line))}
            for line in lines[1:]]


def cypher_set(query: str) -> set[str]:
    """Single-column results as a set, header dropped."""
    return {ln.strip().strip('"') for ln in _run_cypher(query)[1:] if ln.strip()}


def _split_row(line: str) -> list[str]:
    """cypher-shell `plain` output: comma-separated, quoted fields may hold commas."""
    out, cur, quoted, i = [], "", False, 0
    while i < len(line):
        char = line[i]
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            out.append(cur.strip().strip('"'))
            cur = ""
            i += 1
            if i < len(line) and line[i] == " ":
                i += 1
            continue
        cur += char
        i += 1
    out.append(cur.strip().strip('"'))
    return out


# --------------------------------------------------------------- repo target
def ingested_repos() -> list[str]:
    """Every repo_id the graph currently holds."""
    return sorted(cypher_set(
        "MATCH (n:GraphNode) WHERE n.repo_id IS NOT NULL "
        "RETURN DISTINCT n.repo_id;"))


def target_repos() -> list[str]:
    """Repos to measure: argv, else $ADDUCE_REPO, else everything ingested."""
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        return args
    if os.environ.get("ADDUCE_REPO"):
        return [r.strip() for r in os.environ["ADDUCE_REPO"].split(",") if r.strip()]
    found = ingested_repos()
    if not found:
        print("no repos in the graph -- ingest one first, or pass a repo id",
              file=sys.stderr)
    return found


def repo_path(repo_id: str) -> str:
    return f"{REPO_ROOT}/{repo_id}"


def ingested_at(repo_id: str) -> str:
    """When this repo was last ingested.

    Worth printing beside every measurement. The harness reads the STORED
    graph, which was written by whatever version of the extractors was running
    at ingest time -- so a repo ingested before a fix landed will show that
    fix's bug and look like a live defect. This cost a real debugging detour:
    compose recall read 2/11 on a repo whose current parser handles 11/11.
    Re-ingest before believing a low score.
    """
    rows = cypher(f"MATCH (r:Repo {{repo_id:'{repo_id}'}}) "
                  "RETURN toString(r.last_ingested_at) AS t;")
    return rows[0].get("t", "") if rows else ""


# ------------------------------------------------------------- source access
_file_cache: dict[str, str | None] = {}


def read_file(repo_id: str, path: str) -> str | None:
    """Read a file from the ingested clone. `path` may be absolute or relative."""
    full = path if path.startswith("/") else f"{repo_path(repo_id)}/{path}"
    if full in _file_cache:
        return _file_cache[full]
    out = subprocess.run(["docker", "exec", BACKEND_CONTAINER, "cat", full],
                         capture_output=True, text=True)
    _file_cache[full] = out.stdout if out.returncode == 0 else None
    return _file_cache[full]


def find(repo_id: str, *predicate: str) -> list[str]:
    """`find` inside the clone, .git always excluded."""
    expr = " ".join(predicate)
    return [p for p in sh("docker", "exec", BACKEND_CONTAINER, "sh", "-c",
                          f'find {repo_path(repo_id)} {expr} -not -path "*/.git/*" 2>/dev/null'
                          ).split("\n") if p.strip()]


def evidence_parts(ev: str) -> tuple[str | None, int | None]:
    """Split a `path/to/file.py:123` evidence string."""
    if not ev or ":" not in ev:
        return None, None
    path, _, line = ev.rpartition(":")
    try:
        return path, int(line)
    except ValueError:
        return ev, None


def near(text: str | None, line: int | None, radius: int = 6) -> str | None:
    """The lines around a cited line, for checking what the evidence points at."""
    if text is None or line is None:
        return None
    lines = text.split("\n")
    return "\n".join(lines[max(0, line - 1 - radius):min(len(lines), line + radius)])
