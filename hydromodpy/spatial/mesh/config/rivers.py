"""River-trace inputs consumed by the conformal mesher."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import Length


class MeshCatchmentRiversConfig(HydroModelBase):
    """River-trace inputs consumed by the conformal mesher."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[str, Profile.USER] = Field(
        default="domain_geographic",
        description=(
            "Origin of the river constraints used to force mesh edges along the river network. "
            "Use 'domain_geographic' for the in-memory river trace produced by geographic preprocessing, "
            "or 'file' to reload a vector river dataset from disk."
        ),
    )
    path: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Vector file path used only when source='file'. "
            "The path may be absolute or relative to the TOML location and should point to a line dataset "
            "describing the river centerlines to honor during meshing."
        ),
    )
    clip_to_domain: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "If true, clip the river trace to the effective meshing support before sending it to Gmsh. "
            "Keep this enabled in most workflows to avoid constraining the mesh with segments that lie outside "
            "the chosen domain or scope."
        ),
    )
    min_segment_length: Annotated[Length, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Minimum retained river segment length, in projected metres after reprojection. "
            "Use this to discard tiny residual segments created by clipping or noisy hydrography "
            "that would only add mesh complexity without hydraulic meaning."
        ),
    )
    snap_tolerance: Annotated[Length, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Reserved snapping tolerance, in projected metres, for possible future cleanup of nearly coincident "
            "river vertices. The current workflow stores the value in the launcher contract but does not apply an "
            "additional snapping pass."
        ),
    )

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in {"domain_geographic", "file"}:
            raise ValueError("rivers.source must be 'domain_geographic' or 'file'.")
        return token

    @field_validator("path")
    @classmethod
    def _validate_optional_path(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("rivers.path cannot be empty when provided.")
        return text

    @model_validator(mode="after")
    def _validate_file_mode(self) -> MeshCatchmentRiversConfig:
        if self.source == "file" and self.path is None:
            raise ValueError("rivers.path is required when rivers.source='file'.")
        return self


__all__ = ["MeshCatchmentRiversConfig"]
