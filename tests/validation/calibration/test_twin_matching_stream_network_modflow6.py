"""Twin experiment for the stream-network criterion of Abherve et al. (2023).

Compared with: the hydraulic conductivity of the run that produced the mapped network.

A model run with a known conductivity produces a seepage network. That network,
written as the mapped one, must bring a network-only bisection back to the
conductivity that produced it. Nothing else in the suite runs the criterion end
to end on a real solve: the unit tests fake the trial context, and a real
catchment has no known answer.

The catchment is a planar hillslope, one row of 400 square cells of 2 m, over a
30 m aquifer parallel to the surface. Under uniform recharge ``R`` the water
table reaches the surface where the recharge collected upslope exceeds what the
full aquifer can carry, ``K * d * slope``: the seepage face starts at about
``K d s / R`` from the divide, so the network retracts by one cell per
``cell / (K d s / R)`` of relative K, about 0.56 per cent here. That step is the
resolution of the criterion. It is kept below the one per cent the bisection
stops on, so the recovered value can be held to that one per cent whether the
search lands on the zero plateau or closes its bracket around it.

The drains sit on the surface with the fallback conductance, proportional to K,
which is what makes the network a function of K/R alone. The mapped network is
the downstream closure of the seepage cells, built by the same functions the
criterion calls, and its round trip through the GPKG back onto the mesh is
checked cell for cell before any calibration runs. The round trip goes through
the resolver and ``observed_network_mask`` under the crossing rule, the route a
``stream_geometry_path`` takes in a calibration trial. The calibration sets that
rule: the default, ``heads``, needs a drained area this hillslope never reaches.

What this twin cannot see: on a single row no two network cells meet only at a
corner, so the crossing and the touch rules give the same mask here. The
diagonal-step bias the crossing rule exists to remove is covered by the unit
tests of ``line_crossing_cell_mask``, not by this experiment.

Four solver columns run the same hillslope. MODFLOW-NWT and MODFLOW 6 on its
structured grid use the 400 square cells. The triangle column splits each of
those squares into two triangles of the same strip (800 cells), and the Voronoi
column puts a cell on each node of that triangulation (802 cells, two rows of
nodes on the strip borders). On an unstructured mesh the mapped network is the
polyline through the cell centres of the reach, in order downslope, which the
crossing rule gives back cell for cell. The centres are the polygon centroids
of the triangles and the generator nodes of the Voronoi cells, the points the
criterion samples the top at. The 30 m aquifer, the slope and the recharge are
the same, so the seepage face starts near the same 357 m from the divide. The
two rows of Voronoi nodes sit at one elevation and do not drain into each other,
so the criterion scores the catchment of one row, 401 of the 802 cells.

Tolerances: ``tests/TOLERANCES.md``, rows 76 to 79, for every column. They are
properties of the criterion, a bisection to one per cent on a network drawn on
the cells, and not of the solver.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyproj
import pytest

from hydromodpy.core.stream_geometry import neighbour_spacing_m
from tests._helpers.tolerances import tol
from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.shared.boussinesq_uniform_strip import write_uniform_strip_bundle
from validation_cases.shared.gmsh_irregular_strip import write_gmsh22_triangle_mesh_from_bundle_csv
from validation_cases.shared.loaders import bundle_cell_centers

NOT_APPLICABLE = {
    "boussinesq": (
        "The Boussinesq adapter declares release_flux servable but extract_observables serves only head and discharge, so the stream-network criterion cannot score a Boussinesq trial. The PETSc engine also needs 3000 iterations to solve this hillslope."
    ),
    "boussinesq_local": (
        "The Boussinesq adapter declares release_flux servable but extract_observables serves only head and discharge, so the stream-network criterion cannot score a Boussinesq trial. The sparse Newton method of the default engine also fails on this 800-cell hillslope."
    ),
}

gpd = pytest.importorskip("geopandas")
shapely_geometry = pytest.importorskip("shapely.geometry")
Point = shapely_geometry.Point

pytestmark = [
    pytest.mark.validation,
    pytest.mark.steady,
]

SOLVERS = [
    pytest.param(
        "modflow_nwt",
        id="modflow_nwt",
        marks=[pytest.mark.nwt, pytest.mark.xdist_group(name="twin_matching_stream_nwt")],
    ),
    pytest.param(
        "modflow6",
        id="modflow6",
        marks=[pytest.mark.mf6, pytest.mark.xdist_group(name="twin_matching_stream_mf6")],
    ),
    pytest.param(
        "modflow6_irregular_tri",
        id="modflow6_irregular_tri",
        marks=[
            pytest.mark.mf6,
            pytest.mark.slow,
            pytest.mark.xdist_group(name="twin_matching_stream_tri"),
        ],
    ),
    pytest.param(
        "modflow6_voronoi",
        id="modflow6_voronoi",
        marks=[
            pytest.mark.mf6,
            pytest.mark.slow,
            pytest.mark.xdist_group(name="twin_matching_stream_voronoi"),
        ],
    ),
]
"""The solver columns of the twin. Another column is one more entry here, one
more block in ``_SOLVER_BLOCKS`` and, for a mesh, one in ``_write_bundle``."""

CRS = "EPSG:2154"
OUTPUT = "seepage_network"

K_TRUE_M_S = 6.0e-6
"""K/R = 600. Chosen so the seepage face starts near 360 m, inside the 800 m
hillslope, and so no sweep point of the bracket below falls on it."""

RECHARGE_MM_DAY = 0.864
RECHARGE_M_S = 1.0e-8
RECHARGE_REL = {
    "modflow_nwt": tol(
        "twin_stream_network_calibration_modflow_nwt__recharge_read_back_from_the_solver_files_rel_against_the_input"
    )
}
"""Relative error of the recharge read back from the solver files. MODFLOW 6 writes
double precision and returns the input to 1e-9. MODFLOW-NWT writes its flow terms
in single precision, whose rounding is 6e-8."""
RECHARGE_REL_DEFAULT = 1.0e-9
THICKNESS_M = 30.0
N_CELLS = 400
CELL_M = 2.0

K_BOUNDS_M_S = (7.0e-7, 3.0e-5)
"""0.93 decade below the truth and 0.70 above it: 1.63 decades, not centred.
At the lower bound the network covers 95 per cent of the hillslope, at the upper
one the last three cells of the toe: an excess at one end, a deficit at the
other, as a root search needs."""

REL_TOL = 0.01
"""The paper's one per cent on K/R, the bisection's stopping width."""

K_RECOVERY_REL = tol("twin_stream_network_calibration_mf6_planar_hillslope_400_cells")
"""TOLERANCES.md row 76."""

D_SAT_REL = tol("d_sat_m_at_the_returned_trial_against_the_truth_run")
"""TOLERANCES.md row 78."""

IDENTITY_REL = tol("k_optim_m_s_k_over_r_t_over_r_m_t_optim_m2_s")
"""TOLERANCES.md row 79: the report's ratios are products of what it read."""

