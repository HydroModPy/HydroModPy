"""Inputs, preparation paths and hand references of the one-cell-mesh acceptance test.

Two pairs of solvers read one cell mesh each, because MODFLOW-NWT reads only the
``regular`` engine and Boussinesq only the ``triangle`` engine:

- pair R: a 30 x 40 regular mesh with a non-integer origin and pitch, read by
  MODFLOW 6 and MODFLOW-NWT;
- pair T: the frozen radial-island triangulation, read by MODFLOW 6 and Boussinesq.

Each solver is prepared by its own adapter code up to the arrays it hands to its
solver (nothing is solved): ``prepare_mf6``, ``prepare_nwt``, ``prepare_boussinesq``.
The ``reference_*`` functions compute the same inputs by hand from the raw cell
polygons and the raw sources, with numpy and shapely only, so that two solvers
cannot be wrong together. Not public API.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import flopy
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
import xarray as xr
from pyproj import CRS
from shapely.geometry import Polygon, box

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult, PointRecord, StationLocation
from hydromodpy.data.variables.geology.field import build_geology_field
from hydromodpy.physics.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.solver.boussinesq.flow_to_boussinesq_adapter import resolve_runtime_solver_mesh
from hydromodpy.solver.boussinesq.forcing_resolution import BoussinesqForcingResolver
from hydromodpy.solver.modflow6.builders import (
    bind_recharge_from_flow,
    recharge_to_spd,
    resolve_deferred_heterogeneous_recharge,
)
from hydromodpy.solver.modflow6.support.property_mapping import resolve_flow_property_arrays
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.planning.input_triangulation import (
    domain_polygon_of,
    read_input_triangulation,
)
from hydromodpy.spatial.mesh.request import MeshRequest, RasterGridSpec
from hydromodpy.spatial.raster_support import RasterSupport

REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND_MSH = (
    REPO_ROOT
    / "validation_cases/shared/mesh_bundles"
    / "dupuit_circular_island_ocean_irregular_tri_radial_48/mesh_2d.msh"
)
GRADIENT_TIF = REPO_ROOT / "tests/regression/fixtures/projects/mesh_net/recharge_gradient.tif"
"""The mesh net's recharge raster: 10 x 10 pixels of 61 m over the island, row 0 north."""

CRS_WKT = CRS.from_epsg(2154).to_wkt()
NPER = 3
DAYS = pd.date_range("2001-01-01", periods=NPER, freq="D")
WINDOW = ResolvedSimulationTimeWindow(
    start=pd.Timestamp(DAYS[0]),
    end=pd.Timestamp(DAYS[-1]),
    step_value=1,
    step_unit="day",
    coverage_policy="ignore",
)
MM_DAY_TO_M_S = 1.0e-3 / 86_400.0

K_BY_ZONE = {"A": 1.0e-4, "B": 1.0e-5, "C": 1.0e-6}
SY_BY_ZONE = {"A": 0.05, "B": 0.10, "C": 0.20}
CHARACTERISTIC_DEPTH_M = 20.0
LAYER_THICKNESS_M = (10.0, 20.0, 30.0)
"""Thickness of the three layers of the regular pair."""


@dataclass(frozen=True)
class MeshPair:
    """One cell mesh, its vertical part, its domain and the zone polygons of its geology."""

    name: str
    cell_mesh: PlanarCellMesh
    solver_mesh: SolverMesh
    domain: SimpleNamespace
    zone_polygons: dict[str, Polygon]
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class RechargeCase:
    """One recharge source with the raw numbers a hand reference needs.

    ``xy`` holds the pixel centers or the stations, ``series_mm_day`` their value
    in each of the ``NPER`` periods, ``(NPER, len(xy))``.
    """

    label: str
    method: str
    load_result: LoadResult
    xy: np.ndarray
    series_mm_day: np.ndarray


# ---------------------------------------------------------------------------
# Meshes
# ---------------------------------------------------------------------------


def _vertical_part(cell_mesh: PlanarCellMesh, thicknesses: tuple[float, ...]) -> SolverMesh:
    """A solver mesh whose top slopes unevenly, with layers of the given thicknesses."""
    n = cell_mesh.n_cells
    x, y = cell_mesh.centers.T
    top = 60.0 + 0.04 * (x - x.min()) + 0.025 * (y - y.min())
    edges = np.concatenate([[0.0], np.cumsum(thicknesses)])
    botm = top[None, :] - edges[1:, None]
    return SolverMesh(
        cell_mesh=cell_mesh,
        top=top,
        botm=botm,
        idomain=np.ones((len(thicknesses), n), dtype=int),
    )


