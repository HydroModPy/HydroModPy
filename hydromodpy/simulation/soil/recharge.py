"""Soil reservoir orchestrator: forcings in, MODFLOW-ready grids out.

Turns the daily precipitation and ETP grids ``[data.precipitation]`` and
``[data.etp]`` load into the kernel's ``SoilParameters`` and ``SoilState``,
runs the reservoir day by day, and hands back a recharge, a residual-ETP and
a runoff field (spec section 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.physics.contracts import FieldRecordProto, LoadResultProto
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilFluxes,
    SoilParameters,
    full_soil,
    run_soil_balance,
    spinup_state,
)
from hydromodpy.simulation.soil.columns import (
    SoilColumns,
    aggregate_to_cells,
    capacity_classes,
    catchment_cell_weights,
)
from hydromodpy.simulation.soil.grids import (
    grid_field_record,
    guard_paired_grids,
    load_forcing_grid,
    window_days,
)

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.core.time.window import ResolvedSimulationTimeWindow


RU_LADDER_MM: tuple[float, ...] = (50.0, 100.0, 150.0, 200.0, 250.0)


def soil_parameters(config: SoilReservoirConfig, ru_mm: np.ndarray) -> SoilParameters:
    """Kernel parameters for columns of capacity ``ru_mm``."""
    return SoilParameters(
        ru_mm=np.asarray(ru_mm, dtype=np.float64),
        alpha=config.alpha,
        kc=config.kc,
        impervious_fraction=config.impervious_fraction,
        bypass_fraction=config.bypass_fraction,
        transit_time_days=config.transit_time,
        curve_number=config.curve_number,
        runoff_time_days=config.runoff_time,
        runoff_lag_days=config.runoff_lag,
    )


@dataclass(frozen=True)
class SoilForcings:
    """What the soil reservoir hands to the model, and what it computed."""

    recharge: LoadResultProto  # one FieldRecord "recharge", mm/day, P grid
    residual_etp: LoadResultProto  # one FieldRecord "etp", mm/day, P grid
    runoff: LoadResultProto  # one FieldRecord "runoff", mm/day, P grid, zeros without sealed area
    days: np.ndarray  # (T,) datetime64[ns], the run days [t0, tN)
    precipitation: np.ndarray  # (T, N) mm/day fed to the kernel
    etp: np.ndarray  # (T, N) mm/day as loaded
    fluxes: SoilFluxes
    columns: SoilColumns
    config: SoilReservoirConfig
    parameters: SoilParameters
    spinup_cycles: int  # 0 with spinup = "none"
    never_full_columns: int  # 0 with spinup = "none"
    crs: str

    @property
    def years(self) -> np.ndarray:
        """Calendar year of each day, shape (T,)."""
        return self.days.astype("datetime64[Y]").astype(int) + 1970


# ---------------------------------------------------------------------------
# Spin-up shared by the run and the RU ladder
# ---------------------------------------------------------------------------


def _spinup_or_full(
    config: SoilReservoirConfig, params: SoilParameters, precipitation: np.ndarray, etp: np.ndarray
):
    """Starting state under ``config.spinup``, and the ``Spinup`` that produced it.

    Returns ``(state, None)`` for ``spinup = "none"``: nothing settles, so
    there is nothing to check.
    """
    if config.spinup == "none":
        return full_soil(params), None
    result = spinup_state(precipitation[:365], etp[:365], params)
    return result.state, result


def _runoff_cn_history(spinup_result) -> np.ndarray | None:
    """Days preceding day 0 for ``runoff_lag``: the settled spin-up's last cycle, or None.

    A settled first year repeats forever by construction, so its own days are
    the best estimate of what came before the run; ``spinup = "none"`` or
    ``runoff_lag = 0`` (which never reads this) leaves the first days at zero.
    """
    return spinup_result.last_cycle_runoff_cn if spinup_result is not None else None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _holding(like: LoadResultProto, field: FieldRecordProto) -> LoadResultProto:
    """A load result of the class of ``like`` that holds ``field`` alone."""
    return type(like)(fields=[field])


def compute_soil_forcings(
    *,
    precipitation: LoadResultProto | None,
    etp: LoadResultProto | None,
    config: SoilReservoirConfig,
    window: ResolvedSimulationTimeWindow,
    model_crs: str,
    soil_capacity: LoadResultProto | None = None,
    catchment: gpd.GeoDataFrame | None = None,
) -> SoilForcings:
    """Run the soil reservoir over ``[simulation.time]`` and grid its outputs back."""
    days = window_days(window)
    precip_grid, x_p, y_p, time_p, precip_record = load_forcing_grid(
        precipitation,
        section="[data.precipitation]",
        family="precipitation",
        window=window,
        days=days,
        model_crs=model_crs,
    )
    etp_grid, x_e, y_e, time_e, _etp_record = load_forcing_grid(
        etp,
        section="[data.etp]",
        family="etp",
        window=window,
        days=days,
        model_crs=model_crs,
    )
    guard_paired_grids(x_p, y_p, time_p, x_e, y_e, time_e)

    ny, nx = y_p.size, x_p.size
    n_cells = ny * nx
    cell_weights = catchment_cell_weights(
        x_p, y_p, bbox=precip_record.bbox, catchment=catchment, crs=model_crs
    )
    if soil_capacity is None:
        columns = SoilColumns(
            cell_index=np.arange(n_cells),
            class_index=np.zeros(n_cells, dtype=np.int64),
            x=np.tile(x_p, ny),
            y=np.repeat(y_p, nx),
            ru_shape=np.ones(n_cells),
            cell_fraction=np.ones(n_cells),
            basin_weight=cell_weights,
        )
    else:
        columns = capacity_classes(
            soil_capacity,
            x=x_p,
            y=y_p,
            crs=model_crs,
            bbox=precip_record.bbox,
            cell_weights=cell_weights,
        )

    precip_columns = precip_grid[:, columns.cell_index]
    etp_columns = etp_grid[:, columns.cell_index]

    ru_mm = config.ru * columns.ru_shape
    parameters = soil_parameters(config, ru_mm)
    initial, spinup_result = _spinup_or_full(config, parameters, precip_columns, etp_columns)
    if spinup_result is not None and not spinup_result.settled:
        first_year = (
            f"{pd.Timestamp(days[0]):%Y-%m-%d} to "
            f"{pd.Timestamp(days[0]) + pd.Timedelta(days=364):%Y-%m-%d}"
        )
        raise ConfigError(
            "the soil storage at the end of the first year still moved by "
            f"{spinup_result.last_change_mm:.2f} mm after 20 repetitions of "
            f"{first_year}: the first year does not bring the soil to a repeating "
            'state. Write spinup = "none" under [flow.sinks_sources.recharge.soil], '
            "or start the run on a year that refills the soil."
        )
    spinup_cycles = spinup_result.cycles if spinup_result is not None else 0
    never_full_columns = int(np.sum(spinup_result.never_full)) if spinup_result is not None else 0

    fluxes = run_soil_balance(
        precip_columns,
        etp_columns,
        parameters,
        initial,
        runoff_cn_history_mm=_runoff_cn_history(spinup_result),
    )

    recharge_grid = aggregate_to_cells(fluxes.recharge, columns, n_cells)
    residual_etp_grid = aggregate_to_cells(fluxes.residual_etp, columns, n_cells)
    runoff_grid = aggregate_to_cells(fluxes.runoff, columns, n_cells)

    recharge_field = grid_field_record(
        "recharge", recharge_grid, x=x_p, y=y_p, days=days, like=precip_record
    )
    residual_etp_field = grid_field_record(
        "etp", residual_etp_grid, x=x_p, y=y_p, days=days, like=precip_record
    )
    runoff_field = grid_field_record(
        "runoff", runoff_grid, x=x_p, y=y_p, days=days, like=precip_record
    )

    return SoilForcings(
        recharge=_holding(precipitation, recharge_field),
        residual_etp=_holding(precipitation, residual_etp_field),
        runoff=_holding(precipitation, runoff_field),
        days=days,
        precipitation=precip_columns,
        etp=etp_columns,
        fluxes=fluxes,
        columns=columns,
        config=config,
        parameters=parameters,
        spinup_cycles=spinup_cycles,
        never_full_columns=never_full_columns,
        crs=precip_record.crs,
    )


def ru_ladder(
    forcings: SoilForcings, ru_values: tuple[float, ...] = RU_LADDER_MM
) -> tuple[tuple[float, float], ...]:
    """Basin recharge, mm/year, for each ``ru`` in ``ru_values``, other parameters fixed.

    A rung whose spin-up does not settle in 20 cycles reports ``nan`` rather
    than a number built on a soil state that never repeated: this table is
    informational, so it stays silent about the run itself (X13 already
    checked that) but never prints a silently wrong figure for a rung.
    """
    n_years = len(forcings.days) / 365.25
    rows = []
    for ru in ru_values:
        ru_mm = ru * forcings.columns.ru_shape
        parameters = soil_parameters(forcings.config, ru_mm)
        initial, spinup_result = _spinup_or_full(
            forcings.config, parameters, forcings.precipitation, forcings.etp
        )
        if spinup_result is not None and not spinup_result.settled:
            rows.append((ru, float("nan")))
            continue
        fluxes = run_soil_balance(
            forcings.precipitation,
            forcings.etp,
            parameters,
            initial,
            runoff_cn_history_mm=_runoff_cn_history(spinup_result),
        )
        basin_recharge = fluxes.recharge @ forcings.columns.basin_weight
        rows.append((ru, float(basin_recharge.sum() / n_years)))
    return tuple(rows)
