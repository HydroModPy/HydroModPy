"""A figure drawn from a run holds the geometry the trial scored, bit for bit.

The mesh is a grid whose cell centers are not the centroids of its polygons, as on a
Voronoi mesh whose seeds the solver sampled its top at. It holds a lake across the
mapped stream and a catchment outline that cuts the grid. The trial builds the
criterion geometry from the model it solved. The run keeps what the criterion read
(through ``run_outputs``), and the figure reads that back. The two partitions must
agree on every mask, every distance, the threshold and the signed residual J.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.observations.network_geometry import (
    heads_settings,
    network_maps_from_run,
)
from hydromodpy.catchment.drainage.descent import DescentBasin
from hydromodpy.catchment.drainage.graph import cell_centroids_from_mesh
from hydromodpy.catchment.stream_network.cost import score_on_geometry
from hydromodpy.catchment.stream_network.network import build_simulated_network
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.results.derive.stream.comparison import network_comparison_from_run
from hydromodpy.results.derive.stream.criterion_inputs import mapped_cells
from hydromodpy.results.run.descent import (
    RunDescent,
    StoredBasin,
    read_catchment_cells,
    read_criterion_recharge,
    read_open_water,
)
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.workflow.steps.run_outputs import _keep_what_the_criterion_reads
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.display._network_comparison_run import stored_descent

CRS = "EPSG:2154"
ROWS, COLUMNS, CELL = 10, 8, 100.0
N_CELLS = ROWS * COLUMNS
AXIS = 6
LAKE = [45, 53]
RECHARGE_M_S = 1.0e-8
SNAPPED_OUTLET = ((AXIS + 0.4) * CELL, (ROWS - 0.5) * CELL)

# The mapped stream bends across the grid, so the cells it crosses depend on the
# points the segments between neighbors join. It crosses the two lake cells.
STREAM = LineString(
    [
        (1.7946 * CELL, 1.2 * CELL),
        (4.6867 * CELL, 4.0 * CELL),
        (6.2076 * CELL, 6.8 * CELL),
        (6.3212 * CELL, 9.6 * CELL),
    ]
)


def _seeds(vertices, faces) -> np.ndarray:
    """The points the top was sampled at: the centroids, moved inside their cells."""
    rows, columns = np.divmod(np.arange(N_CELLS), COLUMNS)
    move_x = ((columns * 7 + rows * 3) % 5 - 2) * 0.12 * CELL
    move_y = ((columns * 5 + rows * 11) % 5 - 2) * 0.12 * CELL
    centroids = cell_centroids_from_mesh(vertices, faces)
    return centroids + np.column_stack([move_x, move_y])


def _topography() -> np.ndarray:
    rows, columns = np.divmod(np.arange(N_CELLS), COLUMNS)
    return 1000.0 - rows + 2.0 * np.abs(columns - AXIS)


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    directory = tmp_path_factory.mktemp("equal")
    vertices, faces = quad_mesh(ROWS, COLUMNS, cell_size=CELL)
    stream_file = directory / "stream.gpkg"
    gpd.GeoDataFrame(geometry=[STREAM], crs=CRS).to_file(stream_file, driver="GPKG")
    outline_file = directory / "watershed.gpkg"
    gpd.GeoDataFrame(
        geometry=[box(0.4 * CELL, 0.2 * CELL, (COLUMNS - 0.45) * CELL, ROWS * CELL)], crs=CRS
    ).to_file(outline_file, driver="GPKG")
    return SimpleNamespace(
        directory=directory,
        vertices=vertices,
        faces=faces,
        seeds=_seeds(vertices, faces),
        topography=_topography(),
        stream_file=stream_file,
        outline_file=outline_file,
    )


def _output(case, drawn_by: str):
    return validate_calib_output(
        {
            "support": "network",
            "map": {
                "complete": str(case.stream_file),
                "drawn_by": drawn_by,
                "clip_to_catchment": False,
            },
            "model": {"neighbours": "D8", "seepage_threshold": 1.0e-3},
        }
    )


def _trial_ctx(case, basin):
    solver_mesh = SimpleNamespace(
        top=case.topography,
        planar_mesh=SimpleNamespace(
            vertices=case.vertices, flat_connectivity=case.faces, n_cells=N_CELLS
        ),
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL * CELL),
        cell_centers=lambda: case.seeds,
    )
    geographic = SimpleNamespace(
        crs_project=CRS,
        watershed_shp=case.outline_file,
        x_outlet_snapped=SNAPPED_OUTLET[0],
        y_outlet_snapped=SNAPPED_OUTLET[1],
    )
    model = SimpleNamespace(
        solver_mesh=solver_mesh,
        recharge=RECHARGE_M_S,
        open_water_cell_ids=list(LAKE),
        dam_foot_cells={},
        descent_basin=basin,
    )
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6", process_type="flow"),
        state=SimpleNamespace(setup=SimpleNamespace(geographic=geographic)),
        solver_run=SimpleNamespace(solver_model=model),
    )


def _kept_store(case, ctx):
    """What ``run_outputs`` keeps of the trial's model, in a real field store."""
    path = case.directory / "fields.zarr"
    SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1).close()
    with SimulationZarr(path) as fields:
        fields.write_mesh(case.vertices, case.faces, np.zeros((2, N_CELLS)))
    store = SimpleNamespace(
        sim_id="sim-equal",
        save_zarr=True,
        fields_path=path,
        facts=SimpleNamespace(period_start=None),
        open_zarr=lambda _: SimulationZarr(path),
    )
    _keep_what_the_criterion_reads(
        ctx=SimpleNamespace(run=ctx.run, solver_run=ctx.solver_run, state=ctx.state),
        sim_id=store.sim_id,
        store=store,
    )
    return SimpleNamespace(open_zarr=store.open_zarr)


