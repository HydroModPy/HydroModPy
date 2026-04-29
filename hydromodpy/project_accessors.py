"""Helper accessors exposed on :class:`hydromodpy.project.Project`.

Split from ``project.py`` to keep the facade focused on the run/lifecycle API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.project import Project
    from hydromodpy.results.run import Run


class ProjectDataAccessor:
    """Helper exposed as ``project.data``.

    Lists input-data cache entries used by the project, locates a specific
    :class:`~hydromodpy.data.entry.DataEntry`, and reports missing variables.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    def list(self, variable: str | None = None) -> pd.DataFrame:
        import pandas as pd

        loaded = self._project.data_loaded
        if variable is not None:
            loaded = {v for v in loaded if v == variable}
        return pd.DataFrame({"variable": sorted(loaded)})

    def missing(self) -> list[str]:
        plan_types = getattr(self._project._ctx.data_plan, "types", ()) or ()
        loaded = self._project.data_loaded
        return [t for t in plan_types if t not in loaded]


class ProjectRunsAccessor:
    """Helper exposed as ``project.runs``.

    Thin wrapper around :class:`~hydromodpy.results.catalog.SimulationCatalog`
    that pre-filters queries by the current project name.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    def list(self) -> pd.DataFrame:
        store = self._project._store
        if store is None:
            import pandas as pd

            return pd.DataFrame()
        return store.list_simulations(project=self._project._project_name)

    def find(self, **filters: Any) -> list[Run]:
        store = self._project._store
        if store is None:
            return []
        return store.find(project=self._project._project_name, **filters)

    def latest(self) -> Run | None:
        df = self.list()
        if df.empty:
            return None
        return self._project._store[df.iloc[-1]["sim_id"]]

    def best(self, metric: str) -> Run | None:
        store = self._project._store
        if store is None:
            return None
        return store.best(self._project._project_name, metric=metric)
