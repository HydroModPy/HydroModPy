"""Catalog and lifecycle helper bound to :class:`hydromodpy.project.Project`.

Encapsulates the Catalog access (``store``, ``runs``, ``data``,
``__getitem__``) and lifecycle hooks (``close``). Split from
:mod:`hydromodpy.project.facade` so the facade keeps a small surface and the
god-class limit holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.project.accessors import ProjectDataAccessor, ProjectRunsAccessor

if TYPE_CHECKING:
    from hydromodpy.project.facade import Project
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


class ProjectCatalog:
    """Catalog and lifecycle methods bound to a :class:`Project` instance.

    Composed by :class:`Project` (``project._catalog``). Reads project
    state by reference; never owns it.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    @property
    def store(self) -> Catalog | None:
        """Open Catalog for direct queries across all runs."""
        return self._project._store

    @property
    def data(self) -> ProjectDataAccessor:
        """Accessor for the input-data cache scoped to this project."""
        return ProjectDataAccessor(self._project)

    @property
    def runs(self) -> ProjectRunsAccessor:
        """Accessor for the simulation catalog scoped to this project."""
        return ProjectRunsAccessor(self._project)

    @property
    def data_loaded(self) -> set[str]:
        """Set of data types already loaded for this project."""
        return set(self._project._data_loaded)

    def get(self, sim_id: str) -> Run:
        """Return the Run view associated with ``sim_id``."""
        return self._project._store[sim_id]

    def close(self) -> None:
        """Close the Catalog and clean up preprocessing files.

        Reads the geographic object directly from the context (never triggers
        a lazy build), so closing an unused Project stays cheap. The
        preprocessing tree survives when ``[geographic] write_intermediates``
        asked for the rasters on disk: the option would otherwise write them
        and lose them at the very next close.
        """
        project = self._project
        if project._phase != "uninitialized":
            from hydromodpy.spatial.geographic.store_ingestion import (
                cleanup_stable_folder,
            )

            geographic_cfg = getattr(project._ctx.cfg, "geographic", None)
            cleanup_stable_folder(
                project._ctx.setup.geographic,
                keep=bool(getattr(geographic_cfg, "write_intermediates", False)),
            )
        if project._store is not None:
            project._store.close()
            project._store = None
