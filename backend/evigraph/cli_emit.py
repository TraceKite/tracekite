"""Print a wire model, or refuse to print at all.

Shared by both halves of the CLI. Validating here rather than in a test means
neither can emit a shape `wire.py` does not describe — the schema and the
output cannot drift, because the only way out is through the model.
"""

import json
import sys


def emit(model, payload: dict) -> int:
    from evigraph.wire import WIRE_VERSION

    checked = model(**{**payload, "wire_version": WIRE_VERSION})
    json.dump(checked.model_dump(), sys.stdout, indent=2, sort_keys=True,
              default=str)
    sys.stdout.write("\n")
    return 0