_PROJECT_TOML = """\
[workflow]
mode = "{mode}"

[simulation]
name = "{name}"

[[simulation.process]]
id = "flow"
type = "flow"
solvers = ["{solver_id}"]

# The round trip compares the recharge read back to 1e-9: compact storage
# keeps 16 mantissa bits, about 1e-5.
[simulation.results.persistence]
field_precision = "exact"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "{crs}"

[geographic.synthetic]
case_id = "twin_matching_stream_network"

[geographic.synthetic.grid]
length_x = "{length_m} m"
length_y = "{cell_m} m"
nx = {n_cells}
ny = 1

# 16 m of drop between the first and last cell centres: slope 0.02.
[geographic.synthetic.topography]
kind = "linear"
base_elevation = 50.0
right_to_left_amplitude = 16.0

[domain.depth_model]
kind = "constant_thickness"
thickness = "{thickness_m} m"

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = {k_m_s!r}

[flow.ic]
type = "top"

# A conductance of zero selects the fallback K * cell area / bed thickness,
# the one that keeps the network a function of K/R.
[flow.bc.drainage]
application_domain = "top"
kind = "cauchy"
value = "0.0 m2/s"

[flow.sinks_sources.recharge]
first_clim = "mean"

[data]
types = ["recharge"]
inference_mode = "warn"

[[data.recharge.sources]]
source = "synthetic"
values = [{recharge_mm_day!r}]
runoff_ratio = 0.0

{solver_blocks}
[display]
enabled = false
"""

