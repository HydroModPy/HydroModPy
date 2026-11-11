"""Write-side concerns for :class:`SimulationZarr`.

Every ``write_*`` of :class:`SimulationZarr` is defined here once and bound
on the class as a method: mesh, time, CRS, fields, forcing, geographic
rasters and ACDD root attrs. Each takes the live store as its first argument.
The module also owns the chunk and shard decisions and the CF attributes
that flow from the registry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

import numpy as np
import zarr

from hydromodpy.core.budget.terms import (
    BUDGET_KEPT_TERMS_ATTR,
    BUDGET_POLICY_ATTR,
    POLICY_ALL,
    BudgetKeep,
)
from hydromodpy.core.exceptions import IncompatibleMeshError
from hydromodpy.core.fields.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.core.fields.precision import (
    KEPT_MANTISSA_BITS,
    QUANTIZATION_ALGORITHM,
    to_storage_precision,
)
from hydromodpy.core.fields.vertical_column import IDOMAIN_VALUES
from hydromodpy.core.io.value_digest import value_digest
from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.zarr_store.acdd import compose_acdd_root_attrs
from hydromodpy.results.zarr_store.chunks import (
    compute_balanced_chunks_1d,
    compute_balanced_chunks_2d,
    compute_shard_shape_1d,
    compute_shard_shape_2d,
    should_use_sharding,
)
from hydromodpy.results.zarr_store.constants import BLOSC_ZSTD
from hydromodpy.results.zarr_store.mesh_layout import MeshLayout, cf_flag_meanings
from hydromodpy.results.zarr_store.zarr_schema import (
    child_zarr_path,
    ensure_local_zarr_node_dir,
    update_attrs,
)

if TYPE_CHECKING:
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

logger = get_logger(__name__)


def field_name_from_target(target: zarr.Group, variable: str) -> str:
    """Return the canonical registry field name for ``(group, variable)``."""
    path = target.path or ""
    candidate = f"{path}/{variable}" if path else variable
    for name, desc in field_registry.FIELD_REGISTRY.items():
        if desc.zarr_path == candidate or desc.public_name == variable:
            return name
    return ""


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


def mask_sentinels(values: np.ndarray) -> np.ndarray:
    """Replace MODFLOW dry/no-flow head sentinels with NaN in a float array.

    HDRY/HNOFLO (~ +-1e30) and -6e30 are orders of magnitude above any physical
    head; masking them here, at the field write, means every transient field
    reaches Zarr already NaN-clean and CF ``_FillValue`` == NaN holds on read.
    A non-float array is returned untouched (NaN is invalid for integers).
    """
    if not np.issubdtype(values.dtype, np.floating):
        return values
    # Two comparisons instead of np.abs(): the slab can reach hundreds of MiB
    # and a materialized absolute copy would double the write-side peak.
    sentinel = (values > SENTINEL_ABS_THRESHOLD) | (values < -SENTINEL_ABS_THRESHOLD)
    if not sentinel.any():
        return values
    cleaned = values.copy()
    cleaned[sentinel] = np.nan
    return cleaned


def ensure_child_dir(store_obj: SimulationZarr, target: zarr.Group, name: str) -> None:
    """Pre-create a directory node under ``target`` for the live store."""
    ensure_local_zarr_node_dir(store_obj._path, child_zarr_path(target, name))


def maybe_shards(
    ndim: int,
    n_timesteps: int,
    chunk_shape: tuple[int, ...],
    itemsize: int,
    *,
    n_layers: int,
    n_cells: int,
) -> tuple[int, ...] | None:
    """Pick a shard shape when the total array size crosses the 100 MiB trigger."""
    layer_bytes_per_step = n_layers * n_cells * max(itemsize, 1)
    if not should_use_sharding(n_timesteps, layer_bytes_per_step):
        return None
    if ndim == 1:
        shard = compute_shard_shape_1d(
            n_timesteps,
            (chunk_shape[0], chunk_shape[1]),
            itemsize=itemsize,
        )
        return tuple(shard) if shard is not None else None
    if ndim == 2:
        shard = compute_shard_shape_2d(
            n_timesteps,
            (chunk_shape[0], chunk_shape[1], chunk_shape[2]),
            itemsize=itemsize,
        )
        return tuple(shard) if shard is not None else None
    return None


def _fill_value_for_dtype(dtype: np.dtype) -> object | None:
    """Return the CF _FillValue used for a float/int array dtype."""
    if np.issubdtype(dtype, np.floating):
        return float(np.nan)
    if np.issubdtype(dtype, np.integer):
        return int(np.iinfo(dtype).min)
    return None


def attach_field_attrs(target: zarr.Group, variable: str) -> None:
    """Stamp the registry-derived CF attrs onto an existing field array."""
    name = field_name_from_target(target, variable)
    if not name:
        # Spatial budget components (drn, rcha, wel, sto-ss, ...) are not in the
        # field registry because their names are dynamic, but they are all
        # volumetric fluxes in m3/s (the extractor scales them to SI seconds).
        if (target.path or "").rsplit("/", 1)[-1] == "budget":
            arr = target[variable]
            attrs: dict[str, object] = {
                "units": "m3 s-1",
                "long_name": f"{variable} volumetric flux",
            }
            fill = _fill_value_for_dtype(np.dtype(arr.dtype))
            # Same rule as attrs_for_field: a NaN sentinel stays out of JSON.
            if fill is not None and not isinstance(fill, float):
                attrs["_FillValue"] = fill
                attrs["missing_value"] = fill
            update_attrs(arr, attrs)
        return
    arr = target[variable]
    update_attrs(arr, attrs_for_field(name, np.dtype(arr.dtype)))


def _write_array(
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


# -- Mesh ---------------------------------------------------------------------


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
        _write_array(
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
        _write_array(
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
        _write_array(
            store_obj,
            mesh,
            "z_interfaces",
            interfaces,
            dimension_names=(field_registry.AXIS_LAYER_INTERFACE, field_registry.AXIS_FACE),
            attrs=_Z_INTERFACE_ATTRS,
        )
        if layer_indices is not None:
            _write_array(
                store_obj,
                mesh,
                "layer_indices",
                np.asarray(layer_indices, dtype="int32"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
        if source_cell_indices is not None:
            _write_array(
                store_obj,
                mesh,
                "source_cell_indices",
                np.asarray(source_cell_indices, dtype="int32"),
                dimension_names=(field_registry.AXIS_FACE,),
            )
        if topography is not None:
            topo_arr = _write_array(
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
        _write_array(
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
        _write_array(
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
    _write_array(
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
        idomain_arr = _write_array(
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
        arr = _write_array(
            store_obj,
            mesh,
            name,
            np.asarray(values, dtype="float64"),
            dimension_names=(field_registry.AXIS_FACE,),
        )
        update_attrs(arr, attrs_for_field(name, arr.dtype))
    if layer_thickness is not None:
        thickness_arr = _write_array(
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
        _write_array(
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
    _write_array(
        store_obj,
        mesh,
        "face_family",
        layout.face_family,
        dimension_names=face,
        attrs=_family_attrs(layout.family_names, long_name="Line families each cell belongs to"),
    )
    if layout.face_zone is not None:
        _write_array(
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
        _write_array(
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
    _write_array(
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
            _write_array(
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
        _write_array(
            store_obj,
            mesh,
            "descent_dam_foot",
            feet,
            dimension_names=(field_registry.AXIS_RECORD,),
            attrs={"long_name": "Cells below the dams, where the stream under a lake starts"},
        )
        if basin_values is not None:
            _write_array(
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
            _write_array(
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
            _write_array(
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
        topo_arr = _write_array(
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
            _write_array(
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


# -- Time / CRS --------------------------------------------------------------


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
        _write_array(
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
        _write_array(
            store_obj,
            store_obj._root,
            "crs",
            np.zeros((), dtype="int32"),
            dimension_names=(),
            attrs=attrs,
        )
        _write_mesh_crs(store_obj)


# -- Fields ------------------------------------------------------------------

QUANTIZATION_VARIABLE = "quantization_info"
"""Root container variable that describes the rounding of compact fields (CF-1.11 8.4)."""


def _stamp_quantization(store_obj: SimulationZarr, array: zarr.Array) -> None:
    """Say on ``array`` that it holds rounded values, and how they were rounded.

    CF-1.11 section 8.4 names the attributes: ``quantization`` points at a
    container variable carrying the algorithm, and ``quantization_nsb`` gives
    the mantissa bits kept. A reader can then tell a compact field from an
    exact one without comparing it to anything.
    """
    root = store_obj._root
    if QUANTIZATION_VARIABLE not in root:
        _write_array(
            store_obj,
            root,
            QUANTIZATION_VARIABLE,
            np.zeros((), dtype="int32"),
            dimension_names=(),
            attrs={
                "algorithm": QUANTIZATION_ALGORITHM,
                "implementation": (
                    "hydromodpy.core.field_precision.round_mantissa: round to nearest, "
                    "ties to even, from float64, then an exact cast to float32"
                ),
            },
        )
    update_attrs(
        array,
        {"quantization": QUANTIZATION_VARIABLE, "quantization_nsb": KEPT_MANTISSA_BITS},
    )


def _field_dimensions(
    variable: str, ndim: int, fallback: Callable[[int], tuple[str, ...]]
) -> tuple[str, ...]:
    """Return the axis names of ``variable``, the registry ones when they fit its rank."""
    if field_registry.has(variable):
        dimensions = field_registry.get(variable).dimensions
        if len(dimensions) == ndim:
            return dimensions
    return fallback(ndim)


def _field_path(variable: str, subgroup: str | None) -> str:
    """Return the path of the array inside the store, the key of its value digests."""
    return variable if not subgroup else f"{subgroup.strip('/')}/{variable}"


def _digest_registry(store_obj: SimulationZarr) -> dict[str, dict[str, str]]:
    """Return the registry of value digests of a handle, attached on first use.

    A run hands the registry of its facts to the handle, so the digests
    survive the close and a resume. A handle opened alone keeps its own.
    """
    registry = getattr(store_obj, "field_digests", None)
    if registry is None:
        registry = {}
        store_obj.field_digests = registry
    return registry


def _record_step_digests(
    store_obj: SimulationZarr, path: str, first_step: int, values: np.ndarray, *, stack: bool
) -> None:
    """Keep the digest of the float64 values received, one per step, before any rounding.

    The registry lives in the facts of the run, so it survives a resume that
    does not read the extraction again. A step never written is folded from
    the store at the seal.
    """
    digests = _digest_registry(store_obj).setdefault(path, {})
    if stack:
        for index in range(int(values.shape[0])):
            digests[str(first_step + index)] = value_digest(values[index])
    else:
        digests[str(first_step)] = value_digest(values)


def _to_stored_field(
    store_obj: SimulationZarr,
    values: np.ndarray,
    *,
    path: str,
    first_step: int = 0,
    stack: bool = False,
) -> tuple[np.ndarray, bool]:
    """Mask sentinels, digest the float64 values a rounded field rounds, then cast.

    The digest is taken here because this is the one place the masked values
    exist before ``to_storage_precision``: a rounded array hashes what the run
    computed, not the rounded bytes a replay cannot reproduce on another
    processor.
    """
    cleaned = mask_sentinels(np.asarray(values))
    stored = to_storage_precision(cleaned, store_obj.field_precision)
    quantized = stored is not cleaned
    if quantized:
        _record_step_digests(store_obj, path, first_step, cleaned, stack=stack)
    return stored, quantized


def _field_target(store_obj: SimulationZarr, subgroup: str | None) -> zarr.Group:
    """Return the group holding field arrays, creating ``subgroup`` if needed."""
    if not subgroup:
        return store_obj._root
    if subgroup not in store_obj._root:
        ensure_child_dir(store_obj, store_obj._root, subgroup)
        store_obj._root.create_group(subgroup)
    return store_obj._root[subgroup]


def _create_field_array(
    store_obj: SimulationZarr,
    target: zarr.Group,
    variable: str,
    *,
    n_timesteps: int,
    per_step_shape: tuple[int, ...],
    dtype: np.dtype,
    quantized: bool = False,
) -> None:
    """Create the (time, ...) array for ``variable`` with balanced chunks/shards."""
    itemsize = int(np.dtype(dtype).itemsize)
    if len(per_step_shape) == 1:
        n_layers, n_cells = 1, int(per_step_shape[0])
        full_shape: tuple[int, ...] = (int(n_timesteps), n_cells)
        chunk_shape: tuple[int, ...] = compute_balanced_chunks_1d(
            int(n_timesteps), n_cells, itemsize
        )
    elif len(per_step_shape) == 2:
        n_layers, n_cells = int(per_step_shape[0]), int(per_step_shape[1])
        full_shape = (int(n_timesteps), n_layers, n_cells)
        chunk_shape = compute_balanced_chunks_2d(int(n_timesteps), n_layers, n_cells, itemsize)
    else:
        raise ValueError(f"Expected 1D or 2D per-step values, got shape {per_step_shape}")

    ensure_child_dir(store_obj, target, variable)
    shards = maybe_shards(
        len(per_step_shape),
        int(n_timesteps),
        chunk_shape,
        itemsize,
        n_layers=n_layers,
        n_cells=n_cells,
    )
    create_kwargs: dict[str, Any] = dict(
        shape=full_shape,
        chunks=chunk_shape,
        dtype=dtype,
        dimension_names=_field_dimensions(
            variable, len(full_shape), field_registry.timed_field_dimensions
        ),
        compressors=BLOSC_ZSTD,
        # Derive the fill from the dtype so the array fill and the CF _FillValue
        # attr agree: NaN for floats, iinfo(dtype).min for ints (NaN is invalid
        # for an integer array).
        fill_value=_fill_value_for_dtype(dtype),
        overwrite=True,
    )
    if shards is not None:
        try:
            target.create_array(variable, shards=shards, **create_kwargs)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "ShardingCodec unavailable for %s (shape=%s, "
                "shard=%s): %s. Falling back to plain chunks.",
                variable,
                full_shape,
                shards,
                exc,
            )
            target.create_array(variable, **create_kwargs)
    else:
        target.create_array(variable, **create_kwargs)
    attach_field_attrs(target, variable)
    if quantized:
        _stamp_quantization(store_obj, target[variable])


def write_field(
    store_obj: SimulationZarr,
    variable: str,
    timestep: int,
    values: np.ndarray,
    *,
    n_timesteps: int | None = None,
    subgroup: str | None = None,
) -> None:
    """Append one timestep slice to ``variable`` under ``subgroup`` or root.

    The values are written in the handle's ``field_precision``.
    """
    if np.ndim(values) not in (1, 2):
        raise ValueError(f"Expected 1D or 2D values, got shape {np.shape(values)}")
    with store_obj._guard_write():
        target = _field_target(store_obj, subgroup)
        values, quantized = _to_stored_field(
            store_obj,
            values,
            path=_field_path(variable, subgroup),
            first_step=int(timestep),
        )
        if variable not in target:
            if n_timesteps is None:
                raise ValueError(f"n_timesteps required on first write of '{variable}'")
            _create_field_array(
                store_obj,
                target,
                variable,
                n_timesteps=int(n_timesteps),
                per_step_shape=tuple(int(s) for s in values.shape),
                dtype=values.dtype,
                quantized=quantized,
            )

        arr = target[variable]
        if values.ndim == 1:
            arr[int(timestep), :] = values
        else:
            arr[int(timestep), :, :] = values


def write_static_field(
    store_obj: SimulationZarr,
    variable: str,
    values: np.ndarray,
    *,
    subgroup: str | None = None,
) -> None:
    """Write a field that has no time axis, such as a model input parameter.

    ``write_field`` and ``write_field_stack`` both open the array with a
    leading time dimension. A conductivity field has one value per cell for
    the whole run, so storing it with a time axis would repeat it at every
    step and make every reader slice a dimension that carries no information.
    """
    with store_obj._guard_write():
        target = _field_target(store_obj, subgroup)
        data = mask_sentinels(np.asarray(values))
        arr = _write_array(
            store_obj,
            target,
            variable,
            data,
            dimension_names=_field_dimensions(
                variable, data.ndim, field_registry.static_field_dimensions
            ),
        )
        update_attrs(arr, attrs_for_field(variable, arr.dtype))


def write_field_stack(
    store_obj: SimulationZarr,
    variable: str,
    values: np.ndarray,
    *,
    n_timesteps: int | None = None,
    timestep_offset: int = 0,
    subgroup: str | None = None,
) -> None:
    """Write a ``(time, ...)`` stack of ``variable`` in one batched call.

    Batched writes encode each chunk/shard once. Per-timestep writes into a
    sharded array trigger one read-modify-write of a whole multi-MB shard per
    timestep, which dominated long transient extractions. Use
    ``timestep_offset`` with a total ``n_timesteps`` to stream large arrays in
    time slabs without holding the full stack in memory. The values are
    written in the handle's ``field_precision``.
    """
    if np.ndim(values) not in (2, 3):
        raise ValueError(f"Expected a (time, ...) stack, got shape {np.shape(values)}")
    offset = int(timestep_offset)
    total = int(n_timesteps) if n_timesteps is not None else offset + int(values.shape[0])
    if offset + int(values.shape[0]) > total:
        raise ValueError(
            f"Stack slab [{offset}:{offset + int(values.shape[0])}] exceeds "
            f"n_timesteps={total} for '{variable}'."
        )
    with store_obj._guard_write():
        target = _field_target(store_obj, subgroup)
        values, quantized = _to_stored_field(
            store_obj,
            values,
            path=_field_path(variable, subgroup),
            first_step=offset,
            stack=True,
        )

        per_step_shape = tuple(int(s) for s in values.shape[1:])
        full_shape = (total, *per_step_shape)
        existing = target.get(variable)
        if existing is None or tuple(int(s) for s in existing.shape) != full_shape:
            if offset != 0:
                raise ValueError(f"First slab of '{variable}' must start at timestep_offset=0.")
            _create_field_array(
                store_obj,
                target,
                variable,
                n_timesteps=total,
                per_step_shape=per_step_shape,
                dtype=values.dtype,
                quantized=quantized,
            )

        arr = target[variable]
        arr[offset : offset + int(values.shape[0])] = values


def write_budget_policy(
    store_obj: SimulationZarr, keep: BudgetKeep, written: Iterable[str]
) -> None:
    """Record on ``budget/`` the policy an extractor applied and the terms it kept.

    Under ``"all"`` the kept terms are the names written under ``budget/``.
    Under ``"consumers"`` they are the terms of the plan, produced or not: a
    kept term with no array is one the model does not produce. The group is
    created when absent, so a store that wrote nothing still says so.
    """
    if keep.policy == POLICY_ALL:
        kept = sorted({str(name) for name in written})
    else:
        kept = sorted(keep.terms)
    with store_obj._guard_write():
        group = _field_target(store_obj, "budget")
        update_attrs(group, {BUDGET_POLICY_ATTR: keep.policy, BUDGET_KEPT_TERMS_ATTR: kept})


# -- Forcing -----------------------------------------------------------------


def write_forcing_timeseries(
    store_obj: SimulationZarr,
    variable: str,
    station_id: str,
    timestamps: np.ndarray,
    values: np.ndarray,
    *,
    unit: str = "",
    source: str = "",
) -> None:
    """Persist a per-station forcing timeseries under ``forcing/<var>/<station>``."""
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "forcing")
        forcing = store_obj._root.require_group("forcing")
        ensure_child_dir(store_obj, forcing, variable)
        var_grp = forcing.require_group(variable)
        ensure_child_dir(store_obj, var_grp, station_id)
        sta_grp = var_grp.require_group(station_id)

        ts_bytes = np.asarray(timestamps, dtype="datetime64[ns]").view("int64")
        _write_array(
            store_obj,
            sta_grp,
            "timestamps",
            ts_bytes,
            dimension_names=(field_registry.AXIS_RECORD,),
            attrs={
                "units": "nanoseconds since 1970-01-01T00:00:00",
                "calendar": "proleptic_gregorian",
                "standard_name": "time",
                "long_name": f"Timestamps for {variable}",
                "axis": "T",
            },
        )
        _write_array(
            store_obj,
            sta_grp,
            "values",
            np.asarray(values, dtype="float64"),
            dimension_names=(field_registry.AXIS_RECORD,),
            attrs={
                "units": str(unit),
                "long_name": f"Forcing values for {variable}",
                "source": str(source),
            },
        )
        update_attrs(
            sta_grp,
            {
                "unit": str(unit),
                "source": str(source),
                "n_records": int(len(values)),
            },
        )


def write_forcing_attrs(store_obj: SimulationZarr, attrs: Mapping[str, object]) -> None:
    """Stamp attributes on the ``forcing`` group."""
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "forcing")
        update_attrs(store_obj._root.require_group("forcing"), attrs)


def write_forcing_field(
    store_obj: SimulationZarr,
    variable: str,
    data: np.ndarray,
    *,
    unit: str = "",
    source: str = "",
) -> None:
    """Persist a gridded forcing field under ``forcing/<var>``."""
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "forcing")
        forcing = store_obj._root.require_group("forcing")
        _write_array(
            store_obj,
            forcing,
            variable,
            np.asarray(data),
            dimension_names=field_registry.per_array_dimensions(
                variable, int(np.asarray(data).ndim)
            ),
            attrs={"unit": str(unit), "source": str(source)},
            compressors=BLOSC_ZSTD,
        )


# -- Soil reservoir columns (per-run) ----------------------------------------

# Fixed per-column arrays of the soil reservoir group: name -> (dtype, units,
# long_name). Unlike ``series``, these carry no per-call metadata: the set of
# columns is closed (spec section 6.2), so a caller passing an unknown one
# fails on the dict lookup below.
_SOIL_COLUMN_ARRAYS: dict[str, tuple[str, str, str]] = {
    "cell_index": ("int32", "1", "Flat (y, x) index of the SAFRAN cell"),
    "class_index": ("int32", "1", "Soil capacity class inside the cell"),
    "x": ("float64", "m", "Cell centre x, CRS of the run"),
    "y": ("float64", "m", "Cell centre y, CRS of the run"),
    "ru_mm": ("float64", "mm", "Soil available water capacity of the column"),
    "cell_fraction": ("float64", "1", "Share of its cell the column covers"),
    "basin_weight": ("float64", "1", "Weight of the column in the basin mean"),
}


def write_soil_columns(
    store_obj: SimulationZarr,
    *,
    timestamps: np.ndarray,
    series: Mapping[str, tuple[np.ndarray, str, str, str]],
    columns: Mapping[str, np.ndarray],
    attrs: Mapping[str, object],
) -> None:
    """Persist the soil reservoir columns under ``forcing/soil``.

    ``series`` maps a daily flux or state name to ``(values, units,
    cell_methods, long_name)``, ``(record, soil_column)`` shaped. ``columns``
    maps the fixed per-column arrays of :data:`_SOIL_COLUMN_ARRAYS`,
    ``(soil_column,)`` shaped. ``attrs`` is stamped on the group as-is.
    """
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "forcing")
        forcing = store_obj._root.require_group("forcing")
        ensure_child_dir(store_obj, forcing, "soil")
        soil = forcing.require_group("soil")

        ts = np.asarray(timestamps, dtype="datetime64[ns]").view("int64")
        _write_array(
            store_obj,
            soil,
            "timestamps",
            ts,
            dimension_names=(field_registry.AXIS_RECORD,),
            attrs={
                "units": "nanoseconds since 1970-01-01T00:00:00",
                "calendar": "proleptic_gregorian",
                "standard_name": "time",
                "long_name": "Day of each soil record",
                "axis": "T",
            },
            compressors=BLOSC_ZSTD,
        )

        for name, (values, units, cell_methods, long_name) in series.items():
            _write_array(
                store_obj,
                soil,
                name,
                np.asarray(values, dtype="float64"),
                dimension_names=(field_registry.AXIS_RECORD, field_registry.AXIS_SOIL_COLUMN),
                attrs={
                    "units": str(units),
                    "cell_methods": str(cell_methods),
                    "long_name": str(long_name),
                },
                compressors=BLOSC_ZSTD,
            )

        for name, values in columns.items():
            dtype, units, long_name = _SOIL_COLUMN_ARRAYS[name]
            _write_array(
                store_obj,
                soil,
                name,
                np.asarray(values, dtype=dtype),
                dimension_names=(field_registry.AXIS_SOIL_COLUMN,),
                attrs={"units": units, "long_name": long_name},
                compressors=BLOSC_ZSTD,
            )

        update_attrs(soil, dict(attrs))


# -- Geographic rasters (per-run) -------------------------------------------


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
            _write_array(
                store_obj,
                geo,
                f"{name}_crs",
                np.zeros((), dtype="int32"),
                dimension_names=(),
                attrs=grid_mapping,
            )
            attrs["grid_mapping"] = f"{name}_crs"
        _write_array(
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
        _write_array(
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


# -- Lake abacus comparison (per-run) ---------------------------------------


def write_lake_abacus(
    store_obj: SimulationZarr,
    lake_id: str,
    *,
    stage: np.ndarray,
    real_volume: np.ndarray,
    real_sarea: np.ndarray,
    sim_volume: np.ndarray,
    sim_sarea: np.ndarray,
    stage_unit: str = "m",
    volume_unit: str = "m3",
    area_unit: str = "m2",
) -> None:
    """Persist the reference vs simulated abacus under ``lake_abacus/<lake_id>``.

    The four curves are sampled on the single ``stage`` abscissa, so reading
    ``real_volume[i]`` against ``stage[i]`` only means something when the five
    arrays have one length. Writing them unequal produced a group no reader
    could open, and said so nowhere; it is refused here instead.
    """
    curves = (
        ("stage", np.asarray(stage, dtype="float64"), stage_unit),
        ("real_volume", np.asarray(real_volume, dtype="float64"), volume_unit),
        ("real_sarea", np.asarray(real_sarea, dtype="float64"), area_unit),
        ("sim_volume", np.asarray(sim_volume, dtype="float64"), volume_unit),
        ("sim_sarea", np.asarray(sim_sarea, dtype="float64"), area_unit),
    )
    lengths = {name: int(values.shape[0]) for name, values, _ in curves}
    if len(set(lengths.values())) != 1:
        raise ValueError(
            f"Lake abacus curves of '{lake_id}' are sampled on one stage axis but "
            f"have different lengths: {lengths}"
        )
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "lake_abacus")
        grp = store_obj._root.require_group("lake_abacus")
        ensure_child_dir(store_obj, grp, lake_id)
        lake = grp.require_group(lake_id)
        for name, values, unit in curves:
            _write_array(
                store_obj,
                lake,
                name,
                values,
                dimension_names=(field_registry.AXIS_STAGE_LEVEL,),
                attrs={"units": str(unit)},
            )
        update_attrs(
            lake,
            {"stage_unit": stage_unit, "volume_unit": volume_unit, "area_unit": area_unit},
        )


def write_lake_restart_state(store_obj: SimulationZarr, stages: dict[str, float]) -> None:
    """Persist each lake's final stage under ``lake_state_final`` for hotstart.

    The companion of the heads field for ``[flow] restart_from``: a later run
    seeds each lake's initial stage from this last value. ``stages`` maps
    ``lake_id -> stage`` in meters; an empty mapping writes nothing.
    """
    if not stages:
        return
    lake_ids = [str(lake_id) for lake_id in stages]
    values = np.asarray([float(stages[lake_id]) for lake_id in lake_ids], dtype="float64")
    with store_obj._guard_write():
        ensure_child_dir(store_obj, store_obj._root, "lake_state_final")
        grp = store_obj._root.require_group("lake_state_final")
        _write_array(
            store_obj,
            grp,
            "stage",
            values,
            dimension_names=(field_registry.AXIS_LAKE,),
            attrs={"units": "m"},
        )
        update_attrs(grp, {"lake_ids": lake_ids})


# -- Axis coordinates --------------------------------------------------------


def _axis_extents(root: zarr.Group) -> dict[str, int]:
    """Return the length of the layer and face axes of a finished store."""
    extents: dict[str, int] = {}
    mesh = root.get("mesh")
    if isinstance(mesh, zarr.Group):
        for key, axis in (
            ("n_cells", field_registry.AXIS_FACE),
            ("n_layers", field_registry.AXIS_LAYER),
        ):
            value = mesh.attrs.get(key)
            if value is not None:
                extents[axis] = int(value)
    for _, array in _walk_arrays(root):
        names = array.metadata.dimension_names or ()
        for axis, length in zip(names, array.shape, strict=False):
            if axis in (field_registry.AXIS_LAYER, field_registry.AXIS_FACE):
                extents.setdefault(axis, int(length))
    return extents


def _walk_arrays(group: zarr.Group, prefix: str = "") -> list[tuple[str, zarr.Array]]:
    """Return every array of ``group``, keyed by its path inside the store."""
    found: list[tuple[str, zarr.Array]] = []
    for name, member in group.members():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(member, zarr.Array):
            found.append((path, member))
        elif isinstance(member, zarr.Group):
            found.extend(_walk_arrays(member, path))
    return found


def harmonize_axis_references(store_obj: SimulationZarr) -> None:
    """Materialize the axis coordinates the fields name, and drop dangling ones.

    Every field declares ``coordinates = "time layer face"`` and
    ``grid_mapping = "crs"``. Until this runs, ``layer`` and ``face`` are names
    of nothing, and ``crs`` is a name of nothing on a run with no declared CRS:
    a CF attribute pointing at an absent variable is a broken reference, not
    metadata. Writing the two index arrays gives the face and layer axes a
    coordinate a reader can join on; removing an unresolvable ``grid_mapping``
    leaves the store saying only what is true.

    The root ``n_cells`` and ``n_layers`` are refreshed from the same extents.
    They were stamped at registration, before the mesh existed, and a store
    whose root announces ``n_cells = 0`` over a 200-cell mesh describes nothing.
    """
    root = store_obj.root
    extents = _axis_extents(root)
    with store_obj._guard_write():
        sizes = {
            key: extents[axis]
            for key, axis in (
                ("n_cells", field_registry.AXIS_FACE),
                ("n_layers", field_registry.AXIS_LAYER),
            )
            if axis in extents
        }
        if sizes:
            store_obj._root = update_attrs(root, sizes)
            root = store_obj._root
        if field_registry.AXIS_FACE in extents:
            _write_array(
                store_obj,
                root,
                field_registry.AXIS_FACE,
                np.arange(extents[field_registry.AXIS_FACE], dtype="int32"),
                dimension_names=(field_registry.AXIS_FACE,),
                attrs={
                    "long_name": "Index of a cell along the face axis of the fields",
                    "units": "1",
                    "comment": (
                        "Position along the face axis of every field array, and row of "
                        "mesh/face_node_connectivity."
                    ),
                },
            )
        if field_registry.AXIS_LAYER in extents:
            _write_array(
                store_obj,
                root,
                field_registry.AXIS_LAYER,
                np.arange(extents[field_registry.AXIS_LAYER], dtype="int32"),
                dimension_names=(field_registry.AXIS_LAYER,),
                attrs={
                    "long_name": "Model layer index, 0 at the top of the aquifer",
                    "units": "1",
                    "positive": "down",
                },
            )
        present = {path for path, _ in _walk_arrays(root)}
        for path, array in _walk_arrays(root):
            attrs = dict(array.attrs)
            grid_mapping = attrs.get("grid_mapping")
            group = path.rpartition("/")[0]
            if grid_mapping and not {str(grid_mapping), f"{group}/{grid_mapping}"} & present:
                del array.attrs["grid_mapping"]
            declared = str(attrs.get("coordinates", "")).split()
            resolved = [name for name in declared if name in present]
            if resolved != declared:
                if resolved:
                    array.attrs["coordinates"] = " ".join(resolved)
                else:
                    del array.attrs["coordinates"]


# -- ACDD --------------------------------------------------------------------


def write_acdd_root_attrs(
    store_obj: SimulationZarr,
    *,
    sim_row: dict[str, Any] | None,
    runs_env: dict[str, Any] | None,
    project_table: dict[str, Any] | None = None,
    geographic_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compose and persist ACDD root attrs. Returns the attrs written."""
    attrs = compose_acdd_root_attrs(
        sim_row=sim_row,
        runs_env=runs_env,
        project_table=project_table,
        geographic_bounds=geographic_bounds,
    )
    with store_obj._guard_write():
        store_obj._root = update_attrs(store_obj._root, attrs)
        meta = store_obj._root.require_group("meta")
        # ``meta`` stores the same ACDD payload so a downstream tool can
        # discover the metadata even with .zmetadata stripped.
        update_attrs(meta, attrs)
    return attrs


__all__ = [
    "attach_field_attrs",
    "attrs_for_field",
    "ensure_child_dir",
    "field_name_from_target",
    "harmonize_axis_references",
    "maybe_shards",
    "QUANTIZATION_VARIABLE",
    "write_acdd_root_attrs",
    "write_crs",
    "write_descent",
    "write_field",
    "write_forcing_attrs",
    "write_forcing_field",
    "write_forcing_timeseries",
    "write_geographic_raster",
    "write_lake_abacus",
    "write_mesh",
    "write_static_field",
    "write_time",
    "write_topography",
]