def _geology_polygons(bounds: tuple[float, float, float, float]) -> dict[str, Polygon]:
    """Three zones that meet in a T, with a contact that crosses the mesh obliquely.

    A takes the west part. B and C share the east part along a sloping line that
    starts on the A contact, so that three zones meet at one point and the
    cells around it hold three of them. The polygons overhang the mesh by 100 m.
    """
    x0, y0, x1, y1 = bounds
    width, height = x1 - x0 + 200.0, y1 - y0 + 200.0

    def at(u: float, v: float) -> tuple[float, float]:
        return (x0 - 100.0 + u * width, y0 - 100.0 + v * height)

    return {
        "A": Polygon([at(0, 0), at(0.42, 0), at(0.42, 1), at(0, 1)]),
        "B": Polygon([at(0.42, 0.37), at(1, 0.67), at(1, 1), at(0.42, 1)]),
        "C": Polygon([at(0.42, 0), at(1, 0), at(1, 0.67), at(0.42, 0.37)]),
    }


def _domain(
    tmp_path: Path, bounds: tuple[float, float, float, float]
) -> tuple[SimpleNamespace, dict[str, Polygon]]:
    """The domain of a pair: the vector geology field, and flat surfaces for Boussinesq."""
    polygons = _geology_polygons(bounds)
    path = tmp_path / "units.gpkg"
    gpd.GeoDataFrame(
        {"CODE": list(polygons)}, geometry=list(polygons.values()), crs="EPSG:2154"
    ).to_file(str(path), driver="GPKG")
    x0, y0, x1, y1 = bounds
    support = RasterSupport(
        crs="EPSG:2154",
        dx=(x1 - x0 + 200.0) / 50,
        dy=(y1 - y0 + 200.0) / 50,
        xmin=x0 - 100.0,
        xmax=x1 + 100.0,
        ymin=y0 - 100.0,
        ymax=y1 + 100.0,
        nrows=50,
        ncols=50,
    )
    geology = build_geology_field(
        SimpleNamespace(data=str(path), source="custom"),
        geology_cfg=SimpleNamespace(
            id="geology",
            cell_samples_per_axis=8,
            sources=[SimpleNamespace(source="custom", code_field="CODE")],
        ),
        raster_support=support,
    )
    surface = SimpleNamespace(values=np.full((50, 50), 80.0), support=support)
    substratum = SimpleNamespace(values=np.full((50, 50), 0.0), support=support)
    return (
        SimpleNamespace(zones={"geology": geology}, surface_topo=surface, substratum=substratum),
        polygons,
    )


def _bounds(cell_mesh: PlanarCellMesh) -> tuple[float, float, float, float]:
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    return (
        float(vertices[:, 0].min()),
        float(vertices[:, 1].min()),
        float(vertices[:, 0].max()),
        float(vertices[:, 1].max()),
    )


def regular_pair(tmp_path: Path) -> MeshPair:
    """The 30 x 40 regular mesh of 27.7 m, on a non-integer origin, with three layers."""
    nrow, ncol, pitch = 30, 40, 27.7
    xmin, ymin = 346_512.3, 6_789_012.7
    grid = RasterGridSpec(
        xmin=xmin,
        xmax=xmin + ncol * pitch,
        ymin=ymin,
        ymax=ymin + nrow * pitch,
        dx=pitch,
        dy=pitch,
        nrow=nrow,
        ncol=ncol,
        crs_wkt=CRS_WKT,
    )
    request = MeshRequest(
        domain=box(grid.xmin, grid.ymin, grid.xmax, grid.ymax),
        grid=grid,
        nominal_size_m=pitch,
    )
    cell_mesh = registry.create("regular").build(request)
    assert cell_mesh.structured_shape == (nrow, ncol)
    bounds = _bounds(cell_mesh)
    domain, polygons = _domain(tmp_path, bounds)
    return MeshPair(
        "regular",
        cell_mesh,
        _vertical_part(cell_mesh, LAYER_THICKNESS_M),
        domain,
        polygons,
        bounds,
    )