_MODFLOW6_RUNTIME = """\
[modflow6.runtime]
mf_verbose = false
mf6_ims_complexity = "COMPLEX"
"""

_MESH_RUNTIME = (
    _MODFLOW6_RUNTIME
    + """\
# On these thin strips the 500 outer iterations of the COMPLEX preset do not
# converge at K above about 1e-5 m/s, where the seepage face retreats to the
# toe, and the default ILUT fill moves the network by 10 cells at 1.2e-5 m/s
# against a complete factorization (a fill wider than the band, no drop).
mf6_outer_maximum = 2000
mf6_preconditioner_levels = 50
mf6_preconditioner_drop_tolerance = 0.0
"""
)

_SOLVER_BLOCKS = {
    "modflow_nwt": """\
[mesh.regular]
shape = [1, {n_cells}]

[modflownwt.sgrid.vertical]
nlay = 1
""",
    "modflow6": _MODFLOW6_RUNTIME
    + """\

[mesh.regular]
shape = [1, {n_cells}]

[modflow6.sgrid.vertical]
nlay = 1
""",
    "modflow6_irregular_tri": _MESH_RUNTIME
    + """\

[modflow6.sgrid.vertical]
nlay = 1

[mesh]
engine = "triangle"

[mesh.triangle]
path = "{bundle_dir}/mesh_2d.msh"
""",
    "modflow6_voronoi": _MESH_RUNTIME
    + """\
[modflow6.sgrid.vertical]
nlay = 1

[mesh]
engine = "voronoi"

[mesh.triangle]
path = "{bundle_dir}/mesh_2d.msh"

[mesh.voronoi]
seeds = "triangulation"
""",
}
"""The solver section of the project, per column. The two meshes share one bundle."""

_SOLVER_IDS = {
    "modflow_nwt": "modflow_nwt",
    "modflow6": "modflow6",
    "modflow6_irregular_tri": "modflow6",
    "modflow6_voronoi": "modflow6",
}
"""The ``solvers`` entry of the process, per column."""

_CALIBRATION_TOML = """
[calibration]
method = "bisection"
max_iter = 20
tolerance = {rel_tol!r}
save_runs = "none"

[calibration.method_options]
sweep_points = 7

[calibration.parameters.K]
bounds = [{k_low!r}, {k_high!r}]

[calibration.outputs.{output}]
support = "network"
stream_geometry_path = "{mapped}"
# The twin checks the crossing rule. Under the heads rule the one head of the
# map needs 0.02 km2 drained; the whole hillslope drains 0.0016 km2.
observed_rasterization = "crossing"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["{output}"]
"""


def _write_bundle(root: Path) -> Path:
    """Write the triangle strip of the unstructured columns and return its folder.

    The strip is the 800 m by 2 m hillslope cut in 400 squares of 2 m, each
    split in two triangles. The topography does not come from the bundle: the
    synthetic geography of the project gives the slope to every column, so the
    columns differ by the mesh only. The bundle elevations are placeholders.
    """
    bundle_dir = root / "strip_bundle"
    write_uniform_strip_bundle(
        bundle_dir,
        nx=N_CELLS,
        ny=1,
        length_x_m=N_CELLS * CELL_M,
        width_y_m=CELL_M,
        z_top_m=50.0,
        z_bottom_m=20.0,
        hydraulic_conductivity_m_s=K_TRUE_M_S,
        storage_coefficient=0.1,
    )
    write_gmsh22_triangle_mesh_from_bundle_csv(bundle_dir)
    return bundle_dir


