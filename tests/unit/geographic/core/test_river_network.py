"""The river network drawn on the DEM: rasters, vector, mesh trace and summary."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pyproj import CRS
from shapely.geometry import box

from hydromodpy.spatial.geographic.core.river_network import (
    build_river_network_products,
    resolve_stream_threshold_cells,
)
from hydromodpy.spatial.geographic.river_network_config import RiverNetworkConfig
from tests._helpers.geographic_cases import write_features
from tests._helpers.geotiffs import write_geotiff

STREAMS = np.zeros((4, 4))
STREAMS[:, 1] = 1.0
STREAMS[3, 2] = 1.0


def _points(*xy: tuple[float, float]) -> list[SimpleNamespace]:
    return [SimpleNamespace(x=x, y=y) for x, y in xy]


# A two-part record, a plain record, a record of one point and one whose part
# index points past its points: the Whitebox vector as the backend hands it over.
RECORDS = (
    SimpleNamespace(points=_points((0, 0), (0, 10), (5, 10), (5, 30)), parts=[0, 2]),
    SimpleNamespace(points=_points((0, 0), (20, 0)), parts=[]),
    SimpleNamespace(points=_points((1, 1)), parts=[0]),
    SimpleNamespace(points=_points((50, 0), (50, 10), (50, 20)), parts=[1, 9]),
)


def _answer(values):
    return lambda *args, **kwargs: values


class RecordingBackend:
    """A Whitebox double whose rasters are four by four arrays, recording each write."""

    def __init__(self, records=RECORDS, projection: str = "") -> None:
        self.calls: list[str] = []
        self.records = records
        self.projection = projection
        self.flow = SimpleNamespace(d8_flow_accumulation_raster=_answer(np.arange(16.0)))
        self.delineation = SimpleNamespace(
            extract_streams_raster=_answer(STREAMS),
            remove_short_streams_raster=_answer(STREAMS),
            strahler_stream_order_raster=_answer(2.0 * STREAMS),
            stream_link_identifier_raster=_answer(STREAMS),
            raster_streams_to_vector_raster=self._vector,
        )
        self.raster = SimpleNamespace(
            clip_raster_to_polygon_raster=lambda raster, polygon, **kwargs: raster,
            read_raster=str,
            read_vector=str,
            write_raster=self._write,
            clip_vector=lambda vector, clip: vector,
            write_vector=lambda vector, path: self.calls.append(f"write_vector {Path(path).name}"),
        )

    def _write(self, values, out) -> None:
        self.calls.append(Path(out).name)
        write_geotiff(out, np.asarray(values, dtype="float32").reshape(4, 4), cell=10.0)

    def _vector(self, streams, d8, *, all_vertices=False):
        return SimpleNamespace(records=self.records, projection=self.projection)


def _config(**fields) -> RiverNetworkConfig:
    threshold = {"threshold_mode": "cells", "threshold_cells": 50}
    if fields.get("threshold_mode") == "area_km2":
        threshold = {}
    return RiverNetworkConfig.model_validate({"enabled": True, **threshold, **fields})


def _build(tmp_path: Path, config: RiverNetworkConfig, backend: object, **options):
    geo = tmp_path / "geographic"
    watershed = write_features(tmp_path / "watershed.shp", [box(0.0, 0.0, 40.0, 50.0)])
    return build_river_network_products(
        river_network=config,
        dem_correc_path=tmp_path / "dem_correc.tif",
        d8_pointer_path=tmp_path / "dem_direc.tif",
        watershed_shp=watershed,
        geographic_dir=geo,
        correcflow_dir=tmp_path / "correcflow",
        dem_res_m=10.0,
        streams_tif_path=geo / "river_streams.tif",
        streams_pruned_tif_path=geo / "river_streams_pruned.tif",
        stream_order_strahler_tif_path=geo / "river_stream_order_strahler.tif",
        stream_link_id_tif_path=geo / "river_stream_link_id.tif",
        network_shp_path=geo / "river_network.shp",
        summary_json_path=geo / "river_network_summary.json",
        backend=backend,
        **options,
    )


@pytest.mark.parametrize(
    ("network", "dem_res", "cells"),
    [
        (_config(threshold_mode="area_km2", threshold_area_km2=0.5), 50.0, 200.0),
        (_config(threshold_cells=1234), 10.0, 1234.0),
    ],
    ids=["area", "cells"],
)
def test_the_stream_threshold_is_a_count_of_cells(network, dem_res, cells) -> None:
    assert resolve_stream_threshold_cells(river_network=network, dem_res_m=dem_res) == cells


@pytest.mark.parametrize(
    ("network", "dem_res", "reason"),
    [
        (_config(), 0.0, "dem_res_m must be > 0"),
        (SimpleNamespace(threshold_mode="area_km2", threshold_area_km2=None), 10.0, "area_km2"),
        (SimpleNamespace(threshold_mode="cells", threshold_cells=0), 10.0, "threshold_cells"),
    ],
    ids=["no cell size", "no area", "no cells"],
)
def test_a_threshold_that_names_no_count_is_refused(network, dem_res, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        resolve_stream_threshold_cells(river_network=network, dem_res_m=dem_res)


def test_a_disabled_network_builds_nothing_and_never_calls_the_backend(tmp_path) -> None:
    result = _build(tmp_path, _config(enabled=False), backend=object())
    assert result.enabled is False
    assert result.threshold_cells is result.streams_tif is None
    assert result.hydrographic_network_generated_shp is None
    assert result.hydrographic_network_generated_summary_json is None


def test_the_full_network_is_pruned_ordered_linked_vectorised_and_summarised(tmp_path) -> None:
    backend = RecordingBackend()
    result = _build(tmp_path, _config(prune_short_streams=True), backend, network_crs="EPSG:2154")
    full_and_clipped = [
        ("dem_streams_full.tif", "river_streams.tif"),
        ("dem_streams_pruned_full.tif", "river_streams_pruned.tif"),
        ("dem_stream_order_strahler_full.tif", "river_stream_order_strahler.tif"),
        ("dem_stream_link_id_full.tif", "river_stream_link_id.tif"),
    ]
    written = [name for pair in full_and_clipped for name in pair]
    assert backend.calls == ["dem_acc_cells.tif", *written, "write_vector river_network.shp"]
    assert result.threshold_cells == 50.0
    assert result.active_streams_tif == result.streams_pruned_tif
    assert Path(result.stream_link_id_full_tif).name == "dem_stream_link_id_full.tif"
    assert result.network_crs == "EPSG:2154"
    # The backend wrote no .prj, so the network carries the CRS it was read in.
    prj = Path(result.hydrographic_network_generated_shp).with_suffix(".prj")
    assert prj.read_text() == CRS("EPSG:2154").to_wkt("WKT1_ESRI")
    # The one-point record and the one-point part of the last are left out.
    assert result.river_mesh_trace.segment_count == 4
    summary = json.loads(Path(result.hydrographic_network_generated_summary_json).read_text())
    assert summary["stream_pixel_count"] == int(STREAMS.sum())
    assert summary["segment_count"] == 3
    assert summary["network_total_length_m"] == pytest.approx(10.0 + 20.0 + 20.0 + 10.0)
    assert summary["max_strahler_order"] == 2.0
    assert summary["catchment_area_km2"] == pytest.approx(0.002)
    assert summary["drainage_density_km_per_km2"] == pytest.approx(0.06 / 0.002)


def test_an_empty_vector_removes_the_stale_shapefile_and_keeps_the_summary(tmp_path) -> None:
    backend = RecordingBackend(records=(), projection="EPSG:2154")
    stale = tmp_path / "geographic" / "river_network.shp"
    stale.parent.mkdir(parents=True)
    for suffix in (".shp", ".dbf"):
        stale.with_suffix(suffix).touch()
    flags = dict(compute_strahler_order=False, compute_stream_links=False)
    result = _build(tmp_path, _config(**flags, prune_short_streams=False), backend)
    assert not any(call.startswith("write_vector") for call in backend.calls)
    assert result.hydrographic_network_generated_shp is result.river_mesh_trace is None
    assert result.stream_order_strahler_tif is None
    assert not stale.exists() and not stale.with_suffix(".dbf").exists()
    summary = json.loads(Path(result.hydrographic_network_generated_summary_json).read_text())
    assert (summary["segment_count"], summary["max_strahler_order"]) == (0, None)


def test_a_backend_without_the_raster_tools_is_refused(tmp_path) -> None:
    with pytest.raises(TypeError, match="delineation backend with raster APIs"):
        _build(tmp_path, _config(), SimpleNamespace(raster=None))