def triangle_pair(tmp_path: Path) -> MeshPair:
    """The frozen 1200-triangle radial island, read by the ``triangle`` engine, two layers."""
    triangulation = read_input_triangulation(ISLAND_MSH)
    domain_polygon = domain_polygon_of(triangulation)
    xmin, ymin, xmax, ymax = domain_polygon.bounds
    side = max(xmax - xmin, ymax - ymin) / 10.0
    grid = RasterGridSpec(
        xmin=xmin,
        xmax=xmin + 10 * side,
        ymin=ymin,
        ymax=ymin + 10 * side,
        dx=side,
        dy=side,
        nrow=10,
        ncol=10,
        crs_wkt=CRS_WKT,
    )
    request = MeshRequest(
        domain=domain_polygon,
        grid=grid,
        nominal_size_m=side,
        input_triangulation=triangulation,
        options={},
    )
    cell_mesh = registry.create("triangle").build(request)
    bounds = _bounds(cell_mesh)
    domain, polygons = _domain(tmp_path, bounds)
    return MeshPair(
        "triangle",
        cell_mesh,
        _vertical_part(cell_mesh, LAYER_THICKNESS_M[:2]),
        domain,
        polygons,
        bounds,
    )


# ---------------------------------------------------------------------------
# Recharge sources
# ---------------------------------------------------------------------------


def _field_record(series: np.ndarray, px: np.ndarray, py: np.ndarray) -> FieldRecord:
    dataset = xr.Dataset(
        {"recharge": (("time", "y", "x"), series)},
        coords={"time": DAYS.values, "y": py, "x": px},
    )
    return FieldRecord(
        variable="recharge",
        source="test",
        unit="mm/day",
        data=dataset,
        bbox=(float(px.min()), float(py.min()), float(px.max()), float(py.max())),
        crs="EPSG:2154",
        date_start=DAYS[0],
        date_end=DAYS[-1],
        frequency="D",
        metadata={"array_name": "recharge"},
    )


def _period_scale(array: np.ndarray) -> np.ndarray:
    """``array`` of each period: the daily values grow by 30 % a day."""
    return np.stack([array * (1.0 + 0.3 * period) for period in range(NPER)])


def raster_case(pair: MeshPair, method: str = "nearest") -> RechargeCase:
    """A diagonal recharge gradient that is not symmetric, on pixels that miss the cells.

    The regular pair gets an analytic gradient on 23 x 31 pixels over the mesh
    box; the triangle pair gets the raster of the mesh net, 10 x 10 pixels of 61 m.
    """
    if pair.name == "triangle":
        with rasterio.open(GRADIENT_TIF) as source:
            values = source.read(1).astype(float)
            transform = source.transform
        px = transform.c + (np.arange(values.shape[1]) + 0.5) * transform.a
        py = transform.f + (np.arange(values.shape[0]) + 0.5) * transform.e
    else:
        x0, y0, x1, y1 = pair.bounds
        px = np.linspace(x0 - 60.0, x1 + 60.0, 23)
        py = np.linspace(y0 - 60.0, y1 + 60.0, 31)[::-1]
        u = (px[None, :] - x0) / (x1 - x0)
        v = (py[:, None] - y0) / (y1 - y0)
        values = 1.0 + 2.0 * u + 0.5 * v + 0.8 * u * v
    series = _period_scale(values)
    xx, yy = np.meshgrid(px, py, indexing="xy")
    return RechargeCase(
        label="raster",
        method=method,
        load_result=LoadResult(fields=[_field_record(series, px, py)]),
        xy=np.column_stack([xx.ravel(), yy.ravel()]),
        series_mm_day=series.reshape(NPER, -1),
    )


def station_case(pair: MeshPair, method: str) -> RechargeCase:
    """Three stations with a daily series each, read by ``nearest`` or ``idw``."""
    x0, y0, x1, y1 = pair.bounds
    fractions = np.array([[0.21, 0.33], [0.77, 0.82], [0.58, 0.14]])
    xy = np.column_stack([x0 + fractions[:, 0] * (x1 - x0), y0 + fractions[:, 1] * (y1 - y0)])
    base = np.array([1.2, 3.1, 0.7])
    series = _period_scale(base)
    records = [
        PointRecord(
            station_id=f"S{index}",
            variable="recharge",
            source="test",
            unit="mm/day",
            frequency="D",
            data=pd.DataFrame({"datetime": DAYS, "value": series[:, index]}),
            date_start=DAYS[0].to_pydatetime(),
            date_end=DAYS[-1].to_pydatetime(),
            location=StationLocation(id=f"S{index}", x=float(x), y=float(y), crs="EPSG:2154"),
        )
        for index, (x, y) in enumerate(xy)
    ]
    return RechargeCase(
        label="stations",
        method=method,
        load_result=LoadResult(points=records),
        xy=xy,
        series_mm_day=series,
    )