def _project_toml(
    *, solver: str, mode: str, name: str, k_m_s: float, bundle_dir: Path | None = None
) -> str:
    blocks = _SOLVER_BLOCKS[solver].format(
        n_cells=N_CELLS,
        bundle_dir=None if bundle_dir is None else bundle_dir.as_posix(),
    )
    return _PROJECT_TOML.format(
        solver_id=_SOLVER_IDS[solver],
        solver_blocks=blocks,
        mode=mode,
        name=name,
        crs=CRS,
        length_m=N_CELLS * CELL_M,
        cell_m=CELL_M,
        n_cells=N_CELLS,
        thickness_m=THICKNESS_M,
        k_m_s=float(k_m_s),
        recharge_mm_day=RECHARGE_MM_DAY,
    )


@dataclass(frozen=True)
class Truth:
    """What the run at K_true says, and the mapped network written from it."""

    network: np.ndarray
    seepage: np.ndarray
    catchment: np.ndarray
    polygons: np.ndarray
    centres: np.ndarray
    mesh_crs: str
    recharge_m_s: float
    d_sat_m: float
    cell_spacing_m: float
    mapped_path: Path
    projected_back: np.ndarray
    bundle_dir: Path | None


def _cell_centres(solver: str, polygons: np.ndarray, bundle_dir: Path | None) -> np.ndarray:
    """Return the points the criterion samples the top at, one per cell.

    The polygon centroids on the grid and the triangles, the generator nodes of
    the bundle on the Voronoi mesh, whose polygon centroids are not its centres.
    """
    if solver != "modflow6_voronoi":
        return np.asarray([[p.centroid.x, p.centroid.y] for p in polygons], dtype=float)
    centres, kind = bundle_cell_centers(bundle_dir, len(polygons))
    assert kind == "voronoi", kind
    inside = [bool(p.buffer(1e-9).contains(Point(x, y))) for p, (x, y) in zip(polygons, centres)]
    assert all(inside), "each bundle node must lie in the Voronoi polygon of the same index"
    return centres


def _simulated_network(
    sim: Any, solver: str, bundle_dir: Path | None
) -> tuple[Any, Any, np.ndarray, np.ndarray, np.ndarray, float]:
    """Build the network of a finished run with the criterion's own functions.

    The mapped network does not enter the simulated one: it only feeds the
    distances. The geometry builder still wants a non-empty mask, so every
    cell is passed. The defaults are the calibration output's, read from the
    same model it reads them from.
    """
    from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
    from hydromodpy.core.stream_geometry import build_network_geometry
    from hydromodpy.core.stream_network import build_simulated_network
    from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons

    mesh = sim.mesh
    vertices = np.asarray(mesh.vertices, dtype=float)
    connectivity = np.asarray(mesh.face_node_connectivity)
    topography = np.asarray(mesh.topography, dtype=float).reshape(-1)
    polygons = cell_polygons(vertices, connectivity)
    areas = np.asarray([polygon.area for polygon in polygons], dtype=float)
    centroids = _cell_centres(solver, polygons, bundle_dir)

    # Read back from the budget the solver wrote, as the results layer does.
    recharge = np.asarray(sim.field("recharge", timestep=-1), dtype=float).reshape(-1)
    recharge_m_s = float(np.mean(recharge / areas))

    geometry = build_network_geometry(
        topography=topography,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=np.ones(topography.size, dtype=bool),
        cell_area_m2=areas,
        cell_centroids=centroids,
        mean_recharge_m_s=recharge_m_s,
        tau_specific_ratio=STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
        diagonal_neighbors=STREAM_CRITERION_DEFAULTS.diagonal_neighbors,
    )
    release = np.asarray(sim.field("release_flux", timestep=-1), dtype=float).reshape(-1)
    simulated = build_simulated_network(
        release, threshold_m3_s=geometry.threshold_m3_s, metric=geometry.metric
    )
    return simulated, geometry, polygons, topography, centroids, recharge_m_s


