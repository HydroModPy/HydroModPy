from __future__ import annotations

import pytest

from hydromodpy.geographic.core.river_network import (
    build_river_network_products,
    resolve_stream_threshold_cells,
)
from hydromodpy.geographic.geographic_config import RiverNetworkConfig


class _FailIfCalledBackend:
    def __getattr__(self, name: str):  # pragma: no cover - defensive
        raise AssertionError(f"backend method should not be called when river network is disabled: {name}")


def test_resolve_stream_threshold_cells_from_area_mode():
    cfg = RiverNetworkConfig.model_validate(
        {
            "enabled": True,
            "threshold_mode": "area_km2",
            "threshold_area_km2": 0.5,
        }
    )

    threshold_cells = resolve_stream_threshold_cells(
        river_network=cfg,
        dem_res_m=50.0,
    )
    assert float(threshold_cells) == pytest.approx(200.0)


def test_resolve_stream_threshold_cells_from_cells_mode():
    cfg = RiverNetworkConfig.model_validate(
        {
            "enabled": True,
            "threshold_mode": "cells",
            "threshold_cells": 1234,
        }
    )

    threshold_cells = resolve_stream_threshold_cells(
        river_network=cfg,
        dem_res_m=10.0,
    )
    assert float(threshold_cells) == pytest.approx(1234.0)


def test_build_river_network_products_noop_when_disabled():
    cfg = RiverNetworkConfig.model_validate({"enabled": False})
    result = build_river_network_products(
        river_network=cfg,
        dem_correc_path="dem_correc.tif",
        d8_pointer_path="dem_direc.tif",
        watershed_shp="watershed.shp",
        geographic_dir="results_stable/geographic",
        correcflow_dir="results_stable/demcorrecflow",
        dem_res_m=50.0,
        streams_tif_path="results_stable/geographic/river_streams.tif",
        streams_pruned_tif_path="results_stable/geographic/river_streams_pruned.tif",
        stream_order_strahler_tif_path="results_stable/geographic/river_stream_order_strahler.tif",
        stream_link_id_tif_path="results_stable/geographic/river_stream_link_id.tif",
        network_shp_path="results_stable/geographic/river_network.shp",
        summary_json_path="results_stable/geographic/river_network_summary.json",
        backend=_FailIfCalledBackend(),
    )

    assert result.enabled is False
    assert result.threshold_cells is None
    assert result.streams_tif is None
    assert result.network_shp is None
    assert result.summary_json is None
