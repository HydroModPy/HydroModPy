"""Tests for :class:`hydromodpy.project.state.ProjectState` and its proxy."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.project.facade import Project
from hydromodpy.project.state import PROJECT_ATTR_TO_STATE_FIELD, ProjectState

pytestmark = pytest.mark.fast


def _bare_project() -> Project:
    """Return a Project instance without running ``__init__``.

    Useful to verify the proxy mechanism in isolation without paying the cost
    of a full geographic/data/mesh setup.
    """
    project = object.__new__(Project)
    object.__setattr__(project, "_state", ProjectState())
    return project


def test_project_state_fields_match_mapping() -> None:
    """Every state attribute exposed through ``project.<name>`` maps to a real field."""
    state_fields = set(ProjectState.__dataclass_fields__)
    for project_name, state_field in PROJECT_ATTR_TO_STATE_FIELD.items():
        assert state_field in state_fields, (
            f"PROJECT_ATTR_TO_STATE_FIELD[{project_name!r}] -> {state_field!r} "
            f"is not declared on ProjectState"
        )


def test_project_state_mapping_covers_all_known_attrs() -> None:
    """The proxy mapping covers the 21 attributes formerly set on Project."""
    expected = {
        "_config_path",
        "_cfg",
        "_solver",
        "_time_grid",
        "_headless",
        "_no_display",
        "_mesh_section_data",
        "_external_mesh_input",
        "_mesh_constraints_mode",
        "_spatial_support_registry",
        "_requested_support_ids",
        "_requested_domain_supports",
        "_ctx",
        "_store",
        "_project_name",
        "_run_counter",
        "_active_runs",
        "_last_wall_seconds",
        "_phase",
        "_data_loaded",
        "_run_history",
    }
    assert set(PROJECT_ATTR_TO_STATE_FIELD) == expected


def test_setattr_routes_known_fields_to_state() -> None:
    """Setting a proxied attribute updates ``_state`` and not ``__dict__``."""
    project = _bare_project()
    project._config_path = Path("/tmp/example.toml")
    project._cfg = "fake_cfg"
    project._run_counter = 7

    assert "_config_path" not in project.__dict__
    assert "_cfg" not in project.__dict__
    assert "_run_counter" not in project.__dict__
    assert project._state.config_path == Path("/tmp/example.toml")
    assert project._state.cfg == "fake_cfg"
    assert project._state.run_counter == 7


def test_getattr_reads_state_for_proxied_names() -> None:
    """Reading a proxied attribute returns the corresponding ``_state`` field."""
    project = _bare_project()
    project._state.config_path = Path("/tmp/x.toml")
    project._state.cfg = {"k": "v"}

    assert project._config_path == Path("/tmp/x.toml")
    assert project._cfg == {"k": "v"}


def test_setattr_keeps_unknown_attrs_directly_on_instance() -> None:
    """Attribute names outside the mapping remain on ``Project.__dict__``."""
    project = _bare_project()
    project._runner = "fake_runner"
    project._catalog = "fake_catalog"

    assert project.__dict__["_runner"] == "fake_runner"
    assert project.__dict__["_catalog"] == "fake_catalog"


def test_getattr_raises_for_unknown_names() -> None:
    """``__getattr__`` raises ``AttributeError`` for unmapped private names."""
    project = _bare_project()
    with pytest.raises(AttributeError, match="_not_a_state_field"):
        _ = project._not_a_state_field


def test_project_state_defaults_match_phases_configure_defaults() -> None:
    """The dataclass defaults match the initial values set by ``phases.configure``."""
    state = ProjectState()
    assert state.config_path is None
    assert state.cfg is None
    assert state.solver is None
    assert state.time_grid is None
    assert state.headless is False
    assert state.no_display is False
    assert state.mesh_section_data is None
    assert state.external_mesh_input is None
    assert state.mesh_constraints_mode is None
    assert state.spatial_support_registry is None
    assert state.requested_support_ids == ()
    assert state.requested_domain_supports == {}
    assert state.ctx is None
    assert state.store is None
    assert state.project_name is None
    assert state.run_counter == 0
    assert state.active_runs == {}
    assert state.last_wall_seconds == {}
    assert state.phase == "uninitialized"
    assert state.data_loaded == set()
    assert state.run_history == []
