"""Data-overview launcher — "watershed identity card" workflow.

Orchestrates four phases:

1. **Workspace** — prepare output directories.
2. **Geographic** — delineate watershed from outlet coordinates.
3. **Data loading** — download / load all requested data families.
4. **Report** — generate overview PNGs (one per panel).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_repo_root_on_sys_path() -> Path:
    """Make direct script execution behave like ``python -m`` from the repo root."""
    repo_root = Path(__file__).resolve().parents[2]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    return repo_root


_REPO_ROOT = _ensure_repo_root_on_sys_path()


from hydromodpy.core.config.toml_loader import load_toml_with_base_config

from launchers.data_overview.config import DataOverviewConfig
from launchers.data_overview.state import DataOverviewState


class DataOverviewLauncher:
    """Generate a "watershed identity card" from a TOML configuration file."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        raw_toml = load_toml_with_base_config(self.config_path)
        self.cfg = DataOverviewConfig.from_toml(
            raw_toml, base_dir=self.config_path.parent,
        )

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
                state.domain_geographic.catchment_area_km2
                if state.domain_geographic
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Phase 1 — Workspace
    # ------------------------------------------------------------------

    @staticmethod
    def _setup_workspace(state: DataOverviewState) -> None:
        from hydromodpy.core.workspace.workspace import Workspace

        state.workspace = Workspace(config=state.cfg.workspace)
        logger.info("[overview] Workspace: %s", state.workspace.project_root)

    # ------------------------------------------------------------------
    # Phase 1b — DEM bootstrap (API download)
    # ------------------------------------------------------------------

    @staticmethod
    def _bootstrap_dem(state: DataOverviewState) -> None:
        """Download DEM via IGN BD ALTI API when ``dem_init_path`` is absent.

        Uses the outlet coordinates + a generous buffer to build a bbox,
        then downloads and injects the path into the geographic config.
        """
        geo_cfg = state.cfg.geographic
        if (
            geo_cfg.dem_init_path is not None
            and str(geo_cfg.dem_init_path) != "__DEM_API_BOOTSTRAP__"
            and geo_cfg.dem_init_path.exists()
        ):
            return

        # Check if a DEM API source is configured in [data.dem].
        dem_source = _find_dem_api_source(state.cfg)
        if dem_source is None:
            raise ValueError(
                "No dem_init_path and no [data.dem] API source configured. "
                "Either set geographic.dem_init_path or add:\n"
                "  [data]\n  types = [..., \"dem\"]\n"
                "  [[data.dem.sources]]\n  source = \"ign_bdalti\""
            )

        x_out = geo_cfg.x_outlet
        y_out = geo_cfg.y_outlet
        if x_out is None or y_out is None:
            raise ValueError(
                "DEM bootstrap requires outlet coordinates "
                "(geographic.x_outlet / y_outlet)."
            )

        # Build a generous bbox around the outlet (30 km buffer).
        _BUFFER_M = 30_000
        bbox = (x_out - _BUFFER_M, y_out - _BUFFER_M,
                x_out + _BUFFER_M, y_out + _BUFFER_M)

        from hydromodpy.data.variables.dem.apis.ign_bdalti import (
            fetch_bdalti,
        )

        cache_dir = Path.home() / ".cache" / "hydromodpy" / "dem"
        if state.workspace is not None and state.workspace.paths.data_path is not None:
            cache_dir = state.workspace.paths.data_path / "dem"
        cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info("[overview] Downloading DEM via %s API ...", dem_source)
        tif_path = fetch_bdalti(output_dir=cache_dir, bbox=bbox)
        logger.info("[overview] DEM downloaded: %s", tif_path)

        # Inject into geographic config so the pipeline can use it.
        geo_cfg.dem_init_path = tif_path

    # ------------------------------------------------------------------
    # Phase 2 — Geographic
    # ------------------------------------------------------------------

    @staticmethod
    def _setup_geographic(state: DataOverviewState) -> None:
        from hydromodpy.spatial.geographic.core.derived_features import (
            coerce_geographic_derived_features,
        )
        from hydromodpy.spatial.geographic.geographic import Geographic

        geographic = Geographic(state.cfg.geographic, state.workspace)
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
    # Phase 3 — Data loading
    # ------------------------------------------------------------------

    def _load_data(self, state: DataOverviewState) -> None:
        from hydromodpy.data.plan import DataLoadPlan
        from launchers.data_overview.data_loader import OverviewDataLoader

        # Build a minimal data plan from the explicit types list.
        data_plan = DataLoadPlan(
            explicit_types=tuple(state.cfg.data.types),
            inferred_types=(),
        )

        loader = OverviewDataLoader(
            config_path=self.config_path,
            data_plan=data_plan,
        )
        loader.load_all(state)
        logger.info("[overview] Data loaded for: %s", list(data_plan.types))

    # ------------------------------------------------------------------
    # Phase 4 — Report generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_report(state: DataOverviewState) -> list[Path]:
        from hydromodpy.analysis.display.report.overview_report import (
            generate_overview_report,
        )

        paths = generate_overview_report(state)
        if paths:
            logger.info("[overview] Generated %d panel(s):", len(paths))
            for p in paths:
                logger.info("  %s", p)
        else:
            logger.info("[overview] No panels enabled -- nothing to generate.")
        return paths


# ======================================================================
# Module-level helpers
# ======================================================================

def _find_dem_api_source(cfg: DataOverviewConfig) -> str | None:
    """Return the API source name if a DEM API source is configured."""
    _API_SOURCES = {"ign_bdalti"}
    dem_cfg = getattr(cfg.data, "dem", None)
    if dem_cfg is None:
        return None
    for src in getattr(dem_cfg, "sources", []):
        if getattr(src, "source", "") in _API_SOURCES:
            return src.source
    return None
