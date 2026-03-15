"""SIM2 EDR API adapter for wind data."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data_managers.contracts.spatial_field import FieldRecord
from hydromodpy.data_managers.variables.wind.config import WindSourceConfig


SIM2_PARAMETER = "FF_Q"
VARIABLE_NAME = "wind"
INTERNAL_UNIT = "m/s"


def fetch(
    config: WindSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch wind from SIM2 via the GéoSAS EDR API.

    Always returns the full spatial grid as a FieldRecord.
    """
    if bbox is None:
        raise ValueError("SIM2 source requires a bounding box (set extent or mask_path).")
    if project_period is None:
        raise ValueError("SIM2 source requires project_period (date_start/date_end).")

    from hydromodpy.data_managers.common.clients.sim2_edr import Sim2EDRClient

    date_range = f"{project_period[0].strftime('%Y-%m-%d')}/{project_period[1].strftime('%Y-%m-%d')}"

    client = Sim2EDRClient(bbox=bbox, crs="EPSG:2154", date_range=date_range, output_format="CoverageJSON")
    cov_json = client.fetch_cube(parameters=[SIM2_PARAMETER])
    ds = Sim2EDRClient.coverage_json_to_dataset(cov_json)

    return [FieldRecord(
        variable=VARIABLE_NAME,
        source="sim2",
        unit=INTERNAL_UNIT,
        data=ds[[SIM2_PARAMETER]].rename({SIM2_PARAMETER: VARIABLE_NAME}),
        bbox=bbox,
        crs="EPSG:2154",
        date_start=project_period[0],
        date_end=project_period[1],
        frequency="D",
    )]
