"""Twin experiment for the stream-network criterion of Abherve et al. (2023).

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
the resolver and ``observed_network_mask`` under its default crossing rule,
the route a ``stream_geometry_path`` takes in a calibration trial.

What this twin cannot see: on a single row no two network cells meet only at a
corner, so the crossing and the touch rules give the same mask here. The
diagonal-step bias the crossing rule exists to remove is covered by the unit
tests of ``line_crossing_cell_mask``, not by this experiment.

Tolerances: ``tests/TOLERANCES.md``, rows 76 to 79.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests._helpers.tolerances import tol
from tests.regression.golden_utils import assert_required_executables

gpd = pytest.importorskip("geopandas")
shapely_geometry = pytest.importorskip("shapely.geometry")

pytestmark = [
    pytest.mark.validation,
    pytest.mark.steady,
    pytest.mark.mf6,
    pytest.mark.xdist_group(name="twin_matching_stream_network"),
]

CRS = "EPSG:2154"
OUTPUT = "seepage_network"

K_TRUE_M_S = 6.0e-6
"""K/R = 600. Chosen so the seepage face starts near 360 m, inside the 800 m
hillslope, and so no sweep point of the bracket below falls on it."""

RECHARGE_MM_DAY = 0.864
RECHARGE_M_S = 1.0e-8
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
solvers = ["modflow6"]

[simulation.results.derived]
release_flux = true

[simulation.results.budget]
spatial_fields = true

[workspace]
project_root = "."

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

[modflow6.runtime]
mf_verbose = false
mf6_ims_complexity = "COMPLEX"

[modflow6.sgrid.planar]
mode = "resample_to_shape"
nx = {n_cells}
ny = 1
resampling = "nearest"

[modflow6.sgrid.vertical]
nlay = 1

[display]
enabled = false
"""

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

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["{output}"]
"""


def _project_toml(*, mode: str, name: str, k_m_s: float) -> str:
    return _PROJECT_TOML.format(
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
    polygons: np.ndarray
    mesh_crs: str
    recharge_m_s: float
    d_sat_m: float
    mapped_path: Path
    projected_back: np.ndarray


def _simulated_network(sim: Any) -> tuple[Any, np.ndarray, np.ndarray, float]:
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
    centroids = np.asarray([[p.centroid.x, p.centroid.y] for p in polygons], dtype=float)

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
    return simulated, polygons, topography, recharge_m_s


def _mapped_lines(network: np.ndarray, polygons: np.ndarray) -> list[Any]:
    """One line per contiguous run of network cells along a grid row.

    Each line joins the first and last cell centres of its run. It runs along
    the centre segments inside the run and crosses the half medians of the row
    border only at those centres, so the crossing rule marks exactly the cells
    of the run. A run of one cell gets a segment a quarter of a cell on each
    side of its centre, which crosses its half medians at the centre.
    """
    from shapely.geometry import LineString

    centres = np.asarray([[p.centroid.x, p.centroid.y] for p in polygons], dtype=float)
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
    CRS; the centres are the polygon centroids, which on this structured grid
    are the centres MODFLOW 6 sampled the top at.
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


def _truth(root: Path) -> Truth:
    from hydromodpy.physics.flow.history_contract import saturated_thickness_from_head_history
    from hydromodpy.project.facade import Project

    config = root / "truth.toml"
    config.write_text(
        _project_toml(mode="simulation", name="twin_network_truth", k_m_s=K_TRUE_M_S),
        encoding="utf-8",
    )
    project = Project(config, no_display=True)
    try:
        sim = project.simulate()
        simulated, polygons, topography, recharge_m_s = _simulated_network(sim)
        head = np.asarray(sim.field("head", timestep=-1), dtype=float).reshape(1, -1)
        mesh = sim.mesh
        mesh_crs = str(mesh.crs)
        vertices = np.asarray(mesh.vertices, dtype=float)
        connectivity = np.asarray(mesh.face_node_connectivity)
        centres = np.asarray([[p.centroid.x, p.centroid.y] for p in polygons], dtype=float)
    finally:
        project.close()

    # The catchment is the whole row here: the outlet is its toe and every
    # cell descends to it. d_sat is then the plain mean over the mesh.
    thickness = saturated_thickness_from_head_history(
        head, top_m=topography, bottom_m=topography - THICKNESS_M
    )
    lines = _mapped_lines(simulated.network, polygons)
    mapped_path = root / "mapped_network.gpkg"
    gpd.GeoDataFrame(geometry=lines, crs=CRS).to_file(mapped_path, driver="GPKG")
    projected_back = _project_as_the_criterion_does(
        mapped_path, vertices=vertices, connectivity=connectivity, centres=centres
    )
    return Truth(
        network=simulated.network,
        seepage=simulated.seepage,
        polygons=polygons,
        mesh_crs=mesh_crs,
        recharge_m_s=recharge_m_s,
        d_sat_m=float(np.nanmean(thickness)),
        mapped_path=mapped_path,
        projected_back=projected_back,
    )


@pytest.fixture(scope="module")
def truth(tmp_path_factory: pytest.TempPathFactory) -> Truth:
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    return _truth(tmp_path_factory.mktemp("twin_network"))


@pytest.fixture(scope="module")
def report(truth: Truth) -> Any:
    import hydromodpy as hmp

    root = truth.mapped_path.parent
    config = root / "calibration.toml"
    # The value under [flow.param.K.field] is not the truth: the search owns K.
    config.write_text(
        _project_toml(mode="calibration", name="twin_network_calibration", k_m_s=1.0e-5)
        + _CALIBRATION_TOML.format(
            rel_tol=REL_TOL,
            k_low=K_BOUNDS_M_S[0],
            k_high=K_BOUNDS_M_S[1],
            output=OUTPUT,
            mapped=truth.mapped_path.as_posix(),
        ),
        encoding="utf-8",
    )
    return hmp.calibrate(config, return_report=True)


def _metrics_of(report: Any, k_value: float) -> dict[str, float]:
    """Return the published components of the trial evaluated at ``k_value``."""
    rows = report.iterations
    for _, row in rows.iterrows():
        if math.isclose(float(row["parameters"]["K"]["value"]), k_value, rel_tol=1e-12):
            return dict(row["metrics"])
    raise AssertionError(f"no trial at K = {k_value!r} among {len(rows)} iterations.")


def _metric(metrics: dict[str, float], key: str) -> float:
    return float(metrics[f"{OUTPUT}.{key}"])


def test_the_mapped_network_projects_back_onto_the_cells_it_was_written_from(
    truth: Truth,
) -> None:
    """The observation must be the truth network, not a rasterised neighbour of it."""
    n_network = int(truth.network.sum())
    # A face that starts inside the hillslope and runs to its toe: neither empty
    # nor the whole row, so both an excess and a deficit remain possible.
    assert 0.1 * N_CELLS < n_network < 0.9 * N_CELLS, n_network
    assert truth.seepage[-1], "the toe must seep: it is where the network closes."
    assert truth.network[np.argmax(truth.network) :].all(), "one contiguous reach"

    mismatched = np.flatnonzero(truth.projected_back != truth.network)
    assert mismatched.size == 0, f"cells differing after the round trip: {mismatched.tolist()}"
    assert truth.mesh_crs == CRS
    assert math.isclose(truth.recharge_m_s, RECHARGE_M_S, rel_tol=1e-9)


def test_a_network_only_bisection_recovers_the_conductivity_that_made_the_network(
    truth: Truth, report: Any
) -> None:
    """K back to one per cent, J near zero, and the paper's ratios at that K."""
    search = report.extra["search"]
    assert search["converged"] is True, search
    bracket = report.extra["bracket"]
    assert bracket["closed"] is True, bracket
    assert bracket["relative_width"] <= REL_TOL, bracket

    k_hat = float(report.best_parameters["K"])
    assert abs(k_hat / K_TRUE_M_S - 1.0) <= K_RECOVERY_REL, k_hat

    best = _metrics_of(report, k_hat)
    # The criterion scored the network the GPKG holds, projected by its own
    # route: the same count of mapped cells, all reached.
    assert _metric(best, "n_network_obs") == float(truth.network.sum())
    assert _metric(best, "frac_unreachable_so") == 0.0
    # TOLERANCES.md row 77: a stream cannot move by less than one cell.
    cell_spacing = _metric(best, "cell_spacing_m")
    assert math.isclose(cell_spacing, CELL_M, rel_tol=1e-9)
    assert abs(_metric(best, "J_signed")) <= cell_spacing, best
    assert report.best_objective <= cell_spacing

    # The sweep sees the sign structure the root search rests on: an excess of
    # simulated stream at the lower bound, a deficit at the upper one.
    assert _metric(_metrics_of(report, K_BOUNDS_M_S[0]), "J_signed") > 0.0
    assert _metric(_metrics_of(report, K_BOUNDS_M_S[1]), "J_signed") < 0.0

    verdict = report.extra["roptim_verdict"][OUTPUT]
    assert verdict["valid"] is True, verdict

    extra = report.extra
    recharge = _metric(best, "R_mean_m_s")
    assert math.isclose(recharge, truth.recharge_m_s, rel_tol=1e-9)
    assert math.isclose(extra["k_optim_m_s"], k_hat, rel_tol=IDENTITY_REL)
    assert math.isclose(extra["k_over_r"], k_hat / recharge, rel_tol=IDENTITY_REL)
    assert abs(extra["k_over_r"] / (K_TRUE_M_S / RECHARGE_M_S) - 1.0) <= K_RECOVERY_REL

    d_sat = extra["d_sat_m"]
    assert math.isclose(d_sat, _metric(best, "d_sat_m"), rel_tol=IDENTITY_REL)
    assert 0.0 < d_sat <= THICKNESS_M
    assert abs(d_sat / truth.d_sat_m - 1.0) <= D_SAT_REL, (d_sat, truth.d_sat_m)
    assert math.isclose(extra["t_over_r_m"], extra["k_over_r"] * d_sat, rel_tol=IDENTITY_REL)
    assert math.isclose(extra["t_optim_m2_s"], k_hat * d_sat, rel_tol=IDENTITY_REL)
