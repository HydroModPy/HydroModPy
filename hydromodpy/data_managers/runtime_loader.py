"""Runtime data loading orchestrator driven by a resolved data plan.

This module centralizes launcher data-phase loading logic so that the launcher
stays focused on orchestration order.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from hydromodpy.data_managers.plan import DataLoadPlan
from hydromodpy.simulation.time import resolve_simulation_time_window_dates
from hydromodpy.simulation.workspace.path_registry import WorkspacePathRegistry

if TYPE_CHECKING:
    from hydromodpy.simulation.state.run_state import LauncherRunState


class DataManagersRuntimeLoader:
    """Load runtime data objects from a resolved data-manager activation plan."""

    _LEGACY_STATION_EXPORT_DEFAULTS: dict[str, str] = {
        "hydrometry": "hydromodpy/data_managers/hydrometry/exports",
        "piezometry": "hydromodpy/data_managers/piezometry/exports",
    }

    def __init__(self, *, config_path: str | Path, data_plan: DataLoadPlan) -> None:
        self.config_path = Path(config_path).resolve()
        self.data_plan = data_plan

    def load_all(self, result: "LauncherRunState") -> None:
        """Load active data-manager families into ``result``."""
        workspace_paths = self._workspace_paths(result)

        active_types = tuple(self.data_plan.types)
        for type_name in active_types:
            if type_name == "geology":
                self._load_geology_data(result)
                continue
            if type_name == "oceanic":
                self._load_oceanic_data(result)
                continue
            if type_name == "hydrography":
                self._load_hydrography_data(result)
                continue
            if type_name == "intermittency":
                self._load_intermittency_data(result)
                continue
            if type_name == "hydrometry":
                self._load_hydrometry_data(result)
                continue
            if type_name == "piezometry":
                self._load_piezometry_data(result)
                continue
            if type_name == "recharge":
                self._load_recharge_data(result)
                continue
            if type_name == "runoff":
                self._load_runoff_data(result)
                continue
            if type_name == "precipitation":
                self._load_climatic_variable(result, "precipitation")
                continue
            if type_name == "etp":
                self._load_climatic_variable(result, "etp")
                continue
            if type_name == "temperature":
                self._load_climatic_variable(result, "temperature")
                continue
            if type_name == "wind":
                self._load_climatic_variable(result, "wind")
                continue
            if type_name == "humidity":
                self._load_climatic_variable(result, "humidity")
                continue
            if type_name == "radiation":
                self._load_climatic_variable(result, "radiation")
                continue
            if type_name == "soil_moisture":
                self._load_climatic_variable(result, "soil_moisture")
                continue
            print(f"[DataManagersPlanner] Warning: unsupported data type '{type_name}' in plan.")

    def _load_geology_data(self, result: "LauncherRunState") -> None:
        """Load geology support as a standalone data object."""
        from hydromodpy.data_managers.geology.geology_field import GeologyField

        geology_cfg = result.cfg.data.geology
        if geology_cfg is None:
            self._handle_missing_data_section(
                result,
                "geology",
                "missing [data.geology] section",
            )
            return

        raster_support = self._resolve_geology_raster_support(result)
        if raster_support is None:
            self._handle_data_loading_error(
                result,
                "geology",
                ValueError("domain/geographic surface raster support is not available"),
            )
            return

        try:
            result.loaded_data.geology = GeologyField.from_watershed_config(
                geology_cfg,
                raster_support=raster_support,
            )
        except Exception as exc:
            self._handle_data_loading_error(result, "geology", exc)

    @staticmethod
    def _resolve_geology_raster_support(result: "LauncherRunState") -> Any:
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

    def _load_oceanic_data(self, result: "LauncherRunState") -> None:
        """Load oceanic data from ``data.oceanic`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data_managers.variables.oceanic.config import OceanicConfig
        from hydromodpy.data_managers.variables.oceanic.manager import OceanicManager

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
                period = (dt.fromisoformat(oceanic_cfg.date_start), dt.fromisoformat(oceanic_cfg.date_end))
            for src in oceanic_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = OceanicManager(
                config=oceanic_cfg,
                catalog=None,
                project_period=period,
                project_extent=None,
                geographic=result.setup.geographic,
            )
            result.loaded_data.oceanic = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "oceanic", exc)

    def _load_hydrography_data(self, result: "LauncherRunState") -> None:
        """Load hydrography support datasets based on ``data.hydrography`` payload."""
        from hydromodpy.data_managers.hydrography import Hydrography

        workspace_paths = self._workspace_paths(result)
        section = self._get_data_section(result, "hydrography")
        if section is None:
            self._handle_missing_data_section(
                result,
                "hydrography",
                "missing [data.hydrography] section",
            )
            return

        types_obs = self._as_string_list(section.get("types_obs"))
        fields_obs = self._as_string_list(section.get("fields_obs"))
        if not types_obs or not fields_obs:
            self._handle_missing_data_section(
                result,
                "hydrography",
                "data.hydrography requires non-empty 'types_obs' and 'fields_obs'",
            )
            return
        if len(types_obs) != len(fields_obs):
            self._handle_missing_data_section(
                result,
                "hydrography",
                "data.hydrography 'types_obs' and 'fields_obs' must have same length",
            )
            return

        hydro_path = self._resolve_manager_input_path(
            section=section,
            keys=("hydro_path",),
            default_root=workspace_paths.data_path,
        )
        streams_file = section.get("streams_file")
        if isinstance(streams_file, str) and streams_file.strip():
            streams_file = str(self._resolve_path_like(streams_file))
        try:
            result.loaded_data.hydrography = Hydrography(
                out_path=workspace_paths.catch_folder,
                types_obs=types_obs,
                fields_obs=fields_obs,
                geographic=result.setup.geographic,
                hydro_path=hydro_path,
                streams_file=streams_file,
            )
        except Exception as exc:
            self._handle_data_loading_error(result, "hydrography", exc)

    def _load_intermittency_data(self, result: "LauncherRunState") -> None:
        """Load ONDE-style intermittency observations."""
        from hydromodpy.data_managers.intermittency import Intermittency

        workspace_paths = self._workspace_paths(result)
        section = self._get_data_section(result, "intermittency")
        if section is None:
            self._handle_missing_data_section(
                result,
                "intermittency",
                "missing [data.intermittency] section",
            )
            return

        intermittency_path = self._resolve_manager_input_path(
            section=section,
            keys=("intermittency_path", "path"),
            default_root=workspace_paths.data_path,
        )
        file_name = str(section.get("file_name", "regional onde stations.shp")).strip()
        if not file_name:
            self._handle_missing_data_section(
                result,
                "intermittency",
                "data.intermittency requires non-empty 'file_name'",
            )
            return
        try:
            result.loaded_data.intermittency = Intermittency(
                out_path=workspace_paths.catch_folder,
                intermittency_path=intermittency_path,
                file_name=file_name,
                geographic=result.setup.geographic,
            )
        except Exception as exc:
            self._handle_data_loading_error(result, "intermittency", exc)

    def _load_hydrometry_data(self, result: "LauncherRunState") -> None:
        """Load hydrometry records from ``data.hydrometry`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data_managers.variables.hydrometry.config import HydrometryConfig
        from hydromodpy.data_managers.variables.hydrometry.manager import HydrometryManager

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
                period = (dt.fromisoformat(hydro_cfg.date_start), dt.fromisoformat(hydro_cfg.date_end))
            for src in hydro_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = HydrometryManager(
                config=hydro_cfg,
                catalog=None,
                project_period=period,
                project_extent=None,
            )
            result.loaded_data.hydrometry = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "hydrometry", exc)

    def _load_piezometry_data(self, result: "LauncherRunState") -> None:
        """Load piezometry records from ``data.piezometry`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data_managers.variables.piezometry.config import PiezometryConfig
        from hydromodpy.data_managers.variables.piezometry.manager import PiezometryManager

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
                period = (dt.fromisoformat(piezo_cfg.date_start), dt.fromisoformat(piezo_cfg.date_end))
            for src in piezo_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = PiezometryManager(
                config=piezo_cfg,
                catalog=None,
                project_period=period,
                project_extent=None,
            )
            result.loaded_data.piezometry = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "piezometry", exc)

    def _load_recharge_data(self, result: "LauncherRunState") -> None:
        """Load recharge data from ``data.recharge`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data_managers.variables.recharge.config import RechargeConfig
        from hydromodpy.data_managers.variables.recharge.manager import RechargeManager

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
                period = (dt.fromisoformat(recharge_cfg.date_start), dt.fromisoformat(recharge_cfg.date_end))
            for src in recharge_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = RechargeManager(
                config=recharge_cfg,
                catalog=None,
                project_period=period,
                project_extent=None,
            )
            result.loaded_data.recharge = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "recharge", exc)

    def _load_runoff_data(self, result: "LauncherRunState") -> None:
        """Load runoff data from ``data.runoff`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data_managers.variables.runoff.config import RunoffConfig
        from hydromodpy.data_managers.variables.runoff.manager import RunoffManager

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
                period = (dt.fromisoformat(runoff_cfg.date_start), dt.fromisoformat(runoff_cfg.date_end))
            for src in runoff_cfg.sources:
                if not src.mask_path and result.setup.geographic is not None:
                    src.mask_path = Path(result.setup.geographic.watershed_shp)
            manager = RunoffManager(
                config=runoff_cfg,
                catalog=None,
                project_period=period,
                project_extent=None,
            )
            result.loaded_data.runoff = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "runoff", exc)

    # -- Registry of climatic variable managers & configs -----------------
    # Used by _load_climatic_variable() to avoid 7 identical methods.
    _CLIMATIC_REGISTRY: dict[str, tuple[str, str]] = {
        "precipitation": (
            "hydromodpy.data_managers.variables.precipitation.config",
            "hydromodpy.data_managers.variables.precipitation.manager",
        ),
        "etp": (
            "hydromodpy.data_managers.variables.etp.config",
            "hydromodpy.data_managers.variables.etp.manager",
        ),
        "temperature": (
            "hydromodpy.data_managers.variables.temperature.config",
            "hydromodpy.data_managers.variables.temperature.manager",
        ),
        "wind": (
            "hydromodpy.data_managers.variables.wind.config",
            "hydromodpy.data_managers.variables.wind.manager",
        ),
        "humidity": (
            "hydromodpy.data_managers.variables.humidity.config",
            "hydromodpy.data_managers.variables.humidity.manager",
        ),
        "radiation": (
            "hydromodpy.data_managers.variables.radiation.config",
            "hydromodpy.data_managers.variables.radiation.manager",
        ),
        "soil_moisture": (
            "hydromodpy.data_managers.variables.soil_moisture.config",
            "hydromodpy.data_managers.variables.soil_moisture.manager",
        ),
    }

    def _load_climatic_variable(
        self, result: "LauncherRunState", variable: str,
    ) -> None:
        """Generic loader for climatic variables (precipitation, etp, etc.).

        All 7 variables follow the same pattern: config with sources +
        date_start/date_end, manager extending BaseFieldManager.
        """
        import importlib
        from datetime import datetime as dt

        entry = self._CLIMATIC_REGISTRY.get(variable)
        if entry is None:
            print(f"[DataManagersPlanner] Warning: unknown climatic variable '{variable}'.")
            return

        config_module_path, manager_module_path = entry

        raw_section = self._get_data_section(result, variable)
        if raw_section is None:
            self._handle_missing_data_section(
                result, variable, f"missing [data.{variable}] section",
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
                catalog=None,
                project_period=period,
                project_extent=None,
            )
            setattr(result.loaded_data, variable, manager.load())
        except Exception as exc:
            self._handle_data_loading_error(result, variable, exc)

    def _handle_missing_data_section(
        self,
        result: "LauncherRunState",
        type_name: str,
        detail: str,
    ) -> None:
        message = f"Data manager '{type_name}' is active but {detail}."
        if self._is_required_data_type(result, type_name):
            raise ValueError(message)
        print(f"[DataManagersPlanner] Warning: {message}")

    def _handle_data_loading_error(
        self,
        result: "LauncherRunState",
        type_name: str,
        exc: Exception,
    ) -> None:
        message = f"Failed to load data manager '{type_name}': {exc}"
        if self._is_required_data_type(result, type_name):
            raise ValueError(message) from exc
        print(f"[DataManagersPlanner] Warning: {message}")

    def _is_required_data_type(self, result: "LauncherRunState", type_name: str) -> bool:
        inferred_set = set(self.data_plan.inferred_types)
        if type_name in inferred_set and result.cfg.data.inference_mode == "warn":
            return False
        return True

    @staticmethod
    def _get_data_section(
        result: "LauncherRunState",
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
        result: "LauncherRunState",
    ) -> tuple[str, str] | None:
        return resolve_simulation_time_window_dates(result.cfg)

    def _require_simulation_time_window_dates(
        self,
        result: "LauncherRunState",
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
            raise ValueError(
                f"{option_name}=true requires a valid [simulation.time] section."
            )
        return simulation_dates

    def _apply_simulation_window_dates(
        self,
        section: dict[str, Any],
        result: "LauncherRunState",
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
        result: "LauncherRunState",
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

    def _workspace_paths(self, result: "LauncherRunState") -> WorkspacePathRegistry:
        workspace = result.setup.workspace
        if workspace is None:
            raise ValueError("Launcher setup.workspace is required before data loading.")
        if hasattr(workspace, "paths"):
            return workspace.paths
        return WorkspacePathRegistry(
            catch_name=str(getattr(workspace, "catch_name", result.cfg.workspace.catch_name)),
            out_dir_path=Path(getattr(workspace, "out_dir_path", result.cfg.workspace.out_dir_path)),
            data_path=Path(result.cfg.workspace.data_path),
        )

    def _resolve_manager_input_path(
        self,
        *,
        section: Mapping[str, Any] | None,
        keys: tuple[str, ...],
        default_root: Path,
    ) -> Path:
        """Resolve one manager input path with section-override precedence."""
        if section is not None:
            for key in keys:
                raw_value = section.get(key)
                if isinstance(raw_value, str) and raw_value.strip():
                    return self._resolve_path_like(raw_value)
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

