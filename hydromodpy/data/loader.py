"""Runtime data loading orchestrator driven by a resolved data plan.

This module centralizes launcher data-phase loading logic so that the launcher
stays focused on orchestration order. It exposes :class:`DataManagersRuntimeLoader`
for stateful orchestration and :func:`load_variable` as a thin pure helper for
per-variable dispatch.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from datetime import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from hydromodpy.core.logging import get_logger
from hydromodpy.core.time import resolve_simulation_time_window_dates
from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR, WorkspacePathRegistry
from hydromodpy.data._dispatch import VARIABLE_SPECS, VariableSpec
from hydromodpy.data.common.progress import data_phase
from hydromodpy.data.plan import DataLoadPlan
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext


logger = get_logger(__name__)


class DataManagersRuntimeLoader:
    """Load data products for the resolved active manager families.

    The loader owns the shared DuckDB data catalog, resolves each configured
    variable section, applies the simulation time window when relevant, and
    stores loaded products on the workflow context.
    """

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

    @classmethod
    def known_variables(cls) -> set[str]:
        """Return every variable name the loader can dispatch."""
        return set(VARIABLE_SPECS)

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
            spec = VARIABLE_SPECS.get(type_name)
            if spec is not None and spec.loader_method is not None:
                sequential.append(type_name)
            else:
                parallel.append(type_name)

        # Phase 1: sequential types (dependency order preserved).
        for type_name in sequential:
            self._load_single(result, type_name)

        # Phase 2: independent types. The shared DuckDB catalog connection
        # is not thread-safe (single internal cursor); concurrent loaders
        # corrupt one another's result sets, e.g. dropping the runoff
        # series mid-fetch with "Invalid Input Error: No open result set".
        # Loading the rest sequentially is the simplest correct fix and
        # the speed cost is negligible (only a handful of data managers
        # per project, each < 1 s).
        for type_name in parallel:
            try:
                self._load_single(result, type_name)
            except Exception as exc:
                logger.error("Load of '%s' failed: %s", type_name, exc)

    def _load_single(self, result: WorkflowContext, type_name: str) -> None:
        """Load a single data-manager type."""
        spec = VARIABLE_SPECS.get(type_name)
        if spec is None:
            logger.warning("Unsupported data type '%s' in plan.", type_name)
            return
        with data_phase(type_name):
            if spec.loader_method is not None:
                getattr(self, spec.loader_method)(result)
            else:
                self._load_generic_variable(result, type_name)

    def _load_generic_variable(self, result: WorkflowContext, variable: str) -> None:
        """Generic load path for variables following the standard shape.

        Every spec in :data:`VARIABLE_SPECS` whose ``loader_method`` is
        ``None`` follows this flow:

        1. Fetch the ``[data.<variable>]`` section, bail out if absent.
        2. Apply the simulation time window (unless the spec opts out).
        3. Validate the config, resolve period/masks.
        4. Instantiate the manager and stash the result on ``loaded_data``.
        5. Run an optional post-load export hook (intermittency).
        """
        spec = VARIABLE_SPECS[variable]

        raw_section = self._get_data_section(result, variable)
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                variable,
                f"missing [data.{variable}] section",
            )
            return

        if spec.apply_simulation_window:
            self._apply_simulation_window_dates(raw_section, result, variable)

        try:
            config_cls = getattr(
                importlib.import_module(spec.config_module),
                spec.config_class,
            )
            manager_cls = getattr(
                importlib.import_module(spec.manager_module),
                spec.manager_class,
            )

            cfg = config_cls.model_validate(raw_section)
            period = self._resolve_period_for_spec(cfg, spec, result)
            self._apply_default_masks(cfg, result)

            manager_kwargs = {
                "config": cfg,
                "catalog": self._catalog,
                "project_period": period,
                "project_extent": None,
                "data_dir": self._data_dir(variable),
            }
            if variable == "oceanic":
                manager_kwargs["geographic"] = result.setup.geographic

            manager = manager_cls(
                **manager_kwargs,
            )
            load_result = manager.load()
            setattr(result.loaded_data, variable, load_result)

            if spec.export_stable_subdir:
                workspace_paths = self._workspace_paths(result)
                stable_dir = (
                    workspace_paths.project_root / PREPROCESSING_DIR / spec.export_stable_subdir
                )
                manager.export(load_result, stable_dir)
        except Exception as exc:
            self._handle_data_loading_error(result, variable, exc)

    @staticmethod
    def _apply_default_masks(cfg: Any, result: WorkflowContext) -> None:
        geographic = result.setup.geographic
        if geographic is None:
            return
        for src in getattr(cfg, "sources", ()):
            if not getattr(src, "mask_path", None):
                src.mask_path = Path(geographic.watershed_shp)

    def _resolve_period_for_spec(
        self,
        cfg: Any,
        spec: VariableSpec,
        result: WorkflowContext,
    ) -> tuple[dt, dt] | None:
        if spec.period_source == "simulation_or_overview":
            period = self._resolve_simulation_time_window_dates(result)
            if period is not None:
                start, end = period
                return (dt.fromisoformat(start), dt.fromisoformat(end))
            overview = getattr(result.cfg, "overview", None)
            if overview is not None:
                ds = getattr(overview, "date_start", None)
                de = getattr(overview, "date_end", None)
                if ds and de:
                    return (dt.fromisoformat(ds), dt.fromisoformat(de))
            return None
        date_start = getattr(cfg, "date_start", None)
        date_end = getattr(cfg, "date_end", None)
        if date_start and date_end:
            return (dt.fromisoformat(date_start), dt.fromisoformat(date_end))
        return None

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
            code_field = "CODE_LEG"
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
            cfg_dict["source"]["reference_raster_path"] = data_path
            cfg = validate_geology_config_data(cfg_dict)
            loaded = load_geology_encoded_grid_on_raster_support(
                cfg,
                raster_support=raster_support,
            )
        else:
            if source_kind == "vector":
                cfg_dict["source"]["reference_raster_path"] = data_path
            cfg = validate_geology_config_data(cfg_dict)
            loaded = load_geology_encoded_grid(cfg)

        field = GeologyField(
            identifier=str(geology_cfg.id),
            encoded_codes=loaded["encoded_codes"],
            encoded_to_zone=loaded["encoded_to_zone"],
            transform=loaded["transform"],
            crs=loaded["crs"],
            source_kind=str(loaded["source_kind"]),
            default_cell_samples_per_axis=int(geology_cfg.cell_samples_per_axis),
        )
        # Expose the cached source path so the overview report can re-open
        # the original vector file for map rendering. The overview panel
        # looks for one of `source_path`, `geol_file`, `vector_source`.
        field.source_path = data_path
        return field

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
                stable_folder=workspace_paths.project_root / PREPROCESSING_DIR,
            )
            result.loaded_data.hydrography = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "hydrography", exc)

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
    spec = VARIABLE_SPECS.get(variable_name)
    if spec is None:
        raise KeyError(f"Unknown variable: {variable_name!r}")

    plan = DataLoadPlan()
    loader = DataManagersRuntimeLoader(
        config_path=getattr(context, "config_path", Path(".")),
        data_plan=plan,
    )
    loader._catalog = catalog
    if spec.loader_method is not None:
        method = getattr(loader, spec.loader_method)
        return method(config=config, context=context)
    return loader._load_generic_variable(context, variable_name)
