"""`tracekite ingest`: hand a repository to a running TraceKite server.

A git URL is queued for the server to clone, exactly like the UI's Ingest
button. A directory is shipped as a git bundle of its committed content, so
what gets ingested is precisely what is on disk — a repository that exists
only on this machine, unpushed commits included. Uncommitted changes are
not shipped; the command says so when it sees them.
"""

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

import httpx

from tracekite.utils.hashing import normalize_github_url, upload_repo_id

DEFAULT_SERVER = "http://127.0.0.1:28080"
_TERMINAL = {"completed", "failed"}


class IngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class DirectoryPlan:
    """A local repository to ship: validated name plus the refs to bundle."""
    path: str
    name: str
    refs: tuple[str, ...]
    server_branch: str | None   # only an explicit --branch reaches the clone


def add_ingest_parser(sub) -> None:
    p = sub.add_parser(
        "ingest", help="queue a repository for ingestion on a TraceKite server")
    p.add_argument("target",
                   help="git URL for the server to clone, or a local "
                        "directory ('.' ships its committed content as a "
                        "git bundle upload)")
    p.add_argument("--server",
                   default=os.environ.get("TRACEKITE_SERVER", DEFAULT_SERVER),
                   help="default: $TRACEKITE_SERVER, else %(default)s")
    p.add_argument("--branch", default=None)
    p.add_argument("--token", default=None,
                   help="git host token for private repositories (URL form)")
    p.add_argument("--name", default=None,
                   help="repository name for a directory upload "
                        "(default: directory name; must be lowercase)")
    p.add_argument("--no-wait", action="store_true",
                   help="print the job id and exit instead of waiting")
    p.set_defaults(func=cmd_ingest)


def cmd_ingest(args) -> int:
    try:
        if os.path.isdir(args.target):
            job = _ingest_directory(args)
        else:
            job = _ingest_url(args)
    except IngestError as exc:
        print(f"ingest: {exc}", file=sys.stderr)
        return 2
    print(f"queued job {job['job_id']} for repository {job['repo_id']}")
    if args.no_wait:
        print(f"status: GET {args.server}/api/jobs/{job['job_id']}")
        return 0
    return _wait_for_job(args.server, job["job_id"])


def plan_directory(path: str, name: str | None,
                   branch: str | None) -> DirectoryPlan:
    """Validate a directory target and decide what the bundle will carry."""
    path = os.path.realpath(path)
    if _git(path, "rev-parse", "--is-inside-work-tree", check=False) != "true":
        raise IngestError(f"{path} is not a git repository")
    # git -C <subdir> bundle create ships the whole repository, not the
    # subdirectory; resolve to the toplevel so the name and the content agree.
    toplevel = _git(path, "rev-parse", "--show-toplevel")
    if toplevel != path:
        print(f"ingest: {path} is a subdirectory; shipping the whole "
              f"repository at {toplevel}", file=sys.stderr)
        path = toplevel
    name = name or os.path.basename(path)
    try:
        upload_repo_id(name)      # the same rule the server will apply
    except ValueError as exc:
        raise IngestError(f"{exc}; pass --name to choose one")
    if not _git(path, "rev-parse", "--verify", "HEAD", check=False):
        raise IngestError(
            "no commits yet — a bundle of an empty history would ingest "
            "nothing; commit first")
    current = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD",
                   check=False)
    refs = ["HEAD", branch] if branch else (
        ["HEAD", current] if current else ["HEAD"])
    if _git(path, "status", "--porcelain", check=False):
        print("ingest: working tree has uncommitted changes; only committed "
              "content is shipped", file=sys.stderr)
    return DirectoryPlan(path=path, name=name, refs=tuple(refs),
                         server_branch=branch)


def create_bundle(plan: DirectoryPlan, bundle_path: str) -> int:
    """Write the bundle and return its size in bytes."""
    _git(plan.path, "bundle", "create", bundle_path, *plan.refs)
    return os.path.getsize(bundle_path)


def _ingest_directory(args) -> dict:
    plan = plan_directory(args.target, args.name, args.branch)
    with tempfile.TemporaryDirectory(prefix="tracekite-ingest-") as tmp:
        bundle_path = os.path.join(tmp, f"{plan.name}.bundle")
        size = create_bundle(plan, bundle_path)
        print(f"uploading {plan.name} ({size / 1e6:.1f} MB bundle, "
              f"refs: {', '.join(plan.refs)})")
        data = {"name": plan.name}
        if plan.server_branch:
            data["branch"] = plan.server_branch
        with open(bundle_path, "rb") as handle:
            response = httpx.post(
                f"{args.server}/api/repos/ingest-upload",
                data=data,
                files={"file": (f"{plan.name}.bundle", handle,
                                "application/octet-stream")},
                timeout=httpx.Timeout(600, connect=30))
    return _expect_202(response)


def _ingest_url(args) -> dict:
    try:
        normalize_github_url(args.target)
    except ValueError as exc:
        raise IngestError(f"{exc} (and it is not a directory either)")
    response = httpx.post(
        f"{args.server}/api/repos/ingest",
        json={"github_url": args.target, "branch": args.branch,
              "github_token": args.token},
        timeout=30)
    return _expect_202(response)


def _expect_202(response) -> dict:
    if response.status_code == 202:
        return response.json()
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    raise IngestError(f"server returned {response.status_code}: {detail}")


def _wait_for_job(server: str, job_id: str, timeout_s: int = 1800) -> int:
    deadline = time.monotonic() + timeout_s
    last_line = None
    while time.monotonic() < deadline:
        try:
            job = httpx.get(f"{server}/api/jobs/{job_id}",
                            timeout=30).json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"ingest: status poll failed ({exc}); retrying",
                  file=sys.stderr)
            time.sleep(2)
            continue
        line = f"{job.get('status')} {job.get('progress', 0)}% " \
               f"{job.get('message', '')}".strip()
        if line != last_line:
            print(line)
            last_line = line
        status = job.get("status")
        if status in _TERMINAL:
            if status == "completed":
                return 0
            print(f"ingest failed: {job.get('error') or job.get('message')}",
                  file=sys.stderr)
            return 1
        time.sleep(2)
    print("ingest: timed out waiting for the job; it may still finish — "
          f"check GET {server}/api/jobs/{job_id}", file=sys.stderr)
    return 1


def _git(path: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", path, *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise IngestError(
            f"git {' '.join(args)} failed: {result.stderr.strip()[:200]}")
    return result.stdout.strip()
