"""The raster bundle of the watershed, through a backend that clips in memory."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.spatial.geographic.domain_rasters import build_domain_rasters
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths


def _write_tif(path: str | Path, values: np.ndarray) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype=values.dtype,
        transform=from_origin(0.0, 100.0, 10.0, 10.0),
    ) as dst:
        dst.write(values, 1)


def _shape(path: str | Path) -> tuple[int, int]:
    with rasterio.open(path) as src:
        return src.shape


def _crs(path: str | Path) -> str:
    with rasterio.open(path) as src:
        return src.crs.to_string()


def _memory_backend(widths: dict[str, int]) -> SimpleNamespace:
    """A polygon is a width here, and clipping keeps that many rows and columns."""

    def read_raster(path: str) -> np.ndarray:
        with rasterio.open(path) as src:
            return src.read(1)

    def clip(raster: np.ndarray, width: int, *, maintain_dimensions: bool) -> np.ndarray:
        return raster[:width, :width]

    return SimpleNamespace(
        raster=SimpleNamespace(
            read_raster=read_raster,
            read_vector=widths.__getitem__,
            clip_raster_to_polygon_raster=clip,
            modify_no_data_value_raster=lambda raster, new_value: raster,
            write_raster=lambda raster, path: _write_tif(path, raster),
            vector_lines_to_raster_vector=lambda vector, base_raster: np.zeros_like(base_raster),
        )
    )


def _build(tmp_path: Path, *, box: int, buffer: int, watershed: int):
    paths = build_geographic_paths(tmp_path / "out")
    regional = np.arange(64.0, dtype="float32").reshape(8, 8)
    for name in ("dem", "fill", "direc"):
        _write_tif(tmp_path / f"{name}.tif", regional)
    products = build_domain_rasters(
        dem_init_path=tmp_path / "dem.tif",
        correc_path=tmp_path / "fill.tif",
        direc_path=tmp_path / "direc.tif",
        watershed_shp="watershed.shp",
        watershed_buff_shp="buffer.shp",
        paths=paths,
        crs_project="EPSG:2154",
        backend=_memory_backend(
            {paths.box_buff: box, "buffer.shp": buffer, "watershed.shp": watershed}
        ),
    )
    return paths, products


def test_rasters_of_one_shape_keep_the_clip_of_their_own_polygon(tmp_path: Path) -> None:
    paths, products = _build(tmp_path, box=5, buffer=5, watershed=5)

    assert products.watershed_dem == paths.watershed_dem
    assert products.watershed_contour_tif == paths.watershed_contour_tif
    for field in vars(products).values():
        assert _shape(field) == (5, 5)
        assert _crs(field) == "EPSG:2154"


@pytest.mark.parametrize(
    ("clipped", "box"),
    [
        ("watershed_dem", "watershed_box_buff_dem"),
        ("watershed_buff_fill", "watershed_box_buff_fill"),
        ("watershed_direc", "watershed_box_buff_direc"),
    ],
)
def test_rasters_of_diverging_shapes_are_written_again_on_the_box_grid(
    tmp_path: Path, clipped: str, box: str
) -> None:
    paths, _ = _build(tmp_path, box=6, buffer=5, watershed=4)

    assert _shape(getattr(paths, clipped)) == (6, 6)
    with rasterio.open(getattr(paths, clipped)) as out, rasterio.open(getattr(paths, box)) as ref:
        assert np.array_equal(out.read(1), ref.read(1))
