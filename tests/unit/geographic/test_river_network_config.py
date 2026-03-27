from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.spatial.geographic import GeographicConfig
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths


def test_river_network_config_accepts_area_threshold_mode():
    cfg = GeographicConfig.model_validate(
        {
            "source_mode": "synthetic",
            "river_network": {
                "enabled": True,
                "threshold_mode": "area_km2",
                "threshold_area_km2": 0.5,
                "min_stream_length_m": "250 m",
            },
        }
    )

    assert cfg.river_network.enabled is True
    assert str(cfg.river_network.threshold_mode) == "area_km2"
    assert float(cfg.river_network.threshold_area_km2) == pytest.approx(0.5)
    assert float(cfg.river_network.min_stream_length_m) == pytest.approx(250.0)


def test_river_network_config_accepts_cells_threshold_mode():
    cfg = GeographicConfig.model_validate(
        {
            "source_mode": "synthetic",
            "river_network": {
                "enabled": True,
                "threshold_mode": "cells",
                "threshold_cells": 2000,
            },
        }
    )

    assert cfg.river_network.enabled is True
    assert str(cfg.river_network.threshold_mode) == "cells"
    assert float(cfg.river_network.threshold_cells) == pytest.approx(2000.0)


def test_river_network_config_rejects_missing_threshold_value():
    with pytest.raises(
        ValueError,
        match=r"threshold_mode='cells'.*threshold_cells",
    ):
        GeographicConfig.model_validate(
            {
                "source_mode": "synthetic",
                "river_network": {
                    "enabled": True,
                    "threshold_mode": "cells",
                },
            }
        )


def test_river_network_config_rejects_non_positive_threshold():
    with pytest.raises(
        ValueError,
        match=r"threshold_area_km2 must be > 0",
    ):
        GeographicConfig.model_validate(
            {
                "source_mode": "synthetic",
                "river_network": {
                    "enabled": True,
                    "threshold_mode": "area_km2",
                    "threshold_area_km2": 0.0,
                },
            }
        )


def test_river_network_config_rejects_negative_min_stream_length():
    with pytest.raises(
        ValueError,
        match=r"min_stream_length_m must be >= 0",
    ):
        GeographicConfig.model_validate(
            {
                "source_mode": "synthetic",
                "river_network": {
                    "enabled": True,
                    "threshold_mode": "area_km2",
                    "threshold_area_km2": 0.5,
                    "min_stream_length_m": -1.0,
                },
            }
        )


def test_build_geographic_paths_exposes_river_network_outputs():
    paths = build_geographic_paths(Path("dummy_out"))

    assert paths.river_streams_tif.endswith("river_streams.tif")
    assert paths.river_streams_pruned_tif.endswith("river_streams_pruned.tif")
    assert paths.river_stream_order_strahler_tif.endswith("river_stream_order_strahler.tif")
    assert paths.river_stream_link_id_tif.endswith("river_stream_link_id.tif")
    assert paths.river_network_shp.endswith("river_network.shp")
    assert paths.river_network_summary_json.endswith("river_network_summary.json")
