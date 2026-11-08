from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from shapely.geometry import LineString

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import FaceFamilyTable
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from tests._helpers.cell_meshes import cell_mesh_of

from ._test_boussinesq_flow_adapter_builders import (
    AdapterCall,
    _DummyRasterSupport,
    _DummySurface,
    _homogeneous_param,
    _write_minimal_bundle,
    adapter_call,
)


def _build_flow_config(flow_section: dict[str, object]) -> FlowConfig:
    return FlowConfig.from_toml_section(flow_section, base_dir=Path("."))


def _make_static_recharge_field_record() -> FieldRecord:
    ds = xr.Dataset(
        {
            "recharge": (
                ("y", "x"),
                np.asarray(
                    [
                        [1.0e-7, 4.0e-7],
                        [2.0e-7, 3.0e-7],
                    ],
                    dtype=float,
                ),
            )
        },
        coords={
            "x": np.asarray([0.333333, 0.666667], dtype=float),
            "y": np.asarray([0.333333, 0.666667], dtype=float),
        },
    )
    return FieldRecord(
        variable="recharge",
        source="test",
        unit="m/s",
        data=ds,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )


def test_boussinesq_flow_adapter_supports_runtime_mesh_with_heterogeneous_recharge(
    tmp_path: Path,
) -> None:
    planar_mesh = HydroMesh(
        vertices=np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray([[0, 1, 2], [0, 2, 3]])),),
    )
    support = _DummyRasterSupport(
        xmin=0.0,
        xmax=2.0,
        ymin=0.0,
        ymax=2.0,
        dx=1.0,
        dy=1.0,
        nrows=2,
        ncols=2,
    )
    domain = SimpleNamespace(
        surface_topo=_DummySurface(np.full((2, 2), 10.0, dtype=float), support),
        substratum=_DummySurface(np.full((2, 2), 5.0, dtype=float), support),
        zones={},
    )
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": _homogeneous_param(1.0e-5),
                    "Sy": _homogeneous_param(0.2),
                },
                "ic": {"kind": "custom", "value": 7.0},
                "first_period_steady": False,
                "sinks_sources": {
                    "recharge": {
                        "values": 0.0,
                    }
                },
            }
        )
    )
    flow.sinks_sources["recharge"].heterogeneous_source = LoadResult(
        fields=[_make_static_recharge_field_record()]
    )
    flow.sinks_sources["recharge"].interpolation_method = "nearest"
    call = adapter_call(
        tmp_path,
        flow=flow,
        cell_mesh=cell_mesh_of(planar_mesh),
        domain=domain,
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
    )

    result = call.solve()
    model = result.solver_model

    assert model.state is not None
    assert np.allclose(model.state.recharge_rate_m_s, [4.0e-7, 2.0e-7])
    assert model.runtime_summary["active_recharge"] is True


def test_boussinesq_flow_adapter_reads_the_river_faces_of_the_cell_mesh(
    tmp_path: Path,
) -> None:
    planar_mesh = HydroMesh(
        vertices=np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray([[0, 1, 2], [0, 2, 3]])),),
    )
    support = _DummyRasterSupport(
        xmin=0.0,
        xmax=2.0,
        ymin=0.0,
        ymax=2.0,
        dx=1.0,
        dy=1.0,
        nrows=2,
        ncols=2,
    )
    domain = SimpleNamespace(
        surface_topo=_DummySurface(np.full((2, 2), 10.0, dtype=float), support),
        substratum=_DummySurface(np.full((2, 2), 5.0, dtype=float), support),
        zones={},
    )
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": _homogeneous_param(1.0e-5),
                    "Sy": _homogeneous_param(0.2),
                },
                "ic": {"kind": "custom", "value": 8.0},
                "first_period_steady": False,
                "bc": {
                    "stream": {"kind": "dirichlet", "value": 7.0},
                },
            }
        )
    )
    # The river is the diagonal the two triangles share: the face family the mesh engine writes.
    river_faces = FaceFamilyTable(
        names=("rivers",),
        family=[0],
        cell_a=[0],
        cell_b=[1],
        node_a=[0],
        node_b=[2],
        zone_left=[-1],
        zone_right=[-1],
    )
    call = adapter_call(
        tmp_path,
        flow=flow,
        cell_mesh=replace(cell_mesh_of(planar_mesh), face_families=river_faces),
        domain=domain,
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
    )

    result = call.solve()
    model = result.solver_model

    assert model.mesh is not None
    river_edges = model.mesh.river_edge_indices()
    assert river_edges.shape == (1,)
    assert model.state is not None
    assert model.state.boundary_edge_flux_m3_s is not None
    assert model.state.boundary_edge_flux_m3_s[int(river_edges[0])] > 0.0


def test_boussinesq_flow_adapter_runs_transient_and_writes_outputs(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_transient")
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "top"}, "first_period_steady": False})),
        exchange_mesh=bundle_dir,
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
    )

    result = call.solve()
    model = result.solver_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.head_history_m is not None
    assert model.state.head_history_m.shape == (2, 2)
    # Post-processing is no longer called by the adapter - ResultStore
    # extractors handle it.  Verify the solver output directory exists, under the slot.
    assert result.solved is True
    assert result.written is True
    assert result.output_dir == call.slot.directory
    assert (result.output_dir / "_boussinesq_state_history.npz").exists()
    assert result.metrics["flow_solve_time_seconds"] >= 0.0


