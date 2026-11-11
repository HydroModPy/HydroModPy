"""Twin experiment for the heads rule of the stream-network criterion.

Compared with: the hydraulic conductivity and the stream heads of the run that produced the mapped network.

``test_twin_matching_stream_network_modflow6.py`` runs one row of cells that
drains 0.0016 km2, so it has to force the crossing rule. This twin runs what
protocol 1.3 freezes and writes no key of its network output: the heads rule, the
map cut to the catchment, the catchment bound, D8 where the mesh has corners.

The basin is a comb on a DEM, 80 by 70 cells of 20 m. A main stem runs east to the
outlet on the border, and five straight valleys join it, three from the north and
two from the south, each with its own slope, so their heads do not move at the same
K. Each valley is a V whose talweg runs through cell centers, with sides steep
enough to keep the seepage on the talweg: the flow toward a talweg, about
``R * 300 m``, stays below what the full aquifer carries down a side,
``K * 30 m * 0.06``. The simulated network is then one cell wide, like the trace of
a head, so the map can equal it cell for cell. On a wider network the map could
not, and this would measure that width and not the rule.

At K/R = 600 the run makes six heads, one per valley and one on the main stem, each
draining more than 0.02 km2 and inside its valley. The map holds one line per head,
from that head down the descent to the first confluence, and the main stem runs on
for 200 m past the outlet, so the cut to the catchment makes one more free end that
must not count. A network-only search under the protocol must return that K.

A pass proves little on its own, so the twin also has to fail. A map drawn at
another K must give that K. A map with a head missing, heads placed low or a map 200 m
off must each fail, and each row names the checks it fails. Heads all moved south
shorten three valleys and lengthen two, which keeps K in its band, so D_optim is a
check of its own: J balances and the distances do not vanish. Below the heads, the
path of a line must not count: a map that wanders off the talwegs gives the same K,
and the same map under the crossing rule does not.

One search widens its bounds past the physical ceiling of K, 100 m/s: its trial there
is infeasible, gets the failed cost and leaves the failure streak alone, so the search
walks out and closes.

A generated triangle mesh is left out, see ``NOT_APPLICABLE``. On a Voronoi mesh the
cells follow the talwegs of the DEM drawn at 0.02 km2, a threshold set a priori and
never read from the map, and the map is drawn from that run. Tolerances:
``tests/TOLERANCES.md``, rows 184 to 186, and row 79 for the ratios.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hydromodpy.calibration.config import CalibOutputNetwork
from hydromodpy.calibration.observations.network_geometry import heads_settings
from hydromodpy.catchment.algorithms.network_heads import network_head_candidates
from hydromodpy.catchment.drainage.graph import accumulate_on_downhill_graph
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.model.time.history_contract import saturated_thickness_from_head_history
from hydromodpy.project.facade import Project
from hydromodpy.results.derive.stream.extent import (
    calendar_years,
    extent_masks,
    parse_visible_flow,
    yearly_flow_counts,
)
from hydromodpy.results.derive.stream.heads import trace_from_heads
from hydromodpy.results.session.journal import read_trials
from tests._helpers.tolerances import tol
from tests.validation.calibration.helpers import (
    MODFLOW6_RUNTIME_TOML,
    NETWORK_OUTPUT,
    NETWORK_TWIN_TOML,
    network_metric,
    recharge_read_back_rel,
    require_network_twin_executables,
    simulated_network,
    trial_metrics,
)
from tests.validation.helpers import assert_metric_below

NOT_APPLICABLE = {
    "boussinesq": (
        "The Boussinesq adapter declares release_flux unavailable: observables serves only head and discharge, so the stream-network criterion cannot score a Boussinesq trial."
    ),
    "boussinesq_local": (
        "The Boussinesq adapter declares release_flux unavailable: observables serves only head and discharge, so the stream-network criterion cannot score a Boussinesq trial."
    ),
    "modflow6_irregular_tri": (
        "On triangles the network is not the one cell wide network this twin draws. With XT3D and Newton, MODFLOW 6 cycles by 3 cm on one border cell for 1000 outer iterations. With XT3D alone, K lands 167 per cent off on triangles. Without XT3D, K lands 5.5 per cent off."
    ),
}

gpd = pytest.importorskip("geopandas")
shapely_geometry = pytest.importorskip("shapely.geometry")
LineString = shapely_geometry.LineString

pytestmark = [
    pytest.mark.validation,
    pytest.mark.steady,
]

SOLVERS = [
    pytest.param(
        "modflow_nwt",
        id="modflow_nwt",
        marks=[pytest.mark.nwt, pytest.mark.xdist_group(name="twin_stream_heads_nwt")],
    ),
    pytest.param(
        "modflow6",
        id="modflow6",
        marks=[pytest.mark.mf6, pytest.mark.xdist_group(name="twin_stream_heads_mf6")],
    ),
    pytest.param(
        "modflow6_voronoi",
        id="modflow6_voronoi",
        marks=[
            pytest.mark.mf6,
            pytest.mark.slow,
            pytest.mark.xdist_group(name="twin_stream_heads_voronoi"),
        ],
    ),
]

CRS = "EPSG:2154"
X_WEST, Y_SOUTH = 300000.0, 6800000.0

NX, NY, CELL_M = 80, 70, 20.0
MAIN_ROW = 37
MAIN_SLOPE = 0.01
SOURCE_COLUMNS, SOURCE_SLOPE = 10, 0.04
"""The main stem steepens over its first columns, which gives its head a valley."""
SIDE_SLOPE = 0.06
VALLEYS = ((12, -1, 0.040), (26, 1, 0.044), (41, -1, 0.048), (55, 1, 0.038), (70, -1, 0.052))
"""Talweg column, side of the main stem (-1 north, 1 south) and slope of each valley."""

K_TRUE_M_S = 6.0e-6
K_OTHER_M_S = 7.0e-6
"""The other map a search must follow. All six heads still lie inside their valleys."""
K_BOUNDS_M_S = (7.0e-7, 3.0e-5)
"""The bounds of the first twin. The network covers a third of the basin at the lower
one, and the main stem alone at the upper one."""
RECHARGE_MM_DAY, RECHARGE_M_S, THICKNESS_M = 0.864, 1.0e-8, 30.0

K_RECOVERY_REL = tol("twin_stream_network_calibration_under_heads_mf6_comb_basin")
"""TOLERANCES.md row 184."""

D_OPTIM_M = tol("twin_stream_network_calibration_under_heads_mf6__d_optim_at_the_returned_trial")
"""TOLERANCES.md row 185."""

D_SAT_REL = tol(
    "twin_stream_network_calibration_under_heads_mf6__d_sat_m_of_the_returned_trial_over_the_truth_run"
)
"""TOLERANCES.md row 186."""

IDENTITY_REL = tol("k_optim_m_s_k_over_r_t_over_r_m_t_optim_m2_s")
"""TOLERANCES.md row 79: the report's ratios are products of what it read."""

