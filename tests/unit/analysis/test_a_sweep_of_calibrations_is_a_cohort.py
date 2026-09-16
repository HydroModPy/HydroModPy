"""A structural sweep is a cohort of complete calibrations, compared not ranked.

Refining a mesh and keeping the conductivity that scored best is circular: the
stream-network criterion is normalised by cell size, so the search improves the
number by changing the yardstick. The answer is a cohort: one complete
calibration per mesh, each with its own plan, reported side by side and read for
convergence.

The mechanism for that already exists and is not a second one to build. A
comparison materialises one child TOML per cell and runs it through ``hmp run``,
which dispatches on ``[workflow] mode``. A cell whose overlay declares
``mode = "calibration"`` is therefore a complete calibration, and the cohort
reader compares the cells without ranking them by cost. These tests pin that,
because it is the property the refusal in
``ParameterSpace.from_toml_mapping`` points users at.
"""

from __future__ import annotations

import textwrap
import tomllib
from pathlib import Path

import pytest

_BASE = """
[workspace]
project_root = "."

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

[[simulation.process]]
type = "flow"
solver = "modflow6"

[flow]
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5
"""

_SWEEP = """
[workflow]
mode = "comparison"

[comparison]
comparison_id = "mesh_convergence"
base_simulation_config = "project.toml"
output_root = "outputs/mesh_convergence"
reference_simulation = "mesh_250"

[[comparison.observable]]
name = "seepage_map_last"
variable = "seepage_areas"
support = "map"
time = "last"
unit = "-"

[[comparison.simulation]]
id = "mesh_500"
label = "target cell size 500 m"
solver = "modflow6"

[comparison.simulation.overlay.workflow]
mode = "calibration"

[comparison.simulation.overlay.mesh_catchment.zone_meshing]
global_size = 500.0

[comparison.simulation.overlay.calibration]
method = "grid"
max_iter = 4

[comparison.simulation.overlay.calibration.parameters.K]
bounds = [1e-7, 1e-3]

[[comparison.simulation]]
id = "mesh_250"
label = "target cell size 250 m"
solver = "modflow6"

[comparison.simulation.overlay.workflow]
mode = "calibration"

[comparison.simulation.overlay.mesh_catchment.zone_meshing]
global_size = 250.0

[comparison.simulation.overlay.calibration]
method = "grid"
max_iter = 4

[comparison.simulation.overlay.calibration.parameters.K]
bounds = [1e-7, 1e-3]
"""


@pytest.fixture
def sweep(tmp_path: Path):
    from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig

    (tmp_path / "project.toml").write_text(textwrap.dedent(_BASE), encoding="utf-8")
    path = tmp_path / "sweep.toml"
    path.write_text(textwrap.dedent(_SWEEP), encoding="utf-8")
    return SimulationComparisonConfig.from_toml(
        tomllib.loads(path.read_text(encoding="utf-8")), config_path=path
    )


def test_a_sweep_of_calibrations_validates(sweep) -> None:
    assert [cell.id for cell in sweep.comparison.simulation] == ["mesh_500", "mesh_250"]


def test_each_cell_carries_its_own_mesh(sweep) -> None:
    sizes = [
        cell.overlay["mesh_catchment"]["zone_meshing"]["global_size"]
        for cell in sweep.comparison.simulation
    ]

    assert sizes == [500.0, 250.0]
    assert len(set(sizes)) == len(sizes)


def test_each_cell_declares_itself_a_calibration(sweep) -> None:
    """That is what makes the cell a complete calibration and not a single run."""
    for cell in sweep.comparison.simulation:
        assert cell.overlay["workflow"]["mode"] == "calibration"


def test_the_materialised_child_runs_as_a_calibration(sweep) -> None:
    """The overlay merges last, so it wins over the simulation default."""
    from hydromodpy.analysis.comparison.child_materialization import build_child_payload

    payload, _name = build_child_payload(cfg=sweep, simulation=sweep.comparison.simulation[0])

    assert payload["workflow"]["mode"] == "calibration"
    assert payload["calibration"]["parameters"]["K"]["bounds"] == [1e-7, 1e-3]
    assert payload["mesh_catchment"]["zone_meshing"]["global_size"] == 500.0


def test_the_cohort_is_not_ranked_by_cost(sweep) -> None:
    """A mesh variant is reported, never scored against its siblings."""
    import inspect

    from hydromodpy.analysis.comparison import experiment_config

    source = inspect.getsource(experiment_config)

    assert "objective_value" not in source
