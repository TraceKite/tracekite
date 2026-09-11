"""Helm template references, read without rendering.

A ConfigMap value of `{{ .Values.backend.url }}` is a POINTER, not a
value: the chart never ran, so the text identifies a values-file key and
nothing else. This module extracts that pointer so R9 can follow the
chain values → ConfigMap → env → code.

Only a value that is exactly one reference resolves. A composite like
`http://{{ .Values.host }}:{{ .Values.port }}` would need template
evaluation to reconstruct — splicing it back together is rendering, and
a hand-rendered value is an invented one. Composites return None and the
caller counts them.
"""

import re

_PURE_REF = re.compile(
    r"^\{\{-?\s*\.Values\.([A-Za-z0-9_.\-]+(?:\[\d+\])?)"
    r"\s*(?:\|[^}]*)?-?\}\}$")


def helm_value_ref(value: str) -> str | None:
    """The values-file key a value points at, or None.

    `{{ .Values.backend.url }}` → `backend.url`; pipes like `| quote`
    are presentation, not indirection, and are ignored.
    """
    match = _PURE_REF.match((value or "").strip())
    return match.group(1) if match else None
