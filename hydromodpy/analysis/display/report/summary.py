"""Compute overview summary metrics from a :class:`DataOverviewState`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from hydromodpy.launchers.data_overview import DataOverviewState


@dataclass
class OverviewSummary:
    """Key metrics for the watershed identity card."""

    watershed_name: str = ""
    catchment_area_km2: float = 0.0
    elevation_min_m: float = 0.0
    elevation_max_m: float = 0.0
    elevation_mean_m: float = 0.0
    n_hydrometry_stations: int = 0
    n_piezometry_stations: int = 0
    n_intermittency_stations: int = 0
    geology_types: list[str] = field(default_factory=list)
    mean_annual_precipitation_mm: float | None = None
    mean_annual_etp_mm: float | None = None


def compute_overview_summary(state: DataOverviewState) -> OverviewSummary:
    """Derive an :class:`OverviewSummary` from loaded data."""
    summary = OverviewSummary()

    # Name -------------------------------------------------------------------
    summary.watershed_name = (
        state.cfg.overview.name
        or getattr(state.workspace, "catch_name", "")
    )

    # Catchment area ---------------------------------------------------------
    if state.domain_geographic is not None:
        summary.catchment_area_km2 = state.domain_geographic.catchment_area_km2

    # Elevation from DEM -----------------------------------------------------
    _fill_elevation(summary, state)

    # Station counts ---------------------------------------------------------
    ld = state.loaded_data
    if ld.hydrometry is not None:
        summary.n_hydrometry_stations = len(ld.hydrometry.points)
    if ld.piezometry is not None:
        summary.n_piezometry_stations = len(ld.piezometry.points)
    if ld.intermittency is not None:
        summary.n_intermittency_stations = len(ld.intermittency.points)

    # Geology types ----------------------------------------------------------
    if ld.geology is not None:
        enc = getattr(ld.geology, "encoded_to_zone", {})
        summary.geology_types = sorted({str(v) for v in enc.values()})

    # Mean annual precipitation / ETP ----------------------------------------
    summary.mean_annual_precipitation_mm = _mean_annual_mm(ld.precipitation)
    summary.mean_annual_etp_mm = _mean_annual_mm(ld.etp)

    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fill_elevation(summary: OverviewSummary, state: DataOverviewState) -> None:
    """Read DEM raster to extract min/max/mean elevation."""
    if state.domain_geographic is None:
        return
    dem_path = state.domain_geographic.watershed_box_buff_dem
    if not dem_path:
        return
    try:
        import rasterio

        with rasterio.open(dem_path) as src:
            data = src.read(1)
            nodata = src.nodata
            if nodata is not None:
                mask = np.isclose(data.astype(float), float(nodata))
            else:
                mask = data < 0
            valid = data[~mask]
            if valid.size > 0:
                summary.elevation_min_m = float(np.min(valid))
                summary.elevation_max_m = float(np.max(valid))
                summary.elevation_mean_m = float(np.mean(valid))
    except Exception:
        pass


def _mean_annual_mm(load_result) -> float | None:
    """Compute mean annual total (mm) from a climatic LoadResult."""
    if load_result is None or not load_result.has_points:
        return None
    try:
        import pandas as pd

        all_values: list[pd.Series] = []
        for rec in load_result.points:
            df = rec.data.copy()
            df = df.set_index("datetime").sort_index()
            all_values.append(df["value"])
        if not all_values:
            return None
        combined = pd.concat(all_values, axis=1).mean(axis=1)
        annual = combined.resample("YE").sum()
        return float(annual.mean()) if len(annual) > 0 else None
    except Exception:
        return None