def _mapped_lines(network: np.ndarray, centres: np.ndarray, *, grid: bool) -> list[Any]:
    """The lines that draw the network, through the centres of its cells.

    On a grid, one line per contiguous run of network cells along a row. Each
    line joins the first and last cell centres of its run. It runs along the
    centre segments inside the run and crosses the half medians of the row
    border only at those centres, so the crossing rule marks exactly the cells
    of the run. A run of one cell gets a segment a quarter of a cell on each
    side of its centre, which crosses its half medians at the centre.

    On a triangulation or a Voronoi mesh the cells of the reach, taken in order
    downslope, form one path in which each cell shares an edge with the next
    one, or meets it at a corner of four network cells. One line joins all the
    centres. It crosses the face graph at those centres and along the segments
    that join them, where it keeps the cells it joins.
    """
    from shapely.geometry import LineString

    if not grid:
        reach = np.flatnonzero(network)
        reach = reach[np.lexsort((centres[reach, 1], centres[reach, 0]))]
        return [LineString(centres[reach])]

    lines = []
    for row_y in np.unique(np.round(centres[:, 1], 6)):
        in_row = np.flatnonzero(np.isclose(centres[:, 1], row_y))
        in_row = in_row[np.argsort(centres[in_row, 0])]
        flags = network[in_row]
        start = None
        for position, flag in enumerate([*flags, False]):
            if flag and start is None:
                start = position
            elif not flag and start is not None:
                first, last = in_row[start], in_row[position - 1]
                (x0, y0), (x1, y1) = centres[first], centres[last]
                if first == last:
                    x0, x1 = x0 - CELL_M / 4.0, x0 + CELL_M / 4.0
                lines.append(LineString([(x0, y0), (x1, y1)]))
                start = None
    return lines


def _project_as_the_criterion_does(
    mapped_path: Path, *, vertices: np.ndarray, connectivity: np.ndarray, centres: np.ndarray
) -> np.ndarray:
    """Project the GPKG onto the mesh by the route a calibration trial takes.

    The output is the validated config model, the file is read by the
    resolver, and the mask comes from ``observed_network_mask`` under its
    default rule, the crossing one. The run context only lends the declared
    CRS; the centres are the ones the cell mask samples the top at.
    """
    from types import SimpleNamespace

    from hydromodpy.calibration.config import CalibOutputNetwork
    from hydromodpy.calibration.observations.network_source import resolve_observed_network
    from hydromodpy.calibration.observations.observed_network import observed_network_mask

    output = CalibOutputNetwork(support="network", stream_geometry_path=mapped_path.as_posix())
    run_ctx = SimpleNamespace(
        state=SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(crs_project=CRS)))
    )
    observed = resolve_observed_network(run_ctx, output)
    return np.asarray(
        observed_network_mask(
            run_ctx,
            observed,
            SimpleNamespace(vertices=vertices),
            connectivity,
            cell_centres=centres,
        ).mask,
        dtype=bool,
    )


def _truth(root: Path, solver: str) -> Truth:
    from hydromodpy.physics.flow.history_contract import saturated_thickness_from_head_history
    from hydromodpy.project.facade import Project

    bundle_dir = _write_bundle(root) if _SOLVER_BLOCKS[solver].count("{bundle_dir}") else None
    config = root / "truth.toml"
    config.write_text(
        _project_toml(
            solver=solver,
            mode="simulation",
            name="twin_network_truth",
            k_m_s=K_TRUE_M_S,
            bundle_dir=bundle_dir,
        ),
        encoding="utf-8",
    )
    project = Project(config, no_display=True)
    try:
        sim = project.simulate()
        simulated, geometry, polygons, topography, centres, recharge_m_s = _simulated_network(
            sim, solver, bundle_dir
        )
        head = np.asarray(sim.field("head", timestep=-1), dtype=float).reshape(1, -1)
        mesh = sim.mesh
        mesh_crs = str(mesh.crs)
        vertices = np.asarray(mesh.vertices, dtype=float)
        connectivity = np.asarray(mesh.face_node_connectivity)
    finally:
        project.close()

    # The catchment is the cells whose descent reaches the outlet, the whole
    # strip here, and d_sat is the mean over them weighted by cell area, like
    # the extractor's. On equal cells that is the plain mean.
    thickness = saturated_thickness_from_head_history(
        head, top_m=topography, bottom_m=topography - THICKNESS_M
    )[-1]
    catchment = np.asarray(geometry.catchment, dtype=bool)
    areas = np.asarray(geometry.cell_area_m2, dtype=float)
    kept = catchment & np.isfinite(thickness)
    d_sat = float((thickness[kept] * areas[kept]).sum() / areas[kept].sum())

    lines = _mapped_lines(simulated.network, centres, grid=bundle_dir is None)
    mapped_path = root / "mapped_network.gpkg"
    gpd.GeoDataFrame(geometry=lines, crs=CRS).to_file(mapped_path, driver="GPKG")
    projected_back = _project_as_the_criterion_does(
        mapped_path, vertices=vertices, connectivity=connectivity, centres=centres
    )
    return Truth(
        network=simulated.network,
        seepage=simulated.seepage,
        catchment=catchment,
        polygons=polygons,
        centres=centres,
        mesh_crs=mesh_crs,
        recharge_m_s=recharge_m_s,
        d_sat_m=d_sat,
        cell_spacing_m=neighbour_spacing_m(centres, connectivity, touching=simulated.network),
        mapped_path=mapped_path,
        projected_back=projected_back,
        bundle_dir=bundle_dir,
    )


