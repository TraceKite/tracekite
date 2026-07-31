"""The path algebra: how a public path becomes a service-local one.

One rule application is `strip N segments, then regex-rewrite` under a
longest-prefix guard; a resolution is a CHAIN of applications — edge
gateway to mesh to service — followed until the current target owns no
matching table. Both live here so NORMALIZE (I9: keys are final
before the join) has exactly one implementation of "what does this
gateway do to this path", instead of the two divergent copies it had.

Everything unresolvable declines loudly, never approximately: a cycle in
route tables is broken config and refuses the whole call; a chain deeper
than the cap is unresolved, not truncated; two same-length prefixes
naming different targets stop the chain at the last unambiguous hop.
(The old named-entry code silently took whichever tied rule was parsed
first — an arbitrary pick this module deliberately removes.)
"""

import re
from dataclasses import dataclass

_DEFAULT_MAX_HOPS = 3


@dataclass(frozen=True)
class ChainStep:
    gateway: str
    target: str
    template: str            # the path AFTER this hop
    evidence: tuple
    repo_id: str


@dataclass(frozen=True)
class Chain:
    service: str              # where the path finally lands
    template: str
    steps: tuple[ChainStep, ...] = ()

    @property
    def hops(self) -> int:
        return len(self.steps)

    def evidence(self) -> list[str]:
        return [e for step in self.steps for e in step.evidence]


def apply_rule(rule, template: str) -> str | None:
    """One rule to one path, or None when the rule does not claim it."""
    if not rule.prefix or not template.startswith(rule.prefix):
        return None
    rewritten = template
    if rule.strip_prefix > 0:
        segments = [s for s in rewritten.split("/") if s != ""]
        rewritten = "/" + "/".join(segments[rule.strip_prefix:])
    if rule.rewrite_pattern:
        try:
            rewritten = re.sub(rule.rewrite_pattern,
                               rule.rewrite_replacement, rewritten, count=1)
        except re.error:
            return None       # a broken pattern claims nothing
    return rewritten or "/"


def match_table(rules: list, template: str) -> object | None:
    """The winning rule of one gateway's table, or None.

    Longest prefix wins; a same-length tie naming different targets is
    genuine ambiguity and matches nothing — the caller counts it.
    Returns the literal string "ambiguous" for that case so the caller
    can tell it from "no route".
    """
    matching = [r for r in rules if r.prefix and
                template.startswith(r.prefix)]
    if not matching:
        return None
    longest = max(len(r.prefix) for r in matching)
    finalists = [r for r in matching if len(r.prefix) == longest]
    if len({r.target_name for r in finalists}) > 1:
        return "ambiguous"
    return finalists[0]


def resolve_chain(ctx, service: str, template: str,
                  max_hops: int | None = None) -> Chain | None:
    """Follow route tables from a named service until the path lands.

    Returns the final Chain, or None for the one unservable case — a
    cycle, which is broken config: any edge minted from it would assert
    a callee the tables never actually reach. Depth and ambiguity stop
    the chain at the last sound hop instead; the gateway itself IS a
    true callee, just not the final one.
    """
    cap = int(max_hops if max_hops is not None
              else ctx.confidence.get("gateway_chain_max_hops",
                                      _DEFAULT_MAX_HOPS))
    steps: list[ChainStep] = []
    seen = {service}
    while True:
        rules = ctx.rewrite_routes.get(service)
        rule = match_table(rules, template) if rules else None
        if rule is None:
            break                          # landed: no table claims the path
        if rule == "ambiguous":
            ctx.count("r7.gateway_chain_ambiguous")
            break
        if len(steps) >= cap:
            ctx.count("r7.gateway_chain_too_deep")
            break
        rewritten = apply_rule(rule, template)
        if rewritten is None:
            ctx.count("r7.gateway_rewrite_invalid")
            break
        target = ctx.canon(rule.target_name)
        if target in seen:
            ctx.count("r7.gateway_route_cycle")
            return None
        steps.append(ChainStep(gateway=service, target=target,
                               template=rewritten,
                               evidence=tuple(rule.evidence or []),
                               repo_id=rule.repo_id))
        seen.add(target)
        service, template = target, rewritten
        ctx.count("r7.gateway_rewrites")
    return Chain(service=service, template=template, steps=tuple(steps))
