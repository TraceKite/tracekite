"""Collect source metadata for snapshot identity.

This module performs I/O (Git commands, file reads) and belongs to the
server layer.  The pure computation of snapshot identity lives in
``answer.SnapshotIdentity``.

A directory scan previously registered an empty commit string; this module
fills in the actual Git head SHA, dirty state, and content digest so that
an answer can be reproduced against a named revision rather than a blank.
"""

from __future__ import annotations

import hashlib
import os
import subprocess

from tracekite.answer import RepoRevision
from tracekite.scan_meta import ScanMeta


def _git(path: str, *args: str) -> str | None:
    """Run a Git command in ``path``, return stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def collect_dir_meta(path: str, repo_id: str) -> RepoRevision:
    """Collect Git metadata for a source directory.

    If the directory is not a Git repository, ``unversioned`` is True and
    ``head_sha`` stays None — unknown stays unknown.
    """
    git_dir = os.path.join(path, ".git")
    if not os.path.exists(git_dir):
        return RepoRevision(repo_id=repo_id, unversioned=True)

    head = _git(path, "rev-parse", "HEAD")
    status = _git(path, "status", "--porcelain")
    dirty = bool(status)

    # A content digest is only needed for dirty trees where the head SHA
    # does not fully describe the working copy.  For a clean tree the head
    # SHA is the identity; computing a full digest would be wasteful.
    content_digest = None
    if dirty:
        content_digest = _dirty_digest(path)

    return RepoRevision(
        repo_id=repo_id,
        head_sha=head,
        content_digest=content_digest,
        dirty=dirty,
    )


def _dirty_digest(path: str) -> str | None:
    """A deterministic digest of a dirty working tree.

    Hashes staged, unstaged, and untracked content independently so that
    the three kinds of change each move the digest.  ``git diff`` alone
    only shows unstaged changes — a staged-but-uncommitted file would
    produce the same digest as a clean tree, which is an invented identity.

    Each component is prefixed with a label so that a staged change and an
    unstaged change to the same content do not collide. Untracked bytes are
    hashed into the digest but never returned, so source secrets do not enter
    the answer payload.
    """
    parts: list[str] = []

    staged = _git(path, "diff", "--cached", "--no-color")
    if staged:
        parts.append("staged:" + staged)

    unstaged = _git(path, "diff", "--no-color")
    if unstaged:
        parts.append("unstaged:" + unstaged)

    # Untracked files are invisible to git diff. Hash their paths and bytes,
    # not just their names, so changing an untracked source file changes the
    # snapshot identity as well.
    untracked = _git(path, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked:
        digest = hashlib.sha256()
        for rel_path in sorted(filter(None, untracked.split("\0"))):
            full_path = os.path.join(path, rel_path)
            try:
                with open(full_path, "rb") as handle:
                    content = handle.read()
            except OSError:
                content = b"<unreadable>"
            digest.update(rel_path.encode())
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
        parts.append("untracked:" + digest.hexdigest())

    if not parts:
        return None

    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def collect_artifact_meta(
    meta: dict, repo_id: str, artifact_path: str | None = None
) -> RepoRevision:
    """Build a RepoRevision from artifact metadata.

    Artifacts carry ``head_sha`` in their meta; a missing or empty value
    means the scan could not determine the revision, and that stays None
    rather than becoming a placeholder.  The artifact file digest is the
    content identity when its path is available.
    """
    head = meta.get("head_sha") or None
    artifact_digest = None
    if artifact_path:
        from tracekite.db.artifact import digest_of

        artifact_digest = digest_of(artifact_path)
    return RepoRevision(
        repo_id=repo_id,
        head_sha=head if head else None,
        content_digest=artifact_digest,
        producer=dict(meta.get("producer") or {}),
    )


def collect_input_meta(paths: list[str]) -> tuple[list[RepoRevision], ScanMeta]:
    """Collect revisions and retained scan metadata for input paths."""
    from tracekite.db.artifact import read_meta
    from tracekite.scan_meta import repo_scan_meta_from_artifact

    revisions: list[RepoRevision] = []
    scan_meta = ScanMeta()
    for path in paths:
        if os.path.isfile(path) and path.endswith(".tracekite"):
            meta = read_meta(path)
            repo_ids = ([meta["repo_id"]] if meta.get("repo_id") else
                        list(meta.get("repos") or []))
            for repo_id in repo_ids:
                revisions.append(collect_artifact_meta(meta, repo_id, path))
                scan_meta.add(repo_scan_meta_from_artifact(meta, repo_id))
        elif os.path.isdir(path):
            repo_id = os.path.basename(os.path.abspath(path))
            revisions.append(collect_dir_meta(path, repo_id))
    return revisions, scan_meta
