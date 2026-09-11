"""Every resolver has a labelled fixture exercising it.

F3 already enforces the finer grain — every priced TIER needs a measured
row, and the calibrate gate fails without one. What that cannot say is
that a whole resolver quietly has no estate at all if it also has no
priced tiers yet. This pins the coarse grain: every name in the shipped
roster maps to at least one labelled estate whose expectations exercise
its section, with the exemptions stated rather than implied.
"""

from tracekite.services.calibration import build_estates
from tracekite.services.linker.engine import resolver_order

# Roster name -> confidence section its tiers live under.
_SECTION_OF = {
    "r0_alias": "r0", "r1_compose": "r1", "r2_k8s": "r2",
    "r3_library": "r3", "r4_gateway": "r4", "r5_grpc": "r5",
    "r6_topic": "r6", "r7_http": "r7", "r8_graphql": "r8",
    "r9_env": "r9", "r10_dataset": "r10", "r11_agent": "r11",
    "r12_owner": "r12", "r13_webhook": "r13",
    "r14_operation": "r14",
}

# Stated, not skipped silently: this resolver emits no edges of its own —
# it builds the env-value broadcast table that R9 and R6 consume, and its
# correctness is measured through THEIR tiers.
_EXEMPT = {"r9_env_index": "broadcast side-table builder; measured through "
                           "r9.env_resolved and r6.env_resolved"}


def test_every_resolver_has_an_estate():
    covered = set()
    for estate in build_estates():
        for expectation in estate.expect:
            covered.add(expectation["tier"].split(".")[0])

    roster = [name for phase in ("broadcast", "join")
              for name, _m in resolver_order(phase)]
    missing = []
    for name in roster:
        if name in _EXEMPT:
            continue
        section = _SECTION_OF.get(name)
        assert section, (
            f"{name} is in the roster but not in this test's section map — "
            "a new resolver must be mapped or exempted WITH a reason")
        if section not in covered:
            missing.append(name)
    assert not missing, (
        f"resolver(s) with no labelled estate: {missing}. An unexercised "
        "resolver's precision is a number nobody measured.")


def test_exemptions_name_real_resolvers():
    """An exemption for a resolver that no longer exists is a stale claim."""
    roster = {name for phase in ("broadcast", "join")
              for name, _m in resolver_order(phase)}
    for name in _EXEMPT:
        assert name in roster, name
