"""SIM2 EDR API adapter for radiation data."""

from __future__ import annotations

from datetime import datetime

import xarray as xr

from hydromodpy.data_managers.contracts.spatial_field import FieldRecord
from hydromodpy.data_managers.radiation.config import RadiationSourceConfig

VARIABLE_NAME = "radiation"
INTERNAL_UNIT = "MJ/m2/j"

# 1 J/cm² = 1e4 J/m² = 0.01 MJ/m²
_JCMM2_TO_MJ_M2 = 0.01

_COMPONENT_TO_SIM2 = {
    "atmospheric": "DLI_Q",
    "visible": "SSI_Q",
}


def fetch(
    config: RadiationSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch radiation from SIM2 via the GeoSAS EDR API.

    Always returns the full spatial grid as FieldRecord(s), one per component.
    """
    if bbox is None:
        raise ValueError("SIM2 source requires a bounding box (set extent or mask_path).")
    if project_period is None:
        raise ValueError("SIM2 source requires project_period (date_start/date_end).")

    from hydromodpy.data_managers.common.clients.sim2_edr import Sim2EDRClient

    date_range = f"{project_period[0].strftime('%Y-%m-%d')}/{project_period[1].strftime('%Y-%m-%d')}"
    sim2_params = [_COMPONENT_TO_SIM2[c] for c in config.components]

    client = Sim2EDRClient(bbox=bbox, crs="EPSG:2154", date_range=date_range, output_format="CoverageJSON")
    cov_json = client.fetch_cube(parameters=sim2_params)
    ds = Sim2EDRClient.coverage_json_to_dataset(cov_json)

    results: list[FieldRecord] = []
    for component in config.components:
        sim2_code = _COMPONENT_TO_SIM2[component]
        var_name = f"radiation_{component}"
        var_data = ds[sim2_code] * _JCMM2_TO_MJ_M2

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