def recharge_cases(pair: MeshPair) -> dict[str, RechargeCase]:
    """The three recharge cases of a pair, by name."""
    return {
        "raster-nearest": raster_case(pair),
        "stations-nearest": station_case(pair, "nearest"),
        "stations-idw": station_case(pair, "idw"),
    }


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------


def make_flow(case: RechargeCase, *, profile: bool) -> Flow:
    """A transient flow with K and Sy by zone, an optional exponential K profile, and ``case``."""
    k_param: dict[str, object] = {
        "field": {
            "kind": "heterogeneous",
            "values": dict(K_BY_ZONE),
            "field_spatial_id": "geology",
        }
    }
    if profile:
        k_param["field_vertical_profile"] = {
            "kind": "exponential",
            "characteristic_depth": CHARACTERISTIC_DEPTH_M,
        }
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy", "Ss"],
                "param": {
                    "K": k_param,
                    "Sy": {
                        "field": {
                            "kind": "heterogeneous",
                            "values": dict(SY_BY_ZONE),
                            "field_spatial_id": "geology",
                        }
                    },
                    "Ss": {"field": {"kind": "homogeneous", "value": 1.0e-5}},
                },
                "ic": {"kind": "top"},
                "flow_regime": "transient",
                "first_period_steady": False,
                "sinks_sources": {"recharge": {"values": 0.0}},
            }
        )
    )
    flow.sinks_sources["recharge"].heterogeneous_source = case.load_result
    flow.sinks_sources["recharge"].interpolation_method = case.method
    return flow


# ---------------------------------------------------------------------------
# Preparation by each solver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SolverInputs:
    """What one solver hands to its solver: ``k`` and ``sy`` per layer and cell, recharge per period.

    Arrays are flat in the cell order of the mesh: ``(nlay, n_cells)``, ``(nlay, n_cells)``
    and ``{kper: (n_cells,)}``. Boussinesq has one layer, its recharge is a tuple of periods.
    """

    k: np.ndarray
    sy: np.ndarray
    recharge: dict[int, np.ndarray]


