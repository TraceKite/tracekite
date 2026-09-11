"""Parse-time secret redaction (design §3.4, Invariant 6).

Raw config values never reach nodes, claims, evidence, logs, or dumps.
Config properties become exactly the ``RedactedValue`` fields plus the key.
"""

import hashlib
import hmac as hmac_mod
import math
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from tracekite.engine_config import get_config

KEY_DENYLIST = ("SECRET", "TOKEN", "PASSWORD", "PASSWD", "API_KEY", "APIKEY",
                "PRIVATE", "CREDENTIAL", "AUTH")

_ENTROPY_THRESHOLD_BITS = 4.0
_ENTROPY_MIN_LENGTH = 20
_BOOL_VALUES = {"true", "false", "yes", "no", "on", "off"}
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9\-\.]*[a-z0-9])?(:\d{1,5})?$", re.IGNORECASE)
_ENUMISH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,31}$")


@dataclass
class RedactedValue:
    value_class: str                    # url|hostname|port|number|bool|enum-ish|secret|opaque
    value_host: Optional[str] = None    # join key for R1/R2/R9
    value_port: Optional[int] = None
    value_scheme: Optional[str] = None
    value_path_prefix: Optional[str] = None  # first path segment only
    value_hmac: str = ""                # keyed equality joins without disclosure
    value_len: int = 0

    def to_props(self) -> dict:
        return {
            "value_class": self.value_class,
            "value_host": self.value_host,
            "value_port": self.value_port,
            "value_scheme": self.value_scheme,
            "value_path_prefix": self.value_path_prefix,
            "value_hmac": self.value_hmac,
            "value_len": self.value_len,
        }


class RedactionKeyMissing(RuntimeError):
    """Raised when GRAPH_HMAC_KEY is unset — redaction must never silently degrade."""


def _hmac16(value: str) -> str:
    key = get_config().graph_hmac_key
    if not key:
        raise RedactionKeyMissing("GRAPH_HMAC_KEY must be set before ingesting")
    return hmac_mod.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()[:16]


def hmac16(value: str) -> str:
    """Keyed digest for equality joins without disclosure.

    The linker uses this to match a *code literal* (a topic name in source,
    which is not secret) against a *config value* (redacted at ingest, only its
    hmac stored) — R6 topic indirection is the first consumer."""
    return _hmac16(value)


def shannon_entropy_bits(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(value)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in KEY_DENYLIST)


def looks_high_entropy(value: str) -> bool:
    return (len(value) >= _ENTROPY_MIN_LENGTH
            and shannon_entropy_bits(value) >= _ENTROPY_THRESHOLD_BITS)


def _classify_url(value: str) -> Optional[RedactedValue]:
    if "://" not in value:
        return None
    parts = urlsplit(value.strip())
    if not parts.scheme or not (parts.hostname or parts.path):
        return None
    try:
        port = parts.port
    except ValueError:
        port = None
    path_segments = [seg for seg in parts.path.split("/") if seg]
    return RedactedValue(
        value_class="url",
        value_host=parts.hostname,      # userinfo always stripped
        value_port=port,
        value_scheme=parts.scheme,
        value_path_prefix=path_segments[0] if path_segments else None,
        value_hmac=_hmac16(value),
        value_len=len(value),
    )


def redact(key: str, value: str) -> RedactedValue:
    """Redact a config value into structural, join-safe fields."""
    value = "" if value is None else str(value)
    length = len(value)
    if not value:
        return RedactedValue(value_class="opaque", value_hmac=_hmac16(""), value_len=0)

    if is_secret_key(key):
        # Structural fields nulled: a secret must not leak shape either.
        return RedactedValue(value_class="secret", value_hmac=_hmac16(value), value_len=length)

    # URLs are structured, not secrets: classify before the entropy heuristic
    # (credentials embedded in URLs are dropped — only host/port/scheme/prefix
    # survive). Anything long and random that is not URL-shaped is a secret.
    if url := _classify_url(value):
        return url

    if looks_high_entropy(value):
        return RedactedValue(value_class="secret", value_hmac=_hmac16(value), value_len=length)

    stripped = value.strip()
    hmac16 = _hmac16(value)
    if stripped.lower() in _BOOL_VALUES:
        return RedactedValue(value_class="bool", value_hmac=hmac16, value_len=length)
    if stripped.isdigit():
        num = int(stripped)
        if 0 < num <= 65535:
            return RedactedValue(value_class="port", value_port=num,
                                 value_hmac=hmac16, value_len=length)
        return RedactedValue(value_class="number", value_hmac=hmac16, value_len=length)
    if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
        return RedactedValue(value_class="number", value_hmac=hmac16, value_len=length)
    if "." in stripped and " " not in stripped and _HOSTNAME_RE.match(stripped):
        host, port = stripped, None
        if ":" in stripped:
            host, port_str = stripped.rsplit(":", 1)
            port = int(port_str) if port_str.isdigit() else None
        return RedactedValue(value_class="hostname", value_host=host.lower(),
                             value_port=port, value_hmac=hmac16, value_len=length)
    if _ENUMISH_RE.match(stripped):
        return RedactedValue(value_class="enum-ish", value_hmac=hmac16, value_len=length)
    return RedactedValue(value_class="opaque", value_hmac=hmac16, value_len=length)
