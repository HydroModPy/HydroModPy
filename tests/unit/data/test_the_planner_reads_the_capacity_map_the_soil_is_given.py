"""DataPlanner: activate soil_capacity when the file declares it.

``[data.soil_capacity]`` can be written without listing ``soil_capacity`` in
``data.types``, like the other typed sections (``substratum``,
``hydrometry``): the planner infers the type from the section's presence
alone, with a traceable reason.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.data.loading.planner import DataPlanner


def _write_geotiff(path: Path) -> Path:
    data = np.full((3, 4), 150.0, dtype="float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
    ) as dst:
        dst.write(data, 1)
    return path


def test_no_capacity_map_infers_nothing(tmp_path: Path) -> None:
    cfg = DataConfig.model_validate({"types": []})

    plan = DataPlanner().build(cfg)

    assert "soil_capacity" not in plan.inferred_types
