from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from hydromodpy.analysis.postprocess.flow.matching_streams import MatchingStreams


def _write_raster(path: Path, data: np.ndarray, *, nodata: float = -9999.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": int(data.shape[0]),
        "width": int(data.shape[1]),
        "count": 1,
        "dtype": data.dtype,
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, float(data.shape[0]), 1.0, 1.0),
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


class _FakeWhiteboxBackend:
    def __init__(self) -> None:
        self.vector_calls: list[tuple[str, str]] = []
        self.trace_calls: list[tuple[str, str, str]] = []
        self.distance_calls: list[tuple[str, str, str]] = []
        self.coord_calls: list[str] = []
        self.extract_calls: list[tuple[object, str]] = []

    def raster_to_vector_points(self, input_raster: str, output_shp: str) -> None:
        self.vector_calls.append((input_raster, output_shp))
        gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(0.5, 0.5)], crs="EPSG:2154")
        gdf.to_file(output_shp)

    def trace_downslope_flowpaths(
        self,
        input_points: str,
        d8_pntr: str,
        output_raster: str,
    ) -> None:
        self.trace_calls.append((input_points, d8_pntr, output_raster))
        with rasterio.open(d8_pntr) as src:
            profile = src.profile.copy()
            arr = np.ones((src.height, src.width), dtype=profile["dtype"])
        with rasterio.open(output_raster, "w", **profile) as dst:
            dst.write(arr, 1)

    def downslope_distance_to_stream(
        self,
        dem: str,
        streams: str,
        output_raster: str,
        *,
        use_dinf: bool | None = None,
    ) -> None:
        del use_dinf
        self.distance_calls.append((dem, streams, output_raster))
        with rasterio.open(dem) as src:
            profile = src.profile.copy()
            arr = np.zeros((src.height, src.width), dtype=profile["dtype"])
        with rasterio.open(output_raster, "w", **profile) as dst:
            dst.write(arr, 1)

    def add_point_coordinates_to_table(self, input_shp: str) -> None:
        self.coord_calls.append(input_shp)

    def extract_raster_values_at_points(
        self,
        rasters: str | list[str],
        points: str,
    ) -> None:
        self.extract_calls.append((rasters, points))


def test_matching_streams_skips_empty_simulated_support(tmp_path: Path, monkeypatch) -> None:
    workspace = SimpleNamespace(simulations_folder=str(tmp_path / "simulations"))
    iteration = "run_01"

    routing_fill = tmp_path / "routing_fill.tif"
    routing_direc = tmp_path / "routing_direc.tif"
    observed_streams = tmp_path / "observed_streams.tif"
    seepage = (
        Path(workspace.simulations_folder)
        / iteration
        / "_postprocess"
        / "_rasters"
        / "seepage_areas_t(0).tif"
    )
    _write_raster(routing_fill, np.ones((3, 3), dtype=np.float32))
    _write_raster(routing_direc, np.ones((3, 3), dtype=np.int16), nodata=-32768)
    _write_raster(
        observed_streams,
        np.array(
            [
                [1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        ),
    )
    _write_raster(seepage, np.zeros((3, 3), dtype=np.float32))

    geographic = SimpleNamespace(
        watershed_shp=str(tmp_path / "watershed.shp"),
        watershed_dem=str(routing_fill),
        watershed_fill=str(routing_fill),
        watershed_direc=str(routing_direc),
    )
    hydrography = SimpleNamespace(tif_streams=str(observed_streams))

    backend = _FakeWhiteboxBackend()

    def _fake_clip_tif(tif_path, shp_path, out_path, maintain_dimensions):
        del shp_path, maintain_dimensions
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tif_path, out_path)

    monkeypatch.setattr(
        "hydromodpy.analysis.postprocess.flow.matching_streams.get_whitebox_backend",
        lambda: backend,
    )
    monkeypatch.setattr(
        "hydromodpy.analysis.postprocess.flow.matching_streams.clip_tif",
        _fake_clip_tif,
    )

    model = MatchingStreams(
        geographic=geographic,
        hydrography=hydrography,
        initializing=workspace,
        model_modflow=None,
        iteration_label=iteration,
        from_calib=False,
    )

    assert model.has_observed_support is True
    assert model.has_simulated_support is False
    assert len(backend.vector_calls) == 2
    assert all(Path(out_path).name in {"obs_pt.shp", "obs_ptf.shp"} for _, out_path in backend.vector_calls)
    assert len(backend.trace_calls) == 1
    assert Path(backend.trace_calls[0][0]).name == "obs_pt.shp"
    assert backend.distance_calls == []
    assert backend.coord_calls == []
    assert backend.extract_calls == []
    assert not (Path(workspace.simulations_folder) / iteration / "_matchingstreams" / "sim_pt.shp").exists()
