"""The step dependencies and the earliest affected step."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.steps.dependencies import earliest_affected_step
from hydromodpy.workflow.steps.sequence import standard_steps

# --- test_pipeline_dependencies ---
# Unit tests for :mod:`hydromodpy.workflow.steps.dependencies`.
#
# Covers the longest-prefix matcher used by calibration to decide which
# step must re-run first when a parameter override lands deep in the
# config tree.


class _StubStep:
    """Minimal step-shaped object for the dependency matcher."""

    def __init__(self, name: str, sections: tuple[str, ...]) -> None:
        self.name = name
        self.config_sections = sections


def _toy_pipeline() -> tuple[_StubStep, ...]:
    """Miniature pipeline that exercises the prefix matcher without loading
    the full hydromodpy stack."""
    return (
        _StubStep("validate", ("workspace", "simulation")),
        _StubStep("resolve", ("workspace", "simulation")),
        _StubStep("build_geographic", ("geographic", "data.dem")),
        _StubStep("load_data", ("data",)),
        _StubStep("build_mesh", ("domain.supports",)),
        _StubStep("setup_process", ("domain.depth_model", "flow.ic", "simulation")),
        _StubStep("prepare_solver", ("flow", "transport", "solver")),
        _StubStep("run_solver", ("flow", "transport", "solver")),
        _StubStep("extract", ()),
    )


class TestEarliestAffectedStep:
    def test_flow_param_matches_flow_prefix_at_step_06(self) -> None:
        steps = _toy_pipeline()
        idx = earliest_affected_step(
            {"flow.param.K.field.value"},
            steps,
        )
        assert idx == 6  # prepare_solver

    def test_geographic_override_lands_on_build_geographic(self) -> None:
        steps = _toy_pipeline()
        idx = earliest_affected_step({"geographic.buff_area"}, steps)
        assert idx == 2

    def test_domain_supports_cell_size_hits_build_mesh(self) -> None:
        steps = _toy_pipeline()
        idx = earliest_affected_step({"domain.supports.cell_size"}, steps)
        assert idx == 4

    def test_multiple_paths_returns_lowest_index(self) -> None:
        steps = _toy_pipeline()
        idx = earliest_affected_step(
            {
                "flow.param.K.field.value",  # hits step 6
                "geographic.buff_area",  # hits step 2
            },
            steps,
        )
        assert idx == 2

    def test_dotted_section_matches_exact_only_with_boundary(self) -> None:
        """`flow_rate` must NOT match the section `flow`.

        The matcher uses ``path.startswith(section + ".")`` so that
        sibling names that share a prefix (``flow`` vs ``flow_rate``)
        never spuriously match. A path that matches nothing is refused, which
        is how the near-miss is told apart from a hit.
        """
        steps = (_StubStep("a", ("flow",)),)
        with pytest.raises(ConfigError, match="no pipeline step reads"):
            earliest_affected_step({"flow_rate.value"}, steps)

    def test_exact_section_match_returns_step_index(self) -> None:
        steps = (_StubStep("a", ("flow",)),)
        assert earliest_affected_step({"flow"}, steps) == 0

    def test_a_path_no_step_reads_is_refused(self) -> None:
        """Nothing would re-run, so every trial would score the same model."""
        steps = _toy_pipeline()
        with pytest.raises(ConfigError, match="nonexistent.path"):
            earliest_affected_step({"nonexistent.path"}, steps)

    def test_the_refusal_lists_what_a_step_does_read(self) -> None:
        steps = (_StubStep("a", ("flow",)),)
        with pytest.raises(ConfigError, match="flow"):
            earliest_affected_step({"nowhere"}, steps)

    def test_empty_section_never_matches(self) -> None:
        steps = (_StubStep("a", ("", "flow")),)
        # Only "flow" section can ever match
        with pytest.raises(ConfigError, match="no pipeline step reads"):
            earliest_affected_step({"nothing"}, steps)
        assert earliest_affected_step({"flow.k"}, steps) == 0

    def test_empty_override_paths_raises(self) -> None:
        steps = _toy_pipeline()
        with pytest.raises(ConfigError, match="at least one override path"):
            earliest_affected_step(set(), steps)


class TestStandardStepsAreAnnotated:
    """Ensure every shipped step declares its ``config_sections``."""

    def test_every_standard_step_has_config_sections(self) -> None:
        for step in standard_steps():
            assert hasattr(step, "config_sections"), step.name
            assert isinstance(step.config_sections, tuple), step.name

    def test_flow_section_hits_prepare_solver(self) -> None:
        """Integration check against the real standard pipeline."""
        steps = standard_steps()
        idx: ClassVar[int] = earliest_affected_step(
            {"flow.param.K.field.value"},
            steps,
        )
        # prepare_solver is step index 6 in the canonical sequence
        assert steps[idx].name == "prepare_solver"


# --- test_a_trial_moves_the_aquifer_geometry ---
# A trial that moves the thickness solves the thickness it moved.
#
# The calibration prefix builds the domain once and every trial forks from it,
# sharing the domain by reference. ``setup_process`` owns ``domain.depth_model``,
# so a trial that moves the thickness re-runs from there; until it rebuilt the
# substratum, it re-ran a step that never read the value, and every trial solved
# the geometry of the prefix under a different number.
#
# The project below is synthetic, so no terrain engine runs, and the check stops
# at the solver grid: no binary is needed to read ``botm``.


def _index_of(name: str) -> int:
    return next(i for i, step in enumerate(standard_steps()) if step.name == name)


@pytest.mark.parametrize(
    "path", ["domain.depth_model.thickness", "domain.depth_model.substratum_elevation"]
)
def test_moving_the_geometry_re_runs_from_setup_process(path: str) -> None:
    assert earliest_affected_step([path], standard_steps()) == _index_of("setup_process")


@pytest.mark.parametrize(
    "path", ["domain.depth_model.thickness", "domain.depth_model.substratum_elevation"]
)
def test_the_mesh_guard_lets_the_geometry_through(path: str) -> None:
    space = ParameterSpace.from_toml_mapping({"h": {"bounds": [5.0, 300.0], "path": path}})

    assert space.parameters[0].effective_path == path
