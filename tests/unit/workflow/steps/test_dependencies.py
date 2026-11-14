"""Which workflow step must re-run first when a config path changes.

A step lists the config sections it reads. The earliest affected step is the first
one (by position in the sequence) whose section is a prefix of a changed path, or
lies under it. A `*` key of a section stands for any id of a table.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.steps.dependencies import earliest_affected_step, section_value
from hydromodpy.workflow.steps.sequence import standard_steps


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


def _first_step_of(path: str) -> str:
    steps = standard_steps()
    return steps[earliest_affected_step({path}, steps)].name


@pytest.mark.parametrize(
    ("path", "step"),
    [
        ("flow.sinks_sources.lakes", "load_data"),
        ("flow.sinks_sources.lakes.pond", "load_data"),
        ("flow.sinks_sources.lakes.pond.enabled", "load_data"),
        ("flow.sinks_sources.lakes.pond.cutoff_wall", "load_data"),
        ("flow.sinks_sources.lakes.pond.cutoff_wall.line_path", "load_data"),
        ("flow.sinks_sources.lakes.pond.cutoff_wall.snap_tolerance", "load_data"),
        ("flow.sinks_sources.flow_barriers.dam.enabled", "load_data"),
        ("flow.sinks_sources.flow_barriers.dam.line", "load_data"),
        ("flow.bc.stream", "build_mesh"),
        ("flow.bc.stream.enabled", "build_mesh"),
        ("flow.param.K.field.kind", "build_mesh"),
        ("flow.param.K.field.field_spatial_id", "build_mesh"),
        ("flow.sinks_sources.sfr.net0.enabled", "prepare_solver"),
    ],
)
def test_a_lake_a_wall_a_barrier_or_a_stream_switch_rebuilds_the_mesh(path: str, step: str) -> None:
    assert _first_step_of(path) == step


@pytest.mark.parametrize(
    ("path", "step"),
    [
        ("flow.param.K.field.value", "prepare_solver"),
        ("flow.param.Sy.field.value", "prepare_solver"),
        ("flow.param.Ss.field.value", "prepare_solver"),
        ("flow.param.Kh.field.value", "prepare_solver"),
        ("flow.bc.drainage.value", "prepare_solver"),
        ("flow.bc.stream.value", "prepare_solver"),
        ("flow.sinks_sources.lakes.pond.bedleak", "prepare_solver"),
        ("flow.sinks_sources.lakes.pond.cutoff_wall.k", "prepare_solver"),
        ("flow.sinks_sources.lakes.pond.cutoff_wall.thickness", "prepare_solver"),
        ("flow.sinks_sources.flow_barriers.dam.hydchr", "prepare_solver"),
        ("flow.sinks_sources.sfr.net0.streambed_k", "prepare_solver"),
        ("flow.sinks_sources.recharge.factor", "prepare_solver"),
        ("flow.sinks_sources.wells.W1.flux", "prepare_solver"),
        ("solver.leaky_barrier.bedleak", "prepare_solver"),
        ("domain.depth_model.thickness", "setup_process"),
    ],
)
def test_a_calibrated_parameter_keeps_the_mesh(path: str, step: str) -> None:
    assert _first_step_of(path) == step


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("flow.sinks_sources.lakes.*.enabled", {"pond": False, "lac": True}),
        ("flow.sinks_sources.lakes.pond", {"enabled": False}),
        ("flow.sinks_sources.wells.*.enabled", None),
        ("flow.sinks_sources.lakes.*", {"pond": {"enabled": False}, "lac": {"enabled": True}}),
    ],
)
def test_section_value_reads_every_id_under_a_star(section: str, value: object) -> None:
    document = {
        "flow": {"sinks_sources": {"lakes": {"pond": {"enabled": False}, "lac": {"enabled": True}}}}
    }
    assert section_value(document, section) == value
