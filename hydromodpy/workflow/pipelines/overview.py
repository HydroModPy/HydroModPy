"""Data-overview launcher - "watershed identity card" workflow.

Orchestrates four phases:

1. **Workspace** - prepare output directories.
2. **Geographic** - delineate watershed from outlet coordinates.
3. **Data loading** - download / load all requested data families.
4. **Report** - generate overview PNGs (one per panel).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hydromodpy.core.config import HydroModPyConfig
from hydromodpy.workflow.pipelines.overview_config import DataOverviewState

logger = logging.getLogger(__name__)


class DataOverviewLauncher:
    """Generate a "watershed identity card" from a TOML configuration file."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.cfg = HydroModPyConfig.from_toml(self.config_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Execute the full overview pipeline and return a result summary."""
        state = DataOverviewState(cfg=self.cfg)

        # Phase 1: Workspace
        self._setup_workspace(state)

        # Phase 1b: DEM bootstrap (download via API if no local path)
        self._bootstrap_dem(state)

        # Phase 2: Geographic (watershed delineation)
        self._setup_geographic(state)

        # Phase 3: Data loading
        self._load_data(state)

        # Phase 4: Report generation (PNGs)
        report_paths = self._generate_report(state)

        return {
            "mode": "data_overview",
            "report_paths": [str(p) for p in report_paths],
            "catchment_area_km2": (
                state.domain_geographic.catchment_area_km2 if state.domain_geographic else None
            ),
        }

    # ------------------------------------------------------------------
    # Phase 1 - Workspace
    # ------------------------------------------------------------------

    @staticmethod
    def _setup_workspace(state: DataOverviewState) -> None:
        from hydromodpy.core.workspace.workspace import Workspace

        state.workspace = Workspace(config=state.cfg.workspace)
        logger.info("[overview] Workspace: %s", state.workspace.project_root)

    # ------------------------------------------------------------------
    # Phase 1b - DEM bootstrap (API download)
    # ------------------------------------------------------------------

    def _bootstrap_dem(self, state: DataOverviewState) -> None:
        """Resolve ``geographic.dem_init_path`` from ``[[data.dem.sources]]`` if absent.

        Delegates to the shared resolver so the standard simulation
        pipeline and the overview pipeline behave identically.
        """
        from hydromodpy.data.variables.dem.resolver import (
            resolve_dem_path_from_data_sources,
        )

        geo_cfg = state.cfg.geographic
        if (
            geo_cfg.dem_init_path is not None
            and Path(geo_cfg.dem_init_path).name != "__DEM_API_BOOTSTRAP__"
            and geo_cfg.dem_init_path.exists()
        ):
            return

        cache_dir = None
        if state.workspace is not None and state.workspace.paths.data_path is not None:
            cache_dir = state.workspace.paths.data_path / "dem"

        resolved = resolve_dem_path_from_data_sources(
            state.cfg,
            config_path=self.config_path,
            cache_dir=cache_dir,
        )
        if resolved is None:
            raise ValueError(
                "No dem_init_path and no [data.dem] source configured. "
                "Either set geographic.dem_init_path or add:\n"
                '  [data]\n  types = [..., "dem"]\n'
                '  [[data.dem.sources]]\n  source = "ign_bdalti"\n'
                "or:\n"
                '  [[data.dem.sources]]\n  source = "custom"\n  path = "..."'
            )
        logger.info("[overview] DEM resolved from [data.dem]: %s", resolved)
        geo_cfg.dem_init_path = resolved

    # ------------------------------------------------------------------
    # Phase 2 - Geographic
    # ------------------------------------------------------------------

    @staticmethod
    def _setup_geographic(state: DataOverviewState) -> None:
        from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation
        from hydromodpy.spatial.geographic.core.derived_features import (
            coerce_geographic_derived_features,
        )

        geographic = CatchmentDelineation(state.cfg.geographic, state.workspace)
        state.geographic = geographic

        geographic_features = coerce_geographic_derived_features(
            geographic=geographic,
        )
        if geographic_features is None:
            raise ValueError(
                "Could not resolve geographic derived features from the overview geographic runtime."
            )
        state.geographic_features = geographic_features
        domain_geo = geographic_features.to_domain_geographic_context()
        state.domain_geographic = domain_geo
        logger.info(
            "[overview] Catchment area: %.2f km2",
            domain_geo.catchment_area_km2,
        )

    # ------------------------------------------------------------------
    # Phase 3 - Data loading
    # ------------------------------------------------------------------

    def _load_data(self, state: DataOverviewState) -> None:
        """Load every data family declared in ``[data].types`` into ``state.loaded_data``.

        Uses :class:`DataManagersRuntimeLoader` via a duck-typed proxy that
        mimics ``WorkflowContext``. Overview dates from ``[overview]`` are
        injected into data sections that have no explicit dates of their own.
        """
        from types import SimpleNamespace

        from hydromodpy.data.loader import DataManagersRuntimeLoader
        from hydromodpy.data.plan import DataLoadPlan
        from hydromodpy.spatial.geographic.core.derived_features import (
            attach_reference_hydrographic_network,
        )

        data_plan = DataLoadPlan(
            explicit_types=tuple(state.cfg.data.types),
            inferred_types=(),
        )
        logger.info("[overview] Loading data for: %s", list(data_plan.types))

        self._inject_overview_dates(state)

        proxy = SimpleNamespace(
            cfg=SimpleNamespace(
                data=state.cfg.data,
                workspace=state.cfg.workspace,
                simulation=None,
                overview=state.cfg.overview,
            ),
            setup=SimpleNamespace(
                workspace=state.workspace,
                geographic=state.geographic,
                domain=None,
            ),
            loaded_data=state.loaded_data,
            config_path=self.config_path,
            data_plan=data_plan,
        )

        loader = DataManagersRuntimeLoader(
            config_path=self.config_path,
            data_plan=data_plan,
        )
        loader.load_all(proxy)
        if state.geographic_features is not None:
            state.geographic_features = attach_reference_hydrographic_network(
                state.geographic_features,
                state.loaded_data.hydrography,
            )

    @staticmethod
    def _inject_overview_dates(state: DataOverviewState) -> None:
        """Copy ``[overview].date_start/date_end`` into data sections missing them."""
        overview = state.cfg.overview
        if overview is None or not overview.date_start or not overview.date_end:
            return

        for type_name in state.cfg.data.types:
            section = getattr(state.cfg.data, type_name, None)
            if section is None or not hasattr(section, "date_start"):
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

    # ------------------------------------------------------------------
    # Phase 4 - Report generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_report(state: DataOverviewState) -> list[Path]:
        from hydromodpy.display.overview import generate_overview_report

        return generate_overview_report(state)