_RUNS: dict[str, tuple[Truth, Any]] = {}
"""Truth and calibration report per column, so the two tests of a column share one run."""


def _require_executables(solver: str) -> None:
    assert_required_executables(
        require_modflow=solver == "modflow_nwt",
        require_modflow6=solver.startswith("modflow6"),
        require_modpath=False,
        require_mt3dms=False,
    )


@pytest.fixture
def truth(solver: str, tmp_path_factory: pytest.TempPathFactory) -> Truth:
    if solver not in _RUNS:
        _require_executables(solver)
        built = _truth(tmp_path_factory.mktemp(f"twin_network_{solver}"), solver)
        _RUNS[solver] = (built, None)
    return _RUNS[solver][0]


@pytest.fixture
def report(solver: str, truth: Truth) -> Any:
    import hydromodpy as hmp

    if _RUNS[solver][1] is None:
        root = truth.mapped_path.parent
        config = root / "calibration.toml"
        # The value under [flow.param.K.field] is not the truth: the search owns K.
        config.write_text(
            _project_toml(
                solver=solver,
                mode="calibration",
                name="twin_network_calibration",
                k_m_s=1.0e-5,
                bundle_dir=truth.bundle_dir,
            )
            + _CALIBRATION_TOML.format(
                rel_tol=REL_TOL,
                k_low=K_BOUNDS_M_S[0],
                k_high=K_BOUNDS_M_S[1],
                output=OUTPUT,
                mapped=truth.mapped_path.as_posix(),
            ),
            encoding="utf-8",
        )
        _RUNS[solver] = (truth, hmp.calibrate(config, return_report=True))
    return _RUNS[solver][1]


def _metrics_of(report: Any, k_value: float) -> dict[str, float]:
    """Return the published components of the trial evaluated at ``k_value``."""
    rows = report.iterations
    for _, row in rows.iterrows():
        if math.isclose(float(row["params"]["K"]["value"]), k_value, rel_tol=1e-12):
            return dict(row["metrics"])
    raise AssertionError(f"no trial at K = {k_value!r} among {len(rows)} iterations.")


def _metric(metrics: dict[str, float], key: str) -> float:
    return float(metrics[f"{OUTPUT}.{key}"])


@pytest.mark.parametrize("solver", SOLVERS)
def test_the_mapped_network_projects_back_onto_the_cells_it_was_written_from(
    solver: str, truth: Truth
) -> None:
    """The observation must be the truth network, not a rasterised neighbour of it."""
    n_cells = truth.network.size
    n_network = int(truth.network.sum())
    # A face that starts inside the hillslope and runs to its toe: neither empty
    # nor the whole row, so both an excess and a deficit remain possible.
    assert 0.1 * n_cells < n_network < 0.9 * n_cells, n_network
    toe = np.isclose(truth.centres[:, 0], truth.centres[:, 0].max())
    assert truth.seepage[toe].all(), "the toe must seep: it is where the network closes."
    downstream = truth.centres[:, 0] >= truth.centres[truth.network, 0].min()
    assert truth.network[downstream].all(), "one contiguous reach"

    mismatched = np.flatnonzero(truth.projected_back != truth.network)
    assert mismatched.size == 0, f"cells differing after the round trip: {mismatched.tolist()}"
    # The seal writes the projection as WKT: compare the projections, not the text.
    assert pyproj.CRS.from_user_input(truth.mesh_crs) == pyproj.CRS.from_user_input(CRS)
    assert math.isclose(
        truth.recharge_m_s, RECHARGE_M_S, rel_tol=RECHARGE_REL.get(solver, RECHARGE_REL_DEFAULT)
    )