_GEOGRAPHIC_TOML = """\
[site]
name = "twin_stream_heads"

[geographic]
crs_project = "{crs}"

[geographic.catchment]
kind = "dem"
"""

_LAYERS_TOML = """\
[domain.layers]
nlay = 1
"""

_SOLVER_BLOCKS = {
    "modflow_nwt": _LAYERS_TOML,
    "modflow6": MODFLOW6_RUNTIME_TOML + _LAYERS_TOML,
    "modflow6_voronoi": MODFLOW6_RUNTIME_TOML
    + _LAYERS_TOML
    + """\
[geographic.river_network]
threshold_area_km2 = 0.02

[mesh]
engine = "voronoi"
cell_size = 20.0
""",
}

_CALIBRATION_TOML = """
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = "1 year"

[calibration]
{settings}

[calibration.parameters.K]
bounds = {bounds}

[calibration.outputs.seepage_network]
support = "network"
map.complete = "{mapped}"
{keys}

[calibration.protocol]
name = "matching_hydrographic_network"
storage = false
"""


def _surface() -> np.ndarray:
    """Return the top on the cell centers, row 0 at the north."""
    column, row = np.meshgrid(np.arange(NX), np.arange(NY))
    main = (
        40.0
        + MAIN_SLOPE * (NX - 1 - column) * CELL_M
        + SOURCE_SLOPE * np.maximum(0, SOURCE_COLUMNS - column) * CELL_M
    )
    down = np.abs(row - MAIN_ROW) * CELL_M
    surface = main.astype(float)
    for side in (-1, 1):
        cols = np.asarray([col for col, on, _ in VALLEYS if on == side])
        slopes = np.asarray([slope for _, on, slope in VALLEYS if on == side])
        nearest = np.abs(column[..., None] - cols).argmin(axis=-1)
        gap = np.abs(column - cols[nearest]) * CELL_M
        lifted = (
            main + slopes[nearest] * down + SIDE_SLOPE * gap * np.minimum(1.0, down / (3 * CELL_M))
        )
        surface = np.where(np.sign(row - MAIN_ROW) == side, lifted, surface)
    return surface


