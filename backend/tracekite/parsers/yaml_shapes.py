"""Coercions for loosely-typed YAML.

Kubernetes and gateway configs let one field be a scalar or a list, and
let anything be absent. Both parsers grew the same two coercions
independently and byte-identically, which is the duplication that quietly
becomes two behaviours the first time one of them learns about, say,
tuples.

Deliberately not a general "utils" module: these are about the shape YAML
documents arrive in, and nothing else belongs here.
"""


def as_list(value) -> list:
    """A field that may be a scalar, a list, or absent, as a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def as_str(value) -> str:
    """A field that may be absent, as a string — `None` becomes empty.

    `str(None)` is `"None"`, a four-character name that has matched a real
    service exactly never, so the guard is the point of the function.
    """
    return "" if value is None else str(value)
