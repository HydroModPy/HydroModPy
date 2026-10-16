"""Export the cell mesh of a run as vector layers: its cells, their seeds, the faces of its lines.

Three layers describe the mesh a run was solved on:

``mesh_cells``
    One polygon per cell, with its area, the families it belongs to, its zone,
    its topography and its quality (centre offset, neighbour ratio,
    non-orthogonality).
``mesh_seeds``
    One point per cell, at the centre the solver used, with the rule that
    placed it and the families of the cell.
``mesh_family_faces``
    One segment per face that lies on a line family (a barrier, a boundary),
    with the cells and the zones on its two sides.

A GeoPackage holds the layers of a request in one file; a Shapefile holds one
layer per file. The CRS is the one the ``mesh/`` group states, never the one of
the run root, and ``crs`` reprojects it. A run sealed before the cell-mesh
layout states none, so it holds no layer and the export says why.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.config_kit.export_spec import MESH_LAYERS
from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.logging import get_logger
from hydromodpy.results.derive.mesh_quality import mesh_quality_values
from hydromodpy.results.exporters._tables import FACE_FAMILIES_TABLE, read_table, table_rows

if TYPE_CHECKING:
    import geopandas as gpd

logger = get_logger(__name__)

_DRIVERS = {"geopackage": "GPKG", "shapefile": "ESRI Shapefile"}
_QUALITY_COLUMNS = {
    "area_m2": "mesh_cell_area",
    "center_offset": "mesh_center_offset",
    "neighbour_ratio": "mesh_neighbour_ratio",
    "nonorthogonality_deg": "mesh_nonorthogonality",
}


def mesh_layer_reasons(store: Any, sim_id: str) -> dict[str, str]:
    """Return why each mesh layer is unavailable for a run, an empty mapping when all are held.

    Read from the run directory: the ``mesh/`` group of the field store and
    the ``mesh_face_families`` table.
    """
    sz = store.open_zarr(sim_id)
    try:
        mesh = sz.root.get("mesh")
        reason = _mesh_reason(mesh)
    finally:
        sz.close()
    if reason is not None:
        return dict.fromkeys(MESH_LAYERS, reason)
    if not table_rows(store, sim_id, FACE_FAMILIES_TABLE):
        return {
            "mesh_family_faces": (
                "the mesh has no face on a line family (no barrier and no boundary line)"
            )
        }
    return {}


def available_mesh_layers(store: Any, sim_id: str) -> list[str]:
    """Return the mesh layers this run holds."""
    missing = mesh_layer_reasons(store, sim_id)
    return [name for name in MESH_LAYERS if name not in missing]


def export_mesh_layers(
    store: Any,
    sim_id: str,
    names: Sequence[str],
    dest: str | Path,
    *,
    fmt: str = "geopackage",
    crs: str | None = None,
) -> Path:
    """Write mesh layers to a GeoPackage, or one layer to a Shapefile.

    Parameters
    ----------
    store
        What holds the run: the store of a run being computed or a catalog.
    sim_id
        Simulation UUID.
    names
        The layers to write, among :data:`~hydromodpy.core.config_kit.export_spec.MESH_LAYERS`.
        A Shapefile takes one.
    dest
        Destination file.
    fmt
        ``"geopackage"`` or ``"shapefile"``.
    crs
        CRS to reproject into. Left out, the CRS stated by the ``mesh/`` group.

    Raises
    ------
    ExportError
        The run holds none of a layer, with the reason.
    ValueError
        A format that cannot hold the layers asked, or a name that is no mesh layer.
    """
    if fmt not in _DRIVERS:
        raise ValueError(f"A mesh layer is written as {' or '.join(_DRIVERS)}, not {fmt!r}.")
    unknown = [name for name in names if name not in MESH_LAYERS]
    if unknown:
        raise ValueError(f"{unknown} are no mesh layers. The mesh layers are {list(MESH_LAYERS)}.")
    if fmt == "shapefile" and len(names) != 1:
        raise ValueError(f"A Shapefile holds one layer, and {len(names)} were asked.")
    reasons = mesh_layer_reasons(store, sim_id)
    for name in names:
        if name in reasons:
            raise ExportError(f"run {sim_id[:8]} holds no {name!r}: {reasons[name]}.")

    frames = _read_layers(store, sim_id, names, crs)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "geopackage":
        _write_geopackage(frames, dest)
    else:
        ((_, frame),) = frames.items()
        frame.to_file(str(dest), driver=_DRIVERS[fmt])
    logger.info(
        "Exported mesh layers %s: %s (%s)",
        ", ".join(frames),
        dest,
        ", ".join(f"{len(frame)} features" for frame in frames.values()),
    )
    return dest


def _write_geopackage(frames: dict[str, gpd.GeoDataFrame], dest: Path) -> None:
    """Write the layers to a temporary file beside ``dest``, then swap it in.

    A failed export destroys nothing, and a viewer that holds the previous file
    open keeps reading it until it reloads.
    """
    tmp = dest.with_name(f".{dest.stem}.tmp{dest.suffix}")
    tmp.unlink(missing_ok=True)
    try:
        for index, (name, frame) in enumerate(frames.items()):
            frame.to_file(str(tmp), driver="GPKG", layer=name, mode="w" if index == 0 else "a")
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _mesh_reason(mesh: Any) -> str | None:
    """Say why a ``mesh/`` group cannot give the layers, ``None`` when it can."""
    if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
        return "the run stored no mesh geometry"
    if not mesh.attrs.get("crs"):
        return (
            "the run was sealed before the cell-mesh layout: its mesh states no CRS and "
            "stores no cell centres or families, so its cells cannot be placed in a GIS file"
        )
    return None


def _read_layers(
    store: Any, sim_id: str, names: Sequence[str], crs: str | None
) -> dict[str, gpd.GeoDataFrame]:
    """Build the layers in the CRS of the mesh, reprojected into ``crs`` when given."""
    builders = {
        "mesh_cells": _cells,
        "mesh_seeds": _seeds,
        "mesh_family_faces": _family_faces,
    }
    sz = store.open_zarr(sim_id)
    try:
        mesh = sz.root["mesh"]
        source_crs = str(mesh.attrs["crs"])
        frames = {name: builders[name](sz.root, store, sim_id) for name in names}
    finally:
        sz.close()
    result = {}
    for name, frame in frames.items():
        frame = frame.set_crs(source_crs)
        result[name] = frame if crs is None else frame.to_crs(crs)
    return result


def _packed_rings(connectivity: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the rows with their nodes first, and the node count of each row."""
    missing = connectivity < 0
    order = np.argsort(missing, axis=1, kind="stable")
    return np.take_along_axis(connectivity, order, axis=1), (~missing).sum(axis=1)


