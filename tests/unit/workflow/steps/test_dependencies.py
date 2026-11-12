"""The step dependencies and the earliest affected step."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

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

    def test_exact_section_match_returns_step_index(self) -> None:
        steps = (_StubStep("a", ("flow",)),)
        assert earliest_affected_step({"flow"}, steps) == 0

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
