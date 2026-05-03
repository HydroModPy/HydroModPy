from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from hydromodpy.solver.modflow_common.masstransfer import Masstransfer


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
        self.mass_flux_calls: list[dict[str, str]] = []
        self.vector_points_calls: list[tuple[str, str]] = []
        self.trace_calls: list[tuple[str, str, str]] = []
        self.flow = _FakeFlow(self)
        self.delineation = _FakeDelineation(self)


class _FakeFlow:
    def __init__(self, parent: _FakeWhiteboxBackend) -> None:
        self._parent = parent

    def d8_mass_flux(
        self,
        dem: str,
        loading: str,
        efficiency: str,
        absorption: str,
        output: str,
    ) -> None:
        self._parent.mass_flux_calls.append(
            {
                "dem": dem,
                "loading": loading,
                "efficiency": efficiency,
                "absorption": absorption,
                "output": output,
            }
        )
        with rasterio.open(loading) as src:
            arr = src.read(1)
            profile = src.profile.copy()
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(arr + 10, 1)

    def trace_downslope_flowpaths(
        self,
        input_points: str,
        d8_pntr: str,
        output_raster: str,
    ) -> None:
        self._parent.trace_calls.append((input_points, d8_pntr, output_raster))
        with rasterio.open(d8_pntr) as src:
            profile = src.profile.copy()
            arr = np.ones((src.height, src.width), dtype=profile["dtype"])
        with rasterio.open(output_raster, "w", **profile) as dst:
            dst.write(arr, 1)


class _FakeDelineation:
    def __init__(self, parent: _FakeWhiteboxBackend) -> None:
        self._parent = parent

    def raster_to_vector_points(self, input_raster: str, output_shp: str) -> None:
        self._parent.vector_points_calls.append((input_raster, output_shp))
        gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(0.5, 0.5)], crs="EPSG:2154")
        gdf.to_file(output_shp)


def test_masstransfer_trace_cumulated_uses_backend_and_writes_intermediates(tmp_path: Path) -> None:
    backend = _FakeWhiteboxBackend()
    geographic = SimpleNamespace(
        watershed_box_buff_fill=str(tmp_path / "routing_fill.tif"),
        watershed_box_buff_direc=str(tmp_path / "routing_direc.tif"),
    )
    fill = np.array([[1.0, 2.0], [3.0, -9999.0]], dtype=np.float32)
    direc = np.array([[1, 1], [1, -32768]], dtype=np.int16)
    _write_raster(Path(geographic.watershed_box_buff_fill), fill)
    _write_raster(Path(geographic.watershed_box_buff_direc), direc, nodata=-32768)

    model = Masstransfer(
        geographic,
        "mass_seepage_t(1).tif",
        "tracept_conc_t(1).shp",
        "mass_accumulated_t(1).tif",
        extraction_folder=str(tmp_path / "postprocess"),
        backend=backend,
    )

    raw = np.array([[5.0, -2.0], [7.0, -9999.0]], dtype=np.float32)
    _write_raster(Path(model.raw_rast_path), raw)

    model.trace_cumulated()

    assert len(backend.mass_flux_calls) == 1
    call = backend.mass_flux_calls[0]
    assert call["dem"] == geographic.watershed_box_buff_fill
    assert call["loading"] == model.load_rast_path
    assert call["efficiency"] == model.eff_rast_path
    assert call["absorption"] == model.abs_rast_path
    assert call["output"] == model.mass_rast_path

    with rasterio.open(model.load_rast_path) as src:
        load = src.read(1)
    with rasterio.open(model.eff_rast_path) as src:
        eff = src.read(1)
    with rasterio.open(model.abs_rast_path) as src:
        abs_arr = src.read(1)
    with rasterio.open(model.mass_rast_path) as src:
        mass = src.read(1)

    np.testing.assert_array_equal(load, np.array([[5.0, 0.0], [7.0, 0.0]], dtype=np.float32))
    np.testing.assert_array_equal(eff, np.array([[1.0, 1.0], [1.0, -9999.0]], dtype=np.float32))
    np.testing.assert_array_equal(abs_arr, np.array([[0.0, 0.0], [0.0, -9999.0]], dtype=np.float32))
    np.testing.assert_array_equal(mass, load + 10)


def test_masstransfer_trace_downslope_uses_backend_chain(tmp_path: Path) -> None:
    backend = _FakeWhiteboxBackend()
    geographic = SimpleNamespace(
        watershed_box_buff_fill=str(tmp_path / "routing_fill.tif"),
        watershed_box_buff_direc=str(tmp_path / "routing_direc.tif"),
    )
    _write_raster(Path(geographic.watershed_box_buff_fill), np.ones((2, 2), dtype=np.float32))
    _write_raster(
        Path(geographic.watershed_box_buff_direc),
        np.ones((2, 2), dtype=np.int16),
        nodata=-32768,
    )

    model = Masstransfer(
        geographic,
        "mass_seepage_t(1).tif",
        "tracept_conc_t(1).shp",
        "mass_accumulated_t(1).tif",
        extraction_folder=str(tmp_path / "postprocess"),
        backend=backend,
    )
    _write_raster(Path(model.raw_rast_path), np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.float32))

    model.trace_downslope()

    assert backend.vector_points_calls == [
        (model.raw_rast_path, model.raw_pt_path),
        (model.out_rast_path, model.out_pt_path),
    ]
    assert backend.trace_calls == [
        (model.raw_pt_path, geographic.watershed_box_buff_direc, model.out_rast_path)
    ]
    assert Path(model.raw_pt_path).exists()
    assert Path(model.out_rast_path).exists()
    assert Path(model.out_pt_path).exists()
