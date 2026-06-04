from __future__ import annotations

import pytest

from hydromodpy.workflow.site_selection import (
    load_delineated_catchments_csv,
    load_hydrometry_config_for_site_selection,
)


@pytest.mark.fast
def test_load_delineated_catchments_csv(tmp_path):
    vectors = tmp_path / "vectors"
    vectors.mkdir()
    watershed = vectors / "site_001.geojson"
    watershed.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text(
        "\n".join(
            [
                "site_id,x_outlet,y_outlet,outlet_crs,area_km2,status,watershed_shp",
                "site_001,350000,6810000,EPSG:2154,100,delineated,vectors/site_001.geojson",
            ]
        ),
        encoding="utf-8",
    )

    catchments = load_delineated_catchments_csv(catchments_csv)

    assert len(catchments) == 1
    assert catchments[0].site_id == "site_001"
    assert catchments[0].outlet.x == pytest.approx(350000.0)
    assert catchments[0].area_km2 == pytest.approx(100.0)
    assert catchments[0].watershed_shp == str(watershed.resolve())


@pytest.mark.fast
def test_load_hydrometry_config_for_site_selection_resolves_custom_paths(tmp_path):
    data_dir = tmp_path / "hydrometry_data"
    data_dir.mkdir()
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[hydrometry]",
                'date_start = "2020-01-01"',
                'date_end = "2020-01-02"',
                "",
                "[[hydrometry.sources]]",
                'source = "custom"',
                'path = "hydrometry_data"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_hydrometry_config_for_site_selection(config_path)

    assert cfg.sources[0].path == data_dir.resolve()
