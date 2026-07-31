"""Canonical key normalization shared by ingestion and the linker (design §6.1).

The positional path template turns every parameter flavor into ``{}`` so that
``/users/{id}``, ``/users/:id``, and ``/users/<int:id>`` all join on
``/users/{}``.
"""

import re

_PARAM_SEGMENT = re.compile(
    r"^(\{[^}]*\}|:[A-Za-z_][\w]*|<[^>]*>|\$\{[^}]*\}|\*+)$"
)
_EMBEDDED_PARAM = re.compile(r"\{[^}]*\}|<[^>]*>|\$\{[^}]*\}")


def canonicalize_path_template(path: str) -> str:
    """Normalize a route path into a positional template, e.g. ``/users/{}``."""
    if not path:
        return "/"
    path = path.strip()
    path = re.sub(r"^https?://[^/]+", "", path)
    path = re.sub(r"/{2,}", "/", path)
    if not path.startswith("/"):
        path = "/" + path
    segments = []
    for segment in path.split("/"):
        if not segment:
            continue
        if _PARAM_SEGMENT.match(segment):
            segments.append("{}")
        elif _EMBEDDED_PARAM.search(segment):
            segments.append(_EMBEDDED_PARAM.sub("{}", segment))
        else:
            segments.append(segment)
    return "/" + "/".join(segments) if segments else "/"


def squash_separators(name: str) -> str:
    """Collapse the separators two spellings of one name disagree on.

    `billing-service`, `billing_service` and `billing.service` all become
    `billingservice`, so a comparison can ask "the same name?" without
    caring which convention each side used.

    **For comparison only — never to build a rendezvous key.** Squashing is
    lossy: `a-b` and `ab` collapse together, so a key built this way would
    merge two genuinely different names, which is the wrong-merge the design
    forbids. Existed twice before this, once with `.` in the separator set and
    once without — two functions answering one question differently, which is
    worse than none because neither is obviously wrong.
    """
    return name.lower().replace("-", "").replace("_", "").replace(".", "")


def normalize_http_method(method: str) -> str:
    method = (method or "GET").strip().upper()
    return method if method in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD",
                                "OPTIONS"} else "GET"


def build_purl(dep_type: str, name: str, version: str = "") -> str:
    """Package URL for dependency rendezvous keys (design §2.3)."""
    type_map = {
        "maven": "maven", "gradle": "maven", "npm": "npm", "yarn": "npm",
        "pip": "pypi", "python": "pypi", "poetry": "pypi", "go": "golang",
        "cargo": "cargo", "gem": "gem", "composer": "composer", "nuget": "nuget",
    }
    purl_type = type_map.get((dep_type or "").lower(), "generic")
    name = (name or "").strip()
    if purl_type == "maven" and ":" in name:
        group, artifact = name.split(":", 1)
        base = f"pkg:maven/{group}/{artifact}"
    else:
        base = f"pkg:{purl_type}/{name}"
    version = (version or "").strip()
    if version and not version.startswith("$"):
        return f"{base}@{version}"
    return base
