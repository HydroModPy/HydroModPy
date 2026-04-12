from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.spatial.geographic.core.river_network import (
    build_river_network_products,
    resolve_stream_threshold_cells,
)
from hydromodpy.spatial.geographic.geographic_config import RiverNetworkConfig


class _FailIfCalledBackend:
    def __getattr__(self, name: str):  # pragma: no cover - defensive
        raise AssertionError(f"backend method should not be called when river network is disabled: {name}")


class _EmptyVectorBackend:
    def __init__(self) -> None:
        self.write_vector_calls = 0

    @staticmethod
    def _touch(path: str) -> None:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.touch()

    def d8_flow_accumulation(self, input_dem: str, output_acc: str, *, log: bool = True) -> None:
        _ = (input_dem, log)
        self._touch(output_acc)

    def extract_streams(
        self,
        flow_accumulation: str,
        output_raster: str,
        *,
        threshold: float | int | None = None,
        zero_background: bool | None = None,
    ) -> None:
        _ = (flow_accumulation, threshold, zero_background)
        self._touch(output_raster)

    def clip_raster_to_polygon(
        self,
        input_raster: str,
        input_polygon: str,
        output_raster: str,
        *,
        maintain_dimensions: bool = False,
    ) -> None:
        _ = (input_raster, input_polygon, maintain_dimensions)
        self._touch(output_raster)

    def read_raster(self, path: str):
        return path

    def read_vector(self, path: str):
        return path

    def raster_streams_to_vector_raster(self, streams_raster, d8_pointer, *, all_vertices: bool = False):
        _ = (streams_raster, d8_pointer, all_vertices)
        return type("EmptyVector", (), {"records": (), "projection": "EPSG:2154"})()

    def clip_vector(self, vector, clip_layer):
        _ = clip_layer
        return vector

    def write_vector(self, vector, path: str) -> None:
        _ = (vector, path)
        self.write_vector_calls += 1


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
    assert result.network_crs is None
    assert result.summary_json is None


def test_build_river_network_products_skips_empty_vector_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = RiverNetworkConfig.model_validate(
        {
            "enabled": True,
            "threshold_mode": "area_km2",
            "threshold_area_km2": 1.0,
            "compute_strahler_order": False,
            "compute_stream_links": False,
            "prune_short_streams": False,
        }
    )
    backend = _EmptyVectorBackend()
    network_shp = tmp_path / ".solver_scratch/_preprocessing" / "geographic" / "river_network.shp"
    stale_dbf = network_shp.with_suffix(".dbf")
    stale_dbf.parent.mkdir(parents=True, exist_ok=True)
    network_shp.touch()
    stale_dbf.touch()

    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.core.river_network.compute_river_network_summary",
        lambda **_: {
            "enabled": True,
            "threshold_mode": "area_km2",
            "threshold_value": 1.0,
            "threshold_cells": 400.0,
            "stream_pixel_count": 0,
            "segment_count": 0,
            "network_total_length_m": 0.0,
            "max_strahler_order": None,
            "catchment_area_km2": 1.0,
            "drainage_density_km_per_km2": 0.0,
        },
    )

    result = build_river_network_products(
        river_network=cfg,
        dem_correc_path=tmp_path / "dem_correc.tif",
        d8_pointer_path=tmp_path / "dem_direc.tif",
        watershed_shp=tmp_path / "watershed.shp",
        geographic_dir=tmp_path / ".solver_scratch/_preprocessing" / "geographic",
        correcflow_dir=tmp_path / ".solver_scratch/_preprocessing" / "demcorrecflow",
        dem_res_m=50.0,
        streams_tif_path=tmp_path / ".solver_scratch/_preprocessing" / "geographic" / "river_streams.tif",
        streams_pruned_tif_path=tmp_path / ".solver_scratch/_preprocessing" / "geographic" / "river_streams_pruned.tif",
        stream_order_strahler_tif_path=tmp_path
        / ".solver_scratch/_preprocessing"
        / "geographic"
        / "river_stream_order_strahler.tif",
        stream_link_id_tif_path=tmp_path / ".solver_scratch/_preprocessing" / "geographic" / "river_stream_link_id.tif",
        network_shp_path=network_shp,
        summary_json_path=tmp_path / ".solver_scratch/_preprocessing" / "geographic" / "river_network_summary.json",
        backend=backend,
    )

    assert backend.write_vector_calls == 0
    assert result.network_shp is None
    assert result.river_mesh_trace is None
    assert not network_shp.exists()
    assert not stale_dbf.exists()
    assert Path(str(result.summary_json)).exists()
