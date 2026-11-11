"""The support providers, their registry and the contract of the supports a parameter asks for.

A provider builds a support field (``support_fields.py``), which gives the zone share of each
cell of a mesh. ``build_phase_supports`` builds the supports of a phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol

import numpy as np

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.model.domain.spatial_support_config import (
    CatchmentZonesSupportConfig,
    DomainSupportConfig,
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
    GeologySupportConfig,
)
from hydromodpy.model.domain.support_fields import (
    AliasedSpatialSupportField,
    GeneratedBandsSupportField,
    GeneratedRingsSupportField,
    RasterZonesSupportField,
)


@dataclass(slots=True)
class SupportBuildContext:
    """Runtime objects available when building domain spatial supports."""

    cfg: object
    raw_toml: dict[str, object]
    workspace: object | None
    geographic: object | None
    domain_geographic: object | None
    domain: object
    flow: object | None
    loaded_data: object | None
    time_grid: object | None
    geographic_features: object | None = None


class SpatialSupportProvider(Protocol):
    """Builder contract used by the launcher to materialize support fields."""

    provider_name: ClassVar[str]
    build_phase: ClassVar[Literal["setup", "data"]]

    def build(
        self,
        *,
        support_id: str,
        config: DomainSupportConfig,
        context: SupportBuildContext,
    ) -> object: ...


class GeneratedBandsSupportProvider:
    provider_name = "generated_bands"
    build_phase = "setup"

    def build(
        self,
        *,
        support_id: str,
        config: GeneratedBandsSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        surface_topo = getattr(context.domain, "surface_topo", None)
        support = getattr(surface_topo, "support", None)
        if not isinstance(support, RasterSupport):
            raise ValueError("Generated bands support requires domain.surface_topo.support")
        support.assert_complete_domain()

        if config.axis == "x":
            lower = float(support.xmin)
            upper = float(support.xmax)
        else:
            lower = float(support.ymin)
            upper = float(support.ymax)
        span = upper - lower
        if span <= 0.0:
            raise ValueError("Domain support extent must be strictly positive")

        if config.coordinate_mode == "relative":
            breaks_abs = [lower + float(value) * span for value in config.breaks]
        else:
            breaks_abs = [float(value) for value in config.breaks]

        if any(value <= lower or value >= upper for value in breaks_abs):
            axis_label = "x" if config.axis == "x" else "y"
            raise ValueError(
                f"Generated bands breaks must lie strictly inside the domain {axis_label} extent "
                f"({lower}, {upper})."
            )

        return GeneratedBandsSupportField(
            identifier=support_id,
            axis=config.axis,
            breaks_abs=breaks_abs,
            labels=list(config.labels),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class GeneratedRingsSupportProvider:
    provider_name = "generated_rings"
    build_phase = "setup"

    def build(
        self,
        *,
        support_id: str,
        config: GeneratedRingsSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        surface_topo = getattr(context.domain, "surface_topo", None)
        support = getattr(surface_topo, "support", None)
        if not isinstance(support, RasterSupport):
            raise ValueError("Generated rings support requires domain.surface_topo.support")
        support.assert_complete_domain()

        center_x = (
            float(config.center_x)
            if config.center_x is not None
            else 0.5 * (float(support.xmin) + float(support.xmax))
        )
        center_y = (
            float(config.center_y)
            if config.center_y is not None
            else 0.5 * (float(support.ymin) + float(support.ymax))
        )
        max_radius = min(
            center_x - float(support.xmin),
            float(support.xmax) - center_x,
            center_y - float(support.ymin),
            float(support.ymax) - center_y,
        )
        if max_radius <= 0.0:
            raise ValueError("Generated rings center must lie strictly inside the domain extent.")

        if config.coordinate_mode == "relative":
            radii_abs = [float(value) * max_radius for value in config.radii]
        else:
            radii_abs = [float(value) for value in config.radii]

        if any(value >= max_radius for value in radii_abs):
            raise ValueError(
                "Generated rings radii must lie strictly inside the largest "
                "inscribed circle around the chosen center."
            )

        return GeneratedRingsSupportField(
            identifier=support_id,
            center_x=center_x,
            center_y=center_y,
            radii_abs=radii_abs,
            labels=list(config.labels),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class CatchmentZonesSupportProvider:
    provider_name = "catchment_zones"
    build_phase = "setup"

    def build(
        self,
        *,
        support_id: str,
        config: CatchmentZonesSupportConfig,
        context: SupportBuildContext,
    ) -> object:
        domain = context.domain
        source_zone = domain.get_zone(config.source_zone_id)
        if source_zone is None:
            raise ValueError(
                f"Catchment support '{support_id}' requires domain zone '{config.source_zone_id}'."
            )

        if not hasattr(source_zone, "encoded_codes") or not hasattr(source_zone, "encoded_to_zone"):
            raise TypeError("Catchment source zone must expose encoded_codes and encoded_to_zone.")
        surface_topo = getattr(domain, "surface_topo", None)
        raster_support = getattr(surface_topo, "support", None)
        if not isinstance(raster_support, RasterSupport):
            raise ValueError("Catchment support requires domain.surface_topo.support")

        return RasterZonesSupportField(
            identifier=support_id,
            encoded_codes=np.asarray(source_zone.encoded_codes, dtype=np.int32),
            encoded_to_zone=dict(source_zone.encoded_to_zone),
            raster_support=raster_support,
            nodata_code=int(getattr(source_zone, "nodata_code", 0)),
            source_meta=getattr(source_zone, "source_meta", None),
            default_cell_samples_per_axis=int(config.default_cell_samples_per_axis),
        )


class GeologySupportProvider:
    provider_name = "geology"
    build_phase = "data"

    def build(
        self,
        *,
        support_id: str,
        config: GeologySupportConfig,
        context: SupportBuildContext,
    ) -> object:
        loaded_data = context.loaded_data
        geology = getattr(loaded_data, "geology", None) if loaded_data is not None else None
        if geology is None:
            # A geology the planner inferred for this support loads in warn mode,
            # so a failed load reaches here as a warning, not as an error.
            raise ConfigMissingError(
                f"[domain.supports.{support_id}] kind = 'geology' reads the geology data, and "
                "none was loaded. Declare [data.geology] with a source that covers the "
                "domain, and list 'geology' in data.types so a failed load stops the run."
            )
        if str(getattr(geology, "identifier", "")).strip() == str(support_id).strip():
            return geology
        return AliasedSpatialSupportField(identifier=support_id, delegate=geology)


class SpatialSupportProviderRegistry:
    """Registry of named support providers used by the launcher."""

    def __init__(self) -> None:
        self._providers: dict[str, SpatialSupportProvider] = {}

    def register(self, provider: SpatialSupportProvider) -> None:
        self._providers[str(provider.provider_name).strip().lower()] = provider

    def get(self, provider_name: str) -> SpatialSupportProvider:
        normalized = str(provider_name).strip().lower()
        provider = self._providers.get(normalized)
        if provider is None:
            raise ValueError(f"Unknown spatial support provider '{provider_name}'")
        return provider


def build_default_spatial_support_provider_registry() -> SpatialSupportProviderRegistry:
    """Return the launcher registry populated with the built-in support providers."""
    registry = SpatialSupportProviderRegistry()
    registry.register(GeneratedBandsSupportProvider())
    registry.register(GeneratedRingsSupportProvider())
    registry.register(CatchmentZonesSupportProvider())
    registry.register(GeologySupportProvider())
    return registry


def build_phase_supports(
    domain: object,
    requested_domain_supports: dict[str, object],
    *,
    registry: SpatialSupportProviderRegistry,
    phase: str,
    context: SupportBuildContext,
) -> None:
    """Build into *domain* the requested supports whose provider builds at *phase*.

    A support the domain already holds under its own id is left as it is.
    """
    for support_id, support_cfg in requested_domain_supports.items():
        existing_zone = None if domain is None else domain.get_zone(support_id)
        if (
            existing_zone is not None
            and str(getattr(existing_zone, "identifier", "")).strip() == str(support_id).strip()
        ):
            continue
        provider = registry.get(getattr(support_cfg, "kind", ""))
        if str(provider.build_phase).strip().lower() != str(phase).strip().lower():
            continue
        support_field = provider.build(
            support_id=support_id,
            config=support_cfg,
            context=context,
        )
        domain.set_zone(support_id, support_field)


# ---------------------------------------------------------------------------
# Support contract: which supports the flow parameters ask for
# ---------------------------------------------------------------------------


def collect_requested_support_ids(flow_cfg: object) -> tuple[str, ...]:
    """Return the ordered support ids referenced by heterogeneous flow parameters."""
    raw_param_cfg = getattr(flow_cfg, "param", {})
    if not isinstance(raw_param_cfg, dict):
        return ()

    requested: list[str] = []
    seen: set[str] = set()
    for param_cfg in raw_param_cfg.values():
        support_id = _heterogeneous_support_id(param_cfg)
        if support_id is None:
            continue
        if support_id == "":
            raise ConfigError("Heterogeneous flow parameters require a non-empty field_spatial_id.")
        normalized = support_id.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        requested.append(support_id)
    return tuple(requested)


def _heterogeneous_support_id(param_cfg: object) -> str | None:
    """Return a heterogeneous flow parameter support id, if one is declared."""
    if isinstance(param_cfg, dict):
        kind = str(param_cfg.get("kind", "")).strip().lower()
        if kind == "":
            field_cfg = param_cfg.get("field")
            if isinstance(field_cfg, dict):
                kind = str(field_cfg.get("kind", "")).strip().lower()
        if kind != "heterogeneous":
            return None
        support_id = param_cfg.get("field_spatial_id")
        if support_id is None and isinstance(param_cfg.get("field"), dict):
            support_id = param_cfg["field"].get("field_spatial_id")
        return str(support_id or "").strip()

    field_cfg = getattr(param_cfg, "field", None)
    kind = str(getattr(field_cfg, "kind", "") or "").strip().lower()
    if kind != "heterogeneous":
        return None
    support_id = getattr(field_cfg, "field_spatial_id", "")
    return str(support_id or "").strip()


def support_provider_names(domain_supports: dict[str, object]) -> tuple[str, ...]:
    """Return the ordered provider names declared by resolved support configs."""
    provider_names: list[str] = []
    seen: set[str] = set()
    for support_cfg in domain_supports.values():
        provider_name = str(getattr(support_cfg, "kind", "")).strip().lower()
        if provider_name == "" or provider_name in seen:
            continue
        seen.add(provider_name)
        provider_names.append(provider_name)
    return tuple(provider_names)


def resolve_support_configs(
    domain_cfg: object,
    requested_support_ids: tuple[str, ...],
) -> dict[str, object]:
    """Resolve support configs actually needed by the current flow parameters."""
    if not requested_support_ids:
        return {}

    explicit_supports = getattr(domain_cfg, "supports", {})
    if explicit_supports is None:
        explicit_supports = {}
    if not isinstance(explicit_supports, dict):
        raise TypeError("domain.supports must be a dictionary")

    explicit_by_lower = {
        str(support_id).strip().lower(): support_cfg
        for support_id, support_cfg in explicit_supports.items()
    }

    resolved: dict[str, object] = {}
    for support_id in requested_support_ids:
        support_cfg = explicit_by_lower.get(str(support_id).strip().lower())
        if support_cfg is not None:
            resolved[support_id] = support_cfg
            continue
        raise ConfigError(
            f"Missing domain support declaration for '{support_id}'. "
            "Declare [domain.supports.<id>] with an explicit provider."
        )
    return resolved


def validate_domain_support_contract(
    flow: object | None,
    requested_domain_supports: dict[str, object],
) -> None:
    """Fail early when heterogeneous flow parameters reference undeclared supports.

    *flow* is the built flow process; its heterogeneous parameters are read
    once, and each support id they name must be in *requested_domain_supports*.
    """
    parameters = getattr(flow, "parameters", {}) if flow is not None else {}
    if not isinstance(parameters, dict):
        return

    declared_supports = {
        str(support_id).strip().lower()
        for support_id in requested_domain_supports
        if str(support_id).strip()
    }
    missing_supports: list[str] = []
    seen: set[str] = set()
    for param in parameters.values():
        if not bool(getattr(param, "is_heterogeneous", False)):
            continue
        support_id = str(getattr(param, "field_spatial_id", "")).strip()
        if support_id == "":
            raise ConfigError("Heterogeneous flow parameters require a non-empty field_spatial_id.")
        normalized_support_id = support_id.lower()
        if normalized_support_id in declared_supports or normalized_support_id in seen:
            continue
        seen.add(normalized_support_id)
        missing_supports.append(support_id)

    if missing_supports:
        raise ConfigError(
            "Heterogeneous flow parameters require explicit "
            "[domain.supports.<id>] declarations for: " + ", ".join(missing_supports) + "."
        )
