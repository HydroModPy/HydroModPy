"""Comparison workflow for the steady Dupuit seepage-limit validation case."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.shared import (
    ValidationRunResult,
    load_case_config,
    load_case_metadata,
    load_case_tolerances,
    load_field,
    max_abs_error,
    run_launcher_validation_case,
)
from validation_cases.shared.loaders import run_dual_cell_centers
from validation_cases.shared.strip_geometry import strip_geometry_for_run

from .reference import (
    expected_head_profile_m,
    recharge_mm_day_to_m_per_s,
    seepage_limit_position_m,
)
from .runtime_boussinesq import (
    BOUSSINESQ_BACKENDS,
    boussinesq_scenario_forcing,
    run_boussinesq_seepage_limit_case,
)

CASE_DIR = Path(__file__).resolve().parent

CONDUCTIVITY_UNIT = "m/s"

BACKENDS = (
    "modflow_nwt",
    "modflow6",
    "modflow6_irregular_tri",
    "modflow6_voronoi",
    "boussinesq",
    "boussinesq_local",
)
SCENARIO_SUFFIXES = ("_scaled_down", "_scaled_up", "_k_only")
"""Suffixes of the three scenarios that follow the reference of each solver."""

# The height of a cell top the seepage test of a Boussinesq run allows below the
# surface, in m: a head within this of the surface is a seeping head.
BOUSSINESQ_SEEPAGE_BAND_M = 1e-6

# The largest gap, in m, between the stored cell tops and the plane the closed form
# assumes, binned like the model. The Boussinesq bundle sits 1 micrometre above it,
# which its writer needs at the toe.
GEOMETRY_TOLERANCE_M = 1e-5


def backend_of(scenario: str) -> str:
    """Return the solver a scenario key belongs to: ``modflow6_k_only`` is ``modflow6``."""
    name = str(scenario).strip().lower()
    for suffix in SCENARIO_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def scenarios_of(backend: str) -> tuple[str, ...]:
    """Return the reference scenario of a solver, then its three derived scenarios."""
    return (backend, *(f"{backend}{suffix}" for suffix in SCENARIO_SUFFIXES))


@dataclass(frozen=True, slots=True)
class SeepageLimitComparison:
    """One completed hillslope run with its seepage diagnostics.

    ``topography``, ``watertable`` and ``seepage_mask`` are the profile binned
    on the equal columns of the strip. ``seepage_cells`` and ``watertable_cells``
    are the same fields on the solver cells, in their order: every scenario of
    one solver shares its cells, so two runs compare cell for cell.
    ``mask_row_disagreement`` counts the cells whose seepage state differs from
    that of the majority of their column.
    """

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    solver: str
    timestep: int
    hydraulic_conductivity_m_per_s: float
    recharge_m_per_s: float
    slope: float
    hillslope_length_m: float
    cell_size_m: float
    x_m: np.ndarray
    topography: np.ndarray
    watertable: np.ndarray
    seepage_mask: np.ndarray
    seepage_cells: np.ndarray
    watertable_cells: np.ndarray
    geometry_residual_m: float
    mask_row_disagreement: int
    mask_is_contiguous: bool
    numerical_seepage_limit_m: float
    analytical_seepage_limit_m: float
    seepage_limit_error_m: float
    analytical_head_profile: np.ndarray
    head_profile_max_error_m: float
    drain_outflow_m3_per_s: float

    @property
    def conductivity_over_recharge(self) -> float:
        """Return the K/R ratio, the only combination the solution depends on."""
        return self.hydraulic_conductivity_m_per_s / self.recharge_m_per_s


def _dig(payload: Mapping, path: Sequence[str]) -> object | None:
    """Return a nested TOML value, or None when any level is missing."""
    node: object = payload
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def _parse_conductivity_m_per_s(raw: object) -> float:
    """Parse a ``'<value> m/s'`` hydraulic-conductivity literal."""
    tokens = str(raw).split()
    if len(tokens) != 2 or tokens[1] != CONDUCTIVITY_UNIT:
        raise ValueError(f"Expected a '<value> {CONDUCTIVITY_UNIT}' literal, got {raw!r}.")
    return float(tokens[0])


def _conductivity_from_payload(payload: Mapping) -> float | None:
    raw = _dig(payload, ("flow", "param", "K", "field", "value"))
    return None if raw is None else _parse_conductivity_m_per_s(raw)


def _recharge_from_payload(payload: Mapping) -> float | None:
    sources = _dig(payload, ("data", "recharge", "sources"))
    if not isinstance(sources, list) or not sources:
        return None
    values = _dig(sources[0], ("values",))
    if not isinstance(values, list) or not values:
        return None
    return recharge_mm_day_to_m_per_s(float(values[0]))


def scenario_forcing(
    *,
    case_dir: Path,
    metadata: Mapping,
    config_name: str,
) -> tuple[float, float]:
    """Return ``(K, R)`` in SI for one scenario config, base values included."""
    base_name = str(metadata["base_config"])
    payloads = [load_case_config(case_dir, config_name)]
    if config_name != base_name:
        payloads.append(load_case_config(case_dir, base_name))

    conductivity = next(
        (value for value in map(_conductivity_from_payload, payloads) if value is not None),
        None,
    )
    recharge = next(
        (value for value in map(_recharge_from_payload, payloads) if value is not None),
        None,
    )
    if conductivity is None or recharge is None:
        raise ValueError(f"{config_name} declares no hydraulic conductivity or no recharge.")
    return conductivity, recharge


def _load_grid_field(
    *,
    result: ValidationRunResult,
    observable_name: str,
    expected_shape: tuple[int, ...],
    cell_centers: np.ndarray | None,
) -> tuple[int, np.ndarray]:
    """Load one field binned on the expected ``(nrow, ncol)`` grid."""
    timestep, values = load_field(
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
        expected_shape=expected_shape,
        cell_centers=cell_centers,
    )
    grid = np.asarray(values, dtype=float).reshape(expected_shape)
    return timestep, grid


def _load_cell_field(*, result: ValidationRunResult, observable_name: str) -> np.ndarray:
    """Load one field on the solver cells, one value per cell."""
    _, values = load_field(
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
        expected_shape=None,
    )
    return np.asarray(values, dtype=float).reshape(-1)


def _numerical_seepage_limit_m(
    *,
    x_m: np.ndarray,
    column_seepage: np.ndarray,
    cell_size_m: float,
) -> float:
    """Return the upslope edge of the seeping column block."""
    seeping = np.flatnonzero(column_seepage)
    if seeping.size == 0:
        return 0.0
    first = int(seeping.min())
    return float(x_m[first]) + (0.5 * float(cell_size_m))


def _cell_columns(geometry, *, n_cells: int, ncol: int) -> np.ndarray:
    """Return the profile column of each solver cell, in the order of the cell fields."""
    if geometry.cell_column is not None:
        return np.asarray(geometry.cell_column, dtype=int)
    return np.tile(np.arange(int(ncol)), int(n_cells) // int(ncol))


def _scenario_forcing(
    *,
    solver_name: str,
    config_files: dict,
    metadata: dict,
) -> tuple[float, float]:
    """Return ``(K, R)`` of one scenario: its config, or the runtime table of Boussinesq."""
    if backend_of(solver_name) in BOUSSINESQ_BACKENDS:
        return boussinesq_scenario_forcing(solver_name)
    return scenario_forcing(
        case_dir=CASE_DIR,
        metadata=metadata,
        config_name=str(config_files[solver_name]),
    )


def build_seepage_limit_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> SeepageLimitComparison:
    """Load one completed run and compare it to the closed-form seepage limit."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower()
    backend = backend_of(solver_name)
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=backend or None) if tolerances is None else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    config_files = dict(case_metadata.get("config_files", {}))
    shape_by_solver = dict(output_cfg.get("expected_shape_by_solver", {}))
    expected_shape = tuple(shape_by_solver.get(backend, output_cfg["expected_shape"]))

    # A Voronoi dual holds each head at its node, so its cells bin by node.
    cell_centers = run_dual_cell_centers(result, case_metadata)
    timestep, topography = _load_grid_field(
        result=result,
        observable_name="topography",
        expected_shape=expected_shape,
        cell_centers=cell_centers,
    )
    _, watertable = _load_grid_field(
        result=result,
        observable_name="watertable_elevation",
        expected_shape=expected_shape,
        cell_centers=cell_centers,
    )
    _, mask_fraction = _load_grid_field(
        result=result,
        observable_name="seepage_mask",
        expected_shape=expected_shape,
        cell_centers=cell_centers,
    )
    seepage = mask_fraction > 0.5
    seepage_cells = _load_cell_field(result=result, observable_name="seepage_mask") > 0.5
    watertable_cells = _load_cell_field(result=result, observable_name="watertable_elevation")
    # The discharge is a sum over the cells, not a mean over a column.
    drain_cells = _load_cell_field(result=result, observable_name="drain")

    ncol = int(expected_shape[1])
    hillslope_length_m = float(reference_cfg["hillslope_length_m"])
    substratum_elevation_m = float(reference_cfg["substratum_elevation_m"])
    slope = float(reference_cfg["topography_slope_m_per_m"])
    cell_size_m = hillslope_length_m / float(ncol)

    # The plane is read where the model reads it: at each cell, binned like the
    # model. A surface sampled from a raster is flat past the centre of the end
    # raster columns, so no point is read beyond them.
    geometry = strip_geometry_for_run(
        result,
        ncol=ncol,
        xmin=0.0,
        xmax=hillslope_length_m,
    )
    surface_span = (geometry.surface_west_x, geometry.surface_east_x)
    x_m = hillslope_length_m - geometry.x
    reference_topography = geometry.profile(
        lambda points: substratum_elevation_m + slope * (hillslope_length_m - points),
        within=surface_span,
    )
    geometry_residual_m = float(np.max(np.abs(topography - reference_topography[None, :])))
    if geometry_residual_m > GEOMETRY_TOLERANCE_M:
        raise ValueError(
            f"The stored topography is {geometry_residual_m:.3e} m from the plane the closed "
            "form assumes: the toe must fall on the downslope grid edge and the surface "
            "must be sampled at cell centers."
        )

    conductivity, recharge = _scenario_forcing(
        solver_name=solver_name,
        config_files=config_files,
        metadata=case_metadata,
    )
    analytical_limit = seepage_limit_position_m(
        hillslope_length_m=hillslope_length_m,
        slope=slope,
        hydraulic_conductivity_m_per_s=conductivity,
        recharge_m_per_s=recharge,
    )
    column_seepage = seepage.all(axis=0)
    numerical_limit = _numerical_seepage_limit_m(
        x_m=x_m,
        column_seepage=column_seepage,
        cell_size_m=cell_size_m,
    )
    seeping = np.flatnonzero(column_seepage)
    span = 0 if seeping.size == 0 else int(seeping.max()) - int(seeping.min()) + 1
    contiguous = bool(span == int(seeping.size))

    analytical_head = geometry.profile(
        lambda points: expected_head_profile_m(
            x_m=hillslope_length_m - points,
            hillslope_length_m=hillslope_length_m,
            slope=slope,
            hydraulic_conductivity_m_per_s=conductivity,
            recharge_m_per_s=recharge,
            substratum_elevation_m=substratum_elevation_m,
        ),
        within=surface_span,
    )

    # Cells that disagree with the majority of their column. A column of a
    # structured grid holds identical cells, so this is zero unless the rows differ.
    columns = _cell_columns(geometry, n_cells=seepage_cells.size, ncol=ncol)
    share = np.bincount(columns, weights=seepage_cells.astype(float), minlength=ncol)
    count = np.maximum(np.bincount(columns, minlength=ncol), 1)
    column_majority = (share / count) > 0.5
    row_disagreement = int(np.count_nonzero(seepage_cells != column_majority[columns]))

    return SeepageLimitComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        solver=solver_name,
        timestep=timestep,
        hydraulic_conductivity_m_per_s=conductivity,
        recharge_m_per_s=recharge,
        slope=slope,
        hillslope_length_m=hillslope_length_m,
        cell_size_m=cell_size_m,
        x_m=x_m,
        topography=topography,
        watertable=watertable,
        seepage_mask=seepage,
        seepage_cells=seepage_cells,
        watertable_cells=watertable_cells,
        geometry_residual_m=geometry_residual_m,
        mask_row_disagreement=row_disagreement,
        mask_is_contiguous=contiguous,
        numerical_seepage_limit_m=numerical_limit,
        analytical_seepage_limit_m=analytical_limit,
        seepage_limit_error_m=abs(numerical_limit - analytical_limit),
        analytical_head_profile=analytical_head,
        head_profile_max_error_m=max_abs_error(watertable[0], analytical_head),
        drain_outflow_m3_per_s=float(np.sum(np.abs(drain_cells[np.isfinite(drain_cells)]))),
    )


