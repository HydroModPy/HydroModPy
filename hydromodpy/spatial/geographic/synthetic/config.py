"""Typed configuration for synthetic geographic contexts."""

from __future__ import annotations

from math import isclose
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, computed_field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import PositiveInt
from hydromodpy.core.units import LengthMeters


class SyntheticGridConfig(HydroModelBase):
    """Structured-grid support used to generate one synthetic DEM."""

    length_x: Annotated[LengthMeters, Profile.USER] = Field(
        default=100.0,
        gt=0.0,
        description="Total domain length along x (metres). Accepts inline units, e.g. '0.1 km'.",
    )
    length_y: Annotated[LengthMeters, Profile.USER] = Field(
        default=1.0,
        gt=0.0,
        description="Total domain length along y (metres). Accepts inline units, e.g. '1 m'.",
    )
    nx: Annotated[PositiveInt, Profile.USER] = Field(
        default=100,
        description="Number of cells along x.",
    )
    ny: Annotated[PositiveInt, Profile.USER] = Field(
        default=1,
        description="Number of cells along y.",
    )
    xmin: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Lower x coordinate of the support extent.",
    )
    ymin: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Lower y coordinate of the support extent.",
    )
    crs: Annotated[str, Profile.DEV] = Field(
        default="EPSG:2154",
        description="Projected CRS attached to synthetic outputs.",
    )
    nodata: Annotated[float, Profile.DEV] = Field(
        default=-9999.0,
        description="Nodata sentinel exported to raster artefacts.",
    )

    @model_validator(mode="after")
    def _validate_grid_geometry(self) -> SyntheticGridConfig:
        """Validate that the requested lengths map cleanly to one structured grid."""
        if not isclose(
            float(self.dx),
            float(self.dy),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError(
                "Synthetic geographic v1 requires square cells so one scalar "
                "resolution can still be exposed to legacy solvers."
            )
        return self

    @computed_field
    @property
    def xmax(self) -> float:
        """Upper x coordinate of the support extent."""
        return float(self.xmin) + float(self.length_x)

    @computed_field
    @property
    def ymax(self) -> float:
        """Upper y coordinate of the support extent."""
        return float(self.ymin) + float(self.length_y)

    @computed_field
    @property
    def ncol(self) -> int:
        """Number of raster columns implied by x discretization."""
        return int(self.nx)

    @computed_field
    @property
    def nrow(self) -> int:
        """Number of raster rows implied by y discretization."""
        return int(self.ny)

    @computed_field
    @property
    def dx(self) -> float:
        """Compatibility alias returning the x cell size."""
        return float(self.length_x) / float(self.nx)

    @computed_field
    @property
    def dy(self) -> float:
        """Compatibility alias returning the y cell size."""
        return float(self.length_y) / float(self.ny)


class FlatTopography(HydroModelBase):
    """Constant-elevation analytical topography."""

    kind: Annotated[Literal["flat"], Profile.USER] = Field(
        default="flat",
        description="Analytical topography law: 'flat' keeps one constant elevation.",
    )
    base_elevation: Annotated[float, Profile.USER] = Field(
        default=20.0,
        description="Constant surface elevation (m).",
    )


class LinearTopography(HydroModelBase):
    """Linear analytical topography rising from right to left."""

    kind: Annotated[Literal["linear"], Profile.USER] = Field(
        default="linear",
        description="Analytical topography law: 'linear' increases from right to left.",
    )
    base_elevation: Annotated[float, Profile.USER] = Field(
        default=20.0,
        description="Reference elevation (m) on the right boundary.",
    )
    right_to_left_amplitude: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description=(
            "Additional elevation reached on the left boundary relative to the "
            "right boundary. Positive values make the surface rise from right "
            "to left."
        ),
    )


