"""Stable identity generation for graph nodes, symbols, and contract claims.

Identity rules (design doc §2.1):
- node ids embed a sha256[:16] content hash, never line numbers
- symbols disambiguate via signature-hash + occurrence index
- every symbol also carries a readable, indexed ``symbol_uid``
"""

import hashlib
import re

_GITHUB_HOST = "github.com"


def _sha256_16(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def generate_repo_id(owner: str, repo: str, host: str = _GITHUB_HOST) -> str:
    """Stable repo id: ``owner_repo`` for GitHub, ``host_owner_repo`` elsewhere."""
    base = f"{owner.lower()}_{repo.lower()}"
    if host and host != _GITHUB_HOST:
        host_slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
        return f"{host_slug}_{base}"
    return base


_UPLOAD_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,98}$")


def upload_repo_id(name: str) -> str:
    """Repo id for a directory shipped by ``tracekite ingest .``.

    A local upload has no host or owner to derive identity from, so the id
    is the caller-chosen name under a ``local_`` prefix, keeping it out of
    the ``owner_repo`` namespace host-derived ids live in. The name is
    validated rather than rewritten — it becomes a filename and a graph id,
    so silent case-folding would make the CLI and the server disagree about
    what was ingested.
    """
    if not _UPLOAD_NAME.match(name):
        raise ValueError(
            f"invalid repository name {name!r}: use lowercase letters, "
            "digits, '.', '_' or '-', starting with a letter or digit")
    return f"local_{name}"


def generate_node_id(repo_id: str, node_type: str, path: str,
                     name: str = "", extra: str = "") -> str:
    """Layer-0 node id: ``{repo_id}:{Type}:{sha256[:16]}``.

    ``extra`` must never contain line numbers; symbol callers pass
    :func:`symbol_extra` output instead.
    """
    content = f"{repo_id}:{node_type}:{path}:{name}:{extra}"
    return f"{repo_id}:{node_type}:{_sha256_16(content)}"


def symbol_extra(name: str, arity: int, occurrence_index: int) -> str:
    """Line-number-free disambiguator: signature hash + declaration-order index."""
    signature_hash = hashlib.sha1(f"{name}#{arity}".encode()).hexdigest()[:8]
    return f"{signature_hash}:{occurrence_index}"


def build_symbol_uid(repo_id: str, lang: str, path: str,
                     qualified_name: str, arity: int) -> str:
    """SCIP-shaped readable symbol string, stored as an indexed property."""
    return f"{repo_id} {lang} {path} {qualified_name}#{arity}"


def generate_claim_id(repo_id: str, kind: str, direction: str,
                      key: str, evidence_path: str) -> str:
    content = f"{kind}:{direction}:{key}:{evidence_path}"
    return f"{repo_id}:ContractClaim:{_sha256_16(content)}"


def normalize_github_url(url: str) -> tuple[str, str, str]:
    """Normalize a GitHub URL and extract owner and repo name.

    Returns:
        tuple: (normalized_url, owner, repo_name)

    Raises:
        ValueError: If URL is not a valid GitHub repository URL.
    """
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[: -len(".git")]

    # Anchored, not searched: `re.search` matched `evil.com/?x=github.com/o/r`
    # and then rebuilt a github.com URL from it, so the caller's host check was
    # validating a string this function had just invented.
    std_pattern = (r"^(?:[a-z+]+://)?(?:[^@/]+@)?"
                   r"(?P<host>[A-Za-z0-9.\-]+)"
                   r"(?::\d+)?/(?P<owner>[^/?#]+)/(?P<repo>[^/?#]+)$")
    scp_pattern = (r"^(?:[a-z+]+://)?(?:[^@/]+@)?"
                   r"(?P<host>[A-Za-z0-9.\-]+):"
                   r"(?P<owner>[^/?#]+)/(?P<repo>[^/?#]+)$")
    match = re.match(std_pattern, url) or re.match(scp_pattern, url)
    if not match:
        raise ValueError(
            f"Invalid repository URL: {url}. "
            f"Expected format: https://<host>/<owner>/<repo> or git@<host>:<owner>/<repo>"
        )

    host = match.group("host").lower()
    owner, repo = match.group("owner"), match.group("repo")
    # A leading '-' would reach `git clone` as an option, not a path.
    if owner.startswith("-") or repo.startswith("-"):
        raise ValueError(f"Invalid repository URL: {url}")
    normalized_url = f"https://{host}/{owner}/{repo}"
    return normalized_url, owner, repo


def extract_git_host(url: str) -> str:
    """Return the hostname of a git remote URL (https or scp-like ssh)."""
    https_match = re.match(r"^[a-z+]+://(?:[^@/]+@)?([^/:]+)", url.strip(), re.IGNORECASE)
    if https_match:
        return https_match.group(1).lower()
    scp_match = re.match(r"^(?:[^@/]+@)?([^/:]+):", url.strip())
    if scp_match:
        return scp_match.group(1).lower()
    raise ValueError(f"Cannot determine git host from URL: {url}")


def sanitize_path(path: str) -> str:
    """Reduce a path to a repo-relative, traversal-free form.

    Resolves segment-wise rather than stripping ``..`` textually: the textual
    form left ``....//`` collapsing back to ``../`` after one pass.
    """
    parts: list[str] = []
    for segment in re.split(r"[\\/]+", path or ""):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts)
