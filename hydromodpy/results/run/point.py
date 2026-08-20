"""Point interrogation of a finished run: one cell, one variable, one series.

What
----
Ask a persisted run for the value of a variable in one precise cell, after the
fact. The cell is named by project-CRS coordinates, by its index, or by a
depth that picks the layer. The answer is a long-format table: one row per
timestep (one row for a steady run), which also makes the multi-run form
(:func:`read_points`) a plain concatenation ready for a scenario comparison.

Why
---
Everything needed already existed and was unreachable: the point-to-cell
lookup (:mod:`hydromodpy.results.spatial_index`) and the on-the-fly
derivations (:mod:`hydromodpy.results.derive.virtual_fields`). This module
binds them to a run and exposes one gesture, so a virtual field
(``watertable_depth`` ...) answers exactly like a persisted one.

How
---
A persisted field is sliced in a single Zarr call (``array[:, layer, cell]``):
one decompression pass over the touched chunks rather than one per timestep.
A virtual field is rebuilt timestep by timestep through the shared derivation
and reduced to the cell right away, so memory stays at one field.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.array import lookup_zarr_path

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

POINT_COLUMNS: tuple[str, ...] = (
    "run",
    "sim_id",
    "variable",
    "timestep",
    "time",
    "value",
    "unit",
    "cell",
    "layer",
    "x",
    "y",
)
"""Column order of the long-format table returned by every reader here."""

_SEARCH_GROUPS: tuple[str | None, ...] = (None, "state", "derived", "budget", "mesh")


class PointOutsideMeshError(ValueError):
    """The requested coordinates fall outside the simulation mesh."""


@dataclass(frozen=True, slots=True)
class PointRequest:
    """Where to read: coordinates, a cell index, and how to pick the layer.

    Exactly one of ``(x, y)`` or ``cell`` identifies the cell. At most one of
    ``layer`` or ``depth`` picks the layer; ``depth`` is metres below the local
    model top and resolves against the mesh layer thicknesses.
    """

    x: float | None = None
    y: float | None = None
    cell: int | None = None
    layer: int | None = None
    depth: float | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        has_xy = self.x is not None and self.y is not None
        if not has_xy and (self.x is not None or self.y is not None):
            raise ValueError("Coordinates need both x and y.")
        if has_xy == (self.cell is not None):
            raise ValueError("Give either coordinates (x and y) or a cell index, not both.")
        if self.layer is not None and self.depth is not None:
            raise ValueError("Give either a layer index or a depth, not both.")
        if self.depth is not None and self.depth < 0:
            raise ValueError(f"depth must be >= 0, got {self.depth}.")

    @property
    def name(self) -> str:
        """Label of the point, defaulting to a readable position."""
        if self.label:
            return self.label
        if self.cell is not None:
            return f"cell{self.cell}"
        return f"{self.x:g}_{self.y:g}"


@dataclass(frozen=True, slots=True)
class ResolvedPoint:
    """A request bound to one run: cell index, layer index, and coordinates."""

    cell: int
    layer: int | None
    x: float | None
    y: float | None
    label: str


def _mesh_fingerprint(run: Run, mesh: Any) -> str:
    """Geometry fingerprint of the run, used to key the point-to-cell caches.

    The ``mesh_hash`` the run recorded is preferred; a run that never recorded
    one is fingerprinted from the mesh arrays themselves, so the cache is keyed
    by the geometry either way and never by the run identity.
    """
    value = run._load_row().get("mesh_hash")
    if value not in (None, ""):
        return str(value)
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(mesh.vertices, dtype="float64").tobytes())
    digest.update(np.ascontiguousarray(mesh.face_node_connectivity, dtype="int64").tobytes())
    return digest.hexdigest()


def resolve_point(run: Run, request: PointRequest) -> ResolvedPoint:
    """Bind a :class:`PointRequest` to one run's mesh.

    Raises :class:`PointOutsideMeshError` when the coordinates miss the mesh,
    and ``IndexError`` when an explicit cell or layer index is out of range.
    """
    from hydromodpy.results.spatial_index import cell_index_cache_dir, locator_for

    mesh = run.mesh
    n_cells = int(np.asarray(mesh.face_node_connectivity).shape[0])

    if request.cell is not None:
        cell = int(request.cell)
        if not 0 <= cell < n_cells:
            raise IndexError(f"Cell {cell} is out of range for a mesh of {n_cells} cells.")
        x, y = _cell_centroid(mesh, cell)
    else:
        locator = locator_for(
            mesh.vertices,
            mesh.face_node_connectivity,
            fingerprint=_mesh_fingerprint(run, mesh),
            cache_dir=cell_index_cache_dir(run._catalog.project_path),
        )
        found = locator.locate(
            {request.name: (float(request.x), float(request.y))}, warn_outside=False
        )[request.name]
        if found is None:
            raise PointOutsideMeshError(
                f"Point ({request.x}, {request.y}) falls outside the mesh of run "
                f"'{run.name or run.sim_id[:8]}'."
            )
        cell = int(found)
        x, y = float(request.x), float(request.y)

    layer = _resolve_layer(run, mesh, cell, request)
    return ResolvedPoint(cell=cell, layer=layer, x=x, y=y, label=request.name)


def _cell_centroid(mesh: Any, cell: int) -> tuple[float, float]:
    """Return the centroid of one face, used to report where a cell index is."""
    vertices = np.asarray(mesh.vertices)[:, :2]
    nodes = np.asarray(mesh.face_node_connectivity)[cell]
    nodes = nodes[nodes >= 0]
    return float(vertices[nodes, 0].mean()), float(vertices[nodes, 1].mean())


def _resolve_layer(run: Run, mesh: Any, cell: int, request: PointRequest) -> int | None:
    """Return the layer index to read, from an explicit index or from a depth."""
    n_layers = int(run.n_layers or 1)
    if request.layer is not None:
        layer = int(request.layer)
        if layer < 0:
            layer += n_layers
        if not 0 <= layer < n_layers:
            raise IndexError(f"Layer {request.layer} is out of range for {n_layers} layers.")
        return layer
    if request.depth is None:
        return None
    return _layer_at_depth(run, mesh, cell, float(request.depth), n_layers)


def _layer_at_depth(run: Run, mesh: Any, cell: int, depth: float, n_layers: int) -> int:
    """Return the layer holding *depth* metres below the local model top."""
    thickness = _layer_thickness(run, cell, n_layers)
    if thickness is None:
        z = np.asarray(mesh.z_interfaces, dtype="float64").ravel()
        if z.size < 2:
            return 0
        thickness = np.abs(np.diff(z))[:n_layers]
    bottoms = np.cumsum(np.asarray(thickness, dtype="float64"))
    index = int(np.searchsorted(bottoms, depth, side="left"))
    return min(index, n_layers - 1)


def _layer_thickness(run: Run, cell: int, n_layers: int) -> np.ndarray | None:
    """Per-layer thickness at one cell, or ``None`` when the mesh omits it."""
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        mesh_grp = sz.root.get("mesh")
        if mesh_grp is None or "layer_thickness" not in mesh_grp:
            return None
        array = mesh_grp["layer_thickness"]
        if array.ndim != 2:
            return None
        return np.asarray(array[:, cell], dtype="float64")[:n_layers]
    finally:
        sz.close()


def read_point(
    run: Run,
    variable: str | Sequence[str],
    request: PointRequest,
    *,
    timestep: int | None = None,
) -> pd.DataFrame:
    """Read one or more variables at one point of a finished run.

    Returns a long-format frame with :data:`POINT_COLUMNS`: one row per
    timestep and variable, one row per variable for a steady run.
    """
    names = [variable] if isinstance(variable, str) else list(variable)
    if not names:
        raise ValueError("At least one variable is required.")
    point = resolve_point(run, request)
    time_index = _time_index(run)
    frames = [
        _read_one(run, name, point, time_index=time_index, timestep=timestep) for name in names
    ]
    return pd.concat(frames, ignore_index=True)[list(POINT_COLUMNS)]


def read_points(
    runs: Iterable[Run],
    variable: str | Sequence[str],
    request: PointRequest,
    *,
    timestep: int | None = None,
) -> pd.DataFrame:
    """Read the same point on several runs and stack the answers.

    The real gesture behind a scenario comparison: the coordinates are
    resolved per run (two runs rarely share a mesh), and the ``run`` column
    tells the series apart.
    """
    frames = [read_point(run, variable, request, timestep=timestep) for run in runs]
    if not frames:
        return pd.DataFrame(columns=list(POINT_COLUMNS))
    return pd.concat(frames, ignore_index=True)


class RunPointProvider:
    """Point interrogation bound to one run or to a group of them.

    Exposed as ``run.probe`` and ``group.probe``. It lives beside the
    :class:`Run` facade rather than on it so the point gesture can grow
    without pushing the facade over its method budget, exactly like
    ``run.array``.
    """

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def series(
        self,
        variable: str | Sequence[str],
        *,
        x: float | None = None,
        y: float | None = None,
        cell: int | None = None,
        layer: int | None = None,
        depth: float | None = None,
        label: str | None = None,
        timestep: int | None = None,
        output: Path | str | None = None,
    ) -> pd.DataFrame:
        """Read one or more variables in one precise cell.

        The cell is named by project-CRS coordinates (``x`` and ``y``), by its
        index (``cell``), or by a ``depth`` in metres below the local model top
        that picks the layer. Virtual fields (``watertable_depth`` ...) answer
        like persisted ones.

        Parameters
        ----------
        variable
            Field name, or a list of them.
        x, y
            Coordinates in the simulation CRS. Mutually exclusive with ``cell``.
        cell
            Zero-based cell index. Mutually exclusive with ``x`` / ``y``.
        layer
            Zero-based layer index; negative counts from the bottom.
        depth
            Metres below the local model top, resolved against the mesh layer
            thicknesses. Mutually exclusive with ``layer``.
        label
            Name of the point, reported in the table.
        timestep
            Keep a single timestep instead of the whole series.
        output
            Optional ``.csv`` or ``.parquet`` path to write the table to.

        Returns
        -------
        pandas.DataFrame
            Long-format table with :data:`POINT_COLUMNS`: one row per timestep,
            variable and run (one row per variable for a steady run).

        Examples
        --------
        >>> run.probe.series("head", x=352000.0, y=6789000.0)
        >>> run.probe.series("watertable_depth", cell=1204, timestep=-1)
        >>> group.probe.series("head", x=352000.0, y=6789000.0, depth=12.5)
        """
        request = PointRequest(x=x, y=y, cell=cell, layer=layer, depth=depth, label=label)
        frame = read_points(self._owner._iter_runs(), variable, request, timestep=timestep)
        if output is not None:
            write_point_table(frame, output)
        return frame

    @property
    def declared(self) -> pd.DataFrame:
        """Points declared in ``[observation]`` and sampled during the run.

        Columns: ``run``, ``station_id``, ``x``, ``y``, ``cell_id``, ``layer``.
        The matching series read back with
        ``run.timeseries(variable, station="obs:<station_id>")``.
        """
        frames = []
        for run in self._owner._iter_runs():
            frame = run._catalog.backend.query(
                "SELECT station_id, x, y, cell_id, layer FROM observation_points "
                "WHERE sim_id = ? ORDER BY station_id",
                [run.sim_id],
            )
            frame.insert(0, "run", run.name or run.sim_id[:8])
            frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=["run", "station_id", "x", "y", "cell_id", "layer"])
        return pd.concat(frames, ignore_index=True)


def _time_index(run: Run) -> pd.DatetimeIndex | None:
    """Calendar axis of the run, or ``None`` when it carries none."""
    try:
        return run.time_index
    except Exception:
        logger.debug("Run %s has no calendar time axis", run.sim_id, exc_info=True)
        return None


def _read_one(
    run: Run,
    variable: str,
    point: ResolvedPoint,
    *,
    time_index: pd.DatetimeIndex | None,
    timestep: int | None,
) -> pd.DataFrame:
    """Read one variable at one resolved point as a long-format frame."""
    values, layer = _cell_values(run, variable, point)
    steps = np.arange(values.size, dtype="int64")
    if timestep is not None:
        index = timestep + values.size if timestep < 0 else timestep
        if not 0 <= index < values.size:
            raise IndexError(f"Timestep {timestep} is out of range for {values.size} steps.")
        values = values[index : index + 1]
        steps = steps[index : index + 1]
    times: Any = pd.NaT
    if time_index is not None and len(time_index) > int(steps.max()):
        times = pd.DatetimeIndex(time_index)[steps]
    unit = field_registry.get(variable).units if field_registry.has(variable) else ""
    return pd.DataFrame(
        {
            "run": run.name or run.sim_id[:8],
            "sim_id": run.sim_id,
            "variable": variable,
            "timestep": steps,
            "time": times,
            "value": values.astype("float64"),
            "unit": unit,
            "cell": point.cell,
            "layer": pd.array([pd.NA if layer is None else layer] * len(steps), dtype="Int64"),
            "x": point.x,
            "y": point.y,
        }
    )


def _cell_values(run: Run, variable: str, point: ResolvedPoint) -> tuple[np.ndarray, int | None]:
    """Return the values of *variable* at one cell, with the layer actually read.

    The layer is ``None`` when the stored array carries no layer axis, so the
    table never claims a layer the data does not have.
    """
    sz = run._catalog.open_zarr(run.sim_id)
    try:
        array = _locate_array(sz.root, variable)
        if array is not None:
            return _slice_cell(array, point, time_resolved=_is_time_resolved(variable))
        return _virtual_cell_values(run, sz, variable, point)
    finally:
        sz.close()


def _is_time_resolved(variable: str) -> bool:
    """Return True when the leading axis of the stored array is time.

    Registered static geometry (``topography``, ``layer_thickness``) has none;
    an unregistered solver array is assumed time-resolved, which is what the
    Zarr reader already assumes.
    """
    if not field_registry.has(variable):
        return True
    return field_registry.get(variable).shape.startswith("time")


def _locate_array(root: Any, variable: str) -> Any | None:
    """Find the stored array of *variable*, or ``None`` when not persisted."""
    if field_registry.has(variable):
        array = lookup_zarr_path(root, field_registry.get(variable).zarr_path)
        if array is not None:
            return array
    for group_name in _SEARCH_GROUPS:
        group = root if group_name is None else root.get(group_name)
        if group is not None and variable in group:
            return group[variable]
    return None


def _slice_cell(
    array: Any, point: ResolvedPoint, *, time_resolved: bool
) -> tuple[np.ndarray, int | None]:
    """Slice one cell out of a stored array, in a single read.

    Shapes follow the field registry: ``(time, layer, cell)``,
    ``(time, cell)``, ``(layer, cell)`` and ``(cell,)``. One Zarr call means
    one decompression pass over the touched chunks, whatever the length of
    the series.
    """
    cell = point.cell
    layer = 0 if point.layer is None else point.layer
    if array.ndim == 3:
        return np.asarray(array[:, layer, cell], dtype="float64").ravel(), layer
    if array.ndim == 2:
        if time_resolved:
            return np.asarray(array[:, cell], dtype="float64").ravel(), None
        return np.asarray(array[layer, cell], dtype="float64").ravel(), layer
    return np.asarray(array[cell], dtype="float64").ravel(), None


def _virtual_cell_values(
    run: Run, sz: Any, variable: str, point: ResolvedPoint
) -> tuple[np.ndarray, int | None]:
    """Rebuild a non-persisted field at one cell, timestep by timestep.

    The derivation runs on the whole field (it is the same code a map read
    uses, so the two can never disagree) but only the cell is kept, which
    caps memory at one field instead of one stack.
    """
    from hydromodpy.results.derive.virtual_fields import (
        available_virtual_fields,
        derive_field_slice,
    )

    if variable not in available_virtual_fields(sz.root):
        raise FieldNotFoundError(
            f"Field '{variable}' is neither persisted nor derivable in simulation '{run.sim_id}'.",
            sim_id=run.sim_id,
            variable=variable,
        )
    n_steps = int(run.n_timesteps or 1)
    layer = point.layer
    used: int | None = None
    out = np.empty(n_steps, dtype="float64")
    for step in range(n_steps):
        field = np.asarray(derive_field_slice(sz, run.sim_id, variable, step, layer=layer))
        if field.ndim == 2:
            used = 0 if layer is None else layer
            field = field[used]
        out[step] = float(field.ravel()[point.cell])
    return out, used


def write_point_table(frame: pd.DataFrame, dest: Path | str) -> Path:
    """Write a point table to CSV or Parquet, picked from the extension."""
    path = Path(dest).expanduser()
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".csv":
        frame.to_csv(path, index=False)
    elif suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        raise ValueError(
            f"Unsupported point-table format '{suffix or path.name}': use .csv or .parquet."
        )
    return path


__all__ = [
    "POINT_COLUMNS",
    "PointOutsideMeshError",
    "PointRequest",
    "ResolvedPoint",
    "RunPointProvider",
    "read_point",
    "read_points",
    "resolve_point",
    "write_point_table",
]
