from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.workflow.site_selection import build_site_selection_from_hydrometry_config

from ._test_build_builders import make_config, make_record


@pytest.mark.fast
def test_build_site_selection_from_hydrometry_config_uses_loader_then_builds(tmp_path):
    hydrometry_cfg = HydrometryConfig(
        date_start="2020-01-01",
        date_end="2020-01-02",
        sources=[HydrometrySourceConfig(source="hubeau", product="QmnJ")],
    )
    loader_calls = {}

    def fake_loader(**kwargs):
        loader_calls.update(kwargs)
        return [make_record("J123456701")]

    def fake_flow_builder(**_kwargs):
        return FlowProducts(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    def fake_delineation_builder(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    result = build_site_selection_from_hydrometry_config(
        config=make_config(tmp_path),
        hydrometry_config=hydrometry_cfg,
        hydrometry_loader=fake_loader,
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert loader_calls["config"] is hydrometry_cfg
    assert [candidate.source_feature_id for candidate in result.candidates] == ["J123456701"]
    assert result.output_paths == {}
