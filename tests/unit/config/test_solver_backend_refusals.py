from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError, IncompatibleCapabilitiesError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial.state import PriorState
from hydromodpy.model.model import ModelTime, model_from_flow
from hydromodpy.model.supports import INITIAL_STATE_TRAITS
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.boussinesq.solver_contract import assert_supported_runtime_subset
from tests._helpers.fake_solvers import fake_adapter
from tests._helpers.model_factory import default_options, small_geometry

# A flow solver name that is neither built in nor a plugin is refused by name,
# with the names this installation serves.
#
# The name used to become a custom backend, and the first capability check
# refused it with a message about the drainage boundary.


def _config(tmp_path, solver: str, bc: dict) -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        simulation={"process": [{"id": "flow_main", "kind": "flow", "solvers": [solver]}]},
        flow=FlowConfig(bc=bc),
    )


def test_a_registered_plugin_flow_solver_is_accepted(tmp_path, isolated_solvers) -> None:
    isolated_solvers.solvers.register(fake_adapter("pluginflow"))
    cfg = _config(tmp_path, "pluginflow", {})
    assert cfg.solver.backend_name == "pluginflow"


# A transport solver name that is neither built in nor a plugin is refused by name,
# with the names this installation serves.
#
# The name used to pass validation, and the run failed later.


def _config_2(tmp_path, transport: str) -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        simulation={
            "process": [
                {"id": "flow_main", "kind": "flow", "solvers": ["modflow6"]},
                {"id": "transport_main", "kind": "transport", "solvers": [transport]},
            ]
        },
    )


# ``[flow] restart_from`` is read by one backend, and the others said nothing.
#
# A spin-up ends by handing back the Zarr of its converged state, and the whole
# point of the exercise is to feed it to ``[flow] restart_from`` in the production
# run. Only the MODFLOW 6 builders read that key. On MODFLOW-NWT and on Boussinesq
# it was accepted and never looked at: the run started from the initial condition
# the file declares, produced a perfectly plausible result, and nothing said the
# antecedent had been dropped.
#
# The support is a trait the backend lists in its supports rather than a list of
# names here, so a backend added later says what it can do instead of waiting to
# be added here.


PRIOR_STATE = INITIAL_STATE_TRAITS[PriorState]


def _base_kwargs(tmp_path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": GeographicConfig(source_mode="synthetic"),
    }


# Declaring a lake on a non-modflow6 backend raises a typed error.
#
# A lake is a MODFLOW 6 LAK advanced package; no other backend implements it.
# The cross-section config validator and the boussinesq
# solver-contract fail-fast must both surface the typed
# :class:`IncompatibleCapabilitiesError` (HMPY.E407), not a bare ValueError or a
# silent pass.


LAKES = {"lac0": {"bedleak": 0.1, "initial_stage": "85 m"}}


def test_boussinesq_solver_contract_rejects_lake_with_typed_error() -> None:
    flow = Flow(FlowConfig(sinks_sources={"lakes": LAKES}))
    model = model_from_flow(
        flow,
        geometry=small_geometry(),
        time=ModelTime.from_flow(flow, None),
        options=default_options(),
    )
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        assert_supported_runtime_subset(model, solvers.get("flow", "boussinesq").supports)
    assert "lake" in str(excinfo.value)
    assert excinfo.value.code == "HMPY.E407"


# A ``[lay, row, col]`` address is refused while the file loads when the mesh has no rows.
#
# Only the ``regular`` engine has rows and columns. A well or an explicit SFR reach that
# names its cell that way on a triangle or Voronoi mesh would stop the build after the
# meshing; the configuration refuses it before any step, and names where the address is.


CELL = {"kind": "cell", "cell": [0, 1, 2]}


XY = {"kind": "absolute_xy", "x": 1.0, "y": 2.0}


REACH = {
    "cell": CELL,
    "length": "100 m",
    "width": "2 m",
    "slope": 0.001,
    "top": "10 m",
}


def _payload(
    mesh: dict[str, Any] | None,
    *,
    well: dict[str, Any] | None = None,
    reach: dict[str, Any] | None = None,
    solver: str = "modflow6",
) -> dict[str, Any]:
    sinks: dict[str, Any] = {}
    if well is not None:
        sinks["wells"] = {"W1": {"location": well, "flux": -1.0}}
    if reach is not None:
        sinks["sfr"] = {"net": {"reaches": [reach]}}
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"source_mode": "synthetic"},
        "solver": {"backend": solver},
        "flow": {"sinks_sources": sinks},
    }
    if mesh is not None:
        payload["mesh"] = mesh
    return payload


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_an_explicit_reach_addressed_by_row_and_column_is_refused_too(engine: str) -> None:
    with pytest.raises(ValueError, match=r"flow\.sinks_sources\.sfr\.net\.reaches\[0\]\.cell"):
        HydroModPyConfig.model_validate(_payload({"engine": engine}, reach=REACH))


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_a_well_located_by_coordinates_loads_on_every_engine(engine: str) -> None:
    HydroModPyConfig.model_validate(_payload({"engine": engine}, well=XY))


def test_every_address_of_the_file_is_named_at_once() -> None:
    payload = _payload({"engine": "triangle"}, well=CELL, reach=REACH)

    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(payload)
    message = str(excinfo.value)
    assert "wells.W1.location" in message
    assert "sfr.net.reaches[0].cell" in message


# ``rectify_on_mesh`` needs nothing from the solver top, and the keys that went are refused.
#
# The channel is traced on the descent D, a filled copy of the solver top, so the
# solver top is never raised for the routing. The solver top conditioning keys and
# the SFR threshold no longer exist: a TOML that still declares one fails to load.


def _toml(
    project_root, *, sgrid: str = "", top_sampling: str = "", nwt: str = "", sfr: str = ""
) -> str:
    return f"""
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"

[solver.modflow6.sgrid]
{sgrid}

[solver.modflow6.sgrid.top_sampling]
{top_sampling}

[solver.modflow_nwt.sgrid]
{nwt}

[flow]

[flow.sinks_sources.sfr.nancon]
rectify_on_mesh = true
route_drainage = true
{sfr}

[flow.sinks_sources.sfr.nancon.width]
kind = "constant"
value = "2 m"
"""


def _load(tmp_path, **kwargs) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(_toml(tmp_path, **kwargs), encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[{section}.sgrid.top_sampling]
mode = "zonal"
{extra}
"""


def _load_2(tmp_path: Path, section: str, extra: str = "") -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), section=section, extra=extra),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


def test_a_zonal_nwt_top_with_a_channel_source_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="MODFLOW-NWT does not read the channel tree"):
        _load_2(tmp_path, "solver.modflow_nwt")


def test_a_zonal_nwt_top_without_channel_source_is_allowed(tmp_path: Path) -> None:
    cfg = _load_2(tmp_path, "solver.modflow_nwt", 'channel_source = "none"')

    assert cfg.solver.options_of("modflow_nwt").sgrid.top_sampling.mode == "zonal"
