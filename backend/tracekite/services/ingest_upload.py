"""Server-side handling for `tracekite ingest .` uploads.

The CLI ships a local repository as a git bundle; this module validates and
stores it for the ingest job. Validation is deliberately shallow — the name
rule and the bundle magic — because the job runs a real `git clone` against
the file, which rejects anything malformed loudly and with git's own error.
"""

import os
import uuid

from fastapi import UploadFile

from tracekite.utils.hashing import upload_repo_id
from tracekite.utils.paths import get_upload_dir

# First line of every bundle git writes; v3 adds capability headers.
BUNDLE_MAGICS = (b"# v2 git bundle", b"# v3 git bundle")

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
    with open(path, "wb") as out:
        out.write(head)
        while chunk := upload.file.read(_CHUNK):
            out.write(chunk)
    return repo_id, path


def discard_bundle(path: str) -> None:
    """Best-effort cleanup; the clone has its own copy either way."""
    try:
        os.unlink(path)
    except OSError:
        pass
