"""Horizontal flow barrier (HFB) payload for the flow process.

Defines :class:`FlowBarrierConfig`, a thin vertical low-permeability barrier on
a polyline, modeled in MODFLOW 6 as a Horizontal Flow Barrier (HFB). It is the
canonical barrier payload, used in two places:

* a general addon ``[flow.sinks_sources.flow_barriers.<id>]`` (modflow6 backend
  only; declaring one activates it, there is no active_bc gate), and
* the dam cutoff wall / grout curtain ``[...lakes.<id>.cutoff_wall]``, where the
  barrier sits on the dam axis and forces the under-dam seepage below the wall.

The barrier trace is a polyline given inline (``line`` = vertex coordinates in
the project CRS) or as a vector file (``line_path``: gpkg / shapefile / GeoJSON).
``depths`` set how deep the barrier reaches below the model top: one value is a
uniform depth, several are interpolated per vertex along the trace. The
resistance is the HFB hydraulic characteristic ``hydchr`` (an inverse time =
K_barrier / thickness_barrier); declare it directly with ``hydchr`` (+
``hydchr_unit``) or let it derive from ``k`` and ``thickness``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units.hydraulic_conductivity import (
    convert_to_m_per_s,
    normalize_m_per_s_unit,
)
from hydromodpy.core.units.leakance import convert_to_per_s, normalize_per_s_unit
from hydromodpy.core.units.length import convert_to_m, factor_to_m


class FlowBarrierConfig(HydroModelBase):
    """Typed payload for one MODFLOW 6 horizontal flow barrier (HFB).

    The barrier is a quasi-impermeable vertical wall on a polyline. It sits on
    the shared mesh faces the trace crosses and spans every top layer down to
    ``depths`` below the model top, so the flow is blocked there and forced
    underneath. The dam cutoff wall is the lake-derived use of this payload.
    """

    auto: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Auto-place the dam cutoff wall (lakes only): the trace is derived at "
            "bind time as the chord across the reservoir at its downstream neck "
            "(the footprint point nearest the catchment outlet), perpendicular to "
            "the outlet-flow direction. Mutually exclusive with line / line_path; "
            "the mesh dam refinement then follows this auto axis too."
        ),
    )
    line: Annotated[list[tuple[float, float]] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Inline barrier-trace vertices [(x, y), ...] in the project CRS. "
            "Mutually exclusive with line_path and auto."
        ),
    )
    line_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Barrier-trace file: a vector polyline (gpkg / shp / GeoJSON) or a CSV of "
            "ordered x,y (or lon,lat) vertices. A bare filename resolves against "
            "<workspace>/data/cutoff_wall/. Alternative to line and auto."
        ),
    )
    depths: Annotated[list[float] | None, Profile.USER] = Field(
        default=None,
        min_length=1,
        description=(
            "Barrier depth [m] below the top (or below crest_elevation). One value is "
            "uniform; several are interpolated per vertex along the trace. The HFB blocks "
            "every layer down to this depth. Mutually exclusive with base_elevation."
        ),
    )
    crest_elevation: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description=(
            "Absolute TOP elevation of the barrier [m, model datum]; defaults to the cell "
            "top (the DEM). Set it when the barrier crest sits below the DEM top."
        ),
    )
    base_elevation: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description=(
            "Absolute BOTTOM elevation of the barrier [m, model datum]. When set, the HFB "
            "spans [base_elevation, crest_elevation or top] and blocks EVERY layer in that "
            "band. Use it to make a full-height dam impervious: the concrete body plus the "
            "grout curtain block all flow from the crest down to the curtain foot (e.g. "
            "base_elevation = 41 m), so nothing seeps across the dam above that. Mutually "
            "exclusive with depths."
        ),
    )
    hydchr: Annotated[float | None, Profile.USER] = Field(
        default=None,
        ge=0.0,
        description=(
            "HFB hydraulic characteristic [1/T] = K_barrier / thickness_barrier. "
            "A near-zero value (e.g. 1e-9 1/s) is a quasi-impermeable wall. "
            "Mutually exclusive with k + thickness."
        ),
    )
    hydchr_unit: Annotated[str, Profile.USER] = Field(
        default="1/s",
        description="Unit of hydchr (1/T): 1/s, 1/day, 1/h, 1/min. Converted to 1/s for MF6.",
    )
    k: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description="Barrier hydraulic conductivity [L/T]; used with thickness when hydchr is unset.",
    )
    k_unit: Annotated[str, Profile.USER] = Field(
        default="m/s",
        description="Unit of k (L/T): m/s, m/day, m/h, m/min. Converted to m/s.",
    )
    thickness: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description="Barrier thickness [L]; used with k when hydchr is unset.",
    )
    thickness_unit: Annotated[str, Profile.USER] = Field(
        default="m",
        description="Unit of thickness (L): m, cm, mm, km. Converted to m.",
    )

    @field_validator("hydchr_unit")
    @classmethod
    def _validate_hydchr_unit(cls, value: str) -> str:
        """Reject a hydchr unit that is not an inverse time (1/T) at config time."""
        normalize_per_s_unit(value)
        return value

    @field_validator("k_unit")
    @classmethod
    def _validate_k_unit(cls, value: str) -> str:
        """Reject a k unit that is not a velocity (L/T) at config time."""
        normalize_m_per_s_unit(value)
        return value

    @field_validator("thickness_unit")
    @classmethod
    def _validate_thickness_unit(cls, value: str) -> str:
        """Reject a thickness unit that is not a length (L) at config time."""
        factor_to_m(value)
        return value

    @field_validator("line")
    @classmethod
    def _validate_line(cls, value):
        """A polyline needs at least two vertices."""
        if value is not None and len(value) < 2:
            raise ValueError("flow barrier line needs at least two vertices.")
        return value

    @field_validator("depths")
    @classmethod
    def _validate_depths(cls, value: list[float] | None) -> list[float] | None:
        """Every depth is a positive distance below the top."""
        if value is not None and any(d <= 0.0 for d in value):
            raise ValueError("flow barrier depths must be positive (metres below the top).")
        return value

    @model_validator(mode="after")
    def _validate_vertical_extent(self) -> FlowBarrierConfig:
        """Exactly one way to set the barrier foot: a depth XOR an absolute base_elevation."""
        if (self.depths is None) == (self.base_elevation is None):
            raise ValueError(
                "flow barrier needs exactly one vertical extent: set depths (below the top / "
                "crest) or base_elevation (an absolute floor), not both and not neither."
            )
        return self

    @model_validator(mode="after")
    def _validate_geometry_source(self) -> FlowBarrierConfig:
        """Exactly one geometry source: auto XOR inline line XOR a vector file."""
        if self.auto:
            if self.line is not None or self.line_path is not None:
                raise ValueError(
                    "flow barrier auto derives the trace; do not also set line or line_path."
                )
            return self
        if (self.line is None) == (self.line_path is None):
            raise ValueError(
                "flow barrier needs exactly one geometry source: set auto, line (inline "
                "coordinates), or line_path (a vector file)."
            )
        return self

    @model_validator(mode="after")
    def _validate_resistance(self) -> FlowBarrierConfig:
        """Exactly one resistance source: hydchr alone XOR (k and thickness)."""
        has_hydchr = self.hydchr is not None
        has_k = self.k is not None
        has_thickness = self.thickness is not None
        if has_hydchr:
            if has_k or has_thickness:
                raise ValueError(
                    "flow barrier resistance is over-specified: set hydchr alone, or k and "
                    "thickness (without hydchr), not a mix."
                )
            return self
        if not (has_k and has_thickness):
            raise ValueError(
                "flow barrier needs a resistance source: set hydchr, or both k and thickness."
            )
        return self

    def effective_hydchr(self) -> float:
        """Return the HFB hydraulic characteristic in 1/s for the solver."""
        if self.hydchr is not None:
            return convert_to_per_s(self.hydchr, unit=self.hydchr_unit, label="flow barrier hydchr")
        k_si = convert_to_m_per_s(self.k, unit=self.k_unit, label="flow barrier k")
        thickness_si = convert_to_m(
            self.thickness, unit=self.thickness_unit, label="flow barrier thickness"
        )
        return k_si / thickness_si


__all__ = ["FlowBarrierConfig"]
