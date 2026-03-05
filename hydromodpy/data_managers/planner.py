"""Resolve active data-manager types from explicit config plus inference rules.

Current inference scope (V3)
----------------------------
- ``domain.zone_ids`` containing ``geology`` -> activate ``geology``
- presence of ``[hydrometry_stations]`` in raw TOML -> activate ``hydrometry``
- ``flow.active_bc`` containing ``stream`` -> activate ``hydrography``
- ``flow.active_bc`` containing ``ocean`` -> activate ``oceanic``
- markers found in ``hooks.py`` -> activate corresponding manager families
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.data_managers.data_managers_config import DataManagersConfig
from hydromodpy.data_managers.plan import DataLoadPlan


class DataManagersPlanner:
    """Build a deterministic data-manager activation plan."""

    _HOOK_MARKERS_BY_TYPE: dict[str, tuple[str, ...]] = {
        "hydrography": ("hydrography(", "result.hydrography"),
        "intermittency": ("intermittency(", "result.intermittency"),
        "hydrometry": ("stationset", "result.hydrometry", "hydrometry_stations"),
        "oceanic": ("oceanic(", "result.oceanic"),
        "piezometry": ("piezometer", "result.piezometry"),
    }

    def build(
        self,
        config: DataManagersConfig,
        *,
        domain_zone_ids: Sequence[str] | None = None,
        raw_toml: Mapping[str, Any] | None = None,
        flow_active_bc: Sequence[str] | None = None,
        hook_python_path: str | Path | None = None,
    ) -> DataLoadPlan:
        """Resolve data-manager types from explicit and inferred declarations.

        Parameters
        ----------
        config:
            Validated declarative `data` config (`data.types`, nested sections).
        domain_zone_ids:
            Normalized `domain.zone_ids` list used for zone-driven inference.
        raw_toml:
            Raw untyped TOML dictionary used for custom-section inference
            (for example `[hydrometry_stations]`).
        flow_active_bc:
            Validated `flow.active_bc` list used for boundary-condition-driven
            inference (`stream`/`ocean`).
        hook_python_path:
            Optional path to ``hooks.py``. When provided and file exists, the
            planner scans text markers to infer hook-driven data families.
        """
        explicit_types = tuple(config.types)
        inferred_types: list[str] = []
        reasons_by_type: dict[str, list[str]] = {}

        # Never infer over explicitly declared types.
        explicit_set = set(explicit_types)
        if self._domain_requests_geology(domain_zone_ids) and "geology" not in explicit_set:
            self._add_inference(
                inferred_types,
                reasons_by_type,
                "geology",
                "inferred from domain.zone_ids containing 'geology'",
            )

        if self._has_hydrometry_section(raw_toml) and "hydrometry" not in explicit_set:
            self._add_inference(
                inferred_types,
                reasons_by_type,
                "hydrometry",
                "inferred from [hydrometry_stations] section in TOML",
            )

        active_bc = self._normalize_tokens(flow_active_bc)
        if "stream" in active_bc and "hydrography" not in explicit_set:
            self._add_inference(
                inferred_types,
                reasons_by_type,
                "hydrography",
                "inferred from flow.active_bc containing 'stream'",
            )
        if "ocean" in active_bc and "oceanic" not in explicit_set:
            self._add_inference(
                inferred_types,
                reasons_by_type,
                "oceanic",
                "inferred from flow.active_bc containing 'ocean'",
            )

        hook_reasons = self._infer_types_from_hook_file(hook_python_path)
        for type_name, reason in hook_reasons.items():
            if type_name in explicit_set:
                continue
            self._add_inference(
                inferred_types,
                reasons_by_type,
                type_name,
                reason,
            )

        if config.inference_mode == "strict":
            self._enforce_strict_mode(config, inferred_types)

        return DataLoadPlan(
            explicit_types=explicit_types,
            inferred_types=tuple(inferred_types),
            reasons_by_type={
                type_name: tuple(reasons)
                for type_name, reasons in reasons_by_type.items()
            },
        )

    @staticmethod
    def _domain_requests_geology(domain_zone_ids: Sequence[str] | None) -> bool:
        return "geology" in DataManagersPlanner._normalize_tokens(domain_zone_ids)

    @staticmethod
    def _has_hydrometry_section(raw_toml: Mapping[str, Any] | None) -> bool:
        if raw_toml is None:
            return False
        return "hydrometry_stations" in raw_toml

    @staticmethod
    def _normalize_tokens(values: Sequence[str] | None) -> set[str]:
        """Normalize string sequences to lower-cased token sets."""
        if values is None:
            return set()
        return {str(raw).strip().lower() for raw in values if str(raw).strip()}

    @classmethod
    def _infer_types_from_hook_file(
        cls,
        hook_python_path: str | Path | None,
    ) -> dict[str, str]:
        """Infer manager types by scanning textual markers in ``hooks.py``."""
        if hook_python_path is None:
            return {}
        hook_path = Path(hook_python_path)
        if not hook_path.exists() or not hook_path.is_file():
            return {}

        content = hook_path.read_text(encoding="utf-8", errors="ignore").lower()
        inferred: dict[str, str] = {}
        for type_name, markers in cls._HOOK_MARKERS_BY_TYPE.items():
            matching = [marker for marker in markers if marker in content]
            if not matching:
                continue
            inferred[type_name] = (
                "inferred from hooks.py markers: " + ", ".join(matching)
            )
        return inferred

    @staticmethod
    def _enforce_strict_mode(
        config: DataManagersConfig,
        inferred_types: Sequence[str],
    ) -> None:
        """Raise when strict mode requires explicit ``data.<type>`` sections."""
        missing_sections: list[str] = []
        for type_name in inferred_types:
            if type_name == "geology":
                # geology can be safely defaulted as a typed config section.
                continue
            if getattr(config, type_name, None) is None:
                missing_sections.append(type_name)
        if missing_sections:
            joined = ", ".join(missing_sections)
            raise ValueError(
                "data.inference_mode='strict' requires explicit data sections "
                f"for inferred types: {joined}."
            )

    @staticmethod
    def _add_inference(
        inferred_types: list[str],
        reasons_by_type: dict[str, list[str]],
        type_name: str,
        reason: str,
    ) -> None:
        if type_name not in inferred_types:
            inferred_types.append(type_name)
        reasons_by_type.setdefault(type_name, [])
        if reason not in reasons_by_type[type_name]:
            reasons_by_type[type_name].append(reason)
