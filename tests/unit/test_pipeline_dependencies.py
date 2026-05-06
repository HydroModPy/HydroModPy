"""Unit tests for :mod:`hydromodpy.workflow.internals.dependencies`.

Covers the longest-prefix matcher used by calibration to decide which
step must re-run first when a parameter override lands deep in the
config tree.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.dependencies import earliest_affected_step
from hydromodpy.workflow.orchestrator import standard_steps


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
        never spuriously match.
        """
        steps = (_StubStep("a", ("flow",)),)
        # Should not match: "flow_rate" is not a descendant of "flow"
        assert earliest_affected_step({"flow_rate.value"}, steps) == 1

    def test_exact_section_match_returns_step_index(self) -> None:
        steps = (_StubStep("a", ("flow",)),)
        assert earliest_affected_step({"flow"}, steps) == 0

    def test_no_match_returns_len_steps(self) -> None:
        steps = _toy_pipeline()
        # "nonexistent" doesn't match any section in the toy pipeline
        idx = earliest_affected_step({"nonexistent.path"}, steps)
        assert idx == len(steps)

    def test_empty_section_never_matches(self) -> None:
        steps = (_StubStep("a", ("", "flow")),)
        # Only "flow" section can ever match
        assert earliest_affected_step({"nothing"}, steps) == 1
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
