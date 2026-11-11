"""The descent D of a run and what the stream criterion reads beside it.

The solver build stores D under ``fields.zarr/mesh/`` (``descent_*`` arrays),
with the basin of D at the catchment outlet (``descent_basin``). A run sealed
before that has no D: its view rebuilds D from the stored top with
:func:`hydromodpy.catchment.drainage.descent.descent_from_stored_mesh` and says so once. A run
sealed with D but before the basin has D and no basin (``basin`` is ``None``).
The share of each cell's area inside the delineated catchment polygon lands
beside the basin as ``catchment_fraction`` (:func:`read_catchment_fraction`).
Display reaches D through ``run.descent`` and never imports ``catchment`` or
``solver``.

The run keeps three more things the criterion read when it ran, so a figure reads
back what the trials scored: the cells of open water (``mesh/open_water``), the
cells inside the catchment outline (``mesh/catchment_cells``) and the mean
recharge the seepage threshold is a fraction of
(:func:`read_criterion_recharge`).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.catchment.drainage.descent import descent_from_stored_mesh, descent_graph
from hydromodpy.catchment.drainage.filling import DEFAULT_EPSILON_M
from hydromodpy.core.logging import get_logger
from hydromodpy.model.forcing.recharge_rates import CRITERION_MEAN_RECHARGE_ATTR
from hydromodpy.results.run.contracts import MeshDescent

if TYPE_CHECKING:
    from collections.abc import Callable

    from hydromodpy.results.run.view import Run

logger = get_logger(__name__)

_LARGEST_BASIN_RULE = "largest_basin"


@dataclass(frozen=True, slots=True, eq=False)
class StoredBasin:
    """The basin of D a run stored under ``mesh/descent_basin``."""

    mask: np.ndarray
    """(n_faces,) bool, read-only: the faces of the basin."""

    area_m2: float
    rule: str
    """How the outlet was found (``basin_rule``)."""

    attrs: dict[str, object] = field(default_factory=dict)
    """The stored attributes: ``descent_outlet``, ``basin_rule``, ``basin_area_m2``,
    ``basin_seeded_at_outlet`` and ``basin_version``, as far as the run holds them."""

    @property
    def is_catchment(self) -> bool:
        """False for the largest basin of a domain with neither outlet nor polygon."""
        return self.rule != _LARGEST_BASIN_RULE


_REPORT_KEYS = (
    "n_raised",
    "max_raise_m",
    "n_lake_flooded",
    "max_lake_flood_m",
    "n_pinned_raised",
    "max_pinned_raise_m",
)
_BASIN_ARRAY = "descent_basin"
_BASIN_ATTRS = (
    "descent_outlet",
    "basin_rule",
    "basin_area_m2",
    "basin_seeded_at_outlet",
    "basin_version",
)
_VIEW_ATTRIBUTES = frozenset(item.name for item in fields(MeshDescent)) | {"diagonal_neighbors"}


class RunDescent:
    """Lazy, memoized holder of one run's :class:`MeshDescent`.

    The first attribute read loads D; the next ones reuse it, so a gallery of
    figures pays one read, and one INFO line for an old run, per run.
    """

    def __init__(
        self,
        load: Callable[[], MeshDescent],
        load_dam_foot: Callable[[], np.ndarray] | None = None,
        load_basin: Callable[[], StoredBasin | None] | None = None,
        *,
        load_open_water: Callable[[], np.ndarray | None] | None = None,
        load_catchment_cells: Callable[[], np.ndarray | None] | None = None,
        load_recharge: Callable[[], float | None] | None = None,
    ) -> None:
        self._load = load
        self._load_dam_foot = load_dam_foot
        self._load_basin = load_basin
        self._criterion_loaders = {
            "open_water": load_open_water,
            "catchment_cells": load_catchment_cells,
            "recharge": load_recharge,
        }
        self._criterion_inputs: dict[str, Any] = {}
        self._view: MeshDescent | None = None
        self._dam_foot: np.ndarray | None = None
        self._basin: StoredBasin | None = None
        self._basin_read = False

    @classmethod
    def of_run(cls, run: Run) -> RunDescent:
        """The holder for ``run``: its stored D, else one rebuilt from its top."""
        return cls(
            lambda: load_descent(run),
            lambda: read_dam_foot(run),
            lambda: read_basin(run),
            load_open_water=lambda: read_open_water(run),
            load_catchment_cells=lambda: read_catchment_cells(run),
            load_recharge=lambda: read_criterion_recharge(run),
        )

    @property
    def dam_foot(self) -> np.ndarray:
        """The cell ids below the dams, read alone: D is neither loaded nor rebuilt.

        Empty for a run that stored none, so a figure that only needs the feet
        never pays for D nor logs the rebuild of an old run.
        """
        if self._view is not None:
            return self._view.dam_foot
        if self._load_dam_foot is None:
            return self.view().dam_foot
        if self._dam_foot is None:
            self._dam_foot = self._load_dam_foot()
        return self._dam_foot

    def stored_basin(self) -> StoredBasin | None:
        """The stored basin of D with its attributes, read alone, ``None`` when the run has none.

        D is neither loaded nor rebuilt, so a reader that only wants the
        catchment of a run sealed without D does not pay for a rebuild.
        """
        if self._view is None and self._load_basin is not None:
            if not self._basin_read:
                self._basin = self._load_basin()
                self._basin_read = True
            return self._basin
        view = self.view()
        if view.basin is None:
            return None
        return _basin_of(view.basin, view.basin_attrs)

    def open_water(self) -> np.ndarray | None:
        """The cells of open water the criterion left out, ``None`` when the run kept none."""
        return self._criterion_input("open_water")

    def catchment_cells(self) -> np.ndarray | None:
        """The cells inside the catchment outline, ``None`` when the run has no outline."""
        return self._criterion_input("catchment_cells")

    def criterion_recharge(self) -> float | None:
        """The mean recharge the trials read, in m/s, ``None`` when the run kept none."""
        return self._criterion_input("recharge")

    def _criterion_input(self, name: str) -> Any:
        """Read one criterion input once, alone: D is neither loaded nor rebuilt."""
        if name not in self._criterion_inputs:
            load = self._criterion_loaders[name]
            self._criterion_inputs[name] = None if load is None else load()
        return self._criterion_inputs[name]

    def view(self) -> MeshDescent:
        """Return the loaded descent."""
        if self._view is None:
            self._view = self._load()
        return self._view

    def __getattr__(self, name: str):
        if name in _VIEW_ATTRIBUTES:
            return getattr(self.view(), name)
        raise AttributeError(name)


def load_descent(run: Run) -> MeshDescent:
    """Read the stored D of ``run``, or rebuild it when the run holds none."""
    stored = _read_stored(run)
    if stored is not None:
        return stored
    return _rebuild(run)


def read_dam_foot(run: Run) -> np.ndarray:
    """Read ``mesh/descent_dam_foot`` alone, empty when the run holds none."""
    sz = run._catalog.open_zarr(run._sim_id)
    try:
        mesh = sz.root.get("mesh")
        if mesh is None or "descent_dam_foot" not in mesh:
            return _read_only([], "int64")
        return _read_only(mesh["descent_dam_foot"][:], "int64")
    finally:
        sz.close()


def read_basin(run: Run) -> StoredBasin | None:
    """Read ``mesh/descent_basin`` and its attributes alone, ``None`` when the run holds none.

    D is neither loaded nor rebuilt, so a reader that only wants the catchment of
    a run pays for one array.
    """
    sz = run._catalog.open_zarr(run._sim_id)
    try:
        return basin_of_group(sz.root.get("mesh"))
    finally:
        sz.close()


def basin_of_group(mesh: Any) -> StoredBasin | None:
    """Read the basin of D in a ``mesh/`` group, ``None`` for a group that holds none.

    The one reader of ``descent_basin``: a run view and the catchment
    aggregation, which holds a Zarr group and no run, both call it.
    """
    if mesh is None or _BASIN_ARRAY not in mesh:
        return None
    array = mesh[_BASIN_ARRAY]
    attrs = dict(array.attrs)
    return _basin_of(
        _read_only(array[:], bool), {key: attrs[key] for key in _BASIN_ATTRS if key in attrs}
    )


def _basin_of(mask: np.ndarray, attrs: dict[str, object]) -> StoredBasin:
    """Return the basin of a read-only ``mask`` and its stored attributes."""
    return StoredBasin(
        mask=mask,
        area_m2=float(attrs["basin_area_m2"]) if "basin_area_m2" in attrs else float("nan"),
        rule=str(attrs.get("basin_rule", "")),
        attrs=attrs,
    )


def read_open_water(run: Run) -> np.ndarray | None:
    """Read ``mesh/open_water`` alone: the cells whose water extent the model was told.

    ``None`` when the run stored none, which a run sealed before the criterion
    inputs were kept does not.
    """
    return _read_mesh_mask(run, "open_water")


def read_catchment_cells(run: Run) -> np.ndarray | None:
    """Read ``mesh/catchment_cells`` alone: the cells inside the catchment outline.

    ``None`` when the run has no outline to read (a synthetic domain).
    """
    return _read_mesh_mask(run, "catchment_cells")


def read_criterion_recharge(run: Run) -> float | None:
    """Read the mean recharge the trials read, in m/s, or ``None`` when the run kept none."""
    sz = run._catalog.open_zarr(run._sim_id)
    try:
        forcing = sz.root.get("forcing")
        kept = None if forcing is None else forcing.attrs.get(CRITERION_MEAN_RECHARGE_ATTR)
    finally:
        sz.close()
    return None if kept is None else float(kept)


def _read_mesh_mask(run: Run, name: str) -> np.ndarray | None:
    sz = run._catalog.open_zarr(run._sim_id)
    try:
        mesh = sz.root.get("mesh")
        if mesh is None or name not in mesh:
            return None
        return _read_only(mesh[name][:], bool)
    finally:
        sz.close()


def read_catchment_fraction(run: Run) -> np.ndarray | None:
    """Read ``mesh/catchment_fraction`` alone, ``None`` when the run holds none."""
    sz = run._catalog.open_zarr(run._sim_id)
    try:
        mesh = sz.root.get("mesh")
        if mesh is None or "catchment_fraction" not in mesh:
            return None
        return _read_only(mesh["catchment_fraction"][:], "float64")
    finally:
        sz.close()


def _read_only(values: np.ndarray, dtype: str | type) -> np.ndarray:
    out = np.array(values, dtype=dtype)
    out.flags.writeable = False
    return out


def _read_stored(run: Run) -> MeshDescent | None:
    sz = run._catalog.open_zarr(run._sim_id)
    try:
        mesh = sz.root.get("mesh")
        if mesh is None or "descent_receiver" not in mesh:
            return None
        receiver = _read_only(mesh["descent_receiver"][:], "int64")
        surface = _read_only(mesh["descent_surface"][:], "float64")
        attrs = dict(mesh["descent_receiver"].attrs)
        dam_foot = (
            _read_only(mesh["descent_dam_foot"][:], "int64")
            if "descent_dam_foot" in mesh
            else _read_only([], "int64")
        )
        masks = {
            name: _read_only(mesh[f"descent_{name}"][:], bool)
            for name in ("base_level", "constant_head", "raised", "channel", "pinned")
        }
        stored_basin = basin_of_group(mesh)
    finally:
        sz.close()
    epsilon = attrs.get("epsilon")
    return MeshDescent(
        receiver=receiver,
        surface=surface,
        graph=descent_graph(receiver, surface),
        adjacency=str(attrs.get("adjacency", "shared_nodes")),
        epsilon=None if epsilon is None else float(epsilon),
        report={key: float(attrs[key]) for key in _REPORT_KEYS if key in attrs},
        rebuilt=False,
        dam_foot=dam_foot,
        basin=None if stored_basin is None else stored_basin.mask,
        basin_attrs={} if stored_basin is None else stored_basin.attrs,
        **masks,
    )


def _rebuild(run: Run) -> MeshDescent:
    mesh = run.mesh
    if mesh.topography is None:
        raise ValueError(f"run {run.sim_id} stored no mesh topography to build a descent on.")
    logger.info(
        "Run %s predates the stored descent: it is rebuilt from the stored top, without "
        "channel pins, constant-head seeds or lakes.",
        run.sim_id,
    )
    return rebuilt_view(mesh.topography, mesh.face_node_connectivity, mesh.vertices)


def rebuilt_view(
    top: np.ndarray, face_node_connectivity: np.ndarray, vertices: np.ndarray
) -> MeshDescent:
    """Build the unpinned D of a stored mesh and wrap it as a view."""
    descent = descent_from_stored_mesh(top, face_node_connectivity, vertices)
    adjacency = "shared_nodes" if descent.diagonal_neighbors else "shared_faces"
    report = {
        "n_raised": descent.n_raised,
        "max_raise_m": descent.max_raise_m,
        "n_lake_flooded": descent.n_lake_flooded,
        "max_lake_flood_m": descent.max_lake_flood_m,
        "n_pinned_raised": descent.n_pinned_raised,
        "max_pinned_raise_m": descent.max_pinned_raise_m,
    }
    return MeshDescent(
        receiver=_read_only(descent.receiver, "int64"),
        surface=_read_only(descent.surface, "float64"),
        base_level=_read_only(descent.base_level, bool),
        constant_head=_read_only(descent.constant_head, bool),
        raised=_read_only(descent.raised, bool),
        channel=_read_only(descent.channel, bool),
        pinned=_read_only(descent.pinned, bool),
        graph=descent.metric.graph,
        adjacency=adjacency,
        epsilon=DEFAULT_EPSILON_M,
        report=report,
        rebuilt=True,
    )


__all__ = (
    "RunDescent",
    "StoredBasin",
    "basin_of_group",
    "load_descent",
    "read_basin",
    "read_catchment_cells",
    "read_catchment_fraction",
    "read_criterion_recharge",
    "read_dam_foot",
    "read_open_water",
    "rebuilt_view",
)
