"""Credential-safe git operations (design §3.4, §9).

Tokens travel via GIT_ASKPASS + environment — never in argv or remote URLs —
so they cannot leak into process lists, logs, or .git/config.
"""

import logging
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Optional

from tracekite.config import settings
from tracekite.utils.hashing import extract_git_host
from tracekite.utils.paths import ensure_workspace, get_repo_workspace_path

logger = logging.getLogger(__name__)


class CloneError(RuntimeError):
    pass


def resolve_token(host: str, explicit_token: Optional[str] = None) -> Optional[str]:
    """Per-request token wins; otherwise the configured PAT for github.com."""
    if explicit_token:
        return explicit_token
    if host == "github.com" and settings.github_token:
        return settings.github_token
    return None


def _write_askpass(token: str) -> str:
    fd, path = tempfile.mkstemp(prefix="askpass-", suffix=".sh")
    with os.fdopen(fd, "w") as handle:
        handle.write(
            '#!/bin/sh\ncase "$1" in\n'
            '  Username*) echo "x-access-token" ;;\n'
            '  Password*) echo "$GIT_TOKEN" ;;\n'
            "esac\n"
        )
    os.chmod(path, stat.S_IRWXU)
    return path


def _assert_no_credentials(repo_path: str) -> None:
    git_config = os.path.join(repo_path, ".git", "config")
    if os.path.exists(git_config):
        with open(git_config) as handle:
            content = handle.read()
        for line in content.splitlines():
            if "url" in line and "@" in line.split("=", 1)[-1] and "://" in line:
                raise CloneError("Clone left credentials in .git/config; aborting")


def clone_repository(git_url: str, repo_id: str, branch: Optional[str] = None,
                     token: Optional[str] = None) -> str:
    """Shallow, blob-filtered, host-allowlisted clone into the workspace.

    Clones into a staging directory and swaps it in only on success. The
    obvious order — delete the old tree, then clone — makes a refresh
    DESTRUCTIVE when the clone fails: a private repository whose token has
    expired loses its working tree and cannot get it back, while the graph
    still holds its claims and the repo goes `failed_clean`. That happened
    twice on this project's own estate before the order was fixed, and the
    second time it was already documented.

    A failed refresh must leave the tree exactly as it was — the same rule
    the ingest pipeline already follows by clearing the graph only after a
    successful scan.
    """
    host = extract_git_host(git_url)
    if host not in settings.allowed_hosts_list():
        raise CloneError(f"Git host {host!r} is not in ALLOWED_GIT_HOSTS")

    ensure_workspace()
    dest = get_repo_workspace_path(repo_id)
    staging = f"{dest}.incoming"

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", "/tmp"),
        "GIT_TERMINAL_PROMPT": "0",
    }
    askpass_path = None
    effective_token = resolve_token(host, token)
    if effective_token:
        askpass_path = _write_askpass(effective_token)
        env["GIT_ASKPASS"] = askpass_path
        env["GIT_TOKEN"] = effective_token

    cmd = ["git", "clone", "--depth", "1", "--filter=blob:none", "--single-branch"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [git_url, staging]

    try:
        return _staged_clone(cmd, env, repo_id, staging, dest, what=git_url)
    finally:
        if askpass_path:
            os.unlink(askpass_path)


def clone_bundle(bundle_path: str, repo_id: str,
                 branch: Optional[str] = None) -> str:
    """Clone an uploaded git bundle into the workspace.

    clone_repository's host allowlist answers "may we contact this network
    host"; a bundle crossed that boundary when the upload route validated
    and stored it, so this clones the local file directly. `--depth` and
    `--filter` are omitted: bundle transport ignores them. The staging
    discipline is the shared one — a failed clone leaves the previous tree
    exactly as it was.
    """
    ensure_workspace()
    dest = get_repo_workspace_path(repo_id)
    staging = f"{dest}.incoming"
    cmd = ["git", "clone", "--single-branch"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [bundle_path, staging]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", "/tmp"),
        "GIT_TERMINAL_PROMPT": "0",
    }
    return _staged_clone(cmd, env, repo_id, staging, dest, what="uploaded bundle")


def _staged_clone(cmd: list[str], env: dict, repo_id: str, staging: str,
                  dest: str, what: str) -> str:
    """Run one git clone into `staging`, swap it over `dest` on success.

    # One flag checked in `finally`, rather than cleanup in each except
    # clause: `except TimeoutExpired: raise CloneError` propagates the NEW
    # exception, so a sibling `except` never runs and the timeout path would
    # leak its staging tree.
    """
    if os.path.exists(staging):
        shutil.rmtree(staging)
    cloned = False
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True,
            timeout=settings.clone_timeout_s,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()[-500:]
            raise CloneError(f"git clone failed for {what}: {stderr}")
        _assert_no_credentials(staging)
        cloned = True
    except subprocess.TimeoutExpired:
        raise CloneError(f"git clone timed out after {settings.clone_timeout_s}s")
    finally:
        # Discards the staging tree and only that: `dest` is still the last
        # good clone. Unconditional on failure, because git creates the
        # target directory before it can fail, so "has a .git" does not
        # distinguish a usable clone from a half-written one.
        if not cloned:
            shutil.rmtree(staging, ignore_errors=True)

    _swap_in(staging, dest)
    logger.info("Cloned %s into %s", what, dest)
    return dest


def _swap_in(staging: str, dest: str) -> None:
    """Replace `dest` with `staging`, keeping the old tree until it lands.

    Not atomic — two renames cannot be — but ordered so the window where
    neither exists is as small as possible, and so a failure mid-swap leaves
    the previous tree recoverable at `<dest>.previous` rather than gone.
    """
    previous = f"{dest}.previous"
    if os.path.exists(previous):
        shutil.rmtree(previous, ignore_errors=True)
    if os.path.exists(dest):
        os.rename(dest, previous)
    try:
        os.rename(staging, dest)
    except OSError:
        if os.path.exists(previous) and not os.path.exists(dest):
            os.rename(previous, dest)      # put it back
        raise
    shutil.rmtree(previous, ignore_errors=True)


def _git_output(repo_path: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise CloneError(f"git {' '.join(args)} failed: {result.stderr.strip()[:200]}")
    return result.stdout.strip()


def get_head_commit_sha(repo_path: str) -> str:
    return _git_output(repo_path, "rev-parse", "HEAD")


def get_default_branch(repo_path: str) -> str:
    try:
        return _git_output(repo_path, "symbolic-ref", "--short", "HEAD")
    except CloneError:
        # Detached HEAD: return the short SHA rather than inventing "main",
        # which may not exist in the repository. The field is "what HEAD
        # points to", and a SHA is the honest answer.
        return _git_output(repo_path, "rev-parse", "--short", "HEAD")


def delete_repository(repo_id: str) -> bool:
    """Remove the cloned working copy for a repo."""
    repo_path = get_repo_workspace_path(repo_id)
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
        logger.info("Deleted workspace for %s", repo_id)
        return True
    return False
