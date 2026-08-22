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

from .reference import (
    expected_head_profile_m,
    hillslope_coordinate_m,
    hillslope_slope,
    recharge_mm_day_to_m_per_s,
    seepage_limit_position_m,
)

CASE_DIR = Path(__file__).resolve().parent

CONDUCTIVITY_UNIT = "m/s"


@dataclass(frozen=True, slots=True)
class SeepageLimitComparison:
    """One completed hillslope run with its seepage diagnostics."""

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
) -> tuple[int, np.ndarray]:
    """Load one field and reshape it to the expected ``(nrow, ncol)`` grid."""
    timestep, values = load_field(
        store=result.store,
        sim_id=result.sim_id,
        observable_name=observable_name,
        expected_shape=expected_shape,
    )
    grid = np.asarray(values, dtype=float).reshape(expected_shape)
    return timestep, grid


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


def build_seepage_limit_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> SeepageLimitComparison:
    """Load one completed run and compare it to the closed-form seepage limit."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(getattr(result, "solver_name", "")).strip().lower()
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name or None)
        if tolerances is None
        else tolerances
    )

    output_cfg = dict(case_metadata.get("output", {}))
    reference_cfg = dict(case_metadata.get("reference", {}))
    config_files = dict(case_metadata.get("config_files", {}))
    expected_shape = tuple(output_cfg["expected_shape"])

    timestep, topography = _load_grid_field(
        result=result,
        observable_name="topography",
        expected_shape=expected_shape,
    )
    _, watertable = _load_grid_field(
        result=result,
        observable_name="watertable_elevation",
        expected_shape=expected_shape,
    )
    _, raw_mask = _load_grid_field(
        result=result,
        observable_name="seepage_mask",
        expected_shape=expected_shape,
    )
    _, drain = _load_grid_field(
        result=result,
        observable_name="drain",
        expected_shape=expected_shape,
    )
    seepage = raw_mask > 0.5

    ncol = int(expected_shape[1])
    hillslope_length_m = float(reference_cfg["hillslope_length_m"])
    substratum_elevation_m = float(reference_cfg["substratum_elevation_m"])
    cell_size_m = hillslope_length_m / float(ncol)
    topography_profile = topography[0]
    slope = hillslope_slope(topography_profile=topography_profile, cell_size_m=cell_size_m)
    x_m = hillslope_coordinate_m(
        topography_profile=topography_profile,
        slope=slope,
        substratum_elevation_m=substratum_elevation_m,
    )
    plane_x_m = (np.arange(ncol, dtype=float)[::-1] + 0.5) * cell_size_m
    if not np.allclose(x_m, plane_x_m):
        raise ValueError(
            "The stored topography is not the plane the closed form assumes: the toe "
            "must fall on the downslope grid edge and the surface must be sampled at "
            "cell centers."
        )
    geometry_residual_m = float(np.max(np.abs(x_m - plane_x_m)))

    conductivity, recharge = scenario_forcing(
        case_dir=CASE_DIR,
        metadata=case_metadata,
        config_name=str(config_files[solver_name]),
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

    analytical_head = expected_head_profile_m(
        x_m=x_m,
        hillslope_length_m=hillslope_length_m,
        slope=slope,
        hydraulic_conductivity_m_per_s=conductivity,
        recharge_m_per_s=recharge,
        substratum_elevation_m=substratum_elevation_m,
    )

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
        geometry_residual_m=geometry_residual_m,
        mask_row_disagreement=int(np.count_nonzero(seepage != seepage[0][None, :])),
        mask_is_contiguous=contiguous,
        numerical_seepage_limit_m=numerical_limit,
        analytical_seepage_limit_m=analytical_limit,
        seepage_limit_error_m=abs(numerical_limit - analytical_limit),
        analytical_head_profile=analytical_head,
        head_profile_max_error_m=max_abs_error(watertable[0], analytical_head),
        drain_outflow_m3_per_s=float(np.sum(np.abs(drain[np.isfinite(drain)]))),
    )


def run_seepage_limit_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> SeepageLimitComparison:
    """Run one scenario of the case and return its seepage diagnostics."""
    metadata = load_case_metadata(CASE_DIR)
    tolerances = load_case_tolerances(CASE_DIR, solver=solver)
    result = run_launcher_validation_case(
        case_dir=CASE_DIR,
        test_file=caller_file,
        timeout=timeout,
        solver=solver,
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
) -> dict[str, SeepageLimitComparison]:
    """Run every declared scenario once and return them keyed by solver name."""
    metadata = load_case_metadata(CASE_DIR)
    return {
        solver: run_seepage_limit_comparison(
            caller_file=caller_file,
            timeout=timeout,
            solver=solver,
        )
        for solver in sorted(dict(metadata.get("config_files", {})))
    }


def mask_disagreement_cells(left: SeepageLimitComparison, right: SeepageLimitComparison) -> int:
    """Return the number of cells whose seepage state differs between two runs."""
    return int(np.count_nonzero(left.seepage_mask != right.seepage_mask))


def head_disagreement_m(left: SeepageLimitComparison, right: SeepageLimitComparison) -> float:
    """Return the maximum absolute water-table difference between two runs."""
    return max_abs_error(left.watertable, right.watertable)


def drain_outflow_ratio(left: SeepageLimitComparison, right: SeepageLimitComparison) -> float:
    """Return the ratio of total drain outflow between two runs."""
    return float(left.drain_outflow_m3_per_s / right.drain_outflow_m3_per_s)


__all__ = [
    "SeepageLimitComparison",
    "build_seepage_limit_comparison",
    "drain_outflow_ratio",
    "head_disagreement_m",
    "mask_disagreement_cells",
    "run_seepage_limit_comparison",
    "run_seepage_limit_sweep",
    "scenario_forcing",
]
