from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError, IncompatibleCapabilitiesError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial.state import PriorState
from hydromodpy.model.model import ModelTime, model_from_flow
from hydromodpy.model.supports import INITIAL_STATE_TRAITS
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.solver_config import SolverConfig
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


def test_an_unknown_flow_solver_is_refused_with_the_valid_names(tmp_path) -> None:
    with pytest.raises(ValueError) as excinfo:
        _config(tmp_path, "modflow7", {"drainage": {}})
    message = str(excinfo.value)
    assert "simulation.process.solvers names 'modflow7'" in message
    assert "this installation serves boussinesq, linear_reservoir, modflow6, modflow_nwt" in message
    assert "drainage" not in message


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


def test_an_unknown_transport_solver_is_refused_with_the_valid_names(tmp_path) -> None:
    with pytest.raises(ValueError) as excinfo:
        _config_2(tmp_path, "modpth")
    message = str(excinfo.value)
    assert "simulation.process.solvers names 'modpth'" in message
    assert "this installation serves" in message
    assert "modpath" in message
    assert "modflow6_prt" in message


def test_a_built_in_transport_solver_is_accepted(tmp_path) -> None:
    cfg = _config_2(tmp_path, "modflow6_prt")
    assert cfg.simulation.process[1].solvers == ["modflow6_prt"]


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


def test_only_the_backend_that_reads_it_lists_the_trait() -> None:
    assert PRIOR_STATE in solvers.get("flow", "modflow6").supports
    assert PRIOR_STATE not in solvers.get("flow", "modflow_nwt").supports
    assert PRIOR_STATE not in solvers.get("flow", "boussinesq").supports


@pytest.mark.parametrize("backend", ["modflow_nwt", "boussinesq"])
def test_a_backend_that_cannot_restart_refuses_the_key(tmp_path, backend: str) -> None:
    with pytest.raises(IncompatibleCapabilitiesError) as caught:
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            solver=SolverConfig(backend=backend),
            flow=FlowConfig(restart_from="runs/spinup_3/fields.zarr"),
        )

    message = str(caught.value)
    assert f"solver.backend = {backend!r} does not honor flow.restart_from" in message
    assert "(modflow6)" in message


def test_modflow6_accepts_it(tmp_path) -> None:
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend="modflow6"),
        flow=FlowConfig(restart_from="runs/spinup_3/fields.zarr"),
    )

    assert cfg.flow.restart_from == "runs/spinup_3/fields.zarr"


def test_leaving_it_unset_is_fine_on_any_backend(tmp_path) -> None:
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend="boussinesq"),
        mesh=MeshConfig(engine="triangle", families={"rivers": "none"}),
        flow=FlowConfig(),
    )

    assert cfg.flow.restart_from is None


@pytest.mark.parametrize("kind", ["steady_state", "spinup_cyclic"])
def test_a_restart_beside_a_computed_start_is_refused(tmp_path, kind: str) -> None:
    with pytest.raises(ValueError, match="overwrite the restart"):
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            solver=SolverConfig(backend="modflow6"),
            flow=FlowConfig(restart_from="runs/spinup_3/fields.zarr", ic={"h": {"kind": kind}}),
        )


# Declaring a lake on a non-modflow6 backend raises a typed error.
#
# A lake is a MODFLOW 6 LAK advanced package; no other backend implements it.
# The cross-section config validator and the boussinesq
# solver-contract fail-fast must both surface the typed
# :class:`IncompatibleCapabilitiesError` (HMPY.E407), not a bare ValueError or a
# silent pass.


LAKES = {"lac0": {"bedleak": 0.1, "initial_stage": "85 m"}}


@pytest.mark.parametrize("backend", ["boussinesq", "modflow_nwt"])
def test_a_lake_on_another_backend_raises_typed_error(tmp_path, backend: str) -> None:
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            solver=SolverConfig(backend=backend),
            flow=FlowConfig(sinks_sources={"lakes": LAKES}),
        )
    assert excinfo.value.code == "HMPY.E407"
    assert backend in str(excinfo.value)


