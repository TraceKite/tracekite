"""Classify a host the estate calls but does not own.

A call to `api.stripe.com` is *qualified* — the source names a host — but no
internal service answers it, so the join declines and the call disappears into
an anonymous counter. That reads exactly like a broken internal call, and it
hides a real dependency: a Stripe outage breaks the same consumers an internal
outage would.

**Classifying is not linking.** Nothing here emits an edge. It turns an
anonymous decline into a named one, so "three services call Stripe" becomes a
countable fact rather than an absence. Precision is untouched by construction:
this code only ever runs where the resolver has already decided not to match.

The catalog lives in `config/vendor_catalog.yml` because it is exactly the
kind of thing an operator extends — every estate calls a different set.
"""

import logging
import os
from dataclasses import dataclass

import yaml

from adduce.services.linker.base import config_dir

logger = logging.getLogger(__name__)

CATALOG_FILE = "vendor_catalog.yml"


@dataclass(frozen=True)
class Vendor:
    name: str
    category: str


def load_vendors(path: str | None = None) -> dict[str, Vendor]:
    """Host suffix -> vendor. Missing catalog is not an error.

    Unlike `confidence.yml`, an absent catalog degrades to "classify nothing"
    rather than refusing to run: a missing confidence table would make every
    edge's score a guess, but a missing catalog only costs labels on calls
    that were already being declined.
    """
    target = path or os.path.join(config_dir(), CATALOG_FILE)
    try:
        with open(target, encoding="utf-8") as handle:
            table = yaml.safe_load(handle) or {}
    except OSError:
        logger.debug("No vendor catalog at %s; external hosts stay unnamed",
                     target)
        return {}

    by_suffix: dict[str, Vendor] = {}
    for name, spec in (table.get("vendors") or {}).items():
        vendor = Vendor(name=str(name),
                        category=str((spec or {}).get("category", "")))
        for suffix in (spec or {}).get("suffixes") or []:
            by_suffix[str(suffix).lower()] = vendor
    return by_suffix


def classify(host: str, by_suffix: dict[str, Vendor]) -> Vendor | None:
    """The vendor owning `host`, or None.

    Longest suffix wins, so `files.stripe.com` is not shadowed by a shorter
    entry someone adds later. A host matching nothing returns None and is
    counted as unknown-external rather than guessed at — naming it after the
    nearest vendor would be inventing a dependency.
    """
    if not host or not by_suffix:
        return None
    candidate = host.strip().lower().rstrip("/")
    for suffix in sorted(by_suffix, key=len, reverse=True):
        if candidate == suffix or candidate.endswith(suffix):
            return by_suffix[suffix]
    return None


# Tails that mean "inside the cluster", whatever precedes them. Checked at
# any depth: `billing.default.svc` and `billing.default.svc.cluster.local`
# are the same internal service wearing more labels.
_INTERNAL_TAILS = frozenset({
    "local", "internal", "svc", "cluster", "localdomain", "lan", "intranet",
})


def looks_external(host: str) -> bool:
    """Whether a name is a routable host rather than an internal service name.

    A dotted name with a public-looking tail is a host; `billing`,
    `order-service` and `billing.default.svc` are not. Deliberately
    conservative in that direction — misreading an internal name as external
    files a genuine missing edge under "third party", where nobody will look
    for it again.
    """
    if not host:
        return False
    candidate = host.strip().lower().split("?")[0].rstrip("/")
    parts = [p for p in candidate.split(".") if p]
    if len(parts) < 2:
        return False
    if any(part in _INTERNAL_TAILS for part in parts[1:]):
        return False
    tail = parts[-1]
    return tail.isalpha() and len(tail) >= 2
