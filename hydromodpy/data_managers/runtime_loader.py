"""Runtime data loading orchestrator driven by a resolved data plan.

This module centralizes launcher data-phase loading logic so that the launcher
stays focused on orchestration order and hook execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.data_managers.plan import DataLoadPlan
from hydromodpy.data_managers.oceanic import Oceanic
from hydromodpy.watershed.climatic import Climatic

if TYPE_CHECKING:
    from launchers.run_result import RunResult


class DataManagersRuntimeLoader:
    """Load runtime data objects from a resolved data-manager activation plan."""

    def __init__(self, *, config_path: str | Path, data_plan: DataLoadPlan) -> None:
        self.config_path = Path(config_path).resolve()
        self.data_plan = data_plan

    def load_all(self, result: "RunResult") -> None:
        """Load active data-manager families into ``result``."""
        ws = result.setup.workspace
        result.data.climatic = Climatic(out_path=ws.catch_folder)

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

    def _load_geology_data(self, result: "RunResult") -> None:
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

        raster_support = result.setup.domain.surface_topo.support
        if raster_support is None:
            self._handle_data_loading_error(
                result,
                "geology",
                ValueError("domain surface raster support is not available"),
            )
            return

        try:
            result.data.geology = GeologyField.from_watershed_config(
                geology_cfg,
                raster_support=raster_support,
            )
        except Exception as exc:
            self._handle_data_loading_error(result, "geology", exc)

    def _load_oceanic_data(self, result: "RunResult") -> None:
        """Load oceanic data and optional mean sea-level boundary value."""
        cfg = result.cfg
        section = self._get_data_section(
            result,
            "oceanic",
            legacy_keys=("oceanic",),
        )
        oceanic_path = cfg.workspace.data_path
        if section is not None and section.get("oceanic_path") is not None:
            oceanic_path = self._resolve_path_like(section["oceanic_path"])
        try:
            oceanic = Oceanic()
            oceanic.extract_local_data(
                out_path=result.setup.workspace.catch_folder,
                geographic=result.setup.geographic,
                oceanic_path=oceanic_path,
            )
            oceanic.update_MSL(oceanic.fetch_msl_or_default(result.setup.geographic))
            result.data.oceanic = oceanic
        except Exception as exc:
            self._handle_data_loading_error(result, "oceanic", exc)

    def _load_hydrography_data(self, result: "RunResult") -> None:
        """Load hydrography support datasets based on ``data.hydrography`` payload."""
        from hydromodpy.watershed import Hydrography

        cfg = result.cfg
        section = self._get_data_section(
            result,
            "hydrography",
            legacy_keys=("hydrography",),
        )
        if section is None:
            self._handle_missing_data_section(
                result,
                "hydrography",
                "missing [data.hydrography] (or legacy [hydrography]) section",
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

        hydro_path = self._resolve_path_like(
            section.get("hydro_path", cfg.workspace.data_path)
        )
        streams_file = section.get("streams_file")
        if isinstance(streams_file, str) and streams_file.strip():
            streams_file = str(self._resolve_path_like(streams_file))
        try:
            result.data.hydrography = Hydrography(
                out_path=result.setup.workspace.catch_folder,
                types_obs=types_obs,
                fields_obs=fields_obs,
                geographic=result.setup.geographic,
                hydro_path=hydro_path,
                streams_file=streams_file,
            )
        except Exception as exc:
            self._handle_data_loading_error(result, "hydrography", exc)

    def _load_intermittency_data(self, result: "RunResult") -> None:
        """Load ONDE-style intermittency observations."""
        from hydromodpy.watershed import Intermittency

        cfg = result.cfg
        section = self._get_data_section(
            result,
            "intermittency",
            legacy_keys=("intermittency",),
        )
        if section is None:
            self._handle_missing_data_section(
                result,
                "intermittency",
                "missing [data.intermittency] (or legacy [intermittency]) section",
            )
            return

        intermittency_path = self._resolve_path_like(
            section.get("intermittency_path", section.get("path", cfg.workspace.data_path))
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
            result.data.intermittency = Intermittency(
                out_path=result.setup.workspace.catch_folder,
                intermittency_path=intermittency_path,
                file_name=file_name,
                geographic=result.setup.geographic,
            )
        except Exception as exc:
            self._handle_data_loading_error(result, "intermittency", exc)

    def _load_hydrometry_data(self, result: "RunResult") -> None:
        """Load hydrometry station sets from data section or legacy custom section."""
        from hydromodpy.data_managers.hydrometry.hydrometry_config import (
            validate_hydrometry_config_data,
        )
        from hydromodpy.data_managers.hydrometry.station_set import StationSet

        raw_section = self._get_data_section(
            result,
            "hydrometry",
            legacy_keys=("hydrometry_stations",),
        )
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "hydrometry",
                "missing [data.hydrometry] and legacy [hydrometry_stations] sections",
            )
            return

        payload = self._normalize_station_set_section(raw_section, root_key="hydrometry")
        if str(payload["selection"].get("mode", "mask")).strip().lower() == "mask":
            payload["selection"]["mask_path"] = str(result.setup.geographic.watershed_shp)

        try:
            payload = validate_hydrometry_config_data(payload)
            self._resolve_station_set_paths(payload)
            result.data.hydrometry = StationSet.from_config(payload)
        except Exception as exc:
            self._handle_data_loading_error(result, "hydrometry", exc)

    def _load_piezometry_data(self, result: "RunResult") -> None:
        """Load piezometry station sets from data section or legacy custom section."""
        from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet
        from hydromodpy.data_managers.piezometry.piezometry_config import (
            validate_piezometry_config_data,
        )

        raw_section = self._get_data_section(
            result,
            "piezometry",
            legacy_keys=("piezometry_stations",),
        )
        if raw_section is None:
            self._handle_missing_data_section(
                result,
                "piezometry",
                "missing [data.piezometry] and legacy [piezometry_stations] sections",
            )
            return

        payload = self._normalize_station_set_section(raw_section, root_key="piezometry")
        if str(payload["selection"].get("mode", "mask")).strip().lower() == "mask":
            payload["selection"]["mask_path"] = str(result.setup.geographic.watershed_shp)

        try:
            payload = validate_piezometry_config_data(payload)
            self._resolve_station_set_paths(payload)
            result.data.piezometry = PiezometerSet.from_config(payload)
        except Exception as exc:
            self._handle_data_loading_error(result, "piezometry", exc)

    def _handle_missing_data_section(
        self,
        result: "RunResult",
        type_name: str,
        detail: str,
    ) -> None:
        message = f"Data manager '{type_name}' is active but {detail}."
        if self._is_required_data_type(result, type_name):
            raise ValueError(message)
        print(f"[DataManagersPlanner] Warning: {message}")

    def _handle_data_loading_error(
        self,
        result: "RunResult",
        type_name: str,
        exc: Exception,
    ) -> None:
        message = f"Failed to load data manager '{type_name}': {exc}"
        if self._is_required_data_type(result, type_name):
            raise ValueError(message) from exc
        print(f"[DataManagersPlanner] Warning: {message}")

    def _is_required_data_type(self, result: "RunResult", type_name: str) -> bool:
        inferred_set = set(self.data_plan.inferred_types)
        if type_name in inferred_set and result.cfg.data.inference_mode == "warn":
            return False
        return True

    @staticmethod
    def _get_data_section(
        result: "RunResult",
        type_name: str,
        *,
        legacy_keys: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        section_value = getattr(result.cfg.data, type_name, None)
        if isinstance(section_value, Mapping):
            return dict(section_value)
        for key in legacy_keys:
            legacy_value = result.raw_toml.get(key)
            if isinstance(legacy_value, Mapping):
                return dict(legacy_value)
        return None

    def _resolve_path_like(self, value: Any) -> Path:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = (self.config_path.parent / path).resolve()
        return path

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

    @staticmethod
    def _normalize_station_set_section(
        section: Mapping[str, Any],
        *,
        root_key: str,
    ) -> dict[str, Any]:
        if root_key in section and isinstance(section[root_key], Mapping):
            return {
                root_key: dict(section.get(root_key, {})),
                "source": dict(section.get("source", {})),
                "selection": dict(section.get("selection", {})),
                "output": dict(section.get("output", {})),
            }
        return {
            root_key: {
                key: value
                for key, value in section.items()
                if key not in {"source", "selection", "output"}
            },
            "source": dict(section.get("source", {})),
            "selection": dict(section.get("selection", {})),
            "output": dict(section.get("output", {})),
        }

    def _resolve_station_set_paths(self, payload: dict[str, Any]) -> None:
        source_cfg = payload.get("source", {})
        selection_cfg = payload.get("selection", {})
        output_cfg = payload.get("output", {})

        local_data_dir = source_cfg.get("local_data_dir")
        if isinstance(local_data_dir, str) and local_data_dir.strip():
            source_cfg["local_data_dir"] = str(self._resolve_path_like(local_data_dir))

        mask_path = selection_cfg.get("mask_path")
        if isinstance(mask_path, str) and mask_path.strip():
            selection_cfg["mask_path"] = str(self._resolve_path_like(mask_path))

        output_path = output_cfg.get("path")
        if isinstance(output_path, str) and output_path.strip():
            output_cfg["path"] = str(self._resolve_path_like(output_path))
