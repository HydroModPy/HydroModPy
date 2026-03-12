"""Build legacy geographic raster artifacts on the canonical watershed support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import rasterio

from hydromodpy.backends import WhiteboxBackend, WhiteboxWorkflowsBackend, get_whitebox_backend
from hydromodpy.geographic.geographic_io import ensure_crs
from hydromodpy.geographic.geographic_paths import GeographicPaths
from hydromodpy.geographic.core.domain_dem import clip_dem_to_box_buffer
from hydromodpy.support.tools import toolbox


@dataclass(frozen=True)
class LegacyDomainRasterProducts:
    """Canonical raster artifacts produced by the full legacy pipeline."""

    watershed_box_buff_dem: str
    watershed_box_buff_fill: str
    watershed_box_buff_direc: str
    watershed_buff_dem: str
    watershed_buff_fill: str
    watershed_buff_direc: str
    watershed_dem: str
    watershed_fill: str
    watershed_direc: str
    watershed_contour_tif: str


def _clip_raster(
    *,
    src: str | Path,
    polygon: str | Path,
    dst: str | Path,
    maintain_dimensions: bool,
    crs_project: str | None,
    nodata: float | None,
    backend: WhiteboxBackend,
) -> None:
    """Clip one raster and enforce CRS / nodata conventions."""
    dst_path = str(dst)
    backend.clip_raster_to_polygon(
        str(src),
        str(polygon),
        dst_path,
        maintain_dimensions=maintain_dimensions,
    )
    ensure_crs(dst_path, crs_project)
    if nodata is not None:
        backend.modify_no_data_value(dst_path, new_value=float(nodata))


def _export_reshaped_rasters(
    *,
    paths: GeographicPaths,
) -> None:
    """Re-export legacy rasters on the box-buffer grid when shapes diverge."""
    jobs = [
        (paths.watershed_box_buff_dem, paths.watershed_dem, -9999),
        (paths.watershed_box_buff_fill, paths.watershed_fill, -9999),
        (paths.watershed_box_buff_direc, paths.watershed_direc, -32768),
        (paths.watershed_box_buff_dem, paths.watershed_buff_dem, -9999),
        (paths.watershed_box_buff_fill, paths.watershed_buff_fill, -9999),
        (paths.watershed_box_buff_direc, paths.watershed_buff_direc, -32768),
        (paths.watershed_box_buff_dem, paths.watershed_box_buff_dem, -9999),
        (paths.watershed_box_buff_fill, paths.watershed_box_buff_fill, -9999),
        (paths.watershed_box_buff_direc, paths.watershed_box_buff_direc, -32768),
    ]
    for src_path, dst_path, nodata in jobs:
        with rasterio.open(src_path) as src:
            data = src.read(1)
        toolbox.export_tif(paths.watershed_box_buff_dem, data, dst_path, nodata)


def build_legacy_domain_rasters(
    *,
    dem_init_path: str | Path,
    correc_path: str | Path,
    direc_path: str | Path,
    correc_data: object | None = None,
    direc_data: object | None = None,
    watershed_shp: str | Path,
    watershed_buff_shp: str | Path,
    paths: GeographicPaths,
    crs_project: str | None = None,
    backend: WhiteboxBackend | None = None,
) -> LegacyDomainRasterProducts:
    """
    Build the full legacy raster bundle used by solvers and postprocess.

    The generated files preserve historical names and nodata conventions.
    """
    tool = get_whitebox_backend() if backend is None else backend

    if isinstance(tool, WhiteboxWorkflowsBackend):
        dem_init_raster = tool.read_raster(str(dem_init_path))
        correc_raster = correc_data if correc_data is not None else tool.read_raster(str(correc_path))
        direc_raster = direc_data if direc_data is not None else tool.read_raster(str(direc_path))
        box_buff_vector = tool.read_vector(str(paths.box_buff))
        watershed_buff_vector = tool.read_vector(str(watershed_buff_shp))
        watershed_vector = tool.read_vector(str(watershed_shp))

        watershed_box_buff_dem = tool.clip_raster_to_polygon_raster(
            dem_init_raster,
            box_buff_vector,
            maintain_dimensions=False,
        )
        watershed_box_buff_dem = tool.modify_no_data_value_raster(
            watershed_box_buff_dem,
            new_value=-9999.0,
        )
        tool.write_raster(watershed_box_buff_dem, str(paths.watershed_box_buff_dem))
        ensure_crs(paths.watershed_box_buff_dem, crs_project)

        raster_sources: dict[str, object] = {
            str(correc_path): correc_raster,
            str(direc_path): direc_raster,
            str(paths.watershed_box_buff_dem): watershed_box_buff_dem,
        }
        polygon_sources: dict[str, object] = {
            str(paths.box_buff): box_buff_vector,
            str(watershed_buff_shp): watershed_buff_vector,
            str(watershed_shp): watershed_vector,
        }

        jobs = [
            (correc_path, paths.box_buff, paths.watershed_box_buff_fill, False, None),
            (direc_path, paths.box_buff, paths.watershed_box_buff_direc, False, None),
            (paths.watershed_box_buff_dem, watershed_buff_shp, paths.watershed_buff_dem, True, -9999),
            (correc_path, watershed_buff_shp, paths.watershed_buff_fill, False, None),
            (direc_path, watershed_buff_shp, paths.watershed_buff_direc, False, None),
            (paths.watershed_box_buff_dem, watershed_shp, paths.watershed_dem, True, None),
            (correc_path, watershed_shp, paths.watershed_fill, False, None),
            (direc_path, watershed_shp, paths.watershed_direc, False, None),
        ]
        for src, polygon, dst, maintain_dimensions, nodata in jobs:
            clipped = tool.clip_raster_to_polygon_raster(
                raster_sources[str(src)],
                polygon_sources[str(polygon)],
                maintain_dimensions=maintain_dimensions,
            )
            if nodata is not None:
                clipped = tool.modify_no_data_value_raster(clipped, new_value=float(nodata))
            tool.write_raster(clipped, str(dst))
            ensure_crs(dst, crs_project)
        tool.vector_lines_to_raster(
            str(watershed_shp),
            str(paths.watershed_contour_tif),
            base=str(paths.watershed_dem),
        )
    else:
        clip_dem_to_box_buffer(
            dem_init_path=dem_init_path,
            box_buff_shp=paths.box_buff,
            output_dem_path=paths.watershed_box_buff_dem,
            crs_project=crs_project,
            nodata=-9999.0,
            backend=tool,
        )

        jobs = [
            (correc_path, paths.box_buff, paths.watershed_box_buff_fill, False, None),
            (direc_path, paths.box_buff, paths.watershed_box_buff_direc, False, None),
            (paths.watershed_box_buff_dem, watershed_buff_shp, paths.watershed_buff_dem, True, -9999),
            (correc_path, watershed_buff_shp, paths.watershed_buff_fill, False, None),
            (direc_path, watershed_buff_shp, paths.watershed_buff_direc, False, None),
            (paths.watershed_box_buff_dem, watershed_shp, paths.watershed_dem, True, None),
            (correc_path, watershed_shp, paths.watershed_fill, False, None),
            (direc_path, watershed_shp, paths.watershed_direc, False, None),
        ]
        for src, polygon, dst, maintain_dimensions, nodata in jobs:
            _clip_raster(
                src=src,
                polygon=polygon,
                dst=dst,
                maintain_dimensions=maintain_dimensions,
                crs_project=crs_project,
                nodata=nodata,
                backend=tool,
            )

        tool.vector_lines_to_raster(
            str(watershed_shp),
            str(paths.watershed_contour_tif),
            base=str(paths.watershed_dem),
        )
    ensure_crs(paths.watershed_contour_tif, crs_project)

    with (
        rasterio.open(paths.watershed_box_buff_dem) as src1,
        rasterio.open(paths.watershed_buff_dem) as src2,
        rasterio.open(paths.watershed_dem) as src3,
    ):
        if src1.read(1).shape != src2.read(1).shape != src3.read(1).shape:
            _export_reshaped_rasters(paths=paths)

    return LegacyDomainRasterProducts(
        watershed_box_buff_dem=paths.watershed_box_buff_dem,
        watershed_box_buff_fill=paths.watershed_box_buff_fill,
        watershed_box_buff_direc=paths.watershed_box_buff_direc,
        watershed_buff_dem=paths.watershed_buff_dem,
        watershed_buff_fill=paths.watershed_buff_fill,
        watershed_buff_direc=paths.watershed_buff_direc,
        watershed_dem=paths.watershed_dem,
        watershed_fill=paths.watershed_fill,
        watershed_direc=paths.watershed_direc,
        watershed_contour_tif=paths.watershed_contour_tif,
    )

