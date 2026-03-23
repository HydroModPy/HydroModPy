"""Validate and normalize configuration for zone-conformal meshing workflows.

This module stays small on purpose: its role is to define what a valid
zone-meshing configuration looks like before geometry and Gmsh calls are
performed. It separates configuration concerns from the actual meshing logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class ZoneMeshingRefinementFamilySettingsSchema(BaseModel):
    """One family-specific refinement override inside the hotspot policy."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    priority: int = 0
    interface_size: float | None = None
    interface_distance: float | None = None
    interface_sampling: int | None = None

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, value):
        return int(value)

    @field_validator("interface_size", "interface_distance")
    @classmethod
    def _validate_optional_non_negative_family_float(cls, value):
        if value is None:
            return None
        out = float(value)
        if out < 0.0:
            raise ValueError("values must be >= 0")
        return out

    @field_validator("interface_sampling")
    @classmethod
    def _validate_optional_family_sampling(cls, value):
        if value is None:
            return None
        out = int(value)
        if out < 2:
            raise ValueError("interface_sampling must be >= 2 when provided")
        return out


class ZoneMeshingRefinementFamiliesSchema(BaseModel):
    """Validated family-specific refinement policy settings."""

    model_config = ConfigDict(extra="forbid")

    river: ZoneMeshingRefinementFamilySettingsSchema = Field(
        default_factory=lambda: ZoneMeshingRefinementFamilySettingsSchema(
            enabled=True,
            priority=300,
        )
    )
    geology_interface: ZoneMeshingRefinementFamilySettingsSchema = Field(
        default_factory=lambda: ZoneMeshingRefinementFamilySettingsSchema(
            enabled=True,
            priority=200,
        )
    )
    watershed_boundary: ZoneMeshingRefinementFamilySettingsSchema = Field(
        default_factory=lambda: ZoneMeshingRefinementFamilySettingsSchema(
            enabled=True,
            priority=100,
        )
    )


class ZoneMeshingRefinementHotspotSettingsSchema(BaseModel):
    """Validated hotspot-detection thresholds for local refinement budgeting."""

    model_config = ConfigDict(extra="forbid")

    radius: float | None = None
    max_curve_count: int = 180
    max_family_count: int = 2
    min_gap: float = 80.0
    max_node_degree: int = 4
    short_segment_length: float = 120.0
    max_short_segment_count: int = 12

    @field_validator("radius", "min_gap", "short_segment_length")
    @classmethod
    def _validate_optional_non_negative_hotspot_float(cls, value):
        if value is None:
            return None
        out = float(value)
        if out < 0.0:
            raise ValueError("values must be >= 0")
        return out

    @field_validator(
        "max_curve_count",
        "max_family_count",
        "max_node_degree",
        "max_short_segment_count",
    )
    @classmethod
    def _validate_positive_int(cls, value):
        out = int(value)
        if out < 1:
            raise ValueError("values must be >= 1")
        return out


class ZoneMeshingRefinementGridSettingsSchema(BaseModel):
    """Validated grid settings for one locality-first refinement policy."""

    model_config = ConfigDict(extra="forbid")

    cell_size: float | None = None
    neighborhood_rings: int = 1
    enable_exact_gap_check: bool = True
    max_exact_gap_candidates: int = 256

    @field_validator("cell_size")
    @classmethod
    def _validate_optional_positive_cell_size(cls, value):
        if value is None:
            return None
        out = float(value)
        if out <= 0.0:
            raise ValueError("cell_size must be > 0 when provided")
        return out

    @field_validator("neighborhood_rings", "max_exact_gap_candidates")
    @classmethod
    def _validate_positive_grid_int(cls, value):
        out = int(value)
        if out < 1:
            raise ValueError("values must be >= 1")
        return out


