"""SIM2 EDR API adapter for precipitation data."""

from __future__ import annotations

from datetime import datetime

import xarray as xr

from hydromodpy.data_managers.contracts.spatial_field import FieldRecord
from hydromodpy.data_managers.precipitation.config import PrecipitationSourceConfig


VARIABLE_NAME = "precipitation"
INTERNAL_UNIT = "mm/day"


def _sim2_params_for_components(components: list[str]) -> list[str]:
    """Map component names to SIM2 parameter codes."""
    params = []
    if "liquid" in components or "total" in components:
        params.append("PRELIQ_Q")
    if "solid" in components or "total" in components:
        if "PRENEI_Q" not in params:
            params.append("PRENEI_Q")
    return params


def fetch(
    config: PrecipitationSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch precipitation from SIM2 via the GéoSAS EDR API.

    Always returns the full spatial grid as FieldRecord(s), one per component.
    """
    if bbox is None:
        raise ValueError("SIM2 source requires a bounding box (set extent or mask_path).")
    if project_period is None:
        raise ValueError("SIM2 source requires project_period (date_start/date_end).")

    from hydromodpy.data_managers.common.clients.sim2_edr import Sim2EDRClient

    date_range = f"{project_period[0].strftime('%Y-%m-%d')}/{project_period[1].strftime('%Y-%m-%d')}"
    sim2_params = _sim2_params_for_components(config.components)

    client = Sim2EDRClient(bbox=bbox, crs="EPSG:2154", date_range=date_range, output_format="CoverageJSON")
    cov_json = client.fetch_cube(parameters=sim2_params)
    ds = Sim2EDRClient.coverage_json_to_dataset(cov_json)

    results: list[FieldRecord] = []

    for component in config.components:
        if component == "total":
            var_data = ds["PRELIQ_Q"] + ds["PRENEI_Q"]
            var_name = "precipitation_total"
        elif component == "liquid":
            var_data = ds["PRELIQ_Q"]
            var_name = "precipitation_liquid"
        elif component == "solid":
            var_data = ds["PRENEI_Q"]
            var_name = "precipitation_solid"
        else:
            continue

        result_ds = xr.Dataset({var_name: var_data})
        results.append(FieldRecord(
            variable=var_name,
            source="sim2",
            unit=INTERNAL_UNIT,
            data=result_ds,
            bbox=bbox,
            crs="EPSG:2154",
            date_start=project_period[0],
            date_end=project_period[1],
            frequency="D",
        ))

    return results