def _write_dem(path: Path) -> None:
    """Write the surface. The domain raster drops the last row and column of a DEM."""
    import rasterio
    from rasterio.transform import from_origin

    surface = np.pad(_surface(), ((0, 1), (0, 1)), mode="edge")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=NX + 1,
        height=NY + 1,
        count=1,
        dtype="float64",
        crs=CRS,
        transform=from_origin(X_WEST, Y_SOUTH + (NY + 1) * CELL_M, CELL_M, CELL_M),
        nodata=-9999.0,
    ) as raster:
        raster.write(surface, 1)


def _project_toml(*, solver: str, mode: str, name: str, k_m_s: float, dem: Path) -> str:
    return NETWORK_TWIN_TOML.format(
        solver_id="modflow_nwt" if solver == "modflow_nwt" else "modflow6",
        solver_blocks=_SOLVER_BLOCKS[solver],
        geographic=_GEOGRAPHIC_TOML.format(crs=CRS, dem=dem.as_posix()),
        mode=mode,
        name=name,
        thickness_m=THICKNESS_M,
        k_m_s=float(k_m_s),
        recharge_mm_day=RECHARGE_MM_DAY,
    )


@dataclass(frozen=True)
class Truth:
    """What a run at a known K says, with what the map is drawn from."""

    solver: str
    k_m_s: float
    network: np.ndarray
    heads: np.ndarray
    receivers: np.ndarray
    drained_m2: np.ndarray
    metric: Any
    areas: np.ndarray
    centres: np.ndarray
    recharge_m_s: float
    d_sat_m: float
    dem: Path
    root: Path


def _free_ends(network: np.ndarray, receivers: np.ndarray) -> np.ndarray:
    """Return the cells of the network that no cell of the network drains into."""
    fed = receivers[network]
    return np.setdiff1d(np.flatnonzero(network), fed[fed >= 0])


def _truth(root: Path, solver: str, k_m_s: float) -> Truth:
    root.mkdir(parents=True, exist_ok=True)
    dem = root / "basin.tif"
    _write_dem(dem)
    config = root / "truth.toml"
    config.write_text(
        _project_toml(solver=solver, mode="simulation", name="truth", k_m_s=k_m_s, dem=dem),
        encoding="utf-8",
    )
    project = Project(config, no_display=True)
    try:
        sim = project.simulate()
        simulated, geometry, _, topography, centres, recharge_m_s = simulated_network(sim)
        head = np.asarray(sim.field("head", time=-1), dtype=float).reshape(1, -1)
    finally:
        project.close()
    graph = geometry.metric.graph
    areas = np.asarray(geometry.cell_area_m2, dtype=float)
    thickness = saturated_thickness_from_head_history(
        head, top_m=topography, bottom_m=topography - THICKNESS_M
    )[-1]
    catchment = np.asarray(geometry.catchment, dtype=bool) & np.isfinite(thickness)
    d_sat = float((thickness[catchment] * areas[catchment]).sum() / areas[catchment].sum())
    return Truth(
        solver=solver,
        k_m_s=k_m_s,
        network=simulated.network,
        heads=_free_ends(simulated.network, graph.downstream),
        receivers=graph.downstream,
        drained_m2=accumulate_on_downhill_graph(graph, areas),
        metric=geometry.metric,
        areas=areas,
        centres=centres,
        recharge_m_s=recharge_m_s,
        d_sat_m=d_sat,
        dem=dem,
        root=root,
    )


