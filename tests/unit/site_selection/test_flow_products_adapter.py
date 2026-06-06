from __future__ import annotations

import pytest

from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.config import HydrologyConfig
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    build_site_selection_flow_products,
)


@pytest.mark.fast
def test_flow_products_adapter_delegates_to_existing_builder(tmp_path):
    calls = {}

    def fake_builder(**kwargs):
        calls.update(kwargs)
        return FlowProducts(
            correc=str(tmp_path / "dem_breach.tif"),
            direc=str(tmp_path / "dem_direc.tif"),
            acc=str(tmp_path / "dem_acc.tif"),
        )

    hydrology = HydrologyConfig(hydrologic_conditioning="breach")

    bundle = build_site_selection_flow_products(
        dem_init_path=tmp_path / "dem.tif",
        output_dir=tmp_path / "flow",
        hydrology=hydrology,
        crs_project="EPSG:2154",
        builder=fake_builder,
    )

    assert calls["dem_init_path"] == tmp_path / "dem.tif"
    assert calls["dem_out_dir_path"] == tmp_path / "flow"
    assert calls["dem_correc_type"] == "breach"
    assert calls["crs_project"] == "EPSG:2154"
    assert bundle.dem_correction_type == "breach"
    assert bundle.to_manifest_record()["flow_direction_path"].endswith("dem_direc.tif")


@pytest.mark.fast
def test_flow_products_adapter_maps_existing_default_to_fill(tmp_path):
    calls = {}

    def fake_builder(**kwargs):
        calls.update(kwargs)
        return FlowProducts(correc="fill.tif", direc="dir.tif", acc="acc.tif")

    build_site_selection_flow_products(
        dem_init_path=tmp_path / "dem.tif",
        output_dir=tmp_path / "flow",
        hydrology=HydrologyConfig(hydrologic_conditioning="existing_default"),
        builder=fake_builder,
    )

    assert calls["dem_correc_type"] == "fill"