def _stored_run(case, catalog, basin_mask):
    """A run view reading the criterion inputs from the store the run kept."""
    descent_source = SimpleNamespace(
        _catalog=catalog,
        _sim_id="sim-equal",
    )
    network = gpd.GeoDataFrame(geometry=[STREAM], crs=CRS)
    stored = StoredBasin(
        mask=basin_mask, area_m2=float(basin_mask.sum()) * CELL**2, rule="near_point"
    )
    release = np.zeros(N_CELLS)
    release[[28, 62]] = 1.0
    return SimpleNamespace(
        sim_id="sim-equal",
        mesh=SimpleNamespace(
            vertices=case.vertices,
            face_node_connectivity=case.faces,
            topography=case.topography,
            crs=CRS,
            cell_centers=lambda: case.seeds,
        ),
        has_field=lambda variable, **_: variable == "release_flux",
        field=lambda variable, **_: release,
        has_hydrographic_network=lambda role="generated": role == "reference",
        hydrographic_network=lambda role="generated": network,
        _catalog=SimpleNamespace(
            read_geographic_metadata=lambda _: {
                "x_outlet_snapped": str(SNAPPED_OUTLET[0]),
                "y_outlet_snapped": str(SNAPPED_OUTLET[1]),
            }
        ),
        descent=RunDescent(
            lambda: stored_descent(case.topography, case.faces, case.vertices),
            load_basin=lambda: stored,
            load_open_water=lambda: read_open_water(descent_source),
            load_catchment_cells=lambda: read_catchment_cells(descent_source),
            load_recharge=lambda: read_criterion_recharge(descent_source),
        ),
        release=release,
    )


GEOMETRY_ARRAYS = (
    "observed",
    "catchment",
    "excluded",
    "distance_to_observed",
    "distance_to_observed_raw",
    "threshold_m3_s",
    "cell_area_m2",
)
GEOMETRY_NUMBERS = (
    "outlet",
    "h_obs_m",
    "saturation_cap_m",
    "mean_recharge_m_s",
    "catchment_mismatch",
    "basin_mismatch",
    "alpha_obs_closure",
    "alpha_obs_closure_catchment",
)


@pytest.mark.parametrize("drawn_by", ["crossing", "heads", "touch"])
def test_the_figure_scores_the_geometry_the_trial_scored(case, drawn_by) -> None:
    basin = DescentBasin(
        mask=np.ones(N_CELLS, dtype=bool),
        outlet=int(SNAPPED_OUTLET[1] // CELL) * COLUMNS + AXIS,
        rule="near_point",
        area_m2=N_CELLS * CELL * CELL,
        seeded_at_outlet=False,
    )
    ctx = _trial_ctx(case, basin)
    trial = network_maps_from_run(ctx, _output(case, drawn_by)).maximal
    run = _stored_run(case, _kept_store(case, ctx), basin.mask)
    knobs = {}
    if drawn_by == "heads":
        settings = heads_settings(_output(case, drawn_by))
        knobs = {
            "heads_snap_radius_m": settings.snap_radius_m,
            "heads_min_drained_area_km2": settings.min_drained_area_m2 / 1.0e6,
        }

    figure = network_comparison_from_run(
        run,
        tau_specific_ratio=1.0e-3,
        diagonal_neighbors=True,
        observed_rasterization=drawn_by,
        clip_map_to_catchment=False,
        **knobs,
    ).geometry

    assert trial.excluded is not None and trial.excluded.sum() == len(LAKE)
    for name in GEOMETRY_ARRAYS:
        np.testing.assert_array_equal(getattr(figure, name), getattr(trial, name), err_msg=name)
    for name in GEOMETRY_NUMBERS:
        expected = getattr(trial, name)
        got = getattr(figure, name)
        assert (np.isnan(expected) and np.isnan(got)) or got == expected, name

    simulated = build_simulated_network(
        run.release, threshold_m3_s=trial.threshold_m3_s, metric=trial.metric
    )
    assert simulated.network.sum() > 1
    scored_by_figure = score_on_geometry(simulated, figure)
    scored_by_trial = score_on_geometry(simulated, trial)
    assert scored_by_figure.signed_gap == scored_by_trial.signed_gap
    assert scored_by_figure.components == scored_by_trial.components


def test_the_seeds_and_the_centroids_would_not_have_drawn_one_map(case) -> None:
    """The case has power: the old figure routed on the centroids and drew another map."""
    polygons = cell_polygons(case.vertices, case.faces)
    centroids = cell_centroids_from_mesh(case.vertices, case.faces)
    common = {
        "polygons": polygons,
        "vertices": case.vertices,
        "connectivity": case.faces,
        "mesh_crs": CRS,
        "geometry_crs": CRS,
    }

    by_seeds = mapped_cells("crossing", [STREAM], centres=case.seeds, **common).mask
    by_centroids = mapped_cells("crossing", [STREAM], centres=centroids, **common).mask

    assert not np.array_equal(by_seeds, by_centroids)