def prepare_mf6(pair: MeshPair, flow: Flow, tmp_path: Path) -> SolverInputs:
    """The NPF ``k`` and RCHA arrays of a MODFLOW 6 model, as flopy holds them.

    The property mapping and the recharge builders are the ones ``build.py``
    calls; the arrays go through a DISV grid, an NPF and an RCHA package.
    """
    solver_mesh = pair.solver_mesh
    properties = resolve_flow_property_arrays(
        flow=flow,
        domain=pair.domain,
        solver_mesh=solver_mesh,
        required_properties=frozenset({"K", "Sy", "Ss"}),
        optional_fill_values={"Sy": 0.0, "Ss": 0.0},
    )
    model = SimpleNamespace(
        flow=flow,
        recharge=None,
        first_clim=None,
        nper=NPER,
        ncpl=solver_mesh.n_cells,
        perlen=np.ones(NPER),
        steady=np.zeros(NPER, dtype=bool),
        time_grid=SimpleNamespace(window=WINDOW),
        solver_mesh=solver_mesh,
    )
    bind_recharge_from_flow(model)
    resolve_deferred_heterogeneous_recharge(model)
    spd = recharge_to_spd(model)

    simulation = flopy.mf6.MFSimulation(sim_name="one", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(simulation, nper=NPER, perioddata=[(86_400.0, 1, 1.0)] * NPER)
    gwf = flopy.mf6.ModflowGwf(simulation, modelname="one")
    flopy.mf6.ModflowGwfdisv(
        gwf, nlay=solver_mesh.nlay, **solver_mesh.to_disv_kwargs(), idomain=solver_mesh.idomain
    )
    npf = flopy.mf6.ModflowGwfnpf(gwf, k=solver_mesh.flatten_from_grid(properties["hk"]))
    sto = flopy.mf6.ModflowGwfsto(
        gwf, sy=solver_mesh.flatten_from_grid(properties["sy"]), transient={0: True}
    )
    rcha = flopy.mf6.ModflowGwfrcha(gwf, recharge=spd)
    return SolverInputs(
        k=np.asarray(npf.k.get_data(), dtype=float),
        sy=np.asarray(sto.sy.get_data(), dtype=float),
        recharge={
            kper: np.asarray(rcha.recharge.get_data(key=kper), dtype=float) for kper in range(NPER)
        },
    )


def prepare_nwt(pair: MeshPair, flow: Flow, tmp_path: Path) -> SolverInputs:
    """The UPW ``hk`` and RCH ``rech`` arrays of a MODFLOW-NWT model, as flopy holds them.

    ``FlowToModflowAdapter.build`` gives the payloads ``ModflowNwt`` passes to
    the packages; flopy keeps them in single precision, so the arrays handed
    over are returned (double precision) after a round trip that checks the
    package holds exactly their single-precision copy, row 0 north.
    """
    solver_mesh = pair.solver_mesh
    nrow, ncol = solver_mesh.structured_shape
    adapter = FlowToModflowAdapter(
        flow=flow,
        domain=pair.domain,
        solver_mesh=solver_mesh,
        nper=NPER,
        simulation_window=WINDOW,
        sink_fill=False,
    )
    inputs = adapter.build()

    model = flopy.modflow.Modflow(modelname="one", model_ws=str(tmp_path), version="mfnwt")
    flopy.modflow.ModflowDis(
        model,
        nlay=solver_mesh.nlay,
        nrow=nrow,
        ncol=ncol,
        nper=NPER,
        delr=1.0,
        delc=1.0,
        top=solver_mesh.reshape_to_grid(solver_mesh.top),
        botm=solver_mesh.reshape_to_grid(solver_mesh.botm),
        perlen=1.0,
        nstp=1,
    )
    upw = flopy.modflow.ModflowUpw(model, hk=inputs.hk, sy=inputs.sy)
    rch = flopy.modflow.ModflowRch(model, rech=inputs.rch_data)
    assert np.array_equal(upw.hk.array, inputs.hk.astype(np.float32))
    for kper in range(NPER):
        assert np.array_equal(
            rch.rech.array[kper, 0], np.asarray(inputs.rch_data[kper]).astype(np.float32)
        )
    n_layers = solver_mesh.nlay
    return SolverInputs(
        k=np.asarray(inputs.hk, dtype=float).reshape(n_layers, -1),
        sy=np.asarray(inputs.sy, dtype=float).reshape(n_layers, -1),
        recharge={
            kper: np.asarray(inputs.rch_data[kper], dtype=float).reshape(-1) for kper in range(NPER)
        },
    )


def boussinesq_setup(pair: MeshPair, flow: Flow) -> SimpleNamespace:
    """The setup state the Boussinesq flow adapter reads: the cell mesh, the flow, the domain."""
    return SimpleNamespace(
        cell_mesh=pair.cell_mesh,
        flow=flow,
        domain=pair.domain,
        mesh_summary=None,
        geographic_features=None,
    )


def prepare_boussinesq(pair: MeshPair, flow: Flow) -> SolverInputs:
    """The per-cell K, Sy and recharge series a Boussinesq model is built with."""
    mesh = resolve_runtime_solver_mesh(boussinesq_setup(pair, flow))
    resolver = BoussinesqForcingResolver(
        mesh=mesh, flow=flow, time_grid=SimpleNamespace(window=WINDOW)
    )
    series = resolver.resolve_recharge_series(NPER)
    return SolverInputs(
        k=np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float).reshape(1, -1),
        sy=np.asarray(mesh.storage_coefficient, dtype=float).reshape(1, -1),
        recharge={kper: np.asarray(series[kper], dtype=float) for kper in range(NPER)},
    )


# ---------------------------------------------------------------------------
# Hand references, from the raw polygons and the raw sources
# ---------------------------------------------------------------------------


