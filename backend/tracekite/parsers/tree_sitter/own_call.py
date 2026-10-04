"""The part of a call expression that is the call itself.

A call's text is its whole expression: for a chained call that includes every
link before it, and for any call it includes everything nested in its
arguments. Route patterns searched over that text matched whichever
registration came first, once per enclosing call. `Router::new().route("/a",
..).route("/b", ..)` produced `/a` twice and never `/b`, and actix's
`HttpServer::new(|| App::new().route("/health", ..)).bind(..).run()` cited
`/health` at the `HttpServer::new`, `.bind` and `.run` lines as well as its own.

A call owns exactly one match: the one spanning its own method name where that
name sits outside every bracket — earlier links end before it, and calls nested
in its arguments begin after it.
"""

import re
from typing import Optional

_OPEN, _CLOSE = "([{", ")]}"


def _top_level_name(context: str, callee: str) -> int:
    """Index of the last `callee(` outside every bracket, or -1."""
    if not callee:
        return -1
    depth_at, depth = [], 0
    for char in context:
        depth_at.append(depth)
        if char in _OPEN:
            depth += 1
        elif char in _CLOSE:
            depth = max(0, depth - 1)
    pattern = re.compile(r"(?<![\w$])" + re.escape(callee) + r"\s*\(")
    starts = [m.start() for m in pattern.finditer(context)
              if depth_at[m.start()] == 0]
    return starts[-1] if starts else -1


def own_match(pattern: str, context: str, callee: str,
              flags: int = 0) -> Optional[re.Match]:
    """The match of `pattern` that belongs to this call, if any."""
    own = _top_level_name(context, callee)
    if own < 0:
        return None
    for match in re.finditer(pattern, context, flags):
        if match.start() <= own < match.end():
            return match
    return None
