"""A calibrated parameter that re-runs nothing is a search over a constant.

Each trial re-runs the pipeline from the earliest step that consumes the
parameter's configuration path. A path no step declares matched nothing, and the
answer was "no step needs to re-run": the trial then evaluated the previous
model with a new number attached to it. Every trial returned the same cost, the
search converged on whatever it started from, and the report named a calibrated
value.

The mesh is the case that made it visible. ``[mesh_catchment]`` drives the mesh
step and the step did not say so, so calibrating a mesh resolution changed the
number in the record and nothing on disk.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.dependencies import earliest_affected_step
from hydromodpy.workflow.steps.mesh import BuildMeshStep


class _Step:
    def __init__(self, sections: tuple[str, ...]) -> None:
        self.config_sections = sections


_STEPS = (
    _Step(("workspace", "simulation")),
    _Step(("geographic", "data.dem")),
    _Step(("data",)),
    _Step(("domain.supports", "mesh_catchment", "mesh_input")),
    _Step(("flow", "transport")),
    _Step(()),
)


def test_a_path_a_step_owns_selects_that_step() -> None:
    assert earliest_affected_step({"flow.param.K.field.value"}, _STEPS) == 4


def test_a_mesh_path_selects_the_mesh_step() -> None:
    assert earliest_affected_step({"mesh_catchment.resolution"}, _STEPS) == 3


def test_a_path_no_step_owns_is_refused() -> None:
    with pytest.raises(ConfigError, match="no pipeline step"):
        earliest_affected_step({"flow.param.K.field.value", "nowhere.at.all"}, _STEPS)


def test_the_refusal_names_the_path_and_what_a_step_would_have_to_declare() -> None:
    with pytest.raises(ConfigError) as caught:
        earliest_affected_step({"nowhere.at.all"}, _STEPS)

    message = str(caught.value)
    assert "nowhere.at.all" in message
    assert "mesh_catchment" in message


def test_the_mesh_step_declares_the_sections_that_drive_it() -> None:
    """The step reads [mesh_catchment] and [mesh_input]; it has to say so."""
    declared = set(BuildMeshStep.config_sections)

    assert {"mesh_catchment", "mesh_input"} <= declared