def cell_polygons(cell_mesh: PlanarCellMesh, *, origin: tuple[float, float]) -> np.ndarray:
    """The cell polygons from the vertices and the connectivity, relative to ``origin``."""
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2] - np.asarray(origin)
    rings = [
        shapely.linearrings(vertices[ids[ids >= 0]]) for ids in cell_mesh.mesh.flat_connectivity
    ]
    return shapely.polygons(rings)


def reference_centers(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """The mean of the vertices of each cell: the center of a regular or a triangle mesh."""
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    return np.array(
        [vertices[ids[ids >= 0]].mean(axis=0) for ids in cell_mesh.mesh.flat_connectivity]
    )


def reference_zone_fractions(pair: MeshPair) -> dict[str, np.ndarray]:
    """The exact share of each cell in each zone: polygon intersection areas over cell area.

    Coordinates are taken relative to the lower-left corner of the mesh, so that
    the areas are not rounded at the 1e6 m magnitude of the northings.
    """
    origin = (pair.bounds[0], pair.bounds[1])
    cells = cell_polygons(pair.cell_mesh, origin=origin)
    areas = shapely.area(cells)
    return {
        zone: shapely.area(
            shapely.intersection(cells, shapely.transform(polygon, lambda xy: xy - origin))
        )
        / areas
        for zone, polygon in pair.zone_polygons.items()
    }


def reference_zone_values(pair: MeshPair, by_zone: dict[str, float]) -> np.ndarray:
    """The area-weighted mean of a zone value over each cell."""
    fractions = reference_zone_fractions(pair)
    return sum(fractions[zone] * value for zone, value in by_zone.items())


def reference_layer_depths(solver_mesh: SolverMesh) -> np.ndarray:
    """Depth of each layer center below the top, ``(nlay, n_cells)``."""
    layer_top = np.vstack([solver_mesh.top[None, :], solver_mesh.botm[:-1]])
    return solver_mesh.top[None, :] - 0.5 * (layer_top + solver_mesh.botm)


def reference_k(pair: MeshPair, *, profile: bool) -> np.ndarray:
    """K of every layer and cell: the zone mean times ``exp(-depth / D)`` with a profile."""
    surface = reference_zone_values(pair, K_BY_ZONE)[None, :]
    if not profile:
        return np.repeat(surface, pair.solver_mesh.nlay, axis=0)
    return surface * np.exp(-reference_layer_depths(pair.solver_mesh) / CHARACTERISTIC_DEPTH_M)


def reference_recharge(pair: MeshPair, case: RechargeCase) -> dict[int, np.ndarray]:
    """Recharge of every period at every cell center in m/s: nearest source or inverse distance."""
    centers = reference_centers(pair.cell_mesh)
    squared = ((centers[:, None, :] - case.xy[None, :, :]) ** 2).sum(axis=-1)
    if case.method == "nearest":
        nearest = squared.argmin(axis=1)
        return {kper: case.series_mm_day[kper, nearest] * MM_DAY_TO_M_S for kper in range(NPER)}
    weight = 1.0 / squared
    return {
        kper: (weight * case.series_mm_day[kper][None, :]).sum(axis=1)
        / weight.sum(axis=1)
        * MM_DAY_TO_M_S
        for kper in range(NPER)
    }


def reference_area_recharge(
    pair: MeshPair, case: RechargeCase
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """Recharge of every period in m/s as the mean of the pixels over each cell, by exact overlay.

    Returns the recharge and the mask of the cells a pixel reaches; the others
    take the nearest pixel in the code and are not referenced here.
    """
    px = np.unique(case.xy[:, 0])
    py = np.unique(case.xy[:, 1])
    half_x, half_y = 0.5 * (px[1] - px[0]), 0.5 * (py[1] - py[0])
    origin = (pair.bounds[0], pair.bounds[1])
    cells = cell_polygons(pair.cell_mesh, origin=origin)
    x = case.xy[:, 0] - origin[0]
    y = case.xy[:, 1] - origin[1]
    pixels = shapely.box(x - half_x, y - half_y, x + half_x, y + half_y)
    shared = np.array([shapely.area(shapely.intersection(cell, pixels)) for cell in cells])
    covered = shared.sum(axis=1)
    reached = covered > 0.0
    return (
        {
            kper: (shared @ case.series_mm_day[kper])
            / np.where(reached, covered, 1.0)
            * MM_DAY_TO_M_S
            for kper in range(NPER)
        },
        reached,
    )
