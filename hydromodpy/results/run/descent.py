"""The descent D of a run, read from its store or rebuilt for an old one.

The solver build stores D under ``fields.zarr/mesh/`` (``descent_*`` arrays).
A run sealed before that has none: its view rebuilds D from the stored top with
:func:`hydromodpy.core.descent.descent_from_stored_mesh` and says so once.
Display reaches D through ``run.descent`` and never imports ``spatial`` or
``solver``.
"""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M
from hydromodpy.core.descent import descent_from_stored_mesh, descent_graph
from hydromodpy.core.logging import get_logger
from hydromodpy.results.run.contracts import MeshDescent

if TYPE_CHECKING:
    from collections.abc import Callable

    from hydromodpy.results.run import Run

logger = get_logger(__name__)

_REPORT_KEYS = (
    "n_raised",
    "max_raise_m",
    "n_lake_flooded",
    "max_lake_flood_m",
    "n_pinned_raised",
    "max_pinned_raise_m",
)
_VIEW_ATTRIBUTES = frozenset(item.name for item in fields(MeshDescent)) | {"diagonal_neighbors"}


class RunDescent:
    """Lazy, memoised holder of one run's :class:`MeshDescent`.

    The first attribute read loads D; the next ones reuse it, so a gallery of
    figures pays one read, and one INFO line for an old run, per run.
    """

    def __init__(self, load: Callable[[], MeshDescent]) -> None:
        self._load = load
        self._view: MeshDescent | None = None

    @classmethod
    def of_run(cls, run: Run) -> RunDescent:
        """The holder for ``run``: its stored D, else one rebuilt from its top."""
        return cls(lambda: load_descent(run))

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
        masks = {
            name: _read_only(mesh[f"descent_{name}"][:], bool)
            for name in ("base_level", "constant_head", "raised", "channel", "pinned")
        }
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


__all__ = ("RunDescent", "load_descent", "rebuilt_view")
