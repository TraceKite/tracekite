"""The wire contract is published and frozen.

`schemas/evigraph-wire-<version>.json` is what a non-Python host validates
against. These tests are the enforcement half: the published file and the code
cannot drift, and the version cannot change without the filename changing with
it.

The policy, stated once and enforced here:

* **patch** — documentation, descriptions, nothing a reader parses.
* **minor** — a field added with a default. Old readers keep working.
* **major** — a field removed or renamed, a type narrowed, a required field
  added, or the meaning of a value changed. Each silently breaks a reader that
  is still doing the old thing, and a dependency that breaks quietly is worse
  than no dependency at all.

If a test here fails, the contract changed. Decide the bump deliberately, then
regenerate: `python -m evigraph.cli schema > schemas/evigraph-wire-<version>.json`.
"""

import json
import os
import re

from evigraph.wire import PUBLISHED, WIRE_VERSION, json_schemas

SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "schemas")
PUBLISHED_PATH = os.path.join(SCHEMA_DIR, f"evigraph-wire-{WIRE_VERSION}.json")


class TestPublished:
    def test_schema_file_exists_for_this_version(self):
        assert os.path.exists(PUBLISHED_PATH), (
            f"no published schema for {WIRE_VERSION}. Regenerate:\n"
            f"  python -m evigraph.cli schema > {PUBLISHED_PATH}")

    def test_published_file_matches_the_code(self):
        """The freeze. A model changed without republishing means a host
        validating against the file would reject output the CLI still emits."""
        with open(PUBLISHED_PATH, encoding="utf-8") as fh:
            published = json.load(fh)
        assert published == json_schemas(), (
            "wire contract drifted from its published schema — decide the "
            "SemVer bump (see this file's docstring), then regenerate")

    def test_filename_carries_the_version(self):
        """A schema whose version is only inside it cannot be fetched by
        version, and two versions cannot coexist on disk."""
        name = os.path.basename(PUBLISHED_PATH)
        match = re.fullmatch(r"evigraph-wire-(\d+\.\d+\.\d+)\.json", name)
        assert match and match.group(1) == WIRE_VERSION, name

    def test_version_is_semver(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", WIRE_VERSION), WIRE_VERSION


class TestPolicy:
    def test_every_published_model_is_in_the_schema(self):
        """A model a host can receive but cannot validate is unpublished in
        practice, whatever the docstring says."""
        assert set(json_schemas()["schemas"]) == set(PUBLISHED)

    def test_required_fields_are_declared_for_each_model(self):
        """A model with no required fields validates an empty object, which
        makes the schema decorative."""
        for name, schema in json_schemas()["schemas"].items():
            assert schema.get("required"), f"{name} requires nothing"

    def test_load_bearing_fields_stay_required(self):
        """These two are the contract's reason to exist: an edge that cannot
        be checked, or a report that hides what it declined, is the failure
        this project treats as worse than being wrong out loud. A future
        change making either optional is a major bump, and should have to
        delete this test to happen."""
        schemas = json_schemas()["schemas"]
        assert "evidence" in schemas["EdgeRecord"]["required"]
        assert "counters" in schemas["LinkReport"]["required"]