def _lines(truth: Truth, starts: Iterable[int]) -> list[Any]:
    """Return one line per start, down the descent through the cell centers.

    A line stops on the first cell a line already drew, a vertex of that line, so the
    noding finds a junction there. The one that reaches the outlet runs on past it,
    out of the domain.
    """
    lines = []
    drawn: set[int] = set()
    for start in starts:
        cells = [int(start)]
        while cells[-1] not in drawn and truth.receivers[cells[-1]] >= 0:
            drawn.add(cells[-1])
            cells.append(int(truth.receivers[cells[-1]]))
        points = [tuple(truth.centres[cell]) for cell in cells]
        if cells[-1] not in drawn:
            drawn.add(cells[-1])
            points.append((points[-1][0] + 10 * CELL_M, points[-1][1]))
        lines.append(LineString(points))
    return lines


def _main_stem_first(truth: Truth) -> list[int]:
    """Return the heads, the one on the main stem first, so it is one whole line."""
    return sorted(truth.heads.tolist(), key=lambda cell: 0 if cell // NX == MAIN_ROW else 1)


def _moved(truth: Truth, rows: Callable[[int], int]) -> list[int]:
    """Return the heads with each valley head moved along its talweg by ``rows(side)``."""
    moved = []
    for head in _main_stem_first(truth):
        row, column = head // NX, head % NX
        moved.append(
            head if row == MAIN_ROW else (row + rows(int(np.sign(row - MAIN_ROW)))) * NX + column
        )
    return moved


def _write_map(path: Path, lines: list[Any]) -> Path:
    gpd.GeoDataFrame(geometry=lines, crs=CRS).to_file(path, driver="GPKG")
    return path


def _calibrate(
    truth: Truth,
    name: str,
    lines: list[Any],
    *,
    bounds: tuple[float, float] = K_BOUNDS_M_S,
    settings: str = "",
    keys: str = "",
) -> Any:
    """Run the protocol against a map, the value under [flow.param.K.field] being no truth."""
    import hydromodpy as hmp

    root = truth.root / name
    root.mkdir(parents=True, exist_ok=True)
    config = root / "calibration.toml"
    config.write_text(
        _project_toml(
            solver=truth.solver, mode="calibration", name=name, k_m_s=1.0e-5, dem=truth.dem
        )
        + _CALIBRATION_TOML.format(
            settings=settings,
            bounds=list(bounds),
            mapped=_write_map(root / "map.gpkg", lines).as_posix(),
            keys=keys,
        ),
        encoding="utf-8",
    )
    return hmp.calibrate(config)


def _what_fails(report: Any, truth: Truth) -> list[str]:
    """Name every check this search fails against this truth, none when it recovered it."""
    k_hat = float(report.best_parameters["K"])
    best = trial_metrics(report, k_hat)
    failed = []
    if abs(k_hat / truth.k_m_s - 1.0) > K_RECOVERY_REL:
        failed.append("K")
    if network_metric(best, "D_optim") > D_OPTIM_M:
        failed.append("D_optim")
    if network_metric(best, "n_heads") != truth.heads.size:
        failed.append("n_heads")
    if network_metric(best, "n_heads_lost") != 0.0:
        failed.append("n_heads_lost")
    if network_metric(best, "n_network_obs") != truth.network.sum():
        failed.append("n_network_obs")
    return failed


_TRUTHS: dict[tuple[str, float], Truth] = {}
_REPORTS: dict[str, Any] = {}
"""The truths and the plain searches, so the tests of a column share one run."""


def _truth_of(solver: str, k_m_s: float, factory: pytest.TempPathFactory) -> Truth:
    if (solver, k_m_s) not in _TRUTHS:
        require_network_twin_executables(solver)
        _TRUTHS[solver, k_m_s] = _truth(factory.mktemp(f"twin_heads_{solver}"), solver, k_m_s)
    return _TRUTHS[solver, k_m_s]


@pytest.fixture
def truth(solver: str, tmp_path_factory: pytest.TempPathFactory) -> Truth:
    return _truth_of(solver, K_TRUE_M_S, tmp_path_factory)


@pytest.fixture
def report(solver: str, truth: Truth) -> Any:
    if solver not in _REPORTS:
        _REPORTS[solver] = _calibrate(truth, "plain", _lines(truth, _main_stem_first(truth)))
    return _REPORTS[solver]


@pytest.fixture
def grid_truth(tmp_path_factory: pytest.TempPathFactory) -> Truth:
    return _truth_of("modflow6", K_TRUE_M_S, tmp_path_factory)


@pytest.mark.parametrize("solver", SOLVERS)
def test_the_map_holds_the_known_heads_and_traces_back_to_the_network(
    solver: str, truth: Truth
) -> None:
    """The observation must be the truth network, through the functions of a trial."""
    assert truth.heads.size == len(VALLEYS) + 1, truth.heads
    assert truth.drained_m2[truth.heads].min() >= 0.02e6, truth.drained_m2[truth.heads]
    # A network neither empty nor the whole basin, so both signs remain possible.
    assert 0.01 * truth.network.size < truth.network.sum() < 0.1 * truth.network.size
    assert math.isclose(truth.recharge_m_s, RECHARGE_M_S, rel_tol=recharge_read_back_rel(solver))

    lines = _lines(truth, _main_stem_first(truth))
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)
    trace = trace_from_heads(
        truth.metric,
        candidates,
        cell_area_m2=truth.areas,
        settings=heads_settings(CalibOutputNetwork(support="network", map={"complete": "a"})),
    )
    assert trace.n_lost == 0
    assert np.array_equal(np.sort(trace.head_cell), truth.heads)
    mismatched = np.flatnonzero(trace.traced != truth.network)
    assert mismatched.size == 0, f"cells differing after the round trip: {mismatched.tolist()}"


