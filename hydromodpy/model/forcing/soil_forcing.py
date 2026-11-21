"""Soil reservoir orchestrator: forcings in, MODFLOW-ready grids out.

Turns the daily precipitation and ETP grids ``[data.precipitation]`` and
``[data.etp]`` load, and the temperature grid when the snow is on, into the
kernel's ``SoilParameters`` and ``SoilState``, runs the reservoir day by day,
and hands back a recharge, a residual-ETP and a runoff field (spec section 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.model.contracts import FieldRecordProto, LoadResultProto
from hydromodpy.model.forcing.soil_columns import (
    SOIL_MAPS,
    SoilColumns,
    aggregate_to_cells,
    capacity_classes,
    catchment_cell_means,
    catchment_cell_weights,
    with_surface_maps,
)
from hydromodpy.model.forcing.soil_config import SeasonalKc, SoilReservoirConfig
from hydromodpy.model.forcing.soil_grids import (
    grid_field_record,
    guard_paired_grids,
    load_forcing_grid,
    window_days,
)
from hydromodpy.model.soil.kernel import (
    SoilFluxes,
    SoilParameters,
    full_soil,
    run_soil_balance,
    seasonal_kc,
    spinup_state,
)

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.core.time.window import ResolvedSimulationTimeWindow


RU_LADDER_MM: tuple[float, ...] = (50.0, 100.0, 150.0, 200.0, 250.0)


def soil_parameters(
    config: SoilReservoirConfig, ru_mm: np.ndarray, columns: SoilColumns | None = None
) -> SoilParameters:
    """Kernel parameters for columns of capacity ``ru_mm``.

    The sealed share, the curve number and the infiltration ratio come from the
    maps the columns carry, else from the soil section.
    """
    snow = config.snow
    mapped = {
        soil_map.soil_field: getattr(columns, name)
        if columns is not None and getattr(columns, name) is not None
        else getattr(config, soil_map.soil_field)
        for name, soil_map in SOIL_MAPS.items()
    }
    return SoilParameters(
        ru_mm=np.asarray(ru_mm, dtype=np.float64),
        alpha=config.alpha,
        kc=1.0 if isinstance(config.kc, SeasonalKc) else config.kc,
        impervious_fraction=mapped["impervious_fraction"],
        bypass_fraction=config.bypass_fraction,
        transit_time_days=config.transit_time,
        curve_number=mapped["curve_number"],
        infiltration_ratio=mapped["infiltration_ratio"],
        runoff_time_days=config.runoff_time,
        runoff_lag_days=config.runoff_lag,
        method=config.method,
        snow_melt_start_c=None if snow is None else snow.melt_start,
        snow_melt_full_c=None if snow is None else snow.melt_full,
    )


def kc_of_days(config: SoilReservoirConfig, days: np.ndarray) -> np.ndarray | None:
    """The crop coefficient of each day when it follows the season, else None."""
    kc = config.kc
    if not isinstance(kc, SeasonalKc):
        return None
    return seasonal_kc(days, kc.low, kc.high, kc.months)


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
    temperature: np.ndarray | None = None  # (T, N) degC, loaded only when the snow is on
    kc_by_day: np.ndarray | None = None  # (T,) when kc follows the season

    @property
    def years(self) -> np.ndarray:
        """Calendar year of each day, shape (T,)."""
        return self.days.astype("datetime64[Y]").astype(int) + 1970


# ---------------------------------------------------------------------------
# Spin-up shared by the run and the RU ladder
# ---------------------------------------------------------------------------


def _spinup_or_full(
    config: SoilReservoirConfig,
    params: SoilParameters,
    precipitation: np.ndarray,
    etp: np.ndarray,
    *,
    kc_by_day: np.ndarray | None = None,
    temperature: np.ndarray | None = None,
):
    """Starting state under ``config.spinup``, and the ``Spinup`` that produced it.

    Returns ``(state, None)`` for ``spinup = "none"``: nothing settles, so
    there is nothing to check.
    """
    if config.spinup == "none":
        return full_soil(params), None
    result = spinup_state(
        precipitation[:365],
        etp[:365],
        params,
        kc_by_day=None if kc_by_day is None else kc_by_day[:365],
        temperature=None if temperature is None else temperature[:365],
    )
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
    temperature: LoadResultProto | None = None,
    impervious: LoadResultProto | None = None,
    curve_number: LoadResultProto | None = None,
    infiltration_ratio: LoadResultProto | None = None,
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
    temperature_grid = None
    if config.snow is not None:
        temperature_grid, x_t, y_t, time_t, _t_record = load_forcing_grid(
            temperature,
            section="[data.temperature]",
            family="temperature",
            window=window,
            days=days,
            model_crs=model_crs,
        )
        guard_paired_grids(x_p, y_p, time_p, x_t, y_t, time_t, other_section="[data.temperature]")

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
    maps = {
        name: None
        if result is None
        else catchment_cell_means(
            result.fields[0],
            name=name,
            x=x_p,
            y=y_p,
            crs=model_crs,
            bbox=precip_record.bbox,
            catchment=catchment,
        )
        for name, result in zip(
            SOIL_MAPS, (impervious, curve_number, infiltration_ratio), strict=True
        )
    }
    columns = with_surface_maps(columns, maps)

    precip_columns = precip_grid[:, columns.cell_index]
    etp_columns = etp_grid[:, columns.cell_index]
    temperature_columns = (
        None if temperature_grid is None else temperature_grid[:, columns.cell_index]
    )
    kc_by_day = kc_of_days(config, days)

    ru_mm = config.ru * columns.ru_shape
    parameters = soil_parameters(config, ru_mm, columns)
    initial, spinup_result = _spinup_or_full(
        config,
        parameters,
        precip_columns,
        etp_columns,
        kc_by_day=kc_by_day,
        temperature=temperature_columns,
    )
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
        kc_by_day=kc_by_day,
        temperature=temperature_columns,
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
        temperature=temperature_columns,
        kc_by_day=kc_by_day,
        fluxes=fluxes,
        columns=columns,
        config=config,
        parameters=parameters,
        spinup_cycles=spinup_cycles,
        never_full_columns=never_full_columns,
        crs=precip_record.crs,
    )


def basin_water_out(
    forcings: SoilForcings, ru: float, *, precipitation_scale: float = 1.0
) -> tuple[np.ndarray, np.ndarray] | None:
    """Daily basin recharge and runoff, mm/day, for capacity ``ru``, other parameters fixed.

    ``precipitation_scale`` multiplies the precipitation, to see how a bias of the
    rain moves the result. Returns None when the spin-up does not settle in 20
    cycles: a number built on a soil state that never repeated would be wrong.
    """
    precipitation = forcings.precipitation * precipitation_scale
    parameters = soil_parameters(forcings.config, ru * forcings.columns.ru_shape, forcings.columns)
    initial, spinup_result = _spinup_or_full(
        forcings.config,
        parameters,
        precipitation,
        forcings.etp,
        kc_by_day=forcings.kc_by_day,
        temperature=forcings.temperature,
    )
    if spinup_result is not None and not spinup_result.settled:
        return None
    fluxes = run_soil_balance(
        precipitation,
        forcings.etp,
        parameters,
        initial,
        runoff_cn_history_mm=_runoff_cn_history(spinup_result),
        kc_by_day=forcings.kc_by_day,
        temperature=forcings.temperature,
    )
    weights = forcings.columns.basin_weight
    return fluxes.recharge @ weights, fluxes.runoff @ weights


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
        out = basin_water_out(forcings, ru)
        rows.append((ru, float("nan") if out is None else float(out[0].sum() / n_years)))
    return tuple(rows)