def test_a_switched_off_lake_is_accepted_on_any_backend(tmp_path) -> None:
    lakes = {"lac0": {**LAKES["lac0"], "enabled": False}}
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend="modflow_nwt"),
        flow=FlowConfig(sinks_sources={"lakes": lakes}),
    )
    assert cfg.flow.active_bc == []


def test_lake_on_modflow6_is_accepted(tmp_path) -> None:
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend="modflow6"),
        flow=FlowConfig(sinks_sources={"lakes": LAKES}),
    )
    assert cfg.solver.backend_name == "modflow6"
    assert "lake" in cfg.flow.active_bc
    assert "lac0" in cfg.flow.sinks_sources.lakes


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
def test_a_well_addressed_by_row_and_column_is_refused_on_an_unstructured_engine(
    engine: str,
) -> None:
    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(_payload({"engine": engine}, well=CELL))
    message = str(excinfo.value)
    assert "flow.sinks_sources.wells.W1.location" in message
    assert f"mesh.engine is '{engine}'" in message
    assert "absolute_xy or relative_xy" in message


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_an_explicit_reach_addressed_by_row_and_column_is_refused_too(engine: str) -> None:
    with pytest.raises(ValueError, match=r"flow\.sinks_sources\.sfr\.net\.reaches\[0\]\.cell"):
        HydroModPyConfig.model_validate(_payload({"engine": engine}, reach=REACH))


@pytest.mark.parametrize("mesh", [None, {"engine": "regular"}])
def test_the_regular_engine_and_the_default_one_keep_the_address(mesh) -> None:
    HydroModPyConfig.model_validate(_payload(mesh, well=CELL))
    HydroModPyConfig.model_validate(_payload(mesh, reach=REACH))


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


def test_rectify_on_mesh_loads_without_any_solver_top_key(tmp_path):
    cfg = _load(tmp_path)

    sfr = cfg.flow.sinks_sources.sfr["nancon"]
    assert sfr.rectify_on_mesh is True
    assert sfr.route_drainage is True


@pytest.mark.parametrize(
    ("where", "line", "dotted"),
    [
        ("sgrid", "condition_top = true", "solver.modflow6.sgrid.condition_top"),
        ("sgrid", "condition_top_epsilon = 0.01", "solver.modflow6.sgrid.condition_top_epsilon"),
        (
            "top_sampling",
            "network_safety_net = true",
            "solver.modflow6.sgrid.top_sampling.network_safety_net",
        ),
        (
            "top_sampling",
            "max_channel_lowering_m = 2.0",
            "solver.modflow6.sgrid.top_sampling.max_channel_lowering_m",
        ),
        ("nwt", "condition_top = true", "solver.modflow_nwt.sgrid.condition_top"),
        ("sfr", "stream_threshold_km2 = 1.5", "stream_threshold_km2"),
        ("sfr", "stream_threshold_cells = 50", "stream_threshold_cells"),
    ],
)
def test_a_removed_key_is_refused_by_name(tmp_path, where, line, dotted):
    with pytest.raises(Exception, match=re.escape(dotted) + r"\b(?!_)"):
        _load(tmp_path, **{where: line})


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


def test_the_refusal_names_both_ways_out(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        _load_2(tmp_path, "solver.modflow_nwt", 'channel_source = "streams_raster"')

    assert "channel_source = 'none'" in str(excinfo.value)
    assert "MODFLOW 6" in str(excinfo.value)


def test_a_zonal_nwt_top_without_channel_source_is_allowed(tmp_path: Path) -> None:
    cfg = _load_2(tmp_path, "solver.modflow_nwt", 'channel_source = "none"')

    assert cfg.solver.options_of("modflow_nwt").sgrid.top_sampling.mode == "zonal"


def test_modflow6_keeps_its_channel_source(tmp_path: Path) -> None:
    cfg = _load_2(tmp_path, "solver.modflow6")

    assert cfg.solver.options_of("modflow6").sgrid.top_sampling.channel_source == "streams_raster"
