"""Runtime data loading orchestrator driven by a resolved data plan.

This module centralizes launcher data-phase loading logic so that the launcher
stays focused on orchestration order. It exposes :class:`DataManagersRuntimeLoader`
for stateful orchestration and :func:`load_variable` as a thin pure helper for
per-variable dispatch.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from hydromodpy.core.logging import get_logger
from hydromodpy.core.time import resolve_simulation_time_window_dates
from hydromodpy.core.workspace.path_registry import LEGACY_STABLE_DIR, WorkspacePathRegistry
from hydromodpy.data.common.progress import data_phase
from hydromodpy.data.plan import DataLoadPlan
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext


logger = get_logger(__name__)


class DataManagersRuntimeLoader:
    """Load runtime data objects from a resolved data-manager activation plan."""

    _LEGACY_STATION_EXPORT_DEFAULTS: dict[str, str] = {
        "hydrometry": "hydromodpy/data/hydrometry/exports",
        "piezometry": "hydromodpy/data/piezometry/exports",
    }

    def __init__(self, *, config_path: str | Path, data_plan: DataLoadPlan) -> None:
        self.config_path = Path(config_path).resolve()
        self.data_plan = data_plan
        self._catalog: DataCatalogDuckDB | None = None
        self._cache_root: Path | None = None

    def _init_catalog(self, workspace_paths: WorkspacePathRegistry) -> None:
        """Lazily create the shared DataCatalogDuckDB backed by ``data/cache.duckdb``."""
        if self._catalog is not None:
            return
        self._cache_root = workspace_paths.data_dir
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._catalog = DataCatalogDuckDB(self._cache_root / "cache.duckdb")

    def _data_dir(self, variable: str) -> Path | None:
        """Return ``data_path/<variable>/`` for cache storage, or None."""
        if self._cache_root is None:
            return None
        d = self._cache_root / variable
        d.mkdir(parents=True, exist_ok=True)
        return d

    # Dispatch table: type_name -> loader method name (or "climatic" sentinel).
    _LOADER_DISPATCH: dict[str, str] = {
        "dem": "_load_dem_data",
        "geology": "_load_geology_data",
        "oceanic": "_load_oceanic_data",
        "hydrography": "_load_hydrography_data",
        "intermittency": "_load_intermittency_data",
        "hydrometry": "_load_hydrometry_data",
        "piezometry": "_load_piezometry_data",
        "water_quality": "_load_water_quality_data",
        "recharge": "_load_recharge_data",
        "runoff": "_load_runoff_data",
        "precipitation": "_climatic",
        "etp": "_climatic",
        "temperature": "_climatic",
        "wind": "_climatic",
        "humidity": "_climatic",
        "radiation": "_climatic",
        "soil_moisture": "_climatic",
    }

    # Types that must be loaded sequentially (have dependencies on earlier loads).
    _SEQUENTIAL_TYPES = {"dem", "geology", "hydrography"}

    def load_all(self, result: WorkflowContext) -> None:
        """Load active data-manager families into ``result``.

        Sequential types (dem, geology, hydrography) are loaded first in
        order. Remaining independent types (observation + climatic) are
        loaded in parallel via a thread pool.
        """
        workspace_paths = self._workspace_paths(result)
        self._init_catalog(workspace_paths)

        sequential = []
        parallel = []
        for type_name in self.data_plan.types:
            if type_name in self._SEQUENTIAL_TYPES:
                sequential.append(type_name)
            else:
                parallel.append(type_name)

        # Phase 1: sequential types (dependency order preserved)
        for type_name in sequential:
            self._load_single(result, type_name)

        # Phase 2: independent types in parallel
        if len(parallel) <= 1:
            for type_name in parallel:
                self._load_single(result, type_name)
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            errors: list[tuple[str, Exception]] = []
            with ThreadPoolExecutor(max_workers=min(4, len(parallel))) as pool:
                futures = {pool.submit(self._load_single, result, t): t for t in parallel}
                for future in as_completed(futures):
                    t = futures[future]
                    exc = future.exception()
                    if exc is not None:
                        errors.append((t, exc))

            for type_name, exc in errors:
                logger.error("Parallel load of '%s' failed: %s", type_name, exc)

    def _load_single(self, result: WorkflowContext, type_name: str) -> None:
        """Load a single data-manager type."""
        method_key = self._LOADER_DISPATCH.get(type_name)
        if method_key is None:
            logger.warning("Unsupported data type '%s' in plan.", type_name)
            return
        with data_phase(type_name):
            if method_key == "_climatic":
                self._load_climatic_variable(result, type_name)
            else:
                getattr(self, method_key)(result)

    def _load_dem_data(self, result: WorkflowContext) -> None:
        """Load DEM data via DemManager."""
        from hydromodpy.data.variables.dem.config import DemConfig
        from hydromodpy.data.variables.dem.manager import DemManager

        raw_section = self._get_data_section(result, "dem")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "dem",
                "missing [data.dem] section",
            )
            return

        try:
            dem_cfg = DemConfig.model_validate(raw_section)

            for src in dem_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)

            manager = DemManager(
                config=dem_cfg,
                catalog=self._catalog,
                project_extent=None,
                data_dir=self._data_dir("dem"),
                geographic=result.setup.geographic,
            )
            result.loaded_data.dem = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "dem", exc)

    def _load_geology_data(self, result: WorkflowContext) -> None:
        """Load geology data via GeologyManager, then build GeologyField."""
        from hydromodpy.data.variables.geology.config import GeologyConfig
        from hydromodpy.data.variables.geology.manager import GeologyManager

        raw_section = self._get_data_section(result, "geology")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "geology",
                "missing [data.geology] section",
            )
            return

        raster_support = self._resolve_geology_raster_support(result)

        try:
            geology_cfg = GeologyConfig.model_validate(raw_section)

            # Resolve mask from geographic if not set on sources
            for src in geology_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)

            manager = GeologyManager(
                config=geology_cfg,
                catalog=self._catalog,
                project_extent=None,
                data_dir=self._data_dir("geology"),
                geographic=result.setup.geographic,
            )
            load_result = manager.load()

            # Build GeologyField from loaded data
            if load_result.fields:
                field_record = load_result.fields[0]
                geology_field = self._build_geology_field_from_record(
                    field_record,
                    geology_cfg=geology_cfg,
                    raster_support=raster_support,
                )
                result.loaded_data.geology = geology_field
            else:
                self._handle_data_loading_error(
                    result,
                    "geology",
                    ValueError("GeologyManager returned no field records"),
                )
        except Exception as exc:
            self._handle_data_loading_error(result, "geology", exc)

    @staticmethod
    def _build_geology_field_from_record(
        field_record,
        *,
        geology_cfg,
        raster_support,
    ):
        """Build a GeologyField from a FieldRecord (GeoPackage or raster)."""
        from hydromodpy.data.variables.geology.config import (
            validate_geology_config_data,
        )
        from hydromodpy.data.variables.geology.io import (
            infer_source_kind,
            load_geology_encoded_grid,
            load_geology_encoded_grid_on_raster_support,
        )
        from hydromodpy.spatial.field.geology.geology_field import GeologyField

        data_path = field_record.data
        if isinstance(data_path, Path):
            data_path = str(data_path)
        else:
            data_path = str(data_path)

        # BRGM data always uses CODE_LEG; custom sources carry their own code_field.
        source_name = getattr(field_record, "source", "")
        if source_name in ("brgm_1m", "brgm_50k"):
            code_field = "CODE_LEG"
        else:
            # Find the matching source config to retrieve user-specified code_field.
            code_field = "CODE_LEG"  # safe fallback for GeoPackages from BRGM
            for src in getattr(geology_cfg, "sources", []):
                if getattr(src, "source", "") == "custom" and getattr(src, "code_field", None):
                    code_field = src.code_field
                    break
        source_kind = infer_source_kind(data_path)

        cfg_dict = {
            "id": str(geology_cfg.id),
            "source": {
                "path": data_path,
                "kind": source_kind,
                "code_field": code_field,
                "all_touched": False,
            },
            "cell_samples_per_axis": int(geology_cfg.cell_samples_per_axis),
        }

        if raster_support is not None and source_kind == "vector":
            # Add a dummy reference_raster_path for validation
            cfg_dict["source"]["reference_raster_path"] = data_path
            cfg = validate_geology_config_data(cfg_dict)
            loaded = load_geology_encoded_grid_on_raster_support(
                cfg,
                raster_support=raster_support,
            )
        else:
            if source_kind == "vector":
                # Vector without raster support - needs reference raster
                cfg_dict["source"]["reference_raster_path"] = data_path
            cfg = validate_geology_config_data(cfg_dict)
            loaded = load_geology_encoded_grid(cfg)

        return GeologyField(
            identifier=str(geology_cfg.id),
            encoded_codes=loaded["encoded_codes"],
            encoded_to_zone=loaded["encoded_to_zone"],
            transform=loaded["transform"],
            crs=loaded["crs"],
            source_kind=str(loaded["source_kind"]),
            default_cell_samples_per_axis=int(geology_cfg.cell_samples_per_axis),
        )

    @staticmethod
    def _resolve_geology_raster_support(result: WorkflowContext) -> Any:
        """Resolve raster support used by geology loading.

        Preferred source is ``setup.domain.surface_topo.support``. If no
        domain object was prepared, fallback to the geographic-derived surface.
        """
        domain = result.setup.domain
        if domain is not None and domain.surface_topo.support is not None:
            return domain.surface_topo.support

        geographic = result.setup.geographic
        if geographic is None:
            return None
        try:
            surface_topo = geographic.get_domain_surface_topo()
        except Exception:
            return None
        return surface_topo.support

    def _load_oceanic_data(self, result: WorkflowContext) -> None:
        """Load oceanic data from ``data.oceanic`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data.variables.oceanic.config import OceanicConfig
        from hydromodpy.data.variables.oceanic.manager import OceanicManager

        raw_section = self._get_data_section(result, "oceanic")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "oceanic",
                "missing [data.oceanic] section",
            )
            return

        self._apply_simulation_window_dates(raw_section, result, "oceanic")

        try:
            oceanic_cfg = OceanicConfig.model_validate(raw_section)
            period = None
            if oceanic_cfg.date_start and oceanic_cfg.date_end:
                period = (
                    dt.fromisoformat(oceanic_cfg.date_start),
                    dt.fromisoformat(oceanic_cfg.date_end),
                )
            for src in oceanic_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = OceanicManager(
                config=oceanic_cfg,
                catalog=self._catalog,
                project_period=period,
                project_extent=None,
                geographic=result.setup.geographic,
                data_dir=self._data_dir("oceanic"),
            )
            result.loaded_data.oceanic = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "oceanic", exc)

    def _load_hydrography_data(self, result: WorkflowContext) -> None:
        """Load hydrography support datasets based on ``data.hydrography`` payload."""
        from hydromodpy.data.variables.hydrography.config import HydrographyConfig
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        raw_section = self._get_data_section(result, "hydrography")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "hydrography",
                "missing [data.hydrography] section",
            )
            return

        try:
            hydro_cfg = HydrographyConfig.model_validate(raw_section)
            workspace_paths = self._workspace_paths(result)
            manager = HydrographyManager(
                config=hydro_cfg,
                geographic=result.setup.geographic,
                out_path=workspace_paths.project_root,
                catalog=self._catalog,
                data_dir=self._data_dir("hydrography"),
                stable_folder=workspace_paths.project_root / LEGACY_STABLE_DIR,
            )
            result.loaded_data.hydrography = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "hydrography", exc)

    def _load_intermittency_data(self, result: WorkflowContext) -> None:
        """Load ONDE-style intermittency observations via the variable manager."""
        from datetime import datetime as dt

        from hydromodpy.data.variables.intermittency.config import IntermittencyConfig
        from hydromodpy.data.variables.intermittency.manager import IntermittencyManager

        raw_section = self._get_data_section(result, "intermittency")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "intermittency",
                "missing [data.intermittency] section",
            )
            return

        self._apply_simulation_window_dates(raw_section, result, "intermittency")

        try:
            intermittency_cfg = IntermittencyConfig.model_validate(raw_section)
            period = None
            if intermittency_cfg.date_start and intermittency_cfg.date_end:
                period = (
                    dt.fromisoformat(intermittency_cfg.date_start),
                    dt.fromisoformat(intermittency_cfg.date_end),
                )
            for src in intermittency_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = IntermittencyManager(
                config=intermittency_cfg,
                catalog=self._catalog,
                project_period=period,
                project_extent=None,
                data_dir=self._data_dir("intermittency"),
            )
            load_result = manager.load()
            result.loaded_data.intermittency = load_result

            # Export to results_stable/intermittency/ (CSV chronicles).
            workspace_paths = self._workspace_paths(result)
            stable_dir = workspace_paths.project_root / LEGACY_STABLE_DIR / "intermittency"
            manager.export(load_result, stable_dir)
        except Exception as exc:
            self._handle_data_loading_error(result, "intermittency", exc)

    def _load_hydrometry_data(self, result: WorkflowContext) -> None:
        """Load hydrometry records from ``data.hydrometry`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
        from hydromodpy.data.variables.hydrometry.manager import HydrometryManager

        raw_section = self._get_data_section(result, "hydrometry")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "hydrometry",
                "missing [data.hydrometry] section",
            )
            return

        self._apply_simulation_window_dates(raw_section, result, "hydrometry")

        try:
            hydro_cfg = HydrometryConfig.model_validate(raw_section)
            period = None
            if hydro_cfg.date_start and hydro_cfg.date_end:
                period = (
                    dt.fromisoformat(hydro_cfg.date_start),
                    dt.fromisoformat(hydro_cfg.date_end),
                )
            for src in hydro_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = HydrometryManager(
                config=hydro_cfg,
                catalog=self._catalog,
                project_period=period,
                project_extent=None,
                data_dir=self._data_dir("hydrometry"),
            )
            result.loaded_data.hydrometry = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "hydrometry", exc)

    def _load_piezometry_data(self, result: WorkflowContext) -> None:
        """Load piezometry records from ``data.piezometry`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data.variables.piezometry.config import PiezometryConfig
        from hydromodpy.data.variables.piezometry.manager import PiezometryManager

        raw_section = self._get_data_section(result, "piezometry")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "piezometry",
                "missing [data.piezometry] section",
            )
            return

        self._apply_simulation_window_dates(raw_section, result, "piezometry")

        try:
            piezo_cfg = PiezometryConfig.model_validate(raw_section)
            period = None
            if piezo_cfg.date_start and piezo_cfg.date_end:
                period = (
                    dt.fromisoformat(piezo_cfg.date_start),
                    dt.fromisoformat(piezo_cfg.date_end),
                )
            for src in piezo_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = PiezometryManager(
                config=piezo_cfg,
                catalog=self._catalog,
                project_period=period,
                project_extent=None,
                data_dir=self._data_dir("piezometry"),
            )
            result.loaded_data.piezometry = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "piezometry", exc)

    def _load_water_quality_data(self, result: WorkflowContext) -> None:
        """Load water quality records from ``data.water_quality`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data.variables.water_quality.config import WaterQualityConfig
        from hydromodpy.data.variables.water_quality.manager import WaterQualityManager

        raw_section = self._get_data_section(result, "water_quality")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "water_quality",
                "missing [data.water_quality] section",
            )
            return

        try:
            wq_cfg = WaterQualityConfig.model_validate(raw_section)
            # WaterQualityConfig has no date fields - derive period from
            # simulation window or overview dates on the proxy.
            period = self._resolve_simulation_time_window_dates(result)
            if period is None:
                # Fallback: try overview dates (data-overview launcher).
                overview = getattr(result.cfg, "overview", None)
                if overview is not None:
                    ds = getattr(overview, "date_start", None)
                    de = getattr(overview, "date_end", None)
                    if ds and de:
                        period = (dt.fromisoformat(ds), dt.fromisoformat(de))
            for src in wq_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = WaterQualityManager(
                config=wq_cfg,
                catalog=self._catalog,
                project_period=period,
                project_extent=None,
                data_dir=self._data_dir("water_quality"),
            )
            result.loaded_data.water_quality = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "water_quality", exc)

    def _load_recharge_data(self, result: WorkflowContext) -> None:
        """Load recharge data from ``data.recharge`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data.variables.recharge.config import RechargeConfig
        from hydromodpy.data.variables.recharge.manager import RechargeManager

        raw_section = self._get_data_section(result, "recharge")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "recharge",
                "missing [data.recharge] section",
            )
            return

        self._apply_simulation_window_dates(raw_section, result, "recharge")

        try:
            recharge_cfg = RechargeConfig.model_validate(raw_section)
            period = None
            if recharge_cfg.date_start and recharge_cfg.date_end:
                period = (
                    dt.fromisoformat(recharge_cfg.date_start),
                    dt.fromisoformat(recharge_cfg.date_end),
                )
            for src in recharge_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = RechargeManager(
                config=recharge_cfg,
                catalog=self._catalog,
                project_period=period,
                project_extent=None,
                data_dir=self._data_dir("recharge"),
            )
            result.loaded_data.recharge = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "recharge", exc)

    def _load_runoff_data(self, result: WorkflowContext) -> None:
        """Load runoff data from ``data.runoff`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data.variables.runoff.config import RunoffConfig
        from hydromodpy.data.variables.runoff.manager import RunoffManager

        raw_section = self._get_data_section(result, "runoff")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "runoff",
                "missing [data.runoff] section",
            )
            return

        self._apply_simulation_window_dates(raw_section, result, "runoff")

        try:
            runoff_cfg = RunoffConfig.model_validate(raw_section)
            period = None
            if runoff_cfg.date_start and runoff_cfg.date_end:
                period = (
                    dt.fromisoformat(runoff_cfg.date_start),
                    dt.fromisoformat(runoff_cfg.date_end),
                )
            for src in runoff_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = RunoffManager(
                config=runoff_cfg,
                catalog=self._catalog,
                project_period=period,
                project_extent=None,
                data_dir=self._data_dir("runoff"),
            )
            result.loaded_data.runoff = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "runoff", exc)

    # -- Registry of climatic variable managers & configs -----------------
    # Used by _load_climatic_variable() to avoid 7 identical methods.
    _CLIMATIC_REGISTRY: dict[str, tuple[str, str]] = {
        "precipitation": (
            "hydromodpy.data.variables.precipitation.config",
            "hydromodpy.data.variables.precipitation.manager",
        ),
        "etp": (
            "hydromodpy.data.variables.etp.config",
            "hydromodpy.data.variables.etp.manager",
        ),
        "temperature": (
            "hydromodpy.data.variables.temperature.config",
            "hydromodpy.data.variables.temperature.manager",
        ),
        "wind": (
            "hydromodpy.data.variables.wind.config",
            "hydromodpy.data.variables.wind.manager",
        ),
        "humidity": (
            "hydromodpy.data.variables.humidity.config",
            "hydromodpy.data.variables.humidity.manager",
        ),
        "radiation": (
            "hydromodpy.data.variables.radiation.config",
            "hydromodpy.data.variables.radiation.manager",
        ),
        "soil_moisture": (
            "hydromodpy.data.variables.soil_moisture.config",
            "hydromodpy.data.variables.soil_moisture.manager",
        ),
    }

    def _load_climatic_variable(
        self,
        result: WorkflowContext,
        variable: str,
    ) -> None:
        """Generic loader for climatic variables (precipitation, etp, etc.).

        All 7 variables follow the same pattern: config with sources +
        date_start/date_end, manager extending BaseFieldManager.
        """
        import importlib
        from datetime import datetime as dt

        entry = self._CLIMATIC_REGISTRY.get(variable)
        if entry is None:
            logger.warning("Unknown climatic variable '%s'.", variable)
            return

        config_module_path, manager_module_path = entry

        raw_section = self._get_data_section(result, variable)
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                variable,
                f"missing [data.{variable}] section",
            )
            return

        self._apply_simulation_window_dates(raw_section, result, variable)

        try:
            # Dynamic import of config and manager classes
            config_mod = importlib.import_module(config_module_path)
            manager_mod = importlib.import_module(manager_module_path)

            # Config class is named {Variable}Config (e.g. PrecipitationConfig)
            config_cls_name = variable.title().replace("_", "") + "Config"
            config_cls = getattr(config_mod, config_cls_name)
            # Manager class is named {Variable}Manager
            manager_cls_name = variable.title().replace("_", "") + "Manager"
            manager_cls = getattr(manager_mod, manager_cls_name)

            cfg = config_cls.model_validate(raw_section)
            period = None
            if cfg.date_start and cfg.date_end:
                period = (dt.fromisoformat(cfg.date_start), dt.fromisoformat(cfg.date_end))

            for src in cfg.sources:
                if not getattr(src, "mask_path", None) and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)

            manager = manager_cls(
                config=cfg,
                catalog=self._catalog,
                project_period=period,
                project_extent=None,
                data_dir=self._data_dir(variable),
            )
            setattr(result.loaded_data, variable, manager.load())
        except Exception as exc:
            self._handle_data_loading_error(result, variable, exc)

    def _handle_missing_data_section(
        self,
        result: WorkflowContext,
        type_name: str,
        detail: str,
    ) -> None:
        message = f"Data manager '{type_name}' is active but {detail}."
        if self._is_required_data_type(result, type_name):
            raise ValueError(message)
        logger.warning("%s", message)

    def _handle_data_loading_error(
        self,
        result: WorkflowContext,
        type_name: str,
        exc: Exception,
    ) -> None:
        message = f"Failed to load data manager '{type_name}': {exc}"
        if self._is_required_data_type(result, type_name):
            raise ValueError(message) from exc
        logger.warning("%s", message)
        # Propagate warning to any existing LoadResult on the attribute
        existing = getattr(result.loaded_data, type_name, None)
        if existing is not None and hasattr(existing, "warnings"):
            existing.warnings.append(message)

    def _is_required_data_type(self, result: WorkflowContext, type_name: str) -> bool:
        inferred_set = set(self.data_plan.inferred_types)
        if type_name in inferred_set and result.cfg.data.inference_mode == "warn":
            return False
        return True

    @staticmethod
    def _get_data_section(
        result: WorkflowContext,
        type_name: str,
    ) -> dict[str, Any] | None:
        section_value = getattr(result.cfg.data, type_name, None)
        if isinstance(section_value, BaseModel):
            payload = section_value.model_dump(mode="python", exclude_none=True)
            if isinstance(payload, Mapping):
                return dict(payload)
        if isinstance(section_value, Mapping):
            return dict(section_value)
        return None

    @staticmethod
    def _resolve_simulation_time_window_dates(
        result: WorkflowContext,
    ) -> tuple[str, str] | None:
        return resolve_simulation_time_window_dates(result.cfg)

    def _require_simulation_time_window_dates(
        self,
        result: WorkflowContext,
        *,
        option_name: str,
    ) -> tuple[str, str]:
        try:
            simulation_dates = self._resolve_simulation_time_window_dates(result)
        except ValueError as exc:
            raise ValueError(
                f"{option_name}=true requires a valid [simulation.time] section."
            ) from exc
        if simulation_dates is None:
            raise ValueError(f"{option_name}=true requires a valid [simulation.time] section.")
        return simulation_dates

    def _apply_simulation_window_dates(
        self,
        section: dict[str, Any],
        result: WorkflowContext,
        manager_type: str,
    ) -> None:
        """Inject date_start/date_end from [simulation.time] when not explicit.

        In launcher mode, data managers benefit from an automatic date window
        derived from the simulation time config. This avoids requiring the
        user to repeat dates in both [simulation.time] and [data.<type>].
        """
        if section.get("date_start") and section.get("date_end"):
            return
        simulation_dates = self._resolve_simulation_time_window_dates(result)
        if simulation_dates is None:
            return
        date_start, date_end = simulation_dates
        if not section.get("date_start"):
            section["date_start"] = date_start
        if not section.get("date_end"):
            section["date_end"] = date_end

    @staticmethod
    def _coerce_optional_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            token = value.strip().lower()
            if token in {"1", "true", "yes", "on"}:
                return True
            if token in {"0", "false", "no", "off"}:
                return False
        return None

    def _apply_simulation_window_to_station_section(
        self,
        *,
        result: WorkflowContext,
        payload: dict[str, Any],
        root_key: str,
        manager_type: str,
    ) -> None:
        section_raw = payload.get(root_key)
        if not isinstance(section_raw, Mapping):
            return
        section = dict(section_raw)
        payload[root_key] = section

        use_window = self._coerce_optional_bool(section.get("use_simulation_time_window"))
        if use_window is None:
            use_window = False
        if not use_window:
            return

        date_start, date_end = self._require_simulation_time_window_dates(
            result,
            option_name=f"data.{manager_type}.use_simulation_time_window",
        )
        section["date_start"] = date_start
        section["date_end"] = date_end

    def _resolve_path_like(self, value: Any) -> Path:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = (self.config_path.parent / path).resolve()
        return path

    def _workspace_paths(self, result: WorkflowContext) -> WorkspacePathRegistry:
        workspace = result.setup.workspace
        if workspace is None:
            raise ValueError("Launcher setup.workspace is required before data loading.")
        if hasattr(workspace, "paths"):
            return workspace.paths
        return WorkspacePathRegistry.from_config(result.cfg.workspace)

    def _resolve_manager_input_path(
        self,
        *,
        section: Mapping[str, Any] | None,
        keys: tuple[str, ...],
        default_root: Path | None,
    ) -> Path | None:
        """Resolve one manager input path with section-override precedence."""
        if section is not None:
            for key in keys:
                raw_value = section.get(key)
                if isinstance(raw_value, str) and raw_value.strip():
                    return self._resolve_path_like(raw_value)
        if default_root is None:
            return None
        return Path(default_root)

    @staticmethod
    def _as_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, (list, tuple)):
            out: list[str] = []
            for raw in value:
                text = str(raw).strip()
                if text:
                    out.append(text)
            return out
        return []


def load_variable(
    variable_name: str,
    *,
    catalog: DataCatalogDuckDB,
    config: Any,
    context: Any,
) -> Any:
    """Pure dispatch helper: resolve and load a single variable.

    Thin wrapper around :class:`DataManagersRuntimeLoader` that keeps the
    per-variable call site free of stateful plumbing. Callers supply the
    catalog, the already-resolved config model, and a workflow context
    (for the time window / path registry); the helper returns whatever
    the underlying loader method yields (typically a ``LoadResult`` or
    variable-specific object).
    """
    method_name = DataManagersRuntimeLoader._LOADER_DISPATCH.get(variable_name)
    if method_name is None:
        raise KeyError(f"Unknown variable: {variable_name!r}")

    plan = DataLoadPlan()
    loader = DataManagersRuntimeLoader(
        config_path=getattr(context, "config_path", Path(".")),
        data_plan=plan,
    )
    loader._catalog = catalog
    method = getattr(loader, method_name)
    return method(config=config, context=context)