@pytest.mark.parametrize("solver", SOLVERS)
def test_a_network_only_bisection_recovers_the_conductivity_that_made_the_network(
    solver: str, truth: Truth, report: Any
) -> None:
    """K back to one per cent, J near zero, and the paper's ratios at that K."""
    search = report.extra["search"]
    assert search["converged"] is True, search
    bracket = report.extra["bracket"]
    assert bracket["closed"] is True, bracket
    assert bracket["relative_width"] <= REL_TOL, bracket

    k_hat = float(report.best_parameters["K"])
    assert_metric_below(
        "Relative error of the recovered K",
        abs(k_hat / K_TRUE_M_S - 1.0),
        K_RECOVERY_REL,
        inclusive=True,
    )

    best = _metrics_of(report, k_hat)
    # The criterion scored the network the GPKG holds, projected by its own
    # route: the same count of mapped cells inside its catchment, all reached.
    # The catchment is the whole strip but on the Voronoi mesh, whose two rows
    # of nodes sit at one elevation and so do not drain into each other.
    assert _metric(best, "n_network_obs") == float((truth.network & truth.catchment).sum())
    assert _metric(best, "frac_unreachable_so") == 0.0
    # TOLERANCES.md row 77: a stream cannot move by less than one cell.
    cell_spacing = _metric(best, "cell_spacing_m")
    assert math.isclose(cell_spacing, truth.cell_spacing_m, rel_tol=1e-9)
    if solver in ("modflow_nwt", "modflow6"):
        assert math.isclose(cell_spacing, CELL_M, rel_tol=1e-9)
    assert_metric_below(
        "Signed distance gap at the best K",
        abs(_metric(best, "J_signed")),
        cell_spacing,
        unit="m",
        inclusive=True,
    )
    assert report.best_objective <= cell_spacing

    # The sweep sees the sign structure the root search rests on: an excess of
    # simulated stream at the lower bound, a deficit at the upper one.
    assert _metric(_metrics_of(report, K_BOUNDS_M_S[0]), "J_signed") > 0.0
    assert _metric(_metrics_of(report, K_BOUNDS_M_S[1]), "J_signed") < 0.0

    verdict = report.extra["roptim_verdict"][OUTPUT]
    assert verdict["valid"] is True, verdict

    extra = report.extra
    recharge = _metric(best, "R_mean_m_s")
    assert math.isclose(
        recharge,
        truth.recharge_m_s,
        rel_tol=RECHARGE_REL.get(solver, RECHARGE_REL_DEFAULT),
    )
    assert math.isclose(extra["k_optim_m_s"], k_hat, rel_tol=IDENTITY_REL)
    assert math.isclose(extra["k_over_r"], k_hat / recharge, rel_tol=IDENTITY_REL)
    assert abs(extra["k_over_r"] / (K_TRUE_M_S / RECHARGE_M_S) - 1.0) <= K_RECOVERY_REL

    d_sat = extra["d_sat_m"]
    assert math.isclose(d_sat, _metric(best, "d_sat_m"), rel_tol=IDENTITY_REL)
    assert 0.0 < d_sat <= THICKNESS_M
    assert_metric_below(
        "Relative error of the saturation length",
        abs(d_sat / truth.d_sat_m - 1.0),
        D_SAT_REL,
        inclusive=True,
    )
    assert math.isclose(extra["t_over_r_m"], extra["k_over_r"] * d_sat, rel_tol=IDENTITY_REL)
    assert math.isclose(extra["t_optim_m2_s"], k_hat * d_sat, rel_tol=IDENTITY_REL)