def run_seepage_limit_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> SeepageLimitComparison:
    """Run one scenario of the case and return its seepage diagnostics.

    A Boussinesq scenario runs the in-house runtime. Any other solver runs the
    launcher case with a drain at the land surface. The tolerances are those of
    the solver, shared by its four scenarios.
    """
    metadata = load_case_metadata(CASE_DIR)
    scenario = str(metadata.get("default_solver") if solver is None else solver).strip().lower()
    backend = backend_of(scenario)
    tolerances = load_case_tolerances(CASE_DIR, solver=backend)
    if backend in BOUSSINESQ_BACKENDS:
        result = run_boussinesq_seepage_limit_case(
            caller_file=caller_file,
            timeout=timeout,
            scenario=scenario,
        )
    else:
        result = run_launcher_validation_case(
            case_dir=CASE_DIR,
            test_file=caller_file,
            timeout=timeout,
            solver=scenario,
        )
    return build_seepage_limit_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )


def run_seepage_limit_sweep(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    backend: str | None = None,
) -> dict[str, SeepageLimitComparison]:
    """Run every declared scenario once and return them keyed by scenario name.

    With ``backend`` the sweep covers the four scenarios of that solver only.
    """
    metadata = load_case_metadata(CASE_DIR)
    names = sorted(dict(metadata.get("config_files", {})))
    if backend is not None:
        names = [name for name in names if backend_of(name) == backend]
    return {
        name: run_seepage_limit_comparison(
            caller_file=caller_file,
            timeout=timeout,
            solver=name,
        )
        for name in names
    }


def mask_disagreement_cells(left: SeepageLimitComparison, right: SeepageLimitComparison) -> int:
    """Return the number of cells whose seepage state differs between two runs."""
    return int(np.count_nonzero(left.seepage_cells != right.seepage_cells))


def head_disagreement_m(left: SeepageLimitComparison, right: SeepageLimitComparison) -> float:
    """Return the maximum absolute water-table difference between two runs."""
    return max_abs_error(left.watertable_cells, right.watertable_cells)


def drain_outflow_ratio(left: SeepageLimitComparison, right: SeepageLimitComparison) -> float:
    """Return the ratio of total drain outflow between two runs."""
    return float(left.drain_outflow_m3_per_s / right.drain_outflow_m3_per_s)


__all__ = [
    "BACKENDS",
    "SCENARIO_SUFFIXES",
    "SeepageLimitComparison",
    "backend_of",
    "build_seepage_limit_comparison",
    "drain_outflow_ratio",
    "head_disagreement_m",
    "mask_disagreement_cells",
    "run_seepage_limit_comparison",
    "run_seepage_limit_sweep",
    "scenario_forcing",
    "scenarios_of",
]
