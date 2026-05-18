"""``hmp.catalog`` -- single entry point fronting the three DuckDB files."""

from __future__ import annotations

import os
from pathlib import Path

from hydromodpy.catalog.inputs import InputsNamespace
from hydromodpy.catalog.projects import ProjectsNamespace
from hydromodpy.catalog.simulations import SimulationsNamespace


class CatalogFacade:
    """Bundles the three V1 namespaces against a given workspace.

    Resolved by :func:`open_catalog`. The three namespaces lazily attach
    to their backing DuckDB file on first call, so creating a facade for
    a workspace that lacks a cache or local catalog stays cheap.
    """

    def __init__(self, workspace: Path) -> None:
        self._workspace = Path(workspace).expanduser().resolve()
        self.simulations = SimulationsNamespace(self._workspace)
        self.inputs = InputsNamespace(self._workspace)
        self.projects = ProjectsNamespace()

    @property
    def workspace(self) -> Path:
        """Return the workspace path the facade is bound to."""
        return self._workspace

    def close(self) -> None:
        """Release any underlying DuckDB handles held by the namespaces."""
        self.simulations.close()
        self.inputs.close()
        self.projects.close()

    def __enter__(self) -> CatalogFacade:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def open_catalog(workspace: str | Path | None = None) -> CatalogFacade:
    """Open the catalog facade for ``workspace`` (default: ``HMP_WORKSPACE``).

    Falls back to the current working directory when neither argument nor
    env var resolve to a workspace path. The returned facade can be used
    as a context manager.
    """
    if workspace is None:
        env = os.environ.get("HMP_WORKSPACE")
        workspace = env if env else os.getcwd()
    return CatalogFacade(Path(workspace))


__all__ = ["CatalogFacade", "open_catalog"]