class ZoneMeshingRefinementPolicySchema(BaseModel):
    """Validated local refinement policy for mixed river/geology interfaces."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    mode: str = Field(default="family_priority_local_budget")
    hotspot: ZoneMeshingRefinementHotspotSettingsSchema = Field(
        default_factory=ZoneMeshingRefinementHotspotSettingsSchema
    )
    grid: ZoneMeshingRefinementGridSettingsSchema = Field(
        default_factory=ZoneMeshingRefinementGridSettingsSchema
    )
    families: ZoneMeshingRefinementFamiliesSchema = Field(
        default_factory=ZoneMeshingRefinementFamiliesSchema
    )

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value):
        text = str(value).strip().lower()
        allowed = {"family_priority_local_budget", "grid_local_budget"}
        if text not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise ValueError(f"mode must be one of: {allowed_text}")
        return text


class ZoneMeshingSettingsSchema(BaseModel):
    """Validated settings for one conformal 2D Gmsh meshing run."""

    model_config = ConfigDict(extra="forbid")

    algorithm: str = Field(
        default="delaunay",
        description=(
            "Planar Gmsh algorithm name. "
            "In practice the examples use 'delaunay', which is a robust default for irregular geological and river-constrained domains."
        ),
    )
    global_size: float = Field(
        default=250.0,
        description=(
            "Baseline target cell size in projected metres over the full support domain. "
            "Think of it as the coarse background resolution before local interface refinement is added."
        ),
    )
    min_size: float | None = Field(
        default=None,
        description=(
            "Lower bound on local cell size in projected metres. "
            "Use it to prevent extreme refinement from generating very small cells in narrow features."
        ),
    )
    max_size: float | None = Field(
        default=None,
        description=(
            "Upper bound on local cell size in projected metres. "
            "Use it when you want to cap the coarsening far from interfaces."
        ),
    )
    simplify_tolerance: float = Field(
        default=0.0,
        description=(
            "Geometry simplification tolerance, in projected metres, applied before meshing. "
            "Increase it only when the source polygons contain excessive vertex noise that does not carry hydrogeological meaning."
        ),
    )
    heal_tolerance: float = Field(
        default=0.0,
        description=(
            "Cleanup tolerance, in projected metres, used to repair tiny gaps or slivers between input polygons. "
            "Keep it near zero unless the source dataset is known to contain topology artifacts."
        ),
    )
    linear_constraint_snap_tolerance: float = Field(
        default=0.0,
        description=(
            "Optional global snapping tolerance, in projected metres, applied to internal linear constraints "
            "such as rivers or watershed-boundary segments before partition splitting and Gmsh embedding."
        ),
    )
    min_polygon_area: float = Field(
        default=0.0,
        description=(
            "Minimum polygon area, in square metres, kept after cleaning. "
            "Use it to drop microscopic remnants that would otherwise create meaningless tiny mesh patches."
        ),
    )
    refine_interfaces: bool = Field(
        default=False,
        description=(
            "Enable a distance-based size field around geology or river interfaces. "
            "When false, the mesh uses only the global background size constraints."
        ),
    )
    interface_size: float | None = Field(
        default=None,
        description=(
            "Target local size, in projected metres, close to constrained interfaces. "
            "When omitted and refine_interfaces=true, the schema derives a conservative default from global_size/min_size."
        ),
    )
    interface_distance: float | None = Field(
        default=None,
        description=(
            "Influence distance, in projected metres, over which the local interface refinement fades back to the background size. "
            "Larger values spread refinement farther away from the interface network."
        ),
    )
    interface_sampling: int = Field(
        default=64,
        description=(
            "Sampling density used to discretize interface-based distance fields. "
            "Higher values better capture long and sinuous interfaces but increase Gmsh preprocessing cost."
        ),
    )
    refinement_policy: ZoneMeshingRefinementPolicySchema | None = Field(
        default=None,
        description=(
            "Optional local hotspot policy used to selectively thin low-priority "
            "refinement families when the mixed interface network becomes too "
            "dense for one robust Gmsh Delaunay run."
        ),
    )

    @field_validator("algorithm")
    @classmethod
    def _validate_algorithm(cls, value):
        text = str(value).strip().lower()
        if not text:
            raise ValueError("algorithm cannot be empty")
        return text

    @field_validator(
        "global_size",
        "min_size",
        "max_size",
        "simplify_tolerance",
        "heal_tolerance",
        "linear_constraint_snap_tolerance",
        "min_polygon_area",
        "interface_size",
        "interface_distance",
    )
    @classmethod
    def _validate_optional_non_negative_float(cls, value):
        if value is None:
            return None
        out = float(value)
        if out < 0.0:
            raise ValueError("values must be >= 0")
        return out

    @field_validator("interface_sampling")
    @classmethod
    def _validate_interface_sampling(cls, value):
        out = int(value)
        if out < 2:
            raise ValueError("interface_sampling must be >= 2")
        return out

    @model_validator(mode="after")
    def _validate_cross_constraints(self):
        if self.global_size <= 0.0:
            raise ValueError("global_size must be > 0")
        if self.min_size is not None and self.min_size <= 0.0:
            raise ValueError("min_size must be > 0 when provided")
        if self.max_size is not None and self.max_size <= 0.0:
            raise ValueError("max_size must be > 0 when provided")
        if (
            self.min_size is not None
            and self.max_size is not None
            and self.min_size > self.max_size
        ):
            raise ValueError("min_size must be <= max_size")

        if self.refine_interfaces:
            if self.interface_size is None:
                self.interface_size = min(
                    (
                        self.min_size
                        if self.min_size is not None
                        else self.global_size * 0.5
                    ),
                    self.global_size,
                )
            if self.interface_distance is None:
                self.interface_distance = max(
                    self.global_size * 3.0, self.interface_size
                )
            if self.interface_size <= 0.0:
                raise ValueError(
                    "interface_size must be > 0 when refine_interfaces=true"
                )
            if self.interface_size > self.global_size:
                raise ValueError(
                    "interface_size must be <= global_size when refine_interfaces=true"
                )
            if self.interface_distance <= 0.0:
                raise ValueError(
                    "interface_distance must be > 0 when refine_interfaces=true"
                )
        if self.refinement_policy is not None and self.refinement_policy.enabled:
            if not self.refine_interfaces:
                raise ValueError(
                    "refinement_policy.enabled requires refine_interfaces=true"
                )
            if self.refinement_policy.hotspot.radius is None:
                self.refinement_policy.hotspot.radius = self.interface_distance
            if (
                self.refinement_policy.mode == "grid_local_budget"
                and self.refinement_policy.grid.cell_size is None
            ):
                self.refinement_policy.grid.cell_size = max(
                    float(self.interface_distance) * 0.5,
                    float(self.interface_size),
                )
            for family_name in (
                "river",
                "geology_interface",
                "watershed_boundary",
            ):
                family_settings = getattr(self.refinement_policy.families, family_name)
                if family_settings.interface_size is not None:
                    if family_settings.interface_size <= 0.0:
                        raise ValueError(
                            f"{family_name}.interface_size must be > 0 when provided"
                        )
                    if family_settings.interface_size > self.global_size:
                        raise ValueError(
                            f"{family_name}.interface_size must be <= global_size"
                        )
                if family_settings.interface_distance is not None:
                    if family_settings.interface_distance <= 0.0:
                        raise ValueError(
                            f"{family_name}.interface_distance must be > 0 when provided"
                        )
        return self


@dataclass(frozen=True)
class ZoneMeshingRefinementFamilySettings:
    """Family-specific refinement behavior resolved from the config."""

    enabled: bool
    priority: int
    interface_size: float | None
    interface_distance: float | None
    interface_sampling: int | None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "priority": int(self.priority),
            "interface_size": (
                None if self.interface_size is None else float(self.interface_size)
            ),
            "interface_distance": (
                None
                if self.interface_distance is None
                else float(self.interface_distance)
            ),
            "interface_sampling": (
                None
                if self.interface_sampling is None
                else int(self.interface_sampling)
            ),
        }


@dataclass(frozen=True)
class ZoneMeshingRefinementHotspotSettings:
    """Local hotspot thresholds used by the refinement policy."""

    radius: float | None
    max_curve_count: int
    max_family_count: int
    min_gap: float
    max_node_degree: int
    short_segment_length: float
    max_short_segment_count: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "radius": None if self.radius is None else float(self.radius),
            "max_curve_count": int(self.max_curve_count),
            "max_family_count": int(self.max_family_count),
            "min_gap": float(self.min_gap),
            "max_node_degree": int(self.max_node_degree),
            "short_segment_length": float(self.short_segment_length),
            "max_short_segment_count": int(self.max_short_segment_count),
        }


@dataclass(frozen=True)
class ZoneMeshingRefinementGridSettings:
    """Spatial grid settings used by one locality-first refinement policy."""

    cell_size: float | None
    neighborhood_rings: int
    enable_exact_gap_check: bool
    max_exact_gap_candidates: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "cell_size": (
                None if self.cell_size is None else float(self.cell_size)
            ),
            "neighborhood_rings": int(self.neighborhood_rings),
            "enable_exact_gap_check": bool(self.enable_exact_gap_check),
            "max_exact_gap_candidates": int(self.max_exact_gap_candidates),
        }


@dataclass(frozen=True)
class ZoneMeshingRefinementPolicy:
    """Optional local budget policy used before creating Gmsh size fields."""

    enabled: bool
    mode: str
    hotspot: ZoneMeshingRefinementHotspotSettings
    grid: ZoneMeshingRefinementGridSettings
    families: dict[str, ZoneMeshingRefinementFamilySettings]

    def sorted_families_by_priority(self) -> list[str]:
        return [
            family_name
            for family_name, _ in sorted(
                self.families.items(),
                key=lambda item: (
                    int(item[1].priority),
                    str(item[0]),
                ),
                reverse=True,
            )
        ]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "mode": str(self.mode),
            "hotspot": self.hotspot.to_mapping(),
            "grid": self.grid.to_mapping(),
            "families": {
                family_name: settings.to_mapping()
                for family_name, settings in sorted(self.families.items())
            },
        }


@dataclass(frozen=True)
class ZoneMeshingSettings:
    """Typed meshing settings consumed by the conformal Gmsh workflow."""

    algorithm: str
    global_size: float
    min_size: float | None
    max_size: float | None
    simplify_tolerance: float
    heal_tolerance: float
    linear_constraint_snap_tolerance: float
    min_polygon_area: float
    refine_interfaces: bool
    interface_size: float | None
    interface_distance: float | None
    interface_sampling: int
    refinement_policy: ZoneMeshingRefinementPolicy | None

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]) -> "ZoneMeshingSettings":
        """Validate one raw mapping and return one typed settings contract."""
        if not isinstance(config_data, Mapping):
            raise ValueError("zone meshing configuration must be a mapping")
        try:
            parsed = ZoneMeshingSettingsSchema.model_validate(dict(config_data))
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        payload = parsed.model_dump(mode="python")
        refinement_policy_payload = payload.get("refinement_policy")
        refinement_policy = None
        if refinement_policy_payload is not None:
            families_payload = refinement_policy_payload["families"]
            refinement_policy = ZoneMeshingRefinementPolicy(
                enabled=bool(refinement_policy_payload["enabled"]),
                mode=str(refinement_policy_payload["mode"]),
                hotspot=ZoneMeshingRefinementHotspotSettings(
                    radius=(
                        None
                        if refinement_policy_payload["hotspot"]["radius"] is None
                        else float(refinement_policy_payload["hotspot"]["radius"])
                    ),
                    max_curve_count=int(
                        refinement_policy_payload["hotspot"]["max_curve_count"]
                    ),
                    max_family_count=int(
                        refinement_policy_payload["hotspot"]["max_family_count"]
                    ),
                    min_gap=float(refinement_policy_payload["hotspot"]["min_gap"]),
                    max_node_degree=int(
                        refinement_policy_payload["hotspot"]["max_node_degree"]
                    ),
                    short_segment_length=float(
                        refinement_policy_payload["hotspot"]["short_segment_length"]
                    ),
                    max_short_segment_count=int(
                        refinement_policy_payload["hotspot"][
                            "max_short_segment_count"
                        ]
                    ),
                ),
                grid=ZoneMeshingRefinementGridSettings(
                    cell_size=(
                        None
                        if refinement_policy_payload["grid"]["cell_size"] is None
                        else float(refinement_policy_payload["grid"]["cell_size"])
                    ),
                    neighborhood_rings=int(
                        refinement_policy_payload["grid"]["neighborhood_rings"]
                    ),
                    enable_exact_gap_check=bool(
                        refinement_policy_payload["grid"]["enable_exact_gap_check"]
                    ),
                    max_exact_gap_candidates=int(
                        refinement_policy_payload["grid"][
                            "max_exact_gap_candidates"
                        ]
                    ),
                ),
                families={
                    "river": ZoneMeshingRefinementFamilySettings(
                        enabled=bool(families_payload["river"]["enabled"]),
                        priority=int(families_payload["river"]["priority"]),
                        interface_size=(
                            None
                            if families_payload["river"]["interface_size"] is None
                            else float(families_payload["river"]["interface_size"])
                        ),
                        interface_distance=(
                            None
                            if families_payload["river"]["interface_distance"] is None
                            else float(
                                families_payload["river"]["interface_distance"]
                            )
                        ),
                        interface_sampling=(
                            None
                            if families_payload["river"]["interface_sampling"] is None
                            else int(families_payload["river"]["interface_sampling"])
                        ),
                    ),
                    "geology_interface": ZoneMeshingRefinementFamilySettings(
                        enabled=bool(
                            families_payload["geology_interface"]["enabled"]
                        ),
                        priority=int(
                            families_payload["geology_interface"]["priority"]
                        ),
                        interface_size=(
                            None
                            if families_payload["geology_interface"][
                                "interface_size"
                            ]
                            is None
                            else float(
                                families_payload["geology_interface"][
                                    "interface_size"
                                ]
                            )
                        ),
                        interface_distance=(
                            None
                            if families_payload["geology_interface"][
                                "interface_distance"
                            ]
                            is None
                            else float(
                                families_payload["geology_interface"][
                                    "interface_distance"
                                ]
                            )
                        ),
                        interface_sampling=(
                            None
                            if families_payload["geology_interface"][
                                "interface_sampling"
                            ]
                            is None
                            else int(
                                families_payload["geology_interface"][
                                    "interface_sampling"
                                ]
                            )
                        ),
                    ),
                    "watershed_boundary": ZoneMeshingRefinementFamilySettings(
                        enabled=bool(
                            families_payload["watershed_boundary"]["enabled"]
                        ),
                        priority=int(
                            families_payload["watershed_boundary"]["priority"]
                        ),
                        interface_size=(
                            None
                            if families_payload["watershed_boundary"][
                                "interface_size"
                            ]
                            is None
                            else float(
                                families_payload["watershed_boundary"][
                                    "interface_size"
                                ]
                            )
                        ),
                        interface_distance=(
                            None
                            if families_payload["watershed_boundary"][
                                "interface_distance"
                            ]
                            is None
                            else float(
                                families_payload["watershed_boundary"][
                                    "interface_distance"
                                ]
                            )
                        ),
                        interface_sampling=(
                            None
                            if families_payload["watershed_boundary"][
                                "interface_sampling"
                            ]
                            is None
                            else int(
                                families_payload["watershed_boundary"][
                                    "interface_sampling"
                                ]
                            )
                        ),
                    ),
                },
            )
        return cls(
            algorithm=str(payload["algorithm"]),
            global_size=float(payload["global_size"]),
            min_size=(
                None if payload["min_size"] is None else float(payload["min_size"])
            ),
            max_size=(
                None if payload["max_size"] is None else float(payload["max_size"])
            ),
            simplify_tolerance=float(payload["simplify_tolerance"]),
            heal_tolerance=float(payload["heal_tolerance"]),
            linear_constraint_snap_tolerance=float(
                payload["linear_constraint_snap_tolerance"]
            ),
            min_polygon_area=float(payload["min_polygon_area"]),
            refine_interfaces=bool(payload["refine_interfaces"]),
            interface_size=(
                None
                if payload["interface_size"] is None
                else float(payload["interface_size"])
            ),
            interface_distance=(
                None
                if payload["interface_distance"] is None
                else float(payload["interface_distance"])
            ),
            interface_sampling=int(payload["interface_sampling"]),
            refinement_policy=refinement_policy,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialize one typed settings contract to plain Python mapping form."""
        return {
            "algorithm": self.algorithm,
            "global_size": float(self.global_size),
            "min_size": None if self.min_size is None else float(self.min_size),
            "max_size": None if self.max_size is None else float(self.max_size),
            "simplify_tolerance": float(self.simplify_tolerance),
            "heal_tolerance": float(self.heal_tolerance),
            "linear_constraint_snap_tolerance": float(
                self.linear_constraint_snap_tolerance
            ),
            "min_polygon_area": float(self.min_polygon_area),
            "refine_interfaces": bool(self.refine_interfaces),
            "interface_size": (
                None if self.interface_size is None else float(self.interface_size)
            ),
            "interface_distance": (
                None
                if self.interface_distance is None
                else float(self.interface_distance)
            ),
            "interface_sampling": int(self.interface_sampling),
            "refinement_policy": (
                None
                if self.refinement_policy is None
                else self.refinement_policy.to_mapping()
            ),
        }


def parse_zone_meshing_settings(config_data: Mapping[str, Any]) -> ZoneMeshingSettings:
    """Return one typed zone-meshing settings contract from a raw mapping."""

    return ZoneMeshingSettings.from_mapping(config_data)


__all__ = [
    "parse_zone_meshing_settings",
    "ZoneMeshingRefinementFamilySettings",
    "ZoneMeshingRefinementGridSettings",
    "ZoneMeshingRefinementGridSettingsSchema",
    "ZoneMeshingRefinementHotspotSettings",
    "ZoneMeshingRefinementPolicy",
    "ZoneMeshingRefinementPolicySchema",
    "ZoneMeshingSettings",
    "ZoneMeshingSettingsSchema",
]
