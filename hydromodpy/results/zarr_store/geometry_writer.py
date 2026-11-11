"""Write-side of the geometry of a simulation store: mesh, descent, topography, time, CRS and the geographic raster."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np
import zarr

from hydromodpy.core.exceptions import IncompatibleMeshError
from hydromodpy.core.fields.vertical_column import IDOMAIN_VALUES
from hydromodpy.results import field_registry
from hydromodpy.results.zarr_store.constants import BLOSC_ZSTD
from hydromodpy.results.zarr_store.mesh_layout import MeshLayout, cf_flag_meanings
from hydromodpy.results.zarr_store.zarr_schema import (
    child_zarr_path,
    ensure_local_zarr_node_dir,
    update_attrs,
)

if TYPE_CHECKING:
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr


def attrs_for_field(name: str, dtype: np.dtype) -> dict[str, object]:
    """Compose CF attrs for a field straight from the registry + _FillValue.

    A float field declares no ``_FillValue`` attribute. Its missing value is
    NaN, JSON has no token for NaN, and writing one anyway is what made every
    ``zarr.json`` of the corpus invalid under RFC 8259. The array's own Zarr
    ``fill_value`` already carries NaN, serialized as the string ``"NaN"`` the
    Zarr v3 spec defines for it, so nothing is lost and readers still mask.
    An integer sentinel has a JSON number and stays in the CF block.
    """
    if not field_registry.has(name):
        attrs: dict[str, object] = {}
    else:
        attrs = dict(field_registry.cf_attrs(name))
    if np.issubdtype(dtype, np.integer):
        attrs["_FillValue"] = int(np.iinfo(dtype).min)
        attrs["missing_value"] = int(np.iinfo(dtype).min)
    return attrs


def ensure_child_dir(store_obj: SimulationZarr, target: zarr.Group, name: str) -> None:
    """Pre-create a directory node under ``target`` for the live store."""
    ensure_local_zarr_node_dir(store_obj._path, child_zarr_path(target, name))


def write_array(
    store_obj: SimulationZarr,
    parent: zarr.Group,
    name: str,
    data: np.ndarray,
    *,
    dimension_names: tuple[str, ...],
    attrs: dict[str, object] | None = None,
    compressors: Any | None = None,
    fill_value: float | None = None,
) -> zarr.Array:
    """Pre-create the child dir, write an array, and stamp ``attrs``.

    ``dimension_names`` is required, not optional: an array whose axes have no
    name cannot be opened by xarray and cannot be joined to anything. A 0-d
    array passes an empty tuple, which Zarr stores as no names at all.
    """
    ensure_child_dir(store_obj, parent, name)
    kwargs: dict[str, Any] = {
        "data": data,
        "overwrite": True,
        "dimension_names": tuple(dimension_names),
    }
    if compressors is not None:
        kwargs["compressors"] = compressors
    if fill_value is not None:
        kwargs["fill_value"] = fill_value
    arr = parent.create_array(name, **kwargs)
    if attrs:
        update_attrs(arr, attrs)
    return arr


def _interfaces(values: np.ndarray, n_cells: int | None) -> np.ndarray:
    """Return ``z_interfaces`` as a ``(n_layers + 1, n_faces)`` float array, or raise.

    Every cell carries its own column: row 0 is the top of the model, row
    ``k + 1`` the bottom of layer ``k``. A single column given for a mesh of
    known size is the column of every cell.
    """
    interfaces = np.asarray(values, dtype="float64")
    if interfaces.ndim == 1 and n_cells is not None:
        interfaces = np.tile(interfaces.reshape(-1, 1), (1, int(n_cells)))
    if interfaces.ndim != 2 or interfaces.shape[0] < 2:
        raise ValueError(
            "z_interfaces holds one column per cell, shape (n_layers + 1, n_faces); "
            f"got shape {interfaces.shape}"
        )
    if n_cells is not None and interfaces.shape[1] != int(n_cells):
        raise IncompatibleMeshError(
            f"z_interfaces describes {interfaces.shape[1]} cells, the mesh {int(n_cells)}"
        )
    return interfaces


_Z_INTERFACE_ATTRS: dict[str, object] = {
    "long_name": "Altitude of layer interfaces",
    "units": "m",
    "standard_name": "altitude",
    "positive": "up",
}


_IDOMAIN_FLAGS: dict[str, object] = {
    "flag_values": list(IDOMAIN_VALUES),
    "flag_meanings": "pass_through inactive active",
}


_STANDARD_NAMES: dict[str, str] = {"x": "projection_x_coordinate", "y": "projection_y_coordinate"}
"""CF standard name of each horizontal axis: what tells a UGRID reader which array is x."""


_DEGREE_AXES: dict[str, dict[str, str]] = {
    "x": {"standard_name": "longitude", "units": "degrees_east"},
    "y": {"standard_name": "latitude", "units": "degrees_north"},
}
"""CF standard name and unit of each axis of a raster in a geographic CRS."""


_METRE_AXES: dict[str, dict[str, str]] = {
    axis: {"standard_name": name, "units": "m"} for axis, name in _STANDARD_NAMES.items()
}
"""CF standard name and unit of each axis of a raster in a projected CRS."""


_MESH_COORDINATES = ("node_x", "node_y", "face_x", "face_y")
"""The coordinate arrays of ``mesh/`` that name the grid mapping."""


def write_mesh(
    store_obj: SimulationZarr,
    vertices: np.ndarray,
    face_node_connectivity: np.ndarray,
    z_interfaces: np.ndarray,
    layer_indices: np.ndarray | None = None,
    source_cell_indices: np.ndarray | None = None,
    topography: np.ndarray | None = None,
    *,
    layer_thickness: np.ndarray | None = None,
    start_index: int = 0,
    grid_type: str | None = None,
    structured_shape: tuple[int, int] | None = None,
    layout: MeshLayout | None = None,
) -> None:
    """Write the UGRID-1.0 mesh group, including the optional topography array.

    ``z_interfaces`` is the ``(n_layers + 1, n_faces)`` column of every cell
    and ``layer_thickness`` the ``(n_layers, n_faces)`` thickness it implies.

    ``layout`` adds the cell centers, the family bit fields, the zone codes, the
    edge tables and the engine attributes. Without it the group holds the
    topology alone.

    ``vertices`` keeps the nodes as one ``(n_nodes, 3)`` array for the readers
    of HydroModPy. ``node_x`` and ``node_y`` repeat its first two columns,
    because UGRID wants one array per axis, and ``node_coordinates`` names
    them. The third column, z = 0 for a planar mesh, gets no array of its
    own: a UGRID reader would take it for a node elevation. With the CRS
    copied into the group, xugrid opens ``mesh/`` as it is stored.
    """
    with store_obj._guard_write():
        mesh = store_obj._root.require_group("mesh")
        nodes = np.asarray(vertices, dtype="float64")
        write_array(
            store_obj,
            mesh,
            "vertices",
            nodes,
            dimension_names=(field_registry.AXIS_NODE, field_registry.AXIS_NODE_COORDINATE),
            attrs={
                "long_name": "Mesh node coordinates (x, y, z)",
                "units": "m",
                "cf_role": "mesh_node_coordinates",
            },
        )
        _write_node_axes(store_obj, mesh, nodes)
        write_array(
            store_obj,
            mesh,
            "face_node_connectivity",
            np.asarray(face_node_connectivity, dtype="int32"),
            dimension_names=(field_registry.AXIS_FACE, field_registry.AXIS_MAX_FACE_NODES),
            attrs={
                "cf_role": "face_node_connectivity",
                "long_name": "Mapping from every face to its corner nodes",
                "start_index": int(start_index),
                "_FillValue": -1,
            },
        )
        interfaces = _interfaces(z_interfaces, int(np.asarray(face_node_connectivity).shape[0]))
        write_array(
            store_obj,
            mesh,
            "z_interfaces",
            interfaces,
            dimension_names=(field_registry.AXIS_LAYER_INTERFACE, field_registry.AXIS_FACE),
            attrs=_Z_INTERFACE_ATTRS,
        )
        if layer_indices is not None:
            write_array(
                store_obj,
                mesh,
                "layer_indices",
                np.asarray(layer_indices, dtype="int32"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
        if source_cell_indices is not None:
            write_array(
                store_obj,
                mesh,
                "source_cell_indices",
                np.asarray(source_cell_indices, dtype="int32"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
        if topography is not None:
            topo_arr = write_array(
                store_obj,
                mesh,
                "topography",
                np.asarray(topography, dtype="float64"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
            update_attrs(topo_arr, attrs_for_field("topography", topo_arr.dtype))
        _write_vertical_arrays(store_obj, mesh, layer_thickness=layer_thickness)

        n_nodes = int(np.asarray(vertices).shape[0])
        n_cells = int(np.asarray(face_node_connectivity).shape[0])
        mesh_attrs: dict[str, object] = {}
        topology_attrs: dict[str, object] = {
            "cf_role": "mesh_topology",
            "long_name": "UGRID 2D topology of the simulation mesh",
            "topology_dimension": 2,
            "node_coordinates": "node_x node_y",
            "face_node_connectivity": "face_node_connectivity",
        }
        if layout is not None:
            _check_layout(layout, n_nodes=n_nodes, n_cells=n_cells)
            mesh_attrs.update(layout.attrs)
            topology_attrs.update(_write_layout(store_obj, mesh, layout))
        mesh_attrs.update(
            {
                "start_index": int(start_index),
                "n_nodes": n_nodes,
                "n_cells": n_cells,
                "n_layers": int(interfaces.shape[0] - 1),
            }
        )
        if grid_type:
            mesh_attrs["grid_type"] = str(grid_type)
        if structured_shape is not None:
            mesh_attrs["structured_shape"] = [
                int(structured_shape[0]),
                int(structured_shape[1]),
            ]
        update_attrs(mesh, mesh_attrs)

        # UGRID-1.0 topology scalar variable carrying the topology attrs.
        write_array(
            store_obj,
            mesh,
            "topology",
            np.zeros((), dtype="int32"),
            dimension_names=(),
            attrs=topology_attrs,
        )
        _write_mesh_crs(store_obj)


def _write_node_axes(store_obj: SimulationZarr, mesh: zarr.Group, nodes: np.ndarray) -> None:
    """Write the first two columns of ``vertices`` as ``node_x`` and ``node_y``."""
    node = (field_registry.AXIS_NODE,)
    for column, axis in enumerate("xy"):
        write_array(
            store_obj,
            mesh,
            f"node_{axis}",
            np.ascontiguousarray(nodes[:, column]),
            dimension_names=node,
            attrs={
                "standard_name": _STANDARD_NAMES[axis],
                "long_name": f"{axis} coordinate of the mesh node",
                "units": "m",
            },
        )


def _write_mesh_crs(store_obj: SimulationZarr) -> None:
    """Copy the root ``crs`` into ``mesh/`` and name it from the topology and the coordinates.

    A UGRID reader opens ``mesh/`` alone and never sees the root, so the group
    holds its own grid-mapping variable. It is written once both the mesh and
    the CRS exist, whichever comes first, and never on a run with no CRS.
    """
    root = store_obj._root
    mesh = root.get("mesh")
    crs = root.get("crs")
    if not isinstance(mesh, zarr.Group) or not isinstance(crs, zarr.Array):
        return
    if "topology" not in mesh:
        return
    write_array(
        store_obj,
        mesh,
        "crs",
        np.zeros((), dtype="int32"),
        dimension_names=(),
        attrs=dict(crs.attrs),
    )
    for name in ("topology", *_MESH_COORDINATES):
        if name in mesh:
            update_attrs(mesh[name], {"grid_mapping": "crs"})


def _write_vertical_arrays(
    store_obj: SimulationZarr,
    mesh: zarr.Group,
    *,
    layer_thickness: np.ndarray | None,
    streambed_top: np.ndarray | None = None,
    streambed_connection: np.ndarray | None = None,
    idomain: np.ndarray | None = None,
) -> None:
    """Write the per-face arrays that depend on the solved model, when given."""
    if idomain is not None:
        domain = np.atleast_2d(np.asarray(idomain))
        if not np.isin(domain, IDOMAIN_VALUES).all():
            raise ValueError("idomain holds only -1, 0 and 1.")
        idomain_arr = write_array(
            store_obj,
            mesh,
            "idomain",
            domain.astype("int8"),
            dimension_names=field_registry.static_field_dimensions(2),
        )
        update_attrs(
            idomain_arr, {**attrs_for_field("idomain", idomain_arr.dtype), **_IDOMAIN_FLAGS}
        )
    for name, values in (
        ("streambed_top", streambed_top),
        ("streambed_connection", streambed_connection),
    ):
        if values is None:
            continue
        arr = write_array(
            store_obj,
            mesh,
            name,
            np.asarray(values, dtype="float64"),
            dimension_names=(field_registry.AXIS_FACE,),
        )
        update_attrs(arr, attrs_for_field(name, arr.dtype))
    if layer_thickness is not None:
        thickness_arr = write_array(
            store_obj,
            mesh,
            "layer_thickness",
            np.atleast_2d(np.asarray(layer_thickness, dtype="float64")),
            dimension_names=field_registry.static_field_dimensions(2),
        )
        update_attrs(thickness_arr, attrs_for_field("layer_thickness", thickness_arr.dtype))


def _check_layout(layout: MeshLayout, *, n_nodes: int, n_cells: int) -> None:
    """Refuse a layout that does not describe the mesh it is written beside."""
    if layout.face_x.shape[0] != n_cells:
        raise IncompatibleMeshError(
            f"the mesh layout describes {layout.face_x.shape[0]} cells, the connectivity {n_cells}"
        )
    edges = layout.edge_node_connectivity
    if edges.size and int(edges.max()) >= n_nodes:
        raise IncompatibleMeshError("an edge of the mesh layout names a node beyond the vertices")


def _family_attrs(names: tuple[str, ...], *, long_name: str) -> dict[str, object]:
    """Return the CF flag attributes of a family bit field."""
    return {
        "long_name": long_name,
        "flag_masks": [1 << k for k in range(len(names))],
        "flag_meanings": cf_flag_meanings(names),
        "family_names": list(names),
    }


def _write_layout(
    store_obj: SimulationZarr, mesh: zarr.Group, layout: MeshLayout
) -> dict[str, object]:
    """Write the additive arrays of a mesh layout and return the topology attrs they add."""
    face = (field_registry.AXIS_FACE,)
    edge_pair = (field_registry.AXIS_EDGE, field_registry.AXIS_TWO)
    for name, values in (("face_x", layout.face_x), ("face_y", layout.face_y)):
        write_array(
            store_obj,
            mesh,
            name,
            values,
            dimension_names=face,
            attrs={
                "standard_name": _STANDARD_NAMES[name[-1]],
                "long_name": f"{name[-1]} coordinate of the cell centre",
                "units": "m",
                "center_kind": layout.center_kind,
            },
        )
    write_array(
        store_obj,
        mesh,
        "face_family",
        layout.face_family,
        dimension_names=face,
        attrs=_family_attrs(layout.family_names, long_name="Line families each cell belongs to"),
    )
    if layout.face_zone is not None:
        write_array(
            store_obj,
            mesh,
            "face_zone",
            layout.face_zone,
            dimension_names=face,
            attrs={
                "long_name": "Zone of each cell, an index into zone_names",
                "zone_names": list(layout.zone_names),
                "_FillValue": -1,
            },
        )
    for name, values, role in (
        ("edge_node_connectivity", layout.edge_node_connectivity, "edge_node_connectivity"),
        ("edge_face_connectivity", layout.edge_face_connectivity, "edge_face_connectivity"),
    ):
        write_array(
            store_obj,
            mesh,
            name,
            values,
            dimension_names=edge_pair,
            attrs={
                "cf_role": role,
                "long_name": (
                    "Mapping from every edge to its two end nodes"
                    if role == "edge_node_connectivity"
                    else "Mapping from every edge to the cells on its two sides, -1 at the boundary"
                ),
                "start_index": 0,
                "_FillValue": -1,
            },
        )
    write_array(
        store_obj,
        mesh,
        "edge_family",
        layout.edge_family,
        dimension_names=(field_registry.AXIS_EDGE,),
        attrs=_family_attrs(
            layout.edge_family_names, long_name="Face families each mesh edge lies on"
        ),
    )
    return {
        "face_coordinates": "face_x face_y",
        "edge_node_connectivity": "edge_node_connectivity",
        "edge_face_connectivity": "edge_face_connectivity",
        "face_dimension": field_registry.AXIS_FACE,
        "edge_dimension": field_registry.AXIS_EDGE,
    }


def write_descent(
    store_obj: SimulationZarr,
    *,
    receiver: np.ndarray,
    surface: np.ndarray,
    base_level: np.ndarray,
    constant_head: np.ndarray,
    raised: np.ndarray,
    channel: np.ndarray,
    pinned: np.ndarray,
    attrs: Mapping[str, object],
    dam_foot: np.ndarray | None = None,
    basin: np.ndarray | None = None,
    basin_attrs: Mapping[str, object] | None = None,
    catchment_fraction: np.ndarray | None = None,
) -> None:
    """Write the descent D next to the mesh it routes on, under ``mesh/``.

    Seven static per-face arrays, none rounded: the receiver of each cell (-1
    at an outlet), D's filled surface, and the base-level, constant-head,
    raised, channel and pinned masks. ``attrs`` (adjacency kind, epsilon, report
    counts) is stamped on the receiver array. ``descent_dam_foot`` is an eighth
    array, int64, the ids of the cells below the dams (empty when the run has no
    lake); it is a list of cells, not a per-face field. ``basin`` is a ninth
    array, ``descent_basin`` (bool per face): the basin of D at the catchment
    outlet. ``basin_attrs`` is stamped on it and must name ``descent_outlet``,
    a cell of the basin. ``catchment_fraction`` is a tenth array,
    ``catchment_fraction`` (float64 per face, in [0, 1]): the share of each
    cell's area inside the delineated catchment polygon, the weight of a
    catchment total of a spatial quantity. It comes with a basin only.
    Additive: a store without these arrays is still valid.
    """
    arrays = {
        "descent_receiver": (np.asarray(receiver, dtype="int64"), "Receiver cell of the descent"),
        "descent_surface": (np.asarray(surface, dtype="float64"), "Filled surface of the descent"),
        "descent_base_level": (np.asarray(base_level, dtype=bool), "Seeds of the descent"),
        "descent_constant_head": (
            np.asarray(constant_head, dtype=bool),
            "Constant-head cells, where water leaves the model",
        ),
        "descent_raised": (np.asarray(raised, dtype=bool), "Cells the descent raised"),
        "descent_channel": (np.asarray(channel, dtype=bool), "Cells of the channel tree"),
        "descent_pinned": (np.asarray(pinned, dtype=bool), "Cells draining to their pin"),
    }
    sizes = {values.size for values, _ in arrays.values()}
    if len(sizes) != 1 or any(values.ndim != 1 for values, _ in arrays.values()):
        raise ValueError(f"the descent arrays must be 1-D and share one size, got {sorted(sizes)}.")
    basin_values = _checked_basin(basin, basin_attrs, n_cells=next(iter(sizes)))
    fraction_values = _checked_fraction(
        catchment_fraction, has_basin=basin_values is not None, n_cells=next(iter(sizes))
    )
    with store_obj._guard_write():
        mesh = store_obj._root.require_group("mesh")
        for name, (values, long_name) in arrays.items():
            write_array(
                store_obj,
                mesh,
                name,
                values,
                dimension_names=(field_registry.AXIS_FACE,),
                attrs={
                    "long_name": long_name,
                    **(dict(attrs) if name == "descent_receiver" else {}),
                },
            )
        feet = np.unique(np.asarray([] if dam_foot is None else dam_foot, dtype="int64"))
        if feet.size and (feet[0] < 0 or feet[-1] >= np.asarray(receiver).size):
            raise ValueError("a dam foot of the descent is not a cell of the mesh.")
        write_array(
            store_obj,
            mesh,
            "descent_dam_foot",
            feet,
            dimension_names=(field_registry.AXIS_RECORD,),
            attrs={"long_name": "Cells below the dams, where the stream under a lake starts"},
        )
        if basin_values is not None:
            write_array(
                store_obj,
                mesh,
                "descent_basin",
                basin_values,
                dimension_names=(field_registry.AXIS_FACE,),
                attrs={
                    "long_name": "Basin of the descent at the catchment outlet",
                    **dict(basin_attrs or {}),
                },
            )
        if fraction_values is not None:
            write_array(
                store_obj,
                mesh,
                "catchment_fraction",
                fraction_values,
                dimension_names=(field_registry.AXIS_FACE,),
                attrs={
                    "long_name": "Share of the cell area inside the delineated catchment polygon",
                    "units": "1",
                },
            )


def write_criterion_cells(
    store_obj: SimulationZarr,
    *,
    open_water: np.ndarray,
    catchment_cells: np.ndarray | None = None,
) -> None:
    """Write the two per-face masks the stream criterion read, under ``mesh/``.

    ``open_water`` holds the cells whose water extent the model was told (a
    lake), all false when the run has none. ``catchment_cells`` holds the cells
    whose center the catchment outline covers, and is left out when the run has no
    outline. A figure redrawn from the store reads both back, so it scores the
    cells the trials scored. Both must hold one value per cell of the stored mesh.
    """
    masks = {"open_water": open_water, "catchment_cells": catchment_cells}
    values = {
        name: np.asarray(mask, dtype=bool) for name, mask in masks.items() if mask is not None
    }
    stored = store_obj._root.get("mesh")
    n_cells = None
    if stored is not None and "face_node_connectivity" in stored:
        n_cells = int(stored["face_node_connectivity"].shape[0])
    for name, mask in values.items():
        if mask.ndim != 1 or (n_cells is not None and mask.size != n_cells):
            raise ValueError(f"{name} must hold one value per cell ({n_cells}), got {mask.shape}.")
    long_names = {
        "open_water": "Cells whose surface-water extent is an input of the model",
        "catchment_cells": "Cells whose center the catchment outline covers",
    }
    with store_obj._guard_write():
        mesh = store_obj._root.require_group("mesh")
        for name, mask in values.items():
            write_array(
                store_obj,
                mesh,
                name,
                mask,
                dimension_names=(field_registry.AXIS_FACE,),
                attrs={"long_name": long_names[name]},
            )


def _checked_basin(
    basin: np.ndarray | None, basin_attrs: Mapping[str, object] | None, *, n_cells: int
) -> np.ndarray | None:
    """Return the basin mask as a bool array, or refuse one that does not fit D."""
    if basin is None:
        if basin_attrs:
            raise ValueError("basin_attrs were given without a basin.")
        return None
    values = np.asarray(basin, dtype=bool)
    if values.ndim != 1 or values.size != n_cells:
        raise ValueError(f"the basin must hold one value per cell ({n_cells}), got {values.shape}.")
    if not basin_attrs or "descent_outlet" not in basin_attrs:
        raise ValueError("a basin is stored with its descent_outlet attribute.")
    outlet = int(basin_attrs["descent_outlet"])
    if not 0 <= outlet < n_cells or not values[outlet]:
        raise ValueError(f"the outlet cell {outlet} is not a cell of the basin.")
    return values


def _checked_fraction(
    fraction: np.ndarray | None, *, has_basin: bool, n_cells: int
) -> np.ndarray | None:
    """Return the catchment fraction as float64, or refuse one that does not fit the basin."""
    if fraction is None:
        return None
    if not has_basin:
        raise ValueError("a catchment fraction is stored with the basin it weighs.")
    values = np.asarray(fraction, dtype="float64")
    if values.ndim != 1 or values.size != n_cells:
        raise ValueError(
            f"the catchment fraction must hold one value per cell ({n_cells}), got {values.shape}."
        )
    if not np.all((values >= 0.0) & (values <= 1.0)):
        raise ValueError("the catchment fraction must lie in [0, 1] on every cell.")
    return values


def write_topography(
    store_obj: SimulationZarr,
    topography: np.ndarray,
    *,
    z_interfaces: np.ndarray | None = None,
    n_cells: int | None = None,
    n_layers: int | None = None,
    layer_thickness: np.ndarray | None = None,
    idomain: np.ndarray | None = None,
    vertical_layout: str | None = None,
    streambed_top: np.ndarray | None = None,
    streambed_connection: np.ndarray | None = None,
    grid_type: str | None = None,
) -> None:
    """Write what the solved model adds to the mesh: topography and vertical geometry.

    This is the one writer after a run. It never touches the vertices or the
    connectivity. When ``mesh/face_node_connectivity`` is stored, ``n_cells`` is
    compared to it and a different count raises ``IncompatibleMeshError``; a store
    with no stored geometry takes ``n_cells`` as given.

    ``z_interfaces`` is the ``(n_layers + 1, n_faces)`` column of every cell,
    ``idomain`` the ``(n_layers, n_faces)`` activity of the solved model (1
    active, 0 inactive, -1 vertical pass-through, stored as int8), and
    ``vertical_layout`` names how the layers were built, as a ``mesh/``
    attribute. A reader needs nothing else to rebuild the stack.
    """
    with store_obj._guard_write():
        mesh = store_obj._root.require_group("mesh")
        if n_cells is not None and "face_node_connectivity" in mesh:
            stored = int(mesh["face_node_connectivity"].shape[0])
            if stored != int(n_cells):
                raise IncompatibleMeshError(
                    f"the solver grid has {int(n_cells)} cells, the stored mesh {stored}"
                )
        topo_arr = write_array(
            store_obj,
            mesh,
            "topography",
            np.asarray(topography, dtype="float64"),
            dimension_names=(field_registry.AXIS_FACE,),
        )
        update_attrs(topo_arr, attrs_for_field("topography", topo_arr.dtype))
        if z_interfaces is not None:
            stored_cells = (
                int(mesh["face_node_connectivity"].shape[0])
                if "face_node_connectivity" in mesh
                else n_cells
            )
            write_array(
                store_obj,
                mesh,
                "z_interfaces",
                _interfaces(z_interfaces, stored_cells),
                dimension_names=(field_registry.AXIS_LAYER_INTERFACE, field_registry.AXIS_FACE),
                attrs=_Z_INTERFACE_ATTRS,
            )
        _write_vertical_arrays(
            store_obj,
            mesh,
            layer_thickness=layer_thickness,
            streambed_top=streambed_top,
            streambed_connection=streambed_connection,
            idomain=idomain,
        )
        mesh_attrs: dict[str, object] = {}
        if n_cells is not None:
            mesh_attrs["n_cells"] = int(n_cells)
        if n_layers is not None:
            mesh_attrs["n_layers"] = int(n_layers)
        if grid_type:
            mesh_attrs["grid_type"] = str(grid_type)
        if vertical_layout:
            mesh_attrs["vertical_layout"] = str(vertical_layout)
        if mesh_attrs:
            update_attrs(mesh, mesh_attrs)


def write_time(
    store_obj: SimulationZarr,
    values: np.ndarray,
    *,
    epoch: str = "1970-01-01T00:00:00",
    calendar: str = "proleptic_gregorian",
    units: str = "seconds since 1970-01-01T00:00:00",
) -> None:
    """Persist the CF time coordinate.

    Only the 1970-01-01 CF epoch is accepted: ``read_time`` decodes any unit
    scale (seconds/minutes/hours/days since 1970) but cannot honor another epoch,
    so a non-1970 anchor is rejected here rather than producing a store that
    write-validates then fails every read.
    """
    if "1970-01-01" not in epoch or "since 1970-01-01" not in units:
        raise ValueError(
            "write_time only supports the 1970-01-01 CF epoch "
            f"(read_time cannot decode another epoch): got epoch={epoch!r}, units={units!r}."
        )
    with store_obj._guard_write():
        write_array(
            store_obj,
            store_obj._root,
            "time",
            np.asarray(values, dtype="int64"),
            dimension_names=(field_registry.AXIS_TIME,),
            attrs={
                "units": units,
                "calendar": calendar,
                "standard_name": "time",
                "long_name": "Simulation time",
                "axis": "T",
            },
        )
        store_obj._root = update_attrs(store_obj._root, {"time_epoch": epoch})


def write_crs(
    store_obj: SimulationZarr,
    *,
    crs_wkt: str,
    grid_mapping_name: str = "latitude_longitude",
    epsg_code: int | None = None,
    semi_major_axis: float | None = None,
    inverse_flattening: float | None = None,
) -> None:
    """Persist the CF grid-mapping CRS variable."""
    with store_obj._guard_write():
        attrs: dict[str, object] = {"grid_mapping_name": grid_mapping_name}
        if crs_wkt:
            attrs["crs_wkt"] = crs_wkt
        if epsg_code is not None:
            attrs["epsg_code"] = int(epsg_code)
        if semi_major_axis is not None:
            attrs["semi_major_axis"] = float(semi_major_axis)
        if inverse_flattening is not None:
            attrs["inverse_flattening"] = float(inverse_flattening)
        write_array(
            store_obj,
            store_obj._root,
            "crs",
            np.zeros((), dtype="int32"),
            dimension_names=(),
            attrs=attrs,
        )
        _write_mesh_crs(store_obj)


def write_geographic_raster(
    store_obj: SimulationZarr,
    name: str,
    data: np.ndarray,
    *,
    transform: tuple[float, ...],
    crs: str,
    nodata: float = -99999.0,
) -> None:
    """Persist a per-run raster under ``geographic/<name>``, readable as CF.

    The nodata is the Zarr ``fill_value``, which GDAL reads, and the CF
    ``missing_value``, which xarray masks. A ``_FillValue`` attribute would
    have to be base64 text for xarray on a Zarr 3 float array, and CF types it
    as a number. A north-up raster gets its own axes
    ``<name>_y`` and ``<name>_x``, holding the pixel centers of the transform,
    because two rasters of the group need not share a grid. A raster with a
    CRS names its own grid-mapping variable ``<name>_crs``. The ``transform``,
    ``crs``, ``nodata`` and ``shape`` attributes stay, so the HydroModPy reader
    reads a run written before the same way.
    """
    values = np.asarray(data)
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "geographic")
        geo = store_obj._root.require_group("geographic")
        dimensions = field_registry.per_array_dimensions(name, int(values.ndim))
        attrs: dict[str, object] = {
            "transform": list(transform),
            "crs": str(crs),
            "nodata": float(nodata),
            "shape": list(values.shape),
        }
        fill_value = _fill_value(values.dtype, nodata)
        if fill_value is not None:
            attrs["missing_value"] = fill_value
        north_up = len(transform) >= 6 and transform[1] == 0.0 and transform[3] == 0.0
        grid_mapping = _grid_mapping_attrs(str(crs))
        if values.ndim >= 2 and north_up:
            dimensions = (*dimensions[:-2], f"{name}_y", f"{name}_x")
            geographic = grid_mapping.get("grid_mapping_name") == "latitude_longitude"
            _write_pixel_centres(store_obj, geo, name, values.shape[-2:], transform, geographic)
        if grid_mapping:
            write_array(
                store_obj,
                geo,
                f"{name}_crs",
                np.zeros((), dtype="int32"),
                dimension_names=(),
                attrs=grid_mapping,
            )
            attrs["grid_mapping"] = f"{name}_crs"
        write_array(
            store_obj,
            geo,
            name,
            values,
            dimension_names=dimensions,
            attrs=attrs,
            compressors=BLOSC_ZSTD,
            fill_value=fill_value,
        )


def _fill_value(dtype: np.dtype, nodata: float) -> float | int | None:
    """Return ``nodata`` as a fill value of ``dtype``, or None when the type cannot hold it."""
    if dtype.kind == "f":
        return float(nodata)
    if dtype.kind in "iu" and float(nodata).is_integer():
        limits = np.iinfo(dtype)
        if limits.min <= nodata <= limits.max:
            return int(nodata)
    return None


def _write_pixel_centres(
    store_obj: SimulationZarr,
    geo: zarr.Group,
    name: str,
    shape: tuple[int, ...],
    transform: tuple[float, ...],
    geographic: bool,
) -> None:
    """Write the ``<name>_y`` and ``<name>_x`` axes at the pixel centers of a north-up raster.

    A geographic CRS gives longitudes and latitudes in degrees, a projected
    one coordinates in meters.
    """
    rows, columns = int(shape[0]), int(shape[1])
    pixel_x, origin_x, pixel_y, origin_y = (float(transform[i]) for i in (0, 2, 4, 5))
    for axis, centres in (
        ("y", origin_y + (np.arange(rows) + 0.5) * pixel_y),
        ("x", origin_x + (np.arange(columns) + 0.5) * pixel_x),
    ):
        write_array(
            store_obj,
            geo,
            f"{name}_{axis}",
            centres,
            dimension_names=(f"{name}_{axis}",),
            attrs={
                **(_DEGREE_AXES[axis] if geographic else _METRE_AXES[axis]),
                "long_name": f"{axis} coordinate of the pixel centre of {name}",
                "axis": axis.upper(),
            },
        )


def _grid_mapping_attrs(crs: str) -> dict[str, object]:
    """Return the CF grid-mapping attributes of ``crs``, empty when it names no CRS."""
    if not crs:
        return {}
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    try:
        return dict(CRS.from_user_input(crs).to_cf())
    except CRSError:
        return {}


__all__ = [
    "attrs_for_field",
    "ensure_child_dir",
    "write_array",
    "write_criterion_cells",
    "write_crs",
    "write_descent",
    "write_geographic_raster",
    "write_mesh",
    "write_time",
    "write_topography",
]
