"""Reading an artifact written by an older engine.

An artifact outlives the code that wrote it. A CI job publishes one today and
a compaction reads it next month, by which time the wire contract may have
moved — so "refuse everything that is not exactly current" is too strict, and
"read anything and hope" is far too loose.

The SemVer policy in `wire.py` already decides which is which:

* **minor** — a field was added with a default. An older artifact is missing
  it, and the default is known, so it can be filled in. Migrating is safe
  because nothing that was there has changed meaning.
* **major** — a field was removed or renamed, a type narrowed, or the meaning
  of a value changed. There is no honest way to fill that in, so it is
  refused and named.

Migrations are declared, never inferred. A version with no registered
migration is refused rather than passed through: silently reading a shape
nobody wrote a migration for is how a compaction ends up mixing two contracts
and reporting neither.
"""

from adduce.wire import WIRE_VERSION


class UnmigratableArtifact(RuntimeError):
    """The artifact cannot be read by this engine, and why."""


def _parse(version: str) -> tuple[int, int, int]:
    try:
        major, minor, patch = (int(p) for p in version.split("."))
    except (ValueError, AttributeError) as exc:
        raise UnmigratableArtifact(
            f"unreadable wire version {version!r}") from exc
    return major, minor, patch


# (from_major, from_minor) -> callable(meta) -> meta.
#
# Each entry moves an artifact forward exactly one minor step, so a chain of
# them can carry an old artifact to the current version without any single
# migration needing to know the whole history.
MIGRATIONS: dict[tuple[int, int], callable] = {}


def register_migration(from_major: int, from_minor: int):
    """Declare how to carry an artifact one minor version forward."""
    def wrap(fn):
        MIGRATIONS[(from_major, from_minor)] = fn
        return fn
    return wrap


def can_read(version: str) -> tuple[bool, str]:
    """Whether this engine can read that artifact, and why not if it cannot.

    Returns a reason rather than just False: a compaction that skips an
    artifact must be able to say what was skipped and why, or an operator
    sees an index that looks complete.
    """
    try:
        major, minor, _ = _parse(version)
    except UnmigratableArtifact as exc:
        return False, str(exc)

    current_major, current_minor, _ = _parse(WIRE_VERSION)

    if major != current_major:
        return False, (
            f"wire {version} is a different major version than "
            f"{WIRE_VERSION}: a field was removed, renamed, or changed "
            "meaning, and there is no honest way to fill that in")
    if minor > current_minor:
        return False, (
            f"wire {version} is newer than {WIRE_VERSION}; this engine does "
            "not know what was added and would read it as absent")

    step = minor
    while step < current_minor:
        if (major, step) not in MIGRATIONS:
            return False, (
                f"no declared migration from {major}.{step}; refusing rather "
                "than passing an unknown shape through")
        step += 1
    return True, ""


def migrate(meta: dict) -> dict:
    """Carry an artifact's metadata forward to the current wire version.

    Applies one minor step at a time. Raises rather than returning a partially
    migrated dict: half-migrated metadata is worse than none, because it looks
    readable.
    """
    version = meta.get("wire_version", "")
    readable, reason = can_read(version)
    if not readable:
        raise UnmigratableArtifact(reason)

    major, minor, _ = _parse(version)
    _, current_minor, _ = _parse(WIRE_VERSION)

    migrated = dict(meta)
    while minor < current_minor:
        migrated = MIGRATIONS[(major, minor)](migrated)
        minor += 1
    migrated["wire_version"] = WIRE_VERSION
    return migrated


# --- declared migrations ----------------------------------------------------


@register_migration(1, 0)
def _v1_0_to_v1_1(meta: dict) -> dict:
    """1.1 added `absence`: what a scan looked for and did not find.

    A 1.0 artifact never recorded it, and the honest default is not an empty
    report — an empty report would claim the scan was complete and found
    nothing, which is precisely the implied absence C5 exists to remove. So
    the migrated value says outright that the question was not asked.
    """
    return {**meta, "absence": {
        "complete": False,
        "incomplete_because": [
            "written by wire 1.0, which did not record what was searched"],
        "kinds_found": [], "kinds_absent": [],
        "absence_is_evidence": False,
    }}


@register_migration(1, 1)
def _v1_1_to_v1_2(meta: dict) -> dict:
    """1.2 added `HistoryReport`, which is a report, not artifact metadata.

    Nothing an artifact stores changed, so a 1.1 artifact is already a valid
    1.2 artifact and this returns it untouched. Declared anyway rather than
    special-cased in `can_read`: the chain refuses a version with no
    registered migration on purpose, and "this step needs nothing" is a claim
    somebody should have to write down.
    """
    return dict(meta)


@register_migration(1, 2)
def _v1_2_to_v1_3(meta: dict) -> dict:
    """1.3 added report models (deprecations, consumer history) — reports,
    not artifact metadata, so a 1.2 artifact is already a valid 1.3 one.
    Declared as a no-op for the same reason 1.1 -> 1.2 was: the chain
    refuses undeclared steps on purpose."""
    return dict(meta)