@pytest.mark.parametrize("solver", SOLVERS)
def test_a_search_under_the_protocol_recovers_the_conductivity_that_made_the_heads(
    solver: str, truth: Truth, report: Any
) -> None:
    """K in its band, the map drawn whole, the network on it, and what the protocol froze."""
    k_hat = float(report.best_parameters["K"])
    assert_metric_below(
        "Relative error of the recovered K",
        abs(k_hat / K_TRUE_M_S - 1.0),
        K_RECOVERY_REL,
        inclusive=True,
    )
    best = trial_metrics(report, k_hat)
    assert_metric_below(
        "D_optim at the returned trial",
        network_metric(best, "D_optim"),
        D_OPTIM_M,
        unit="m",
        inclusive=True,
    )
    assert _what_fails(report, truth) == []

    # The cut left the end past the outlet out, and the bound of 1.3 read a live number.
    assert network_metric(best, "n_cut_ends") == 1.0
    assert network_metric(best, "catchment_mismatch") <= 0.05
    assert network_metric(best, "n_forced_heads") == 0.0
    # An excess of stream at the lower bound, a deficit at the upper one.
    assert network_metric(trial_metrics(report, K_BOUNDS_M_S[0]), "J_signed") > 0.0
    assert network_metric(trial_metrics(report, K_BOUNDS_M_S[1]), "J_signed") < 0.0

    assert report.protocol["version"] == "1.3"
    sealed = (Path(report.session_dir) / "config.toml").read_text(encoding="utf-8")
    assert 'drawn_by = "heads"' in sealed

    stage = report.phases[0].report
    assert report.phases[0].status == "completed"
    assert stage.extra["bracket"]["closed"] is True
    assert stage.extra["r_optim_verdict"]["seepage_network"]["valid"] is True
    recharge = network_metric(best, "R_mean_m_s")
    assert math.isclose(recharge, truth.recharge_m_s, rel_tol=recharge_read_back_rel(solver))
    assert math.isclose(stage.extra["k_over_r"], k_hat / recharge, rel_tol=IDENTITY_REL)
    assert_metric_below(
        "Relative error of the saturated thickness",
        abs(stage.extra["d_sat_m"] / truth.d_sat_m - 1.0),
        D_SAT_REL,
        inclusive=True,
    )


