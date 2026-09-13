"""Pure conversion of graph property values into API-safe values."""

import json


def parse_json(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def to_native_dt(value):
    return value.to_native() if hasattr(value, "to_native") else value


def json_safe(value):
    """Fold Neo4j temporal values into JSON-safe ISO strings."""
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        native = to_native()
        return native.isoformat() if hasattr(native, "isoformat") else str(native)
    return value
