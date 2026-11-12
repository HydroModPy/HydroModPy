"""What the Boussinesq flow adapter builds, runs and serves back.

It maps a Flow and a cell mesh (or a mesh bundle) to a solver mesh in SI units,
runs the solve, and reads heads (m) and discharge (m3/s) from the state history.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
import zarr
from shapely.geometry import box

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import (
    MeshError,
    ObservableNotAvailableError,
    SolverDivergedError,
    SolverError,
)
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import FaceFamilyTable
from hydromodpy.model.domain.geometry import CatchmentGeometry
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.model import Geometry
from hydromodpy.model.properties.field_spatial import WeightedAverageFieldDiscretization
from hydromodpy.results.derive.catchment_aggregation import catchment_support
from hydromodpy.results.storage.final_state import read_final_state
from hydromodpy.solver.base.plan import SolverRun
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter, _published_support
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_common.solver_runs import keep_all

from ._solver_runs import solver_run_of
from ._test_boussinesq_flow_adapter_builders import (
    AdapterCall,
    _DummyRasterSupport,
    _DummySurface,
    _homogeneous_param,
    _write_custom_bundle,
    _write_minimal_bundle,
    adapter_call,
)

ONE_HOUR = SimpleNamespace(period_lengths_seconds=(3600.0,))
HISTORY_FILE = "_boussinesq_state_history.npz"


def heterogeneous(values: dict[str, float], field_spatial_id: str) -> dict[str, object]:
    return {
        "field": {"kind": "heterogeneous", "values": values, "field_spatial_id": field_spatial_id}
    }


def uniform_flow(**section: object) -> Flow:
    """A flow with K = 1e-5 m/s and Sy = 0.2 everywhere."""
    params = {
        "param_list": ["K", "Sy"],
        "param": {"K": _homogeneous_param(1.0e-5), "Sy": _homogeneous_param(0.2)},
    }
    return Flow(FlowConfig.model_validate(params | section))


def toml_flow(section: dict[str, object]) -> Flow:
    return Flow(FlowConfig.from_toml_section(section, base_dir=Path(".")))


def steady_call(tmp_path: Path, **kwargs: object) -> AdapterCall:
    """A steady run on the minimal two-cell mesh bundle, started from the bottom."""
    return adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"flow_regime": "steady", "ic": {"kind": "bottom"}})),
        exchange_mesh=_write_minimal_bundle(tmp_path / "bundle"),
        **kwargs,
    )


def hourly_call(tmp_path: Path, section: dict[str, object], **bundle: bool) -> AdapterCall:
    """One transient hour on the minimal bundle, for a flow given as a TOML section."""
    return adapter_call(
        tmp_path,
        flow=toml_flow(section),
        exchange_mesh=_write_minimal_bundle(tmp_path / "bundle", **bundle),
        time_grid=ONE_HOUR,
    )


def two_triangles() -> HydroMesh:
    """The unit square cut along its diagonal, 5 m of aquifer under a 10 m surface."""
    return HydroMesh(
        vertices=np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray([[0, 1, 2], [0, 2, 3]])),),
    )


def flat_domain(zones: dict[str, object] | None = None) -> SimpleNamespace:
    support = _DummyRasterSupport(
        xmin=0.0, xmax=2.0, ymin=0.0, ymax=2.0, dx=1.0, dy=1.0, nrows=2, ncols=2
    )
    return SimpleNamespace(
        surface_topo=_DummySurface(np.full((2, 2), 10.0), support),
        substratum=_DummySurface(np.full((2, 2), 5.0), support),
        zones=zones or {},
    )


class HalfDomainSupport:
    """A zone field with a west half and an east half, split at the middle of the cells."""

    def __init__(self, identifier: str = "field_geology") -> None:
        self.identifier = identifier
        self.default_cell_samples_per_axis = 4

    def on_mesh(self, cell_mesh, *, cell_samples_per_axis: int = 10):
        x_centers = np.asarray(cell_mesh.centers[:, 0], dtype=float)
        midpoint = 0.5 * (x_centers.min() + x_centers.max())
        west = (x_centers <= midpoint).astype(float)
        return WeightedAverageFieldDiscretization(
            mesh=cell_mesh,
            field_id=self.identifier,
            zone_keys=("west", "east"),
            fractions_by_zone={"west": west, "east": 1.0 - west},
        )


def test_registry() -> None:
    assert isinstance(solvers.create("flow", "boussinesq"), BoussinesqFlowAdapter)


MESH_PARAMETERS = [
    pytest.param(
        {"K": _homogeneous_param(1.0e-5), "Sy": _homogeneous_param(0.2)},
        {},
        [1.0e-5, 1.0e-5],
        [0.2, 0.2],
        id="homogeneous",
    ),
    pytest.param(
        {
            "K": heterogeneous({"west": 2.0e-5, "east": 5.0e-6}, "field_geology"),
            "Sy": heterogeneous({"west": 0.22, "east": 0.08}, "field_geology"),
        },
        {"field_geology": HalfDomainSupport()},
        [5.0e-6, 2.0e-5],
        [0.08, 0.22],
        id="west and east zones",
    ),
]


@pytest.mark.parametrize(("param", "zones", "k_m_s", "sy"), MESH_PARAMETERS)
def test_mesh_parameters(tmp_path: Path, param, zones, k_m_s, sy) -> None:
    flow = Flow(
        FlowConfig.model_validate(
            {"param_list": ["K", "Sy"], "param": param, "ic": {"kind": "bottom"}}
        )
    )
    call = adapter_call(
        tmp_path,
        flow=flow,
        cell_mesh=cell_mesh_of(two_triangles()),
        domain=flat_domain(zones),
    )

    model = call.solve().solver_model

    assert model.mesh_bundle is None
    np.testing.assert_allclose(model.mesh.hydraulic_conductivity_m_s, k_m_s)
    np.testing.assert_allclose(model.mesh.storage_coefficient, sy)
    # The bottom start puts the head on the 5 m substratum.
    np.testing.assert_allclose(model.state.head_m, [5.0, 5.0])


def test_heterogeneous_recharge(tmp_path: Path) -> None:
    flow = uniform_flow(
        ic={"kind": "custom", "value": 7.0},
        first_period_steady=False,
        sinks_sources={"recharge": {"values": 0.0}},
    )
    # One value per pixel of the 2 x 2 raster, in m/s.
    dataset = xr.Dataset(
        {"recharge": (("y", "x"), np.asarray([[1.0e-7, 4.0e-7], [2.0e-7, 3.0e-7]]))},
        coords={"x": [0.333333, 0.666667], "y": [0.333333, 0.666667]},
    )
    record = FieldRecord(
        variable="recharge",
        source="test",
        unit="m/s",
        data=dataset,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )
    flow.sinks_sources["recharge"].heterogeneous_source = LoadResult(fields=[record])
    flow.sinks_sources["recharge"].interpolation_method = "nearest"
    call = adapter_call(
        tmp_path,
        flow=flow,
        cell_mesh=cell_mesh_of(two_triangles()),
        domain=flat_domain(),
        time_grid=ONE_HOUR,
    )

    model = call.solve().solver_model

    np.testing.assert_allclose(model.state.recharge_rate_m_s, [4.0e-7, 2.0e-7])
    assert model.runtime_summary["active_recharge"] is True


def test_river_faces(tmp_path: Path) -> None:
    flow = uniform_flow(
        ic={"kind": "custom", "value": 8.0},
        first_period_steady=False,
        bc={"stream": {"kind": "dirichlet", "value": 7.0}},
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
        cell_mesh=replace(cell_mesh_of(two_triangles()), face_families=river_faces),
        domain=flat_domain(),
        time_grid=ONE_HOUR,
    )

    model = call.solve().solver_model

    river_edges = model.mesh.river_edge_indices()
    assert river_edges.shape == (1,)
    # The river is lower than the head, so it drains the aquifer.
    assert model.state.boundary_edge_flux_m3_s[int(river_edges[0])] > 0.0


def test_bundle_cell_parameters(tmp_path: Path) -> None:
    # Cell 0 has no K and takes the default, cell 1 has its own.
    bundle_dir = _write_custom_bundle(
        tmp_path / "bundle", conductivity_values=("", "4.0e-5"), conductivity_default=3.0e-5
    )
    flow = Flow(FlowConfig.model_validate({"ic": {"kind": "top"}}))
    call = adapter_call(tmp_path, flow=flow, exchange_mesh=bundle_dir, time_grid=ONE_HOUR)

    model = call.solve().solver_model

    np.testing.assert_allclose(model.mesh.hydraulic_conductivity_m_s, [3.0e-5, 4.0e-5])


BUNDLE_STORAGE = [
    pytest.param(
        {"ic": {"kind": "top"}}, {"storage_default": 0.02}, [0.02, 0.02], id="default storage"
    ),
    pytest.param(
        {"flow_regime": "steady", "ic": {"kind": "bottom"}}, {}, [0.0, 0.0], id="steady, none given"
    ),
]


@pytest.mark.parametrize(("section", "bundle", "expected"), BUNDLE_STORAGE)
def test_bundle_storage(tmp_path: Path, section, bundle, expected) -> None:
    bundle_dir = _write_custom_bundle(tmp_path / "bundle", storage_values=("", ""), **bundle)
    flow = Flow(FlowConfig.model_validate(section))
    call = adapter_call(tmp_path, flow=flow, exchange_mesh=bundle_dir, time_grid=ONE_HOUR)

    model = call.solve().solver_model

    np.testing.assert_allclose(model.mesh.storage_coefficient, expected)
    assert model.has_numerical_solution is True


def test_exchange_mesh_option(tmp_path: Path) -> None:
    flow = Flow(FlowConfig.model_validate({"ic": {"kind": "bottom"}}))
    call = adapter_call(
        tmp_path, flow=flow, exchange_mesh=_write_minimal_bundle(tmp_path / "bundle")
    )

    model = call.solve().solver_model

    assert model.mesh_bundle is not None
    np.testing.assert_allclose(model.state.head_m, [5.0, 4.0])


def test_runs_transient_and_writes_outputs(tmp_path: Path) -> None:
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "top"}, "first_period_steady": False})),
        exchange_mesh=_write_minimal_bundle(tmp_path / "bundle"),
        time_grid=ONE_HOUR,
    )

    result = call.solve()

    model = result.solver_model
    assert model.has_numerical_solution is True
    assert model.state.head_history_m.shape == (2, 2)
    # Post-processing is left to the ResultStore extractors. The adapter only
    # leaves the state history in the slot folder.
    assert result.solved is True
    assert result.written is True
    assert result.output_dir == call.slot.directory
    assert (result.output_dir / HISTORY_FILE).exists()
    # The time of the solve is a duration of the run, not a result: it has its own member.
    assert result.solve_s is not None and result.solve_s >= 0.0
    assert "flow_solve_time_seconds" not in result.metrics


class Store:
    """A run store that keeps the writes of the extractor and says where the run folder is."""

    sim_id = "sim"

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self.fields: dict[str, np.ndarray] = {}
        self.zarr = SimpleNamespace(
            root=zarr.group(),
            close=lambda: None,
            write_budget_policy=lambda *args, **kwargs: None,
            write_topography=lambda *args, **kwargs: None,
        )

    def run_dir_for(self, sim_id: str) -> Path:
        return self._run_dir

    def write_time(self, sim_id: str, values, **kwargs) -> None:
        self.time = np.asarray(values)

    def write_field_stack(self, sim_id: str, name: str, values, **kwargs) -> None:
        self.fields[name] = np.asarray(values)

    def write_budgets(self, sim_id: str, records) -> None:
        self.budgets = list(records)

    def open_zarr(self, sim_id: str):
        return self.zarr


def test_final_state_is_float64(tmp_path: Path) -> None:
    call = adapter_call(
        tmp_path,
        flow=Flow(
            FlowConfig.model_validate(
                {"ic": {"kind": "custom", "value": 8.0}, "first_period_steady": False}
            )
        ),
        exchange_mesh=_write_minimal_bundle(tmp_path / "bundle"),
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0, 3600.0, 3600.0)),
    )
    result = call.solve()
    run_dir = tmp_path / "run"
    store = Store(run_dir)

    BoussinesqOutputAdapter().extract(result, store, keep_all)

    state = read_final_state(run_dir)
    history = result.solver_model.state.head_history_m
    assert state.head.dtype == np.float64
    assert state.head.shape == (1, history.shape[1])
    assert np.array_equal(state.head[0], history[-1])
    assert np.array_equal(state.head[0], store.fields["head"][-1, 0])
    assert (state.lake_stages, state.sfr_stages) == ({}, {})


def test_flow_adapter_extracts_the_head_history(tmp_path: Path) -> None:
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "top"}, "first_period_steady": False})),
        exchange_mesh=_write_minimal_bundle(tmp_path / "bundle"),
        time_grid=ONE_HOUR,
    )
    result = call.solve()
    store = Store(tmp_path / "run")

    BoussinesqFlowAdapter().extract(result, store, keep_all)

    history = result.solver_model.state.head_history_m
    assert np.array_equal(store.fields["head"][-1, 0], history[-1])


def test_no_request_serves_nothing(tmp_path: Path) -> None:
    assert BoussinesqFlowAdapter().observables(solver_run_of(tmp_path), []) == {}


def test_recharge_and_dirichlet(tmp_path: Path) -> None:
    call = hourly_call(
        tmp_path,
        {
            "ic": {"kind": "custom", "value": 7.0},
            "first_period_steady": False,
            "sinks_sources": {"recharge": {"values": 1.0e-7, "units": "m/s"}},
            "bc": {"west_side": {"kind": "dirichlet", "value": 10.0}},
        },
    )

    state = call.solve().solver_model.state

    # The cells held by the west side are a boundary: they take no recharge.
    held = np.isfinite(np.asarray(state.prescribed_head_m_by_cell, dtype=float))
    assert held.any() and not held.all()
    np.testing.assert_allclose(state.recharge_rate_m_s[~held], 1.0e-7)
    np.testing.assert_allclose(state.recharge_rate_m_s[held], 0.0)
    assert state.boundary_edge_flux_m3_s[4] < 0.0


def test_absolute_xy_well(tmp_path: Path) -> None:
    well = {"location": {"kind": "absolute_xy", "x": 0.75, "y": 0.25}, "flux": -1.0e-5}
    call = hourly_call(
        tmp_path,
        {
            "ic": {"kind": "custom", "value": 8.0},
            "first_period_steady": False,
            "sinks_sources": {"wells": {"W1": well}},
        },
    )

    state = call.solve().solver_model.state

    np.testing.assert_allclose(state.well_flux_m3_s[:2], [-1.0e-5, 0.0])


def test_stream_on_river_edges(tmp_path: Path) -> None:
    call = hourly_call(
        tmp_path,
        {
            "ic": {"kind": "custom", "value": 8.0},
            "first_period_steady": False,
            "bc": {"stream": {"kind": "dirichlet", "value": 7.0}},
        },
        river_internal_edge=True,
    )

    state = call.solve().solver_model.state

    assert state.boundary_edge_flux_m3_s[2] > 0.0


def test_ocean_on_coastal_edges(tmp_path: Path) -> None:
    call = hourly_call(
        tmp_path,
        {
            "ic": {"kind": "custom", "value": 8.0},
            "first_period_steady": False,
            "bc": {"ocean": {"kind": "dirichlet", "value": 10.5}},
        },
    )

    model = call.solve().solver_model

    flux = model.state.boundary_edge_flux_m3_s
    assert model.runtime_summary["active_ocean"] is True
    assert flux[0] < 0.0 and flux[1] < 0.0
    np.testing.assert_allclose(flux[[3, 4]], 0.0, atol=1.0e-12)
    assert model.state.head_m[0] > 8.0


def test_build_then_run(tmp_path: Path) -> None:
    call = steady_call(tmp_path)

    built = call.build()

    # Building solves nothing.
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


def test_stop_before_the_solve(tmp_path: Path) -> None:
    call = steady_call(tmp_path)
    stopped = AdapterCall(
        model=call.model,
        options=call.options,
        slot=replace(call.slot, stop_before_solve=True),
        ctx=call.ctx,
    )

    result = stopped.solve()

    assert result.solved is False
    assert result.solver_model.has_numerical_solution is False
    assert not (call.slot.directory / HISTORY_FILE).exists()


def test_divergence_names_the_slot(tmp_path: Path) -> None:
    built = steady_call(tmp_path, name="a_trial").build()
    built.solver_model.processing = lambda **_: False

    with pytest.raises(SolverDivergedError, match=r"failed for run 'a_trial'") as error:
        BoussinesqFlowAdapter().run(built)

    assert error.value.run_id is None


def test_runner_names_the_failed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    call = adapter_call(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "bottom"}})),
        exchange_mesh=_write_minimal_bundle(tmp_path / "bundle"),
    )
    monkeypatch.setattr(Boussinesq, "processing", lambda self, **_: False)

    with pytest.raises(SolverDivergedError) as error:
        call.solve()

    assert error.value.run_id == call.ctx.run.id


def write_state_history(output_dir: Path, head_history, drainage_history=None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"head_history_m": np.asarray(head_history, dtype=float)}
    if drainage_history is not None:
        payload["drainage_flux_history_m3_s"] = np.asarray(drainage_history, dtype=float)
    np.savez(output_dir / HISTORY_FILE, **payload)


def head_request(request_id: str, cell: tuple[int, int, int]) -> ObservableRequest:
    return ObservableRequest(id=request_id, name="head", support="cell", cell=cell)


DISCHARGE = ObservableRequest(id="q", name="discharge", support="domain")

# Head histories have one row per time and one column per cell, in m.
HEAD_STATIONS = [
    pytest.param(
        [[10.0, 11.0, 12.0], [10.5, 11.5, 12.5]],
        {"P1": ((0, 0, 1), [11.0, 11.5])},
        id="one station",
    ),
    pytest.param(
        [[1.0, 2.0], [1.5, 2.5]],
        {"P1": ((0, 0, 0), [1.0, 1.5]), "P2": ((0, 0, 1), [2.0, 2.5])},
        id="two stations",
    ),
]


@pytest.mark.parametrize(("history", "stations"), HEAD_STATIONS)
def test_head_at_cell(tmp_path: Path, history, stations) -> None:
    write_state_history(tmp_path, history)
    requests = [head_request(name, cell) for name, (cell, _) in stations.items()]

    served = BoussinesqFlowAdapter().observables(solver_run_of(tmp_path), requests)

    assert set(served) == set(stations)
    for name, (_, expected) in stations.items():
        assert served[name].request_id == name
        np.testing.assert_array_equal(served[name].values, expected)
        assert served[name].units == "m"


def test_discharge_aligns_with_time_index(tmp_path: Path) -> None:
    write_state_history(tmp_path, np.full((3, 1), 5.0), [[1.0], [2.0], [3.0]])
    time_index = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])

    served = BoussinesqFlowAdapter().observables(
        solver_run_of(tmp_path), [DISCHARGE], time_index=time_index
    )

    result = served["q"]
    assert isinstance(result.times, pd.DatetimeIndex)
    assert result.times.tolist() == time_index.tolist()
    assert result.values.size == len(time_index)


def test_discharge_ignores_negative_terms(tmp_path: Path) -> None:
    # Only the positive drainage terms leave the aquifer: 1 + 3 m3/s.
    write_state_history(tmp_path, np.full((1, 3), 5.0), [[1.0, -2.0, 3.0]])

    served = BoussinesqFlowAdapter().observables(solver_run_of(tmp_path), [DISCHARGE])

    np.testing.assert_array_equal(served["q"].values, [4.0])


def half_of_a_square(tmp_path: Path) -> tuple[np.ndarray, np.ndarray, Path]:
    """A row of four cells and a watershed file that covers the first two."""
    vertices = np.array([[float(i), float(j)] for j in (0, 1) for i in range(5)])
    faces = np.array([[i, i + 1, i + 6, i + 5] for i in range(4)])
    watershed = tmp_path / "watershed.gpkg"
    gpd.GeoDataFrame(geometry=[box(-1.0, -1.0, 2.0, 2.0)], crs="EPSG:2154").to_file(watershed)
    return vertices, faces, watershed


def run_on_a_watershed(
    output_dir: Path, vertices: np.ndarray, faces: np.ndarray, watershed: Path, *, crs: str | None
) -> SolverRun:
    cell_mesh = SimpleNamespace(
        mesh=SimpleNamespace(vertices=vertices),
        geometry=SimpleNamespace(padded_connectivity=faces),
    )
    return solver_run_of(
        output_dir,
        model=make_model(
            geometry=Geometry(
                cells=None,
                domain=None,
                catchment=CatchmentGeometry.from_geographic(
                    SimpleNamespace(watershed_shp=str(watershed)), crs=crs
                ),
            )
        ),
        solver_model=SimpleNamespace(mesh=SimpleNamespace(cell_mesh=cell_mesh)),
    )


def test_discharge_on_published_cells(tmp_path: Path) -> None:
    vertices, faces, watershed = half_of_a_square(tmp_path)
    write_state_history(tmp_path, np.full((1, 4), 5.0), [[1.0, 2.0, 4.0, 8.0]])
    run = run_on_a_watershed(tmp_path, vertices, faces, watershed, crs="EPSG:2154")

    served = BoussinesqFlowAdapter().observables(run, [DISCHARGE])

    # Only the two cells inside the watershed count: 1 + 2 m3/s.
    np.testing.assert_array_equal(served["q"].values, [3.0])


def test_trial_and_run_share_one_mask(tmp_path: Path) -> None:
    vertices, faces, watershed = half_of_a_square(tmp_path)
    run = run_on_a_watershed(tmp_path, vertices, faces, watershed, crs="EPSG:2154")
    store = SimpleNamespace(read_geographic_feature=lambda sim_id, name: gpd.read_file(watershed))
    group = {
        "mesh": {"vertices": vertices, "face_node_connectivity": faces},
        "crs": SimpleNamespace(attrs={"crs_wkt": "EPSG:2154"}),
    }
    published = catchment_support(store, "sim", group, np.ones(4, dtype=bool))

    np.testing.assert_array_equal(_published_support(run), published)


def test_no_crs_keeps_whole_domain(tmp_path: Path) -> None:
    vertices, faces, watershed = half_of_a_square(tmp_path)
    run = run_on_a_watershed(tmp_path, vertices, faces, watershed, crs=None)

    assert _published_support(run) is None


def test_declared_observables() -> None:
    declared = {
        support.name: support
        for support in BoussinesqFlowAdapter().declared_observables(frozenset({"drainage"}))
    }

    assert {name for name, support in declared.items() if support.is_servable_now} == {
        "head",
        "discharge",
    }
    assert {name for name, support in declared.items() if support.can_never_be_served} == {
        "release_flux",
        "stage",
        "routed_discharge",
    }


def test_no_cell_mesh_locates_nothing(tmp_path: Path) -> None:
    adapter = BoussinesqFlowAdapter()
    bundle_run = solver_run_of(tmp_path, solver_model=SimpleNamespace(mesh=SimpleNamespace()))

    assert adapter.locate_cell(bundle_run, 1.0, 1.0) is None
    assert adapter.locate_cell(solver_run_of(tmp_path), 1.0, 1.0) is None
    assert adapter.top_active_layer(bundle_run, 0, 3) == 0


def test_cleanup(tmp_path: Path) -> None:
    adapter = BoussinesqFlowAdapter()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "_boussinesq_summary.json").write_text("{}", encoding="utf-8")

    adapter.cleanup(solver_run_of(scratch))
    adapter.cleanup(solver_run_of(None))

    assert not scratch.exists()


def test_flow_k_and_bundle_k_refused(tmp_path: Path) -> None:
    # The bundle cells carry K and [flow.param.K] sets it too: two sources.
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": heterogeneous({"west": 3.0e-4, "east": 8.0e-7}, "field_hydrofacies"),
                    "Sy": heterogeneous({"west": 0.21, "east": 0.03}, "field_hydrofacies"),
                },
                "ic": {"kind": "top"},
            }
        )
    )
    call = adapter_call(
        tmp_path,
        flow=flow,
        exchange_mesh=bundle_dir,
        time_grid=ONE_HOUR,
        cell_mesh=cell_mesh_of(two_triangles()),
        domain=SimpleNamespace(zones={"field_hydrofacies": HalfDomainSupport("field_hydrofacies")}),
    )

    with pytest.raises(ValueError, match=r"Two sources set K") as error:
        call.solve()

    assert str(bundle_dir) in str(error.value)
    assert "[flow.param.K]" in str(error.value)


BUNDLE_REFUSALS = [
    pytest.param(
        {"conductivity_values": ("", ""), "conductivity_default": 3.0e-5},
        r"Two sources set K",
        id="flow K and default K",
    ),
    pytest.param(
        {"conductivity_values": ("", "")},
        r"cannot be mapped on the mesh bundle",
        id="flow K and no bundle K",
    ),
]


@pytest.mark.parametrize(("bundle", "named"), BUNDLE_REFUSALS)
def test_bundle_refusals(tmp_path: Path, bundle, named: str) -> None:
    bundle_dir = _write_custom_bundle(tmp_path / "bundle", **bundle)
    flow = Flow(
        FlowConfig.model_validate(
            {"param_list": ["K"], "param": {"K": _homogeneous_param(1.0e-5)}, "ic": {"kind": "top"}}
        )
    )
    call = adapter_call(tmp_path, flow=flow, exchange_mesh=bundle_dir, time_grid=ONE_HOUR)

    with pytest.raises(ValueError, match=named):
        call.solve()


def test_no_mesh_refused(tmp_path: Path) -> None:
    call = adapter_call(tmp_path, flow=Flow(FlowConfig.model_validate({"ic": {"kind": "bottom"}})))

    with pytest.raises(MeshError, match=r"exchange_mesh"):
        call.solve()


OBSERVABLE_REFUSALS = [
    pytest.param(head_request("P1", (1, 0, 0)), ValueError, "cell_id", id="head in layer 1"),
    pytest.param(
        ObservableRequest(id="c", name="concentration", support="domain"),
        ObservableNotAvailableError,
        "concentration",
        id="concentration",
    ),
]


@pytest.mark.parametrize(("request_", "error", "named"), OBSERVABLE_REFUSALS)
def test_observable_refusals(tmp_path: Path, request_, error, named: str) -> None:
    write_state_history(tmp_path, [[1.0, 2.0]])

    with pytest.raises(error, match=named):
        BoussinesqFlowAdapter().observables(solver_run_of(tmp_path), [request_])


def test_head_request_needs_a_cell() -> None:
    with pytest.raises(ValueError, match="needs a .* cell"):
        ObservableRequest(id="P1", name="head", support="cell")


def test_no_output_dir_refused() -> None:
    with pytest.raises(SolverError, match="No solver output recorded"):
        BoussinesqFlowAdapter().observables(solver_run_of(None), [DISCHARGE])