def _one_head_missing(truth: Truth) -> list[Any]:
    return _lines(truth, [head for head in _main_stem_first(truth) if head % NX != 41])


def _heads_three_cells_low(truth: Truth) -> list[Any]:
    return _lines(truth, _moved(truth, lambda side: -3 * side))


def _heads_moved_south(truth: Truth) -> list[Any]:
    return _lines(truth, _moved(truth, lambda side: 5))


def _map_200_m_off(truth: Truth) -> list[Any]:
    from shapely.affinity import translate

    return [translate(line, xoff=200.0) for line in _lines(truth, _main_stem_first(truth))]


@pytest.mark.mf6
@pytest.mark.xdist_group(name="twin_stream_heads_mf6")
@pytest.mark.parametrize(
    ("make_lines", "fails"),
    [
        pytest.param(
            _one_head_missing, {"K", "D_optim", "n_heads", "n_network_obs"}, id="one_head_missing"
        ),
        pytest.param(_heads_three_cells_low, {"K", "n_network_obs"}, id="heads_three_cells_low"),
        pytest.param(_heads_moved_south, {"D_optim", "n_network_obs"}, id="heads_moved_south"),
        pytest.param(_map_200_m_off, {"K", "n_heads_lost", "n_network_obs"}, id="map_200_m_off"),
    ],
)
def test_a_wrong_map_or_a_wrong_head_count_fails_the_twin(
    make_lines: Callable[[Truth], list[Any]], fails: set[str], grid_truth: Truth
) -> None:
    """The twin has power: each wrong map fails the checks it should fail, and no other."""
    report = _calibrate(grid_truth, make_lines.__name__.strip("_"), make_lines(grid_truth))
    found = _what_fails(report, grid_truth)
    assert set(found) == fails, (found, report.best_parameters)


