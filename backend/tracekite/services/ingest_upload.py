"""Server-side handling for `tracekite ingest .` uploads.

The CLI ships a local repository as a git bundle; this module validates and
stores it for the ingest job. Validation is deliberately shallow — the name
rule and the bundle magic — because the job runs a real `git clone` against
the file, which rejects anything malformed loudly and with git's own error.
"""

import logging
import os
import uuid

from fastapi import UploadFile

from tracekite.utils.hashing import upload_repo_id
from tracekite.utils.paths import get_upload_dir

logger = logging.getLogger(__name__)

# First line of every bundle git writes; v3 adds capability headers.
BUNDLE_MAGICS = (b"# v2 git bundle", b"# v3 git bundle")

# Matches nginx client_max_body_size; a direct-to-backend upload hits this
# instead of an HTML 413 from the proxy.
MAX_BUNDLE_BYTES = 512 * 1024 * 1024

_CHUNK = 1 << 20


def store_bundle(upload: UploadFile, name: str) -> tuple[str, str]:
    """Validate and spool an upload to the upload dir; return (repo_id, path).

    The filename carries a random suffix so two concurrent uploads of the
    same repository cannot write through each other; only the job's clone
    reads it, and the job handler deletes it afterwards.
    """
    repo_id = upload_repo_id(name)          # raises ValueError on a bad name
    head = upload.file.read(64)
    if not any(head.startswith(magic) for magic in BUNDLE_MAGICS):
        raise ValueError(
            "upload is not a git bundle (expected a '# v2/v3 git bundle' "
            "header)")
    os.makedirs(get_upload_dir(), exist_ok=True)
    path = os.path.join(get_upload_dir(),
                        f"{repo_id}-{uuid.uuid4().hex[:12]}.bundle")
    total = len(head)
    try:
        with open(path, "wb") as out:
            out.write(head)
            while chunk := upload.file.read(_CHUNK):
                total += len(chunk)
                if total > MAX_BUNDLE_BYTES:
                    raise ValueError(
                        f"bundle exceeds the {MAX_BUNDLE_BYTES // (1024 * 1024)} "
                        f"MB upload limit")
                out.write(chunk)
    except Exception:
        discard_bundle(path)
        raise
    return repo_id, path


def discard_bundle(path: str) -> None:
    """Best-effort cleanup; the clone has its own copy either way."""
    try:
        os.unlink(path)
    except OSError:
        pass


def sweep_upload_dir() -> int:
    """Delete orphaned bundles left by a restart between upload and pickup.

    Symmetric with reap_stale_jobs: a restart after the route stored a bundle
    but before the job picked it up leaves the file on disk with no job to
    process or delete it.
    """
    upload_dir = get_upload_dir()
    if not os.path.isdir(upload_dir):
        return 0
    count = 0
    for filename in os.listdir(upload_dir):
        if filename.endswith(".bundle"):
            path = os.path.join(upload_dir, filename)
            try:
                os.unlink(path)
                count += 1
            except OSError:
                pass
    if count:
        logger.warning("Swept %d orphaned bundle(s) from %s", count, upload_dir)
    return count
