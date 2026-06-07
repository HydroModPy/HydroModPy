"""Public contracts for zone-meshing support domains."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ZoneMeshingDomainConfig:
    """Typed support-domain contract shared by conformal meshing workflows."""

    kind: str
    bbox: tuple[float, float, float, float] | None = None
    coordinates: tuple[tuple[float, float], ...] | None = None
    path: str | None = None
    id_field: str | None = None
    selected_id: str | None = None

    @classmethod
    def from_mapping(
        cls,
        config_data: Mapping[str, Any],
    ) -> ZoneMeshingDomainConfig:
        """Validate one raw mapping and return one typed domain contract."""
        from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._domain_schema import (
            validate_zone_meshing_domain_model,
        )

        parsed = validate_zone_meshing_domain_model(config_data)
        return cls.from_normalized_mapping(parsed.model_dump(mode="python"))

    @classmethod
    def from_normalized_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> ZoneMeshingDomainConfig:
        """Build one typed domain contract from already normalized values."""
        bbox_raw = payload.get("bbox")
        coordinates_raw = payload.get("coordinates")
        return cls(
            kind=str(payload["kind"]),
            bbox=(None if bbox_raw is None else tuple(float(value) for value in bbox_raw)),
            coordinates=(
                None
                if coordinates_raw is None
                else tuple((float(pair[0]), float(pair[1])) for pair in coordinates_raw)
            ),
            path=None if payload.get("path") is None else str(payload["path"]),
            id_field=(None if payload.get("id_field") is None else str(payload["id_field"])),
            selected_id=(
                None if payload.get("selected_id") is None else str(payload["selected_id"])
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialize one typed domain contract to mapping form."""
        payload: dict[str, Any] = {"kind": self.kind}
        if self.bbox is not None:
            payload["bbox"] = [float(value) for value in self.bbox]
        if self.coordinates is not None:
            payload["coordinates"] = [[float(x), float(y)] for x, y in self.coordinates]
        if self.path is not None:
            payload["path"] = self.path
        if self.id_field is not None:
            payload["id_field"] = self.id_field
        if self.selected_id is not None:
            payload["selected_id"] = self.selected_id
        return payload


@dataclass(frozen=True)
class ZoneMeshingDomainPayload:
    """Resolved geometry payload returned after loading one support domain."""

    geometry: object
    gdf: object
    summary: dict[str, Any]

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> ZoneMeshingDomainPayload:
        """Build one typed geometry payload from plain mapping form."""
        return cls(
            geometry=payload["geometry"],
            gdf=payload["gdf"],
            summary=dict(payload.get("summary", {})),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialize one typed geometry payload to mapping form."""
        return {
            "geometry": self.geometry,
            "gdf": self.gdf,
            "summary": dict(self.summary),
        }
