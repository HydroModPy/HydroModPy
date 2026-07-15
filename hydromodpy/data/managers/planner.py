"""Resolve active data-manager types from explicit config plus inference rules.

Current inference scope (V3)
----------------------------
- ``domain.zone_ids`` containing ``geology`` -> activate ``geology``
- ``flow.active_bc`` containing ``stream`` -> activate ``hydrography``
- ``flow.active_bc`` containing ``ocean`` -> activate ``oceanic``
- ``flow.active_bc`` containing ``lake``/``reservoir`` -> activate the lake
  families the model actually consumes (``lake_geometry``, ``lake_abacus``,
  ``lake_inflow``, ``lake_withdrawal``). Families without a consumer
  (``lake_bathymetry``, ``lake_levels``, ``lake_outflow``) are not auto-inferred
  so the catalog never accumulates data nothing reads; declare them explicitly if
  needed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hydromodpy.data.managers.config_schema import DataManagersConfig
from hydromodpy.data.managers.plan import DataLoadPlan


class DataPlanner:
    """Infer the active data-manager families for one run.

    The planner starts from ``DataManagersConfig.types`` and appends
    dependencies implied by domain supports or flow boundary conditions. The
    output is deterministic and carries human-readable reasons for inferred
    families.
    """

    def build(
        self,
        config: DataManagersConfig,
        *,
        domain_zone_ids: Sequence[str] | None = None,
        domain_support_provider_names: Sequence[str] | None = None,
        requested_spatial_support_ids: Sequence[str] | None = None,
        raw_toml: Mapping[str, Any] | None = None,
        flow_active_bc: Sequence[str] | None = None,
    ) -> DataLoadPlan:
        """Resolve data-manager types from explicit and inferred declarations.

        Parameters
        ----------
        config:
            Validated declarative `data` config (`data.types`, nested sections).
        domain_zone_ids:
            Normalized `domain.zone_ids` list used for zone-driven inference.
        domain_support_provider_names:
            Provider names declared in `domain.supports`, used to infer data
            dependencies from explicit support declarations.
        requested_spatial_support_ids:
            Spatial support ids actually referenced by heterogeneous parameters.
            When provided, geology is inferred only if at least one support is
            requested.
        raw_toml:
            Raw untyped TOML dictionary used for custom-section inference
            (for example custom hook payloads).
        flow_active_bc:
            Validated `flow.active_bc` list used for boundary-condition-driven
            inference (`stream`/`ocean`).
        """
        explicit_types = tuple(config.types)
        inferred_types: list[str] = []
        reasons_by_type: dict[str, list[str]] = {}

        # Never infer over explicitly declared types.
        explicit_set = set(explicit_types)
        requested_supports = self._normalize_tokens(requested_spatial_support_ids)
        support_required = requested_spatial_support_ids is None or bool(requested_supports)
        provider_names = self._normalize_tokens(domain_support_provider_names)

        if support_required and "geology" in provider_names and "geology" not in explicit_set:
            self._add_inference(
                inferred_types,
                reasons_by_type,
                "geology",
                "inferred from domain.supports provider='geology'",
            )
        elif (
            support_required
            and self._domain_requests_geology(domain_zone_ids)
            and "geology" not in explicit_set
        ):
            self._add_inference(
                inferred_types,
                reasons_by_type,
                "geology",
                "inferred from domain.zone_ids containing 'geology'",
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

        if active_bc & {"lake", "reservoir"}:
            lake_token = "lake" if "lake" in active_bc else "reservoir"
            # Only the families the model consumes: geometry + abacus build the LAK
            # package, inflow + withdrawal feed its forcings. bathymetry is consumed
            # only when a lake opts into bed_reconstruction, so it stays an explicit
            # [data.lake_bathymetry] declaration (not auto-inferred) to avoid
            # dead-loading when the flag is off; levels / outflow have no consumer yet.
            for lake_family in (
                "lake_geometry",
                "lake_abacus",
                "lake_inflow",
                "lake_withdrawal",
            ):
                if lake_family not in explicit_set:
                    self._add_inference(
                        inferred_types,
                        reasons_by_type,
                        lake_family,
                        f"inferred from flow.active_bc containing '{lake_token}'",
                    )

        if config.inference_mode == "strict":
            self._enforce_strict_mode(config, inferred_types)

        return DataLoadPlan(
            explicit_types=explicit_types,
            inferred_types=tuple(inferred_types),
            reasons_by_type={
                type_name: tuple(reasons) for type_name, reasons in reasons_by_type.items()
            },
        )

    @staticmethod
    def _domain_requests_geology(domain_zone_ids: Sequence[str] | None) -> bool:
        return "geology" in DataPlanner._normalize_tokens(domain_zone_ids)

    @staticmethod
    def _normalize_tokens(values: Sequence[str] | None) -> set[str]:
        """Normalize string sequences to lower-cased token sets."""
        if values is None:
            return set()
        return {str(raw).strip().lower() for raw in values if str(raw).strip()}

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