def test_boussinesq_flow_adapter_supports_recharge_and_side_dirichlet(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_supported_inputs")
    call = adapter_call(
        tmp_path,
        flow=Flow(
            _build_flow_config(
                {
                    "ic": {"kind": "custom", "value": 7.0},
                    "first_period_steady": False,
                    "sinks_sources": {"recharge": {"values": 1.0e-7, "units": "m/s"}},
                    "bc": {
                        "west_side": {"kind": "dirichlet", "value": 10.0},
                    },
                }
            )
        ),
        exchange_mesh=bundle_dir,
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
    )

    result = call.solve()
    model = result.solver_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.recharge_rate_m_s is not None
    # The cells held by the west side are a boundary: they take no recharge.
    held = np.isfinite(np.asarray(model.state.prescribed_head_m_by_cell, dtype=float))
    assert held.any() and not held.all()
    assert np.allclose(model.state.recharge_rate_m_s[~held], 1.0e-7)
    assert np.allclose(model.state.recharge_rate_m_s[held], 0.0)
    assert model.state.boundary_edge_flux_m3_s is not None
    assert model.state.boundary_edge_flux_m3_s[4] < 0.0


def test_boussinesq_flow_adapter_supports_absolute_xy_well(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_well")
    call = adapter_call(
        tmp_path,
        flow=Flow(
            _build_flow_config(
                {
                    "ic": {"kind": "custom", "value": 8.0},
                    "first_period_steady": False,
                    "sinks_sources": {
                        "wells": {
                            "W1": {
                                "location": {
                                    "kind": "absolute_xy",
                                    "x": 0.75,
                                    "y": 0.25,
                                },
                                "flux": -1.0e-5,
                            }
                        }
                    },
                }
            )
        ),
        exchange_mesh=bundle_dir,
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
    )

    result = call.solve()
    model = result.solver_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.well_flux_m3_s is not None
    assert np.isclose(model.state.well_flux_m3_s[0], -1.0e-5)
    assert np.isclose(model.state.well_flux_m3_s[1], 0.0)


def test_boussinesq_flow_adapter_supports_stream_on_river_edges(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_stream", river_internal_edge=True)
    call = adapter_call(
        tmp_path,
        flow=Flow(
            _build_flow_config(
                {
                    "ic": {"kind": "custom", "value": 8.0},
                    "first_period_steady": False,
                    "bc": {
                        "stream": {"kind": "dirichlet", "value": 7.0},
                    },
                }
            )
        ),
        exchange_mesh=bundle_dir,
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
    )

    result = call.solve()
    model = result.solver_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.boundary_edge_flux_m3_s is not None
    assert model.state.boundary_edge_flux_m3_s[2] > 0.0


def test_boussinesq_flow_adapter_supports_ocean_on_coastal_edges(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_ocean")
    call = adapter_call(
        tmp_path,
        flow=Flow(
            _build_flow_config(
                {
                    "ic": {"kind": "custom", "value": 8.0},
                    "first_period_steady": False,
                    "bc": {
                        "ocean": {"kind": "dirichlet", "value": 10.5},
                    },
                }
            )
        ),
        exchange_mesh=bundle_dir,
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
    )

    result = call.solve()
    model = result.solver_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.boundary_edge_flux_m3_s is not None
    assert model.runtime_summary["active_ocean"] is True
    assert model.state.boundary_edge_flux_m3_s[0] < 0.0
    assert model.state.boundary_edge_flux_m3_s[1] < 0.0
    assert np.allclose(model.state.boundary_edge_flux_m3_s[[3, 4]], 0.0, atol=1.0e-12)
    assert model.state.head_m[0] > 8.0


def test_boussinesq_flow_adapter_builds_without_solving_and_runs_the_built_run(
    tmp_path: Path,
) -> None:
    """``build`` solves nothing and ``run`` solves the run it is handed, in the slot folder."""
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_build_then_run")
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"flow_regime": "steady", "ic": {"kind": "bottom"}})),
        exchange_mesh=bundle_dir,
    )

    built = call.build()

    assert built.solved is False
    assert built.written is False
    assert built.output_dir is None
    assert built.options is call.options
    assert built.model is call.model
    assert built.solver_model.has_numerical_solution is False
    assert built.solver_model.full_path == call.slot.directory

    solved = BoussinesqFlowAdapter().run(built)

    assert solved.solved is True
    assert solved.output_dir == call.slot.directory
    assert solved.solver_model is built.solver_model
    assert solved.solver_model.has_numerical_solution is True
    assert built.solved is False


def test_a_slot_that_stops_before_the_solve_leaves_the_run_unsolved(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_stop_before_solve")
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"flow_regime": "steady", "ic": {"kind": "bottom"}})),
        exchange_mesh=bundle_dir,
    )
    stopped = AdapterCall(
        model=call.model,
        options=call.options,
        slot=replace(call.slot, stop_before_solve=True),
        ctx=call.ctx,
    )

    result = stopped.solve()

    assert result.solved is False
    assert result.solver_model.has_numerical_solution is False
    assert not (call.slot.directory / "_boussinesq_state_history.npz").exists()


def test_a_run_that_fails_to_converge_names_the_run_by_its_slot(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_diverges")
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"flow_regime": "steady", "ic": {"kind": "bottom"}})),
        exchange_mesh=bundle_dir,
        name="a_trial",
    )
    built = call.build()
    built.solver_model.processing = lambda **_: False

    with pytest.raises(SolverDivergedError, match=r"failed for run 'a_trial'") as error:
        BoussinesqFlowAdapter().run(built)

    assert error.value.run_id is None


def test_the_runner_function_puts_the_run_id_on_a_failed_solve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_diverges_in_solve_one")
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "bottom"}})),
        exchange_mesh=bundle_dir,
    )
    monkeypatch.setattr(Boussinesq, "processing", lambda self, **_: False)

    with pytest.raises(SolverDivergedError) as error:
        call.solve()

    assert error.value.run_id == call.ctx.run.id