@pytest.mark.mf6
@pytest.mark.xdist_group(name="twin_stream_heads_mf6")
def test_a_map_drawn_at_another_conductivity_gives_that_conductivity(
    grid_truth: Truth, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A search that returned the same K whatever the map would pass the plain test."""
    other = _truth_of("modflow6", K_OTHER_M_S, tmp_path_factory)
    report = _calibrate(other, "other", _lines(other, _main_stem_first(other)))
    k_hat = float(report.best_parameters["K"])
    assert abs(k_hat / K_OTHER_M_S - 1.0) <= K_RECOVERY_REL, k_hat
    assert abs(k_hat / K_TRUE_M_S - 1.0) > K_RECOVERY_REL, k_hat


def _wandering(truth: Truth) -> list[Any]:
    """Return the map with every valley line zigzagging a cell off its talweg, its ends kept."""
    lines = _lines(truth, _main_stem_first(truth))
    wander = [
        LineString(
            [
                line.coords[0],
                *(
                    (x + (1.25 if index % 2 else -1.25) * CELL_M, y)
                    for index, (x, y) in enumerate(line.coords[1:-1])
                ),
                line.coords[-1],
            ]
        )
        for line in lines[1:]
    ]
    return [lines[0], *wander]


@pytest.mark.mf6
@pytest.mark.xdist_group(name="twin_stream_heads_mf6")
def test_below_its_head_the_path_of_a_line_counts_under_crossing_only(grid_truth: Truth) -> None:
    """The reason the rule exists: the same wandering map, read by the two rules."""
    lines = _wandering(grid_truth)
    heads = _calibrate(grid_truth, "wander_heads", lines)
    assert abs(float(heads.best_parameters["K"]) / K_TRUE_M_S - 1.0) <= K_RECOVERY_REL
    assert network_metric(trial_metrics(heads, heads.best_parameters["K"]), "D_optim") == 0.0
    crossing = _calibrate(grid_truth, "wander_crossing", lines, keys='map.drawn_by = "crossing"')
    assert abs(float(crossing.best_parameters["K"]) / K_TRUE_M_S - 1.0) > K_RECOVERY_REL


@pytest.mark.mf6
@pytest.mark.xdist_group(name="twin_stream_heads_mf6")
def test_a_search_walks_out_of_the_infeasible_trial_it_crosses(grid_truth: Truth) -> None:
    """A candidate above the physical ceiling of K gets the failed cost, not a stop.

    Bounds that hold no root are widened by a decade on each side. From 1e-5 to 30 m/s
    that reaches 1e-6 m/s, under the truth, and 300 m/s, over the ceiling of 100 m/s, in
    one round, and the bracket the first point gives must survive the second. A trial
    near the ceiling drains so fast that its budget closes to 35 per cent, and any
    rejected trial stops the widening, so this search accepts those budgets.
    """
    report = _calibrate(
        grid_truth,
        "infeasible",
        _lines(grid_truth, _main_stem_first(grid_truth)),
        bounds=(1.0e-5, 30.0),
        settings="reject_water_budget_above = 100.0",
    )
    # read_trials folds the events of a trial: a proposed line is not a failure.
    trials = read_trials(Path(report.session_dir))
    failed = [trial for trial in trials if trial.status != "completed"]
    assert len(failed) == 1, failed
    assert failed[0].params["K"].value > 100.0, failed
    case = next(iter(failed[0].cases.values()))
    assert case.error is not None and case.error.startswith("infeasible"), case
    k_hat = float(report.best_parameters["K"])
    assert abs(k_hat / K_TRUE_M_S - 1.0) <= K_RECOVERY_REL, k_hat


@pytest.mark.mf6
@pytest.mark.xdist_group(name="twin_stream_heads_mf6")
def test_a_map_whose_every_head_is_lost_is_refused_before_the_first_solve(
    grid_truth: Truth,
) -> None:
    """The first twin under heads ended here, on its one head. It says so, and solves nothing."""
    with pytest.raises(ObjectiveError, match=r"every one of the 6 head\(s\) is lost"):
        _calibrate(
            grid_truth,
            "lost",
            _lines(grid_truth, _main_stem_first(grid_truth)),
            keys="map.heads.min_drained_area = 10.0",
        )
    assert not (grid_truth.root / "lost" / "runs" / "lost").exists()


SEASONS_MM_DAY = (1.8, 1.7, 1.4, 1.0, 0.6, 0.3, 0.1, 0.1, 0.3, 0.6, 1.2, 1.7)
SY_TRUE = 0.05
ONE_CELL_M = tol("twin_k_and_sy_on_two_maps")
"""TOLERANCES.md row 187."""

_TWO_MAPS_TOML = """
[calibration]
save_runs = "none"
parameters = {{ K = {{ bounds = [3.0e-6, 1.2e-5] }}, Sy = {{ bounds = [0.025, 0.1] }} }}

[calibration.outputs.seepage_network]
support = "network"
map = {{ complete = "{maximal}", permanent = "{minimal}", heads = {{ min_drained_area = 0.002 }}, calibrate_on = {{ permanent = 0.5, complete = 0.5 }} }}
model = {{ extent = {{ flowing_at_least = "1 month", dry_at_most = "1 month", year_quorum = 1.0, visible_flow = "0.1 L/s" }} }}

[[calibration.objective_blocks]]
name = "extent"
metric = "distance_gap"
uses_outputs = ["seepage_network"]

[[calibration.phases]]
name = "both"
description = "K and Sy on the two maps."
parameters = ["K", "Sy"]
regime = "transient"
objective_blocks = ["extent"]
method = "grid"
max_trials = 9
method_options = {{ points_per_dim = 3 }}
window = {{ start = "2001-01-01" }}
"""


def _seasonal_toml(mode: str, name: str, k_m_s: float, dem: Path) -> str:
    """The comb under a monthly recharge over three years, with a storage."""
    months = ", ".join(str(value) for value in SEASONS_MM_DAY * 3)
    return (
        _project_toml(solver="modflow6", mode=mode, name=name, k_m_s=k_m_s, dem=dem)
        .replace('flow_regime = "steady"\n', "")
        .replace('param_list = ["K"]', 'param_list = ["K", "Sy", "Ss"]')
        .replace(
            "[flow.ic]",
            f'[flow.param.Sy.field]\nkind = "homogeneous"\nunit = "-"\nvalue = {SY_TRUE}\n\n'
            '[flow.param.Ss.field]\nkind = "homogeneous"\nunit = "m-1"\nvalue = 1e-5\n\n[flow.ic]',
        )
        .replace(
            f"values = [{RECHARGE_MM_DAY!r}]",
            f'values = [{months}]\nstart_date = "2000-01-01"\nfreq = "MS"\nperiods = 36',
        )
        .replace(
            "[workspace]",
            '[simulation.time]\nstart_datetime = "2000-01-01"\nend_datetime = "2002-12-31"\n'
            'step_value = "1 month"\n\n[workspace]',
        )
    )


def _two_maps(root: Path, dem: Path) -> tuple[Path, Path]:
    """Draw the yearly minimal and maximal extents of a run at the true K and Sy."""
    config = root / "truth.toml"
    config.write_text(_seasonal_toml("simulation", "truth", K_TRUE_M_S, dem), encoding="utf-8")
    project = Project(config, no_display=True)
    try:
        sim = project.simulate()
        _, geometry, _, _, centres, _ = simulated_network(sim)
        release = [sim.field("release_flux", time=step).reshape(-1) for step in range(36)]
    finally:
        project.close()
    months = np.arange(np.datetime64("2000-01"), np.datetime64("2003-01")).astype("datetime64[D]")
    counts = yearly_flow_counts(
        np.stack(release),
        years=calendar_years(months, window=(np.datetime64("2001-01-01"), None)),
        threshold_m3_s=geometry.threshold_m3_s,
        metric=geometry.metric,
        visible_flow=parse_visible_flow("0.1 L/s"),
        outlet=geometry.outlet,
    )
    masks = extent_masks(counts, maximal_flowing_steps=1, minimal_dry_steps=1, year_quorum=1.0)
    graph = SimpleNamespace(receivers=geometry.metric.graph.downstream, centres=centres)
    maps = []
    for bound, mask in (("minimal", masks.minimal), ("maximal", masks.maximal)):
        heads = _free_ends(mask, graph.receivers).tolist()
        maps.append(_write_map(root / f"{bound}.gpkg", _lines(graph, heads)))
    return maps[0], maps[1]


@pytest.mark.mf6
@pytest.mark.slow
@pytest.mark.xdist_group(name="twin_stream_heads_mf6")
def test_two_maps_read_k_and_leave_sy_within_one_cell(tmp_path: Path) -> None:
    """K and Sy together on two maps: K has its sign on both, Sy moves J by less than a cell.

    So this route gives K and no Sy, and the preflight keeps its warning on the pair.
    """
    import hydromodpy as hmp

    dem = tmp_path / "basin.tif"
    _write_dem(dem)
    minimal, maximal = _two_maps(tmp_path, dem)
    config = tmp_path / "both.toml"
    config.write_text(
        _seasonal_toml("calibration", "both", 1.0e-5, dem)
        + _TWO_MAPS_TOML.format(minimal=minimal.as_posix(), maximal=maximal.as_posix()),
        encoding="utf-8",
    )
    report = hmp.calibrate(config)

    assert report.best_cost == 0.0
    assert report.best_parameters["K"] == pytest.approx(K_TRUE_M_S)
    assert report.best_parameters["Sy"] == pytest.approx(SY_TRUE)
    for _, row in report.trials.iterrows():
        gaps = [
            row["components"][f"{NETWORK_OUTPUT}.J_signed_{bound}"]
            for bound in ("minimal", "maximal")
        ]
        k_ratio = row["parameters"]["K"]["value"] / K_TRUE_M_S
        if k_ratio < 0.75:
            assert min(gaps) > 0.0, gaps
        elif k_ratio > 1.5:
            assert max(gaps) < 0.0, gaps
        else:
            assert max(abs(gap) for gap in gaps) <= ONE_CELL_M, gaps
