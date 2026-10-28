from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.config.dem_config import HydrologyConfig
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    build_site_selection_flow_products,
)
from tests._helpers.site_selection_cases import flow_spy


@pytest.mark.fast
@pytest.mark.parametrize(
    ("conditioning", "expected"), [("breach", "breach"), ("existing_default", "fill")]
)
def test_the_flow_products_are_built_by_the_regional_builder(tmp_path, conditioning, expected):
    calls: dict = {}

    bundle = build_site_selection_flow_products(
        dem_init_path=tmp_path / "dem.tif",
        output_dir=tmp_path / "flow",
        hydrology=HydrologyConfig(hydrologic_conditioning=conditioning),
        crs_project="EPSG:2154",
        builder=flow_spy(calls, direc=tmp_path / "dem_direc.tif"),
    )

    assert (calls["dem_init_path"], calls["dem_out_dir_path"]) == (
        tmp_path / "dem.tif",
        tmp_path / "flow",
    )
    assert (calls["dem_correc_type"], calls["crs_project"]) == (expected, "EPSG:2154")
    assert bundle.dem_correction_type == expected
    assert bundle.to_manifest_record()["flow_direction_path"].endswith("dem_direc.tif")
