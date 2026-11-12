"""Which workflow step must re-run first when a config path changes.

A step lists the config sections it reads. The earliest affected step is the first
one (by position in the sequence) whose section is a prefix of a changed path.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.steps.dependencies import earliest_affected_step


class StubStep:
    def __init__(self, name: str, sections: tuple[str, ...]) -> None:
        self.name = name
        self.config_sections = sections


def toy_pipeline() -> tuple[StubStep, ...]:
    return (
        StubStep("validate", ("workspace", "simulation")),
        StubStep("resolve", ("workspace", "simulation")),
        StubStep("build_geographic", ("geographic", "data.dem")),
        StubStep("load_data", ("data",)),
        StubStep("build_mesh", ("domain.supports",)),
        StubStep("setup_process", ("domain.depth_model", "flow.ic", "simulation")),
        StubStep("prepare_solver", ("flow", "transport", "solver")),
        StubStep("run_solver", ("flow", "transport", "solver")),
        StubStep("extract", ()),
    )


def test_multiple_paths_give_the_lowest_index() -> None:
    # "flow.param.K.field.value" hits step 6, "geographic.buff_area" hits step 2.
    paths = {"flow.param.K.field.value", "geographic.buff_area"}

    assert earliest_affected_step(paths, toy_pipeline()) == 2


def test_exact_section_match() -> None:
    assert earliest_affected_step({"flow"}, (StubStep("a", ("flow",)),)) == 0


def test_empty_section_never_matches() -> None:
    steps = (StubStep("a", ("", "flow")),)

    assert earliest_affected_step({"flow.k"}, steps) == 0
    with pytest.raises(ConfigError, match="no pipeline step reads"):
        earliest_affected_step({"nothing"}, steps)


def test_empty_override_paths_are_refused() -> None:
    with pytest.raises(ConfigError, match="at least one override path"):
        earliest_affected_step(set(), toy_pipeline())