def _cell_polygons(vertices: np.ndarray, connectivity: np.ndarray) -> np.ndarray:
    """Return one polygon per cell, built a node count at a time. Every cell is kept."""
    import shapely

    packed, sizes = _packed_rings(connectivity)
    polygons = np.empty(len(connectivity), dtype=object)
    for size in np.unique(sizes):
        if size < 3:
            continue
        rows = np.flatnonzero(sizes == size)
        polygons[rows] = shapely.polygons(vertices[packed[rows, :size], :2])
    held = np.array([geom is not None for geom in polygons])
    invalid = int((~held).sum()) + int((~shapely.is_valid(polygons[held])).sum())
    if invalid:
        logger.warning(
            "%d of %d mesh cells are not valid polygons; kept as stored", invalid, len(polygons)
        )
    return polygons


def _family_columns(mesh: Any) -> tuple[list[str], list[str], np.ndarray]:
    """Return the exact family names, their CF column names and the bits of each cell."""
    bits = np.asarray(mesh["face_family"][:])
    attrs = mesh["face_family"].attrs
    names = [str(name) for name in attrs.get("family_names", [])]
    meanings = str(attrs.get("flag_meanings", "")).split()
    return names, meanings, bits


def _flag(bits: np.ndarray, index: int) -> np.ndarray:
    return (bits & (1 << index)) != 0


def _cells(root: Any, store: Any, sim_id: str) -> gpd.GeoDataFrame:
    import geopandas as gpd

    mesh = root["mesh"]
    vertices = np.asarray(mesh["vertices"][:], dtype=np.float64)
    connectivity = np.asarray(mesh["face_node_connectivity"][:])
    columns: dict[str, Any] = {"cell_id": np.arange(len(connectivity), dtype=np.int64)}
    columns["area_m2"] = mesh_quality_values(root, _QUALITY_COLUMNS["area_m2"])
    names, meanings, bits = _family_columns(mesh)
    for index, meaning in enumerate(meanings):
        columns[f"family_{meaning}"] = _flag(bits, index)
    if "face_zone" in mesh:
        columns["zone"] = _zone_names(mesh)
    if "topography" in mesh:
        columns["topography"] = np.asarray(mesh["topography"][:], dtype=np.float64)
    for column in ("center_offset", "neighbour_ratio", "nonorthogonality_deg"):
        columns[column] = mesh_quality_values(root, _QUALITY_COLUMNS[column])
    if "descent_basin" in mesh:
        columns["in_basin"] = np.asarray(mesh["descent_basin"][:]).astype(bool)
    return gpd.GeoDataFrame(columns, geometry=_cell_polygons(vertices, connectivity))


def _seeds(root: Any, store: Any, sim_id: str) -> gpd.GeoDataFrame:
    import geopandas as gpd
    import shapely

    mesh = root["mesh"]
    face_x = np.asarray(mesh["face_x"][:], dtype=np.float64)
    face_y = np.asarray(mesh["face_y"][:], dtype=np.float64)
    names, _, bits = _family_columns(mesh)
    families = np.full(len(bits), "", dtype=object)
    for row in np.flatnonzero(bits):
        families[row] = ";".join(
            name for index, name in enumerate(names) if bits[row] & (1 << index)
        )
    columns = {
        "cell_id": np.arange(len(face_x), dtype=np.int64),
        "center_kind": str(mesh["face_x"].attrs.get("center_kind", "")),
        "families": families,
    }
    return gpd.GeoDataFrame(columns, geometry=shapely.points(face_x, face_y))


def _family_faces(root: Any, store: Any, sim_id: str) -> gpd.GeoDataFrame:
    import geopandas as gpd
    import shapely

    mesh = root["mesh"]
    table = read_table(store, sim_id, FACE_FAMILIES_TABLE)
    table = table.sort_values("face_row", kind="stable").reset_index(drop=True)
    vertices = np.asarray(mesh["vertices"][:], dtype=np.float64)[:, :2]
    ends = np.stack(
        [vertices[table["node_a"].to_numpy()], vertices[table["node_b"].to_numpy()]], axis=1
    )
    keep = ["family", "face_row", "edge_id", "cell_a", "cell_b", "zone_left", "zone_right"]
    return gpd.GeoDataFrame(table[keep].copy(), geometry=shapely.linestrings(ends))


def _zone_names(mesh: Any) -> np.ndarray:
    """Return the zone name of each cell, ``None`` where the zone is unknown."""
    codes = np.asarray(mesh["face_zone"][:])
    names = np.array(
        [str(name) for name in mesh["face_zone"].attrs.get("zone_names", [])] + [None],
        dtype=object,
    )
    return names[np.where(codes >= 0, codes, len(names) - 1)]