class RadialIslandTopography(HydroModelBase):
    """Circular emerged island surrounded by submerged ocean cells."""

    kind: Annotated[Literal["radial_island"], Profile.USER] = Field(
        default="radial_island",
        description=(
            "Analytical topography law: 'radial_island' builds one circular "
            "emerged island surrounded by submerged ocean cells."
        ),
    )
    base_elevation: Annotated[float, Profile.USER] = Field(
        default=-1.0,
        description="Submerged ocean-floor elevation (m). Must be < 0.",
    )
    island_radius: Annotated[LengthMeters | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Circular shoreline radius (metres). Defaults to 35% of the smallest domain length. "
            "Accepts inline units."
        ),
    )
    crest_elevation: Annotated[float, Profile.DEV] = Field(
        default=10.0,
        description=(
            "Central island elevation (m). The land surface decays nonlinearly "
            "to sea level at the shoreline."
        ),
    )
    center_x: Annotated[LengthMeters | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional x coordinate (metres) of the island center. Defaults to the grid midpoint."
        ),
    )
    center_y: Annotated[LengthMeters | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional y coordinate (metres) of the island center. Defaults to the grid midpoint."
        ),
    )

    @model_validator(mode="after")
    def _validate_radial_island_payload(self) -> RadialIslandTopography:
        """Validate radial-island specific parameters."""
        if self.island_radius is not None and float(self.island_radius) <= 0.0:
            raise ValueError("synthetic_geographic.topography.island_radius must be > 0.")
        if float(self.crest_elevation) <= 0.0:
            raise ValueError("synthetic_geographic.topography.crest_elevation must be > 0.")
        if float(self.base_elevation) >= 0.0:
            raise ValueError(
                "synthetic_geographic.topography.base_elevation must be < 0 for "
                "'radial_island' so ocean cells remain submerged."
            )
        if float(self.crest_elevation) <= float(self.base_elevation):
            raise ValueError(
                "synthetic_geographic.topography.crest_elevation must be above "
                "base_elevation for 'radial_island'."
            )
        return self


SyntheticTopographyConfig: TypeAlias = Annotated[
    FlatTopography | LinearTopography | RadialIslandTopography,
    Field(discriminator="kind"),
]
"""Discriminated union of analytical topography variants."""


_TOPOGRAPHY_DEFAULT_LEAKS: dict[str, dict[str, Any]] = {
    "flat": {
        "right_to_left_amplitude": 0.0,
        "island_radius": (None, 0.0),
        "crest_elevation": 10.0,
        "center_x": (None, 0.0),
        "center_y": (None, 0.0),
    },
    "linear": {
        "island_radius": (None, 0.0),
        "crest_elevation": 10.0,
        "center_x": (None, 0.0),
        "center_y": (None, 0.0),
    },
    "radial_island": {
        "right_to_left_amplitude": 0.0,
    },
}
"""Pre-discriminated-union default values stripped from raw TOML payloads.

Some legacy ``expert_generated`` TOMLs export every field of the old flat
``SyntheticTopographyConfig`` regardless of the active ``kind``. With the
discriminated union those keys would now be rejected by ``extra="forbid"``.
This map lists, per ``kind``, the default values that may be safely dropped
when present. Any other value still raises a validation error.
"""


def _strip_default_topography_leaks(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop default-valued cross-variant fields from a raw topography payload."""
    kind = str(payload.get("kind", "flat")).strip().lower()
    leaks = _TOPOGRAPHY_DEFAULT_LEAKS.get(kind)
    if leaks is None:
        return payload
    cleaned = dict(payload)
    for field_name, accepted in leaks.items():
        if field_name not in cleaned:
            continue
        value = cleaned[field_name]
        accepted_values = accepted if isinstance(accepted, tuple) else (accepted,)
        if value in accepted_values:
            cleaned.pop(field_name)
    return cleaned


class SyntheticGeographicConfig(HydroModelBase):
    """Top-level config for one synthetic geographic build."""

    case_id: Annotated[str, Profile.USER] = Field(
        default="flat20",
        description="Identifier used by local case runners and outputs.",
    )
    grid: Annotated[SyntheticGridConfig, Profile.USER] = Field(
        default_factory=SyntheticGridConfig,
        description="Synthetic grid definition (extent and cell size).",
    )
    topography: Annotated[SyntheticTopographyConfig, Profile.USER] = Field(
        default_factory=FlatTopography,
        description="Synthetic topography definition (shape, elevations, slope).",
    )

    @model_validator(mode="before")
    @classmethod
    def _filter_topography_default_leaks(cls, data: Any) -> Any:
        """Drop default-valued cross-variant fields from raw topography payloads.

        Legacy ``expert_generated`` TOMLs may dump every field of the old flat
        ``SyntheticTopographyConfig`` regardless of ``kind``. Those keys are now
        forbidden by the discriminated union. We tolerate them only when their
        value matches the legacy default, otherwise validation must fail.
        """
        if not isinstance(data, dict):
            return data
        topography = data.get("topography")
        if not isinstance(topography, dict):
            return data
        cleaned = _strip_default_topography_leaks(topography)
        if cleaned is topography:
            return data
        new_data = dict(data)
        new_data["topography"] = cleaned
        return new_data

    @classmethod
    def from_toml(cls, path: str | Path) -> SyntheticGeographicConfig:
        """Load one config from a TOML file.

        Expected section layout:

        ```toml
        [synthetic_geographic]
        case_id = "flat20"

        [synthetic_geographic.grid]
        ...

        [synthetic_geographic.topography]
        ...
        ```
        """
        from hydromodpy.core.toml_io.loader import validate_toml

        return validate_toml(cls, path, section="synthetic_geographic")
