"""Runtime data loading orchestrator driven by a resolved data plan.

This module centralizes launcher data-phase loading logic so that the launcher
stays focused on orchestration order.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from hydromodpy.data_managers.climatic import Climatic
from hydromodpy.data_managers.plan import DataLoadPlan
from hydromodpy.data_managers.oceanic import Oceanic
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
        result.loaded_data.climatic = Climatic(out_path=workspace_paths.catch_folder)

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
        """Load oceanic data and optional mean sea-level boundary value."""
        workspace_paths = self._workspace_paths(result)
        section = self._get_data_section(result, "oceanic")
        oceanic_path = self._resolve_manager_input_path(
            section=section,
            keys=("oceanic_path",),
            default_root=workspace_paths.data_path,
        )
        msl_source = "auto"
        msl_local_csv: str | None = None
        msl_start_date = "2003-01-01"
        msl_end_date = "2003-01-30"
        msl_default = 0.0
        msl_use_simulation_time_window = False

        if section is not None:
            raw_source = section.get("msl_source")
            if isinstance(raw_source, str) and raw_source.strip():
                msl_source = raw_source.strip().lower()

            raw_local_csv = section.get("msl_local_csv")
            if isinstance(raw_local_csv, str) and raw_local_csv.strip():
                msl_local_csv = str(self._resolve_path_like(raw_local_csv))

            raw_start_date = section.get("msl_start_date")
            if isinstance(raw_start_date, str) and raw_start_date.strip():
                msl_start_date = raw_start_date.strip()

            raw_end_date = section.get("msl_end_date")
            if isinstance(raw_end_date, str) and raw_end_date.strip():
                msl_end_date = raw_end_date.strip()

            raw_default = section.get("msl_default")
            if raw_default is not None:
                try:
                    msl_default = float(raw_default)
                except (TypeError, ValueError):
                    print(
                        "[DataManagersPlanner] Warning: invalid data.oceanic.msl_default="
                        f"{raw_default!r}, using 0.0"
                    )

            raw_use_simulation_time_window = section.get("msl_use_simulation_time_window")
            if isinstance(raw_use_simulation_time_window, bool):
                msl_use_simulation_time_window = raw_use_simulation_time_window
            elif isinstance(raw_use_simulation_time_window, str):
                token = raw_use_simulation_time_window.strip().lower()
                if token in {"1", "true", "yes", "on"}:
                    msl_use_simulation_time_window = True
                elif token in {"0", "false", "no", "off"}:
                    msl_use_simulation_time_window = False

        if msl_use_simulation_time_window:
            simulation_dates = self._resolve_simulation_time_window_dates(result)
            if simulation_dates is None:
                print(
                    "[DataManagersPlanner] Warning: data.oceanic."
                    "msl_use_simulation_time_window=true but [simulation.time] "
                    "is missing or invalid; using data.oceanic.msl_start_date/"
                    "msl_end_date."
                )
            else:
                msl_start_date, msl_end_date = simulation_dates

        try:
            oceanic = Oceanic()
            oceanic.extract_local_data(
                out_path=workspace_paths.catch_folder,
                geographic=result.setup.geographic,
                oceanic_path=oceanic_path,
            )
            oceanic.update_MSL(
                oceanic.fetch_msl_or_default(
                    result.setup.geographic,
                    start_date=msl_start_date,
                    end_date=msl_end_date,
                    default=msl_default,
                    source=msl_source,
                    local_csv_path=msl_local_csv,
                )
            )
            result.loaded_data.oceanic = oceanic
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

        from hydromodpy.data_managers.hydrometry.config import HydrometryConfig
        from hydromodpy.data_managers.hydrometry.manager import HydrometryManager

        raw_section = self._get_data_section(result, "hydrometry")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "hydrometry",
                "missing [data.hydrometry] section",
            )
            return

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
                project_period=period,
                project_extent=None,
            )
            result.loaded_data.hydrometry = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "hydrometry", exc)

    def _load_piezometry_data(self, result: "LauncherRunState") -> None:
        """Load piezometry records from ``data.piezometry`` payload."""
        from datetime import datetime as dt

        from hydromodpy.data_managers.piezometry.config import PiezometryConfig
        from hydromodpy.data_managers.piezometry.manager import PiezometryManager

        raw_section = self._get_data_section(result, "piezometry")
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "piezometry",
                "missing [data.piezometry] section",
            )
            return

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
                project_period=period,
                project_extent=None,
            )
            result.loaded_data.piezometry = manager.load()
        except Exception as exc:
            self._handle_data_loading_error(result, "piezometry", exc)

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
        return resolve_simulation_time_window_dates(result.cfg, strict=False)

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

