"""Lifecycle hooks: let a host observe and veto without forking.

A7 lets a host add a resolver. This lets it watch the ones already there —
and, where it knows something the engine cannot, remove an edge the engine
would otherwise serve. An estate with a decommissioned service, a test
namespace nobody wants in the graph, or a naming convention only the host
understands are all cases where the engine is right in general and wrong here.

Three points, each answering a different question:

* `pre_resolve(name, index, ctx)` — what is about to run
* `post_resolve(name, output, ctx)` — what it produced, and the chance to
  return a smaller set
* `on_decline(counter, n, ctx)` — what it refused

**`on_decline` fires for every `ctx.count()`, not a filtered subset.** In this
codebase `count()` *is* the decline channel — "return nothing and
`ctx.count("rN.reason")` so the decline is visible" — but it also carries
yields like `r7.contracts`. Deciding here which of the ~90 counter names are
"really" declines would mean guessing, and guessing wrong hides exactly the
counter a host was looking for. So everything is offered and the filtering is
the host's, which is the only party that knows what it is looking for.

**Suppression is counted.** A hook that removes edges increments
`hook.suppressed_edges`, because an edge that vanished with no record is
indistinguishable from one that was never found — the failure this project
treats as worse than being wrong out loud.

Hooks may not add edges. Observing and vetoing are safe; injecting is not,
because an edge that did not come from a resolver has no resolver's evidence
behind it, and every edge in this graph cites a file and a line on both sides.
"""

import logging

logger = logging.getLogger(__name__)

_HOOKS: list = []

# `on_decline` fires from `ctx.count()`, and the engine counts suppression —
# so a hook that counts anything would call itself. Guarded rather than
# documented: the recursion is silent until the stack runs out.
_firing = False


def register_hook(hook) -> None:
    """Add a host observer. Any subset of the three methods may be present."""
    known = {"pre_resolve", "post_resolve", "on_decline"}
    present = {name for name in known if callable(getattr(hook, name, None))}
    if not present:
        raise TypeError(
            f"{hook!r} implements none of {sorted(known)}; registering it "
            "would silently do nothing, which is the one thing a "
            "registration must not do")
    _HOOKS.append(hook)


def clear_hooks() -> None:
    """Drop every registered hook. For tests; the app never calls this."""
    _HOOKS.clear()


def registered_hooks() -> list:
    return list(_HOOKS)


def _fire(method: str, *args) -> list:
    """Call `method` on every hook that has it, returning what they returned.

    A hook that raises is logged and skipped, never fatal: a host's observer
    failing must not fail somebody's link run, and a run that died because a
    metrics listener threw is a worse outcome than one that ran unobserved.
    """
    results = []
    for hook in _HOOKS:
        fn = getattr(hook, method, None)
        if fn is None:
            continue
        try:
            results.append(fn(*args))
        except Exception:                                     # noqa: BLE001
            logger.warning("hook %r failed in %s", hook, method, exc_info=True)
    return results


def pre_resolve(name: str, index, ctx) -> None:
    if _HOOKS:
        _fire("pre_resolve", name, index, ctx)


def post_resolve(name: str, output, ctx):
    """Offer the output to each hook; a returned output replaces it.

    Only removal is honoured. A hook that returns *more* edges than it was
    given is refused and counted, because those edges carry no resolver's
    evidence and this graph asserts nothing it cannot cite.
    """
    if not _HOOKS:
        return output
    for replacement in _fire("post_resolve", name, output, ctx):
        if replacement is None:
            continue
        if len(replacement.edges) > len(output.edges):
            ctx.count("hook.rejected_additions")
            logger.warning(
                "hook returned %d edges for %s where the resolver produced "
                "%d; hooks may veto, not invent",
                len(replacement.edges), name, len(output.edges))
            continue
        removed = len(output.edges) - len(replacement.edges)
        if removed:
            ctx.count("hook.suppressed_edges", removed)
        output = replacement
    return output


def on_decline(counter: str, n: int, ctx) -> None:
    global _firing
    if not _HOOKS or _firing:
        return
    _firing = True
    try:
        _fire("on_decline", counter, n, ctx)
    finally:
        _firing = False
