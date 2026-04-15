"""Facade adapter bridging :class:`DataOverviewState` to the runtime loader.

``DataManagersRuntimeLoader.load_all()`` expects a ``WorkflowContext``-shaped
object.  This module builds a lightweight duck-typed proxy so the runtime
loader can be re-used without modification.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from hydromodpy.data.plan import DataLoadPlan
from hydromodpy.data.runtime_loader import DataManagersRuntimeLoader

if TYPE_CHECKING:
    from hydromodpy.analysis.display.report.overview_config import DataOverviewState


class OverviewDataLoader:
    """Load all requested data families into a :class:`DataOverviewState`.

    Internally delegates to :class:`DataManagersRuntimeLoader` through a
    duck-typed proxy that satisfies the ``WorkflowContext`` interface.
    """

    def __init__(self, *, config_path: Path, data_plan: DataLoadPlan) -> None:
        self.config_path = config_path
        self.data_plan = data_plan

    def load_all(self, state: DataOverviewState) -> None:
        """Populate ``state.loaded_data`` via the standard runtime loader."""
        self._inject_overview_dates(state)
        proxy = self._build_proxy(state)
        loader = DataManagersRuntimeLoader(
            config_path=self.config_path,
            data_plan=self.data_plan,
        )
        loader.load_all(proxy)
        # loaded_data is shared by reference — already mutated in place.

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_overview_dates(state: DataOverviewState) -> None:
        """Pre-inject ``overview.date_start/date_end`` into data sections.

        For each active data type, if the corresponding config section exists
        but has no explicit dates, copy from ``[overview]``.
        """
        overview = state.cfg.overview
        if overview is None or not overview.date_start or not overview.date_end:
            return

        data_cfg = state.cfg.data
        for type_name in state.cfg.data.types:
            section = getattr(data_cfg, type_name, None)
            if section is None:
                continue
            # Only inject when the section has date fields and they are empty.
            if not hasattr(section, "date_start"):
                continue
            if not getattr(section, "date_start", None):
                try:
                    section.date_start = overview.date_start
                except (AttributeError, TypeError, ValueError):
                    pass
            if not getattr(section, "date_end", None):
                try:
                    section.date_end = overview.date_end
                except (AttributeError, TypeError, ValueError):
                    pass

    @staticmethod
    def _build_proxy(state: DataOverviewState) -> Any:
        """Build a duck-typed proxy mimicking ``WorkflowContext``.

        The proxy satisfies the attribute paths accessed by
        ``DataManagersRuntimeLoader``:

        - ``result.cfg.data``
        - ``result.cfg.simulation`` → ``None`` (no simulation window)
        - ``result.setup.workspace``
        - ``result.setup.geographic``
        - ``result.setup.domain`` → ``None``
        - ``result.loaded_data``
        - ``result.config_path``
        - ``result.data_plan``
        """
        cfg_proxy = SimpleNamespace(
            data=state.cfg.data,
            workspace=state.cfg.workspace,
            simulation=None,
            overview=state.cfg.overview,
        )

        setup_proxy = SimpleNamespace(
            workspace=state.workspace,
            geographic=state.geographic,
            domain=None,
        )

        return SimpleNamespace(
            cfg=cfg_proxy,
            setup=setup_proxy,
            loaded_data=state.loaded_data,
            config_path=Path(""),
            data_plan=None,
        )
