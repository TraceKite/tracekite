"""The source says true things about itself.

Two rules from AGENTS.md §7 that nothing enforced, and both failed silently:

**No tracker or task IDs in source.** Two CSVs tracked the build-out —
`engine-roadmap.csv` (ids A1..S1) and `coverage-roadmap.csv` (seq numbers
0.01..10.09) — and 340-odd comments cited their rows. Both are untracked
now, which makes every one of those citations a pointer to a file the
reader does not have; they were already pointing at finished work rather
than at the reason the code is shaped the way it is. The ids are frozen
below rather than read back, so this guard does not need them either.

**No stale self-reference.** The package was renamed `app` -> `adduce`. The
imports were all fixed, and `TestNoStaleSelfReference` pins them — but it
parses the AST, so it sees only `import` statements. The rename left
`python -m app.cli` in the CLI's own usage text, in the tree-sitter README's
examples, and in the error message telling a developer how to regenerate the
wire schema: three commands that had been failing for anyone who copied
them, in the places most likely to be copied.

The `I1`..`I10` collision is why the roadmap check skips the letter I:
architecture.md §6 numbers its invariants the same way, so `(I6)` is a
legitimate citation to Evidence completeness and `(I6)` is also roadmap row
"resource caps per phase". Banning the letter outright would delete the
normative half.
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

# The roadmap CSVs are untracked now, so this list is the record of what a
# citation would have pointed at. It is frozen, not a snapshot: the roadmap
# closed at 89/89, so no id can ever join it. Reading the CSVs instead would
# make the guard pass silently on any clone that does not have them, which
# is the failure this project treats as worse than being wrong out loud.
ROADMAP_IDS = frozenset({
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11",
    "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11",
    "B12", "B13", "B14", "B15", "C1", "C2", "C3", "C4", "C5", "C6",
    "C7", "C8", "C9", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8",
    "E1", "E2", "E3", "E4", "E5", "E6", "E7", "F1", "F2", "F3", "F4",
    "F5", "F6", "G1", "G2", "G3", "G4", "G5", "G6", "H1", "H2", "H3",
    "H4", "H5", "H6", "H7", "H8", "I1", "I2", "I3", "I4", "I5", "I6",
    "I7", "J1", "J2", "J3", "J4", "J5", "J6", "J7", "K1", "K2", "K3",
    "Q1", "S1",
})
# Prose counts. The first version of this guard scanned code only, and every
# stale `app.` reference it would have caught was sitting in a document
# instead: a migration guide whose examples all imported `app.db`, the
# accuracy README, architecture.md twice.
_SCAN_ROOTS = ("backend", "backend/adduce", "backend/tools", "backend/tests",
               "frontend/src", "lib", "docs", "scripts", "config", "corpus",
               "packaging", "plugins", "schemas", ".github",
               ".agents/plugins", ".claude-plugin")
# The rules and the front page are prose that describes this repository, so
# they are held to the same standard as the code they describe.
_SCAN_ROOT_FILES = ("README.md", "AGENTS.md", "CONTRIBUTING.md", "CLAUDE.md")
_SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".md", ".yml", ".yaml",
                  ".toml", ".json", ".sh", ".dockerfile"}
_SKIP = ("__pycache__", "node_modules", "components/ui/", "generated/",
         "/dist/", "/fixtures/")

# `(row 7.14)`, `(rows 6.04, 6.05)`, `(roadmap M8 rows 7.10-7.16)`, and the
# label form `Row 6.09:` that opens a docstring.
_SEQ_CITATION = re.compile(
    r"\((?:roadmap\s+)?(?:M\d+\s+)?rows?\s+\d+\.\d+[^)]*\)"
    r"|\(roadmap\s+row\s+M\d+\s+\d+\.\d+\)"
    r"|(?:^|[^A-Za-z])Rows?\s+\d+\.\d+(?=[\s:.,—-])",
    re.MULTILINE)

# `(A4)`, `(F1, F2)`, `(C8/E1)`. The letter I is excluded deliberately.
_ID_CITATION = re.compile(r"\(([A-HJKQS]\d{1,2}(?:\s*[,/]\s*[A-HJKQS]\d{1,2})*)\)")

_STALE_DOTTED = re.compile(r"\bapp\.[a-z_]+(?:\.[a-z_]+)*")
_STALE_PATH = re.compile(r"\bapp/[A-Za-z0-9_./$-]+")

# Two files name these patterns on purpose: this one quotes them as examples,
# and `test_distribution_namespace` asserts the old package name is absent,
# which it cannot do without writing it down.
_QUOTES_THE_PATTERN = {"test_source_hygiene.py",
                       "test_distribution_namespace.py"}


def sources() -> list[pathlib.Path]:
    """Every hand-written source file, vendored and generated trees excluded."""
    found: list[pathlib.Path] = []
    for root in _SCAN_ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            if path.suffix not in _SCAN_SUFFIXES or not path.is_file():
                continue
            posix = path.as_posix()
            if any(skip in posix for skip in _SKIP):
                continue
            found.append(path)
    for name in _SCAN_ROOT_FILES:
        path = REPO / name
        if path.is_file():
            found.append(path)
    return found


def label(path: pathlib.Path) -> str:
    return path.relative_to(REPO).as_posix()


class TestNoTrackerIds:
    def test_no_file_cites_a_coverage_roadmap_row(self):
        offenders = []
        for path in sources():
            if path.name in _QUOTES_THE_PATTERN:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _SEQ_CITATION.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{label(path)}:{line}: {match.group().strip()}")
        assert not offenders, (
            "coverage-roadmap.csv row citations in source (AGENTS.md §7 "
            f"bans tracker ids):\n  " + "\n  ".join(offenders))

    def test_no_file_cites_an_engine_roadmap_id(self):
        known = ROADMAP_IDS
        offenders = []
        for path in sources():
            if path.name in _QUOTES_THE_PATTERN:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _ID_CITATION.finditer(text):
                cited = [part.strip()
                         for part in re.split(r"[,/]", match.group(1))]
                if not any(part in known for part in cited):
                    continue        # a coincidence, not a citation
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{label(path)}:{line}: {match.group()}")
        assert not offenders, (
            "engine-roadmap.csv id citations in source (AGENTS.md §7 "
            f"bans tracker ids):\n  " + "\n  ".join(offenders))


class TestNoStaleSelfReferenceInProse:
    """The AST check covers imports; this covers everything else.

    A stale `app.cli` in a docstring is worse than a stale import, because
    an import fails loudly on the next run and a usage example fails only
    for the reader who trusted it.
    """

    def test_no_file_names_the_old_package_in_a_dotted_path(self):
        offenders = []
        for path in sources():
            if path.name in _QUOTES_THE_PATTERN:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _STALE_DOTTED.finditer(text):
                head = match.group().split(".")[1]
                if not (REPO / "backend" / "adduce" / head).exists() and \
                        not (REPO / "backend" / "adduce" / f"{head}.py").exists():
                    continue                  # some other project's `app.x`
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{label(path)}:{line}: {match.group()}")
        assert not offenders, (
            "the package is `adduce`; these still say `app`:\n  "
            + "\n  ".join(offenders))

    def test_no_file_names_a_path_that_is_really_this_package(self):
        """`app/routes/_index.tsx` is Remix and `app/models/o.rb` is Rails;
        `app/services/claims.py` is this package under its old name. The
        difference is whether the file exists under `backend/adduce/`."""
        offenders = []
        for path in sources():
            if path.name in _QUOTES_THE_PATTERN:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _STALE_PATH.finditer(text):
                rest = match.group().split("/", 1)[1].rstrip(".,;:)— ")
                if not (REPO / "backend" / "adduce" / rest).exists():
                    continue                  # fixture data, not us
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{label(path)}:{line}: {match.group()}")
        assert not offenders, (
            "the package directory is `backend/adduce/`; these still say "
            "`app/`:\n  " + "\n  ".join(offenders))


class TestTheGuardsSeeSomething:
    """A scanner over an empty file list passes every assertion above."""

    def test_it_scans_the_source_it_claims_to(self):
        paths = sources()
        assert len(paths) > 300, f"only {len(paths)} files scanned"
        names = {label(p) for p in paths}
        assert "backend/adduce/cli.py" in names               # production
        assert "backend/tests/test_source_hygiene.py" in names  # tests
        assert not any("components/ui/" in str(p) for p in paths)  # vendored
        assert not any("generated/" in str(p) for p in paths)

    def test_the_roadmap_ids_are_actually_there(self):
        """An empty set would make the id check pass on everything."""
        assert len(ROADMAP_IDS) == 89
        assert "A4" in ROADMAP_IDS and "B14" in ROADMAP_IDS

    @pytest.mark.parametrize("citation", [
        "(row 7.14)", "(rows 6.04, 6.05)", "(roadmap M8 rows 7.10-7.16)",
        "Row 6.09: a docstring label",
    ])
    def test_the_seq_pattern_matches_every_shape_seen(self, citation):
        assert _SEQ_CITATION.search(citation)

    def test_the_id_pattern_leaves_architecture_invariants_alone(self):
        """`(I6)` is Evidence completeness, not roadmap row I6."""
        assert not _ID_CITATION.search("keys are final before the join (I9)")
        assert _ID_CITATION.search("the published wire contract (A4)")
