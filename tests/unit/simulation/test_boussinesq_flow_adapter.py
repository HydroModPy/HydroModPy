from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.process.flow import Flow
from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.adapters.registry import get_solver_adapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _write_minimal_bundle(bundle_dir: Path, *, river_internal_edge: bool = False) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": {"mesh": "mesh_2d.msh"},
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps({"constraints_mode": "geology_only"}, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top,z_bottom",
        [
            "0,0.0,0.0,10.0,5.0",
            "1,1.0,0.0,10.0,5.0",
            "2,1.0,1.0,10.0,5.0",
            "3,0.0,1.0,10.0,5.0",
        ],
    )
    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
        [
            "0,triangle,0,1,2,,0.666667,0.333333,0.5,10.0,10.0,5.0,5.0,1,granite,1.0e-5,0.10",
            "1,triangle,0,2,3,,0.333333,0.666667,0.5,11.0,11.0,4.0,4.0,2,schist,2.0e-5,0.15",
        ],
    )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        [
            "0,0,1,0,,1.0,boundary,false,granite,",
            "1,1,2,0,,1.0,boundary,false,granite,",
            f"2,0,2,0,1,1.414214,internal,{str(bool(river_internal_edge)).lower()},granite,schist",
            "3,2,3,1,,1.0,boundary,false,schist,",
            "4,0,3,1,,1.0,boundary,false,schist,",
        ],
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [
            "0,granite,1.0",
            "1,schist,1.0",
        ],
    )
    return bundle_dir


def _build_flow_config(flow_section: dict[str, object]) -> FlowConfig:
    return FlowConfig.from_toml_section(flow_section, base_dir=Path("."))


def test_registry_exposes_boussinesq_flow_adapter() -> None:
    adapter = get_solver_adapter("flow", "boussinesq")

    assert isinstance(adapter, BoussinesqFlowAdapter)


def test_boussinesq_flow_adapter_loads_bundle_from_mesh_summary(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(FlowConfig.model_validate({"ic": {"type": "bottom"}})),
            domain=None,
            time_grid=None,
            workspace=SimpleNamespace(simulations_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)

    assert state.setup.mesh_bundle is not None
    assert result.primary_model.state is not None
    assert np.allclose(result.primary_model.state.head_m, [5.0, 4.0])


def test_boussinesq_flow_adapter_runs_transient_and_writes_outputs(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_transient")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(FlowConfig.model_validate({"ic": {"type": "top"}})),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.head_history_m is not None
    assert model.state.head_history_m.shape == (2, 2)
    assert (model.full_path / "_boussinesq_summary.json").exists()
    assert (model.full_path / "_boussinesq_state_history.npz").exists()


def test_boussinesq_flow_adapter_supports_recharge_and_side_dirichlet(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_supported_inputs")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "ic": {"type": "custom", "value": 7.0},
                        "active_sinks_sources": ["recharge"],
                        "active_bc": ["west_side"],
                        "sinks_sources": {"recharge": {"values": 1.0e-7}},
                        "bc": {
                            "dirichlet": {
                                "west_side": {"value": 10.0},
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_supported_inputs",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.recharge_rate_m_s is not None
    assert np.allclose(model.state.recharge_rate_m_s, 1.0e-7)
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.state.imposed_head_edge_flux_m3_s[4] < 0.0


def test_boussinesq_flow_adapter_supports_absolute_xy_well(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_well")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "ic": {"type": "custom", "value": 8.0},
                        "active_sinks_sources": ["wells"],
                        "sinks_sources": {
                            "wells": {
                                "W1": {
                                    "location_mode": "absolute_xy",
                                    "x": 0.75,
                                    "y": 0.25,
                                    "flux": -1.0e-5,
                                }
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_well",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.well_flux_m3_s is not None
    assert np.isclose(model.state.well_flux_m3_s[0], -1.0e-5)
    assert np.isclose(model.state.well_flux_m3_s[1], 0.0)


def test_boussinesq_flow_adapter_supports_stream_on_river_edges(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_stream", river_internal_edge=True)
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "ic": {"type": "custom", "value": 8.0},
                        "active_bc": ["stream"],
                        "bc": {
                            "dirichlet": {
                                "stream": {"value": 7.0},
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_stream",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.state.imposed_head_edge_flux_m3_s[2] > 0.0


def test_boussinesq_flow_adapter_supports_ocean_on_coastal_edges(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_ocean")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "ic": {"type": "custom", "value": 8.0},
                        "active_bc": ["ocean"],
                        "bc": {
                            "dirichlet": {
                                "ocean": {"value": 10.5},
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_ocean",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.runtime_summary["active_ocean"] is True
    assert model.state.imposed_head_edge_flux_m3_s[0] < 0.0
    assert model.state.imposed_head_edge_flux_m3_s[1] < 0.0
    assert np.allclose(model.state.imposed_head_edge_flux_m3_s[[3, 4]], 0.0, atol=1.0e-12)
    assert model.state.head_m[0] > 8.0
