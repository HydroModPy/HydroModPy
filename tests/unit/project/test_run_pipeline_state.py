"""The Pipeline receives everything the facade verbs used to read off the Project.

``build_mesh`` reads its mesh sections from the pipeline state, while
``Project.build_mesh`` read the same three off the Project. As long as the model
phase was built by the facade before the Pipeline started, the gap was invisible.
It stopped being invisible when the Pipeline took the model phase over: a state
missing those keys would mesh a project as if it declared no ``[mesh_catchment]``
and no ``[mesh_input]``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.workflow.internals.state import PipelineState

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "declared_name"

[[simulation.process]]
id = "flow"
type = "flow"
solvers = ["modflow_nwt"]

[workspace]
project_root = "{root}"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "{dem}"
x_outlet = 265611.933
y_outlet = 6784182.776
snap_dist = "50 m"
buff_area = "20%"

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[data]
types = []

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
value = "1e-5 m/s"

[mesh_catchment]
constraints_mode = "rivers_only"

[mesh_catchment.zone_meshing]
global_size = 350.0
min_size = 150.0
max_size = 800.0

[display]
enabled = false
"""


@pytest.fixture
def captured_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PipelineState:
    """Return the state ``ProjectRunner.run`` hands to the Pipeline."""
    from hydromodpy.project.facade import Project

    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )

    seen: list[PipelineState] = []

    class _Pipeline:
        def __init__(self, steps, *, workspace) -> None:
            self.steps = steps
            self.workspace = workspace

        def run(self, state, *, resume_from=None, parallel=True, model_phase_ready=False):
            seen.append(state)
            return state

    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)

    project = Project(config_path, no_display=True)
    project.simulate(name="asked_name")

    assert len(seen) == 1
    return seen[0]


def test_the_state_carries_the_declared_mesh_sections(captured_state: PipelineState) -> None:
    """``[mesh_catchment]`` reaches the step that builds the mesh."""
    section = captured_state.data["mesh_section_data"]

    assert section is not None, "the pipeline would mesh as if no section were declared"
    assert captured_state.data["constraints_mode"] == "rivers_only"
    assert captured_state.data["external_mesh_input"] is None


def test_the_state_carries_the_name_the_caller_asked_for(captured_state: PipelineState) -> None:
    """``run_setup`` derives a name from the config; the caller's name wins.

    ``[simulation] name`` says ``declared_name`` here and the caller asked for
    ``asked_name``. Letting the config win would register the run under a name
    its journal does not carry.
    """
    assert captured_state.data["run_name"] == "asked_name"
    assert captured_state.run_id == "asked_name"
