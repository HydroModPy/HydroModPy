"""The inputs of the field tests: hand-built cell meshes, TOML files, a geology raster.

``planar_mesh`` wraps a few hand-written cells into the ``PlanarCellMesh`` a
support samples. ``two_zone_square`` is the granite and micaschists square of
the field demos, cut along its main diagonal. Not public API.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from hydromodpy.spatial.field.two_zone_field import FieldSquare
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.geotiffs import write_geotiff


def planar_mesh(
    vertices: np.ndarray,
    cells: Sequence[Sequence[int]],
    cell_type: CellType,
    *,
    centers: np.ndarray | None = None,
    exact_faces: bool = False,
    cell_zone: np.ndarray | None = None,
    zone_names: tuple[str, ...] = (),
) -> PlanarCellMesh:
    """Return the cell mesh of *cells* on *vertices*, centred on their vertex means by default."""
    vertices = np.asarray(vertices, dtype=float)
    connectivity = (
        tuple(np.asarray(cell) for cell in cells)
        if cell_type is CellType.POLYGON
        else np.asarray(cells)
    )
    hydro = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(cell_type, connectivity),))
    if centers is None:
        centers = np.array([vertices[list(cell)].mean(axis=0) for cell in cells])
    return build_planar_cell_mesh(
        hydro,
        np.asarray(centers, dtype=float),
        center_kind="vertex_mean",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations={
            "graded": False,
            "exact_faces": exact_faces,
            "deterministic": True,
            "needs_cache": False,
        },
        cell_zone=cell_zone,
        zone_names=zone_names,
    )


def two_zone_square() -> FieldSquare:
    """The unit square cut along its main diagonal, granite above it and micaschists below."""
    return FieldSquare(
        line="diag_main",
        zone1_side="positive",
        identifier="field_square",
        zone1_name="granite",
        zone2_name="micaschists",
    )


def write_text(path: Path, text: str) -> Path:
    """Write the dedented *text* to *path* and return it."""
    path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")
    return path


def geology_raster(path: Path) -> Path:
    """Write a 4 x 4 geology raster over the unit square: code 1 in the west half, 2 in the east."""
    codes = np.repeat([[1.0, 1.0, 2.0, 2.0]], 4, axis=0)
    return write_geotiff(
        path, codes, origin=(0.0, 1.0), cell=0.25, crs="EPSG:3857", nodata=-9999.0, dtype="float32"
    )


CONTACT_X = 352_000.0
"""Easting of the contact between the two units of ``vector_geology_field``."""


def vector_geology_support():
    """The 30 x 30 support of 100 m pixels the vector geology is cut to, in Lambert-93."""
    from hydromodpy.spatial.raster_support import RasterSupport

    return RasterSupport(
        crs="EPSG:2154", dx=100.0, dy=100.0, xmin=350_500.0, xmax=353_500.0,
        ymin=6_780_500.0, ymax=6_783_500.0, nrows=30, ncols=30,
    )  # fmt: skip


def vector_geology_field(folder: Path):
    """Two units A and B side by side at ``CONTACT_X``, written in WGS84 to force a reprojection."""
    from types import SimpleNamespace

    import geopandas as gpd
    from shapely.geometry import box

    from hydromodpy.data.variables.geology.field import build_geology_field

    units = gpd.GeoDataFrame(
        {"CODE": ["A", "B"]},
        geometry=[
            box(350_000.0, 6_780_000.0, CONTACT_X, 6_784_000.0),
            box(CONTACT_X, 6_780_000.0, 354_000.0, 6_784_000.0),
        ],
        crs="EPSG:2154",
    )
    path = folder / "units.gpkg"
    units.to_crs("EPSG:4326").to_file(str(path), driver="GPKG")
    return build_geology_field(
        SimpleNamespace(data=str(path), source="custom"),
        geology_cfg=SimpleNamespace(
            id="geology",
            cell_samples_per_axis=8,
            sources=[SimpleNamespace(source="custom", code_field="CODE")],
        ),
        raster_support=vector_geology_support(),
    )
