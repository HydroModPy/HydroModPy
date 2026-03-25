from __future__ import annotations
"""
Domain assembly logic built on top of `Surface` and `DomainConfig`.

This module keeps the high-level orchestration of the model domain:
- accept one already-prepared topographic surface,
- derive the vertical lower surface from the configured depth model,
- expose a compact georeferencing view,
- build thematic zones (currently geology) from explicit external artefacts.

Low-level array manipulations intentionally remain delegated to `Surface`.
"""

from collections.abc import Mapping

from hydromodpy.spatial.domain.depth_model import (
    ConstantThicknessDepthModel,
    FlatSubstratumDepthModel,
)
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.surface import Surface


class Domain:
    """
    Domain object holding geometry and thematic zones.

    Responsibilities
    ----------------
    - store the topographic surface support of the domain,
    - build the lower surface (`substratum`) from `depth_model`,
    - keep a lightweight georeferencing mapping for legacy consumers,
    - store declared thematic zones (such as geology) once they are built outside.

    Main public attributes
    ----------------------
    - `surface_topo`
    - `substratum`
    - `zones`
    - `georeferencing`
    """

    def __init__(
        self,
        config: DomainConfig | Mapping[str, object] | None = None,
        *,
        surface_topo: Surface,
    ):
        self.config = self._coerce_config(config)
        self.surface_topo: Surface = surface_topo
        self.substratum: Surface | None = None
        self.zones: dict[str, object] = {}
        if self.surface_topo.support is not None:
            self.georeferencing = self.surface_topo.support.as_georeferencing_dict()
        else:
            self.georeferencing = {}
        self._build_surfaces()

    @staticmethod
    def _coerce_config(
        config: DomainConfig | Mapping[str, object] | None,
    ) -> DomainConfig:
        """
        Normalize the user-provided config input into one validated `DomainConfig`.

        Accepted inputs are:
        - `None`               -> default `DomainConfig()`
        - `DomainConfig`       -> reused as-is
        - `Mapping[str, obj]`  -> validated through Pydantic
        """
        if config is None:
            return DomainConfig()
        if isinstance(config, DomainConfig):
            return config
        if not isinstance(config, Mapping):
            raise TypeError("Domain config must be a DomainConfig instance or a mapping")
        return DomainConfig.model_validate(dict(config))

    def _build_surfaces(self) -> None:
        """
        Build the lower domain surface from the configured depth model.

        Two modes are currently supported:
        - `ConstantThicknessDepthModel`:
          shift the topography downward by a constant offset,
        - `FlatSubstratumDepthModel`:
          create one flat surface at a constant elevation below the topography.
        """
        depth_model = self.config.depth_model
        if isinstance(depth_model, ConstantThicknessDepthModel):
            self.substratum = self.surface_topo.shifted_down_by(
                float(depth_model.thickness)
            )
        elif isinstance(depth_model, FlatSubstratumDepthModel):
            self.substratum = self.surface_topo.flat_like(
                float(depth_model.substratum_elevation)
            )
        else:
            raise TypeError(f"Unsupported depth_model payload: {type(depth_model)!r}")

    def set_zone(
        self,
        zone_id: str,
        zone_obj: object,
    ) -> None:
        """
        Register one externally-built zone object inside the domain.

        `Domain` no longer constructs thematic zones itself. The caller builds
        them explicitly (for example a `GeologyField`) and stores them here
        under one declared `zone_id`.
        """
        normalized = str(zone_id).strip().lower()
        if normalized == "":
            raise ValueError("zone_id cannot be empty")
        if self.config.zone_ids and normalized not in self.config.zone_ids:
            raise ValueError(
                f"Zone '{normalized}' is not declared in domain.zone_ids: {self.config.zone_ids}"
            )
        self.zones[normalized] = zone_obj

    def get_zone(self, zone_id: str) -> object | None:
        """Return one registered zone by canonical zone id."""
        normalized = str(zone_id).strip().lower()
        if normalized == "":
            raise ValueError("zone_id cannot be empty")
        return self.zones.get(normalized)

    def resolve_spatial_support(self, support_id: str) -> object | None:
        """Resolve one spatial support from zone id or field identifier.

        The launcher stores heterogeneous supports in ``Domain.zones`` under a
        semantic zone key (for example ``"geology"``), while field parameters
        reference the support through ``field_spatial_id`` (for example
        ``"field_geology"``). This method bridges both naming schemes.
        """
        normalized = str(support_id).strip()
        if normalized == "":
            raise ValueError("support_id cannot be empty")

        zone_match = self.zones.get(normalized.lower())
        if zone_match is not None:
            return zone_match

        matches = [
            zone_obj
            for zone_obj in self.zones.values()
            if str(getattr(zone_obj, "identifier", "")).strip() == normalized
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Multiple domain zones match spatial support '{normalized}'."
            )
        return matches[0] if matches else None
