"""What a soil-reservoir run writes about its columns.

Why
---
The soil reservoir solves one column per (cell, soil class) and sends its
daily recharge and runoff to the groundwater model. A run keeps those columns
twice: the daily series under ``forcing/soil`` of the field store, and the
yearly water balance of each column as the ``soil_budget`` table. Both are
formatting of numbers the soil already computed, so they live here and take
plain arrays and a duck-typed ``soil`` (``columns``, ``fluxes``, ``config``,
``parameters``, ``days``, ``crs``): the workflow step collects, this module
lays out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.scope import CATCHMENT

if TYPE_CHECKING:
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr


def soil_budget_rows(soil: object, budget: object) -> list[dict[str, object]]:
    """Build the ``soil_budget`` rows: one per column and year, plus a basin row.

    *budget* is the annual budget of the soil (``annual_budget`` of the soil
    kernel), computed by the caller from the same *soil*.
    """
    columns = soil.columns
    ru_mm = soil.parameters.ru_mm
    n_years, n_columns = budget.precipitation.shape

    rows: list[dict[str, object]] = []
    for j in range(n_columns):
        column_id = f"{int(columns.cell_index[j])}.{int(columns.class_index[j])}"
        for i in range(n_years):
            rows.append(
                {
                    "column_id": column_id,
                    "cell_index": int(columns.cell_index[j]),
                    "class_index": int(columns.class_index[j]),
                    "x": float(columns.x[j]),
                    "y": float(columns.y[j]),
                    "available_water_capacity": float(ru_mm[j]),
                    "basin_weight": float(columns.basin_weight[j]),
                    "year": int(budget.years[i]),
                    "days": int(budget.days[i]),
                    "precipitation": float(budget.precipitation[i, j]),
                    "etp": float(budget.etp[i, j]),
                    "etr": float(budget.etr[i, j]),
                    "residual_etp": float(budget.residual_etp[i, j]),
                    "recharge": float(budget.recharge[i, j]),
                    "runoff": float(budget.runoff[i, j]),
                    "runoff_cn": float(budget.runoff_cn[i, j]),
                    "soil_storage_change": float(budget.soil_storage_change[i, j]),
                    "transit_storage_change": float(budget.transit_storage_change[i, j]),
                    "cn_storage_change": float(budget.cn_storage_change[i, j]),
                    "lag_storage_change": float(budget.lag_storage_change[i, j]),
                    "balance_residual": float(budget.residual[i, j]),
                    "unit": "mm",
                }
            )

    basin_ru_mm = float(np.sum(ru_mm * columns.basin_weight))
    for i in range(n_years):
        rows.append(
            {
                "column_id": CATCHMENT,
                "cell_index": None,
                "class_index": None,
                "x": None,
                "y": None,
                "available_water_capacity": basin_ru_mm,
                "basin_weight": 1.0,
                "year": int(budget.years[i]),
                "days": int(budget.days[i]),
                "precipitation": float(budget.basin("precipitation")[i]),
                "etp": float(budget.basin("etp")[i]),
                "etr": float(budget.basin("etr")[i]),
                "residual_etp": float(budget.basin("residual_etp")[i]),
                "recharge": float(budget.basin("recharge")[i]),
                "runoff": float(budget.basin("runoff")[i]),
                "runoff_cn": float(budget.basin("runoff_cn")[i]),
                "soil_storage_change": float(budget.basin("soil_storage_change")[i]),
                "transit_storage_change": float(budget.basin("transit_storage_change")[i]),
                "cn_storage_change": float(budget.basin("cn_storage_change")[i]),
                "lag_storage_change": float(budget.basin("lag_storage_change")[i]),
                "balance_residual": float(budget.basin("residual")[i]),
                "unit": "mm",
            }
        )
    return rows


def persist_soil_columns(sz: SimulationZarr, soil: object) -> None:
    """Write the soil reservoir's daily columns under ``forcing/soil``."""
    fluxes = soil.fluxes
    config = soil.config
    columns = soil.columns
    series = {
        "etr": (fluxes.etr, "mm/day", "time: mean", "Actual evapotranspiration of the soil"),
        "residual_etp": (
            fluxes.residual_etp,
            "mm/day",
            "time: mean",
            "ETP the soil left unmet",
        ),
        "recharge": (
            fluxes.recharge,
            "mm/day",
            "time: mean",
            "Recharge sent to the water table",
        ),
        "runoff": (
            fluxes.runoff,
            "mm/day",
            "time: mean",
            "Runoff of the sealed share plus the routed curve-number share",
        ),
        "runoff_cn": (
            fluxes.runoff_cn,
            "mm/day",
            "time: mean",
            "Curve-number share of runoff alone",
        ),
        "soil_storage": (
            fluxes.soil_storage,
            "mm",
            "time: point",
            "Soil water storage at the end of the day",
        ),
        "transit_storage": (
            fluxes.transit_storage,
            "mm",
            "time: point",
            "Transit store at the end of the day",
        ),
        "cn_storage": (
            fluxes.cn_storage,
            "mm",
            "time: point",
            "Curve-number runoff routing store at the end of the day",
        ),
        "lag_storage": (
            fluxes.lag_storage,
            "mm",
            "time: point",
            "Routed curve-number runoff delayed by runoff_lag, not yet released, at "
            "the end of the day",
        ),
    }
    columns_arrays = {
        "cell_index": columns.cell_index,
        "class_index": columns.class_index,
        "x": columns.x,
        "y": columns.y,
        "ru_mm": soil.parameters.ru_mm,
        "cell_fraction": columns.cell_fraction,
        "basin_weight": columns.basin_weight,
    }
    attrs = {
        "source": "soil_reservoir",
        "crs": soil.crs,
        "ru_mm": config.ru,
        "alpha": config.alpha,
        "kc": config.kc,
        "impervious_fraction": config.impervious_fraction,
        "bypass_fraction": config.bypass_fraction,
        "transit_time_days": config.transit_time,
        "spinup": config.spinup,
        "spinup_cycles": int(soil.spinup_cycles),
        "never_full_columns": int(soil.never_full_columns),
        "n_cells": int(np.unique(columns.cell_index).size),
        "n_columns": int(columns.cell_index.shape[0]),
    }
    sz.write_soil_columns(
        timestamps=soil.days,
        series=series,
        columns=columns_arrays,
        attrs=attrs,
    )
