"""Typed configuration for synthetic geographic contexts."""

from __future__ import annotations

from math import isclose
from pathlib import Path
import tomllib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.units import parse_length_to_m


class SyntheticGridConfig(BaseModel):
    """Structured-grid support used to generate one synthetic DEM."""

    model_config = ConfigDict(extra="forbid")

    length_x: float = Field(
        default=100.0,
        description="Total domain length along x. Accepts values such as 100, '100 m', or '0.1 km'.",
    )
    length_y: float = Field(
        default=1.0,
        description="Total domain length along y. Accepts values such as 1, '1 m', or '0.001 km'.",
    )
    nx: int = Field(
        default=100,
        ge=1,
        description="Number of cells along x.",
    )
    ny: int = Field(
        default=1,
        ge=1,
        description="Number of cells along y.",
    )
    xmin: float = Field(
        default=0.0,
        description="Lower x coordinate of the support extent.",
    )
    ymin: float = Field(
        default=0.0,
        description="Lower y coordinate of the support extent.",
    )
    crs: str = Field(
        default="EPSG:2154",
        description="Projected CRS attached to synthetic outputs.",
    )
    nodata: float = Field(
        default=-9999.0,
        description="Nodata sentinel exported to raster artefacts.",
    )

    @field_validator("length_x", "length_y", mode="before")
    @classmethod
    def _normalize_lengths_to_m(cls, value, info):
        """Parse user-friendly lengths into meters."""
        label = f"synthetic_geographic.grid.{info.field_name}"
        length_m = float(parse_length_to_m(value, default_unit="m", label=label))
        if length_m <= 0.0:
            raise ValueError(f"{label} must be > 0.")
        return length_m

    @model_validator(mode="after")
    def _validate_grid_geometry(self) -> "SyntheticGridConfig":
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

    @property
    def xmax(self) -> float:
        """Upper x coordinate of the support extent."""
        return float(self.xmin) + float(self.length_x)

    @property
    def ymax(self) -> float:
        """Upper y coordinate of the support extent."""
        return float(self.ymin) + float(self.length_y)

    @property
    def ncol(self) -> int:
        """Number of raster columns implied by x discretization."""
        return int(self.nx)

    @property
    def nrow(self) -> int:
        """Number of raster rows implied by y discretization."""
        return int(self.ny)

    @property
    def dx(self) -> float:
        """Compatibility alias returning the x cell size."""
        return float(self.length_x) / float(self.nx)

    @property
    def dy(self) -> float:
        """Compatibility alias returning the y cell size."""
        return float(self.length_y) / float(self.ny)


class SyntheticTopographyConfig(BaseModel):
    """Analytical topography definition on the synthetic support."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["flat", "linear"] = Field(
        default="flat",
        description=(
            "Analytical topography law. "
            "'flat' keeps one constant elevation. "
            "'linear' increases from right to left with a linear profile."
        ),
    )
    base_elevation: float = Field(
        default=20.0,
        description=(
            "Reference elevation (m). "
            "For 'flat' this is the constant surface elevation. "
            "For 'linear' this is the elevation on the right boundary."
        ),
    )
    right_to_left_amplitude: float = Field(
        default=0.0,
        description=(
            "Additional elevation reached on the left boundary relative to the "
            "right boundary. Positive values make the surface rise from right "
            "to left."
        ),
    )


class SyntheticGeographicConfig(BaseModel):
    """Top-level config for one synthetic geographic build."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(
        default="flat20",
        description="Identifier used by local case runners and outputs.",
    )
    grid: SyntheticGridConfig = Field(default_factory=SyntheticGridConfig)
    topography: SyntheticTopographyConfig = Field(default_factory=SyntheticTopographyConfig)

    @classmethod
    def from_toml(cls, path: str | Path) -> "SyntheticGeographicConfig":
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
        toml_path = Path(path)
        with toml_path.open("rb") as stream:
            raw_toml = tomllib.load(stream)
        section = raw_toml.get("synthetic_geographic")
        if section is None:
            raise ValueError(
                f"Missing [synthetic_geographic] section in TOML file: {toml_path}"
            )
        if not isinstance(section, dict):
            raise ValueError("[synthetic_geographic] must be a mapping payload.")
        return cls.model_validate(section)
