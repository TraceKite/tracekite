"""The overview sample reserves its budget for architecture before leaves."""

import pytest

from evigraph.services.graph_reader import VIEW_MODES


BROAD_MODES = ("overview", "architecture", "code", "api", "dependencies")


def test_overview_prioritizes_structure_before_dependencies():
    priority = VIEW_MODES["overview"]["priority"]
    for node_type in ("Repo", "Folder", "File", "Class", "ApiEndpoint"):
        assert priority[node_type] < priority["Dependency"]
    assert priority["ApiEndpoint"] < priority["File"]


def test_dependency_view_still_prioritizes_dependencies():
    priority = VIEW_MODES["dependencies"]["priority"]
    assert priority["Dependency"] < priority["File"]


@pytest.mark.parametrize("mode", BROAD_MODES)
def test_every_broad_view_has_a_bounded_typed_contract(mode):
    config = VIEW_MODES[mode]
    assert config["node_types"]
    assert config["edge_types"]
    assert 0 < config["limit"] <= 500
    assert set(config["node_types"]) <= set(config["priority"])
    assert "RELATED_TO" not in config["edge_types"]


def test_view_modes_are_semantically_distinct():
    assert "CALLS" in VIEW_MODES["code"]["edge_types"]
    assert "ApiEndpoint" in VIEW_MODES["api"]["node_types"]
    assert "Dependency" in VIEW_MODES["dependencies"]["node_types"]
    assert "DEPENDS_ON" in VIEW_MODES["dependencies"]["edge_types"]
    assert VIEW_MODES["impact"]["node_types"] == []
    assert VIEW_MODES["impact"]["edge_types"] == []
