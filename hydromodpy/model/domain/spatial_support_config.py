from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import CellSamplingDensity, NonEmptyStr
from hydromodpy.core.units.registry import UREG
from hydromodpy.core.units.types import LengthMeters


def _to_meters(value: object, *, label: str) -> float:
    """Convert a length-like value (number or pint string) to meters.

    A number without a unit is read in meters, written as a number or as a
    text, like the elevation of the DEM. Any other text must carry a length
    unit, which it keeps. A length that is not finite is refused.
    """
    if value is None:
        raise ValueError(f"{label} cannot be None.")
    if isinstance(value, bool):
        raise TypeError(f"{label} rejects boolean input.")
    if isinstance(value, (int, float)):
        return _finite_metres(float(value), value=value, label=label)
    if isinstance(value, str):
        token = value.strip()
        if token == "":
            raise ValueError(f"{label}: empty length string is not allowed.")
        try:
            number = float(token)
        except ValueError:
            number = None
        if number is not None:
            return _finite_metres(number, value=value, label=label)
        try:
            quantity = UREG(token)
        except Exception as exc:  # noqa: BLE001 - pint raises half a dozen kinds on such text
            raise ValueError(
                f"{label}: {value!r} is not a number nor a length with a unit."
            ) from exc
        # pint reads "1,5" as 15 and "10 %" as 0.1, both without a dimension, so
        # only a plain number above may be read in meters.
        if not hasattr(quantity, "check") or not quantity.check("[length]"):
            raise ValueError(
                f"{label}: {value!r} is not a length; write it in metres or with a length unit."
            )
        return _finite_metres(float(quantity.to("m").magnitude), value=value, label=label)
    raise TypeError(f"{label}: unsupported length value type {type(value).__name__}.")


def _finite_metres(metres: float, *, value: object, label: str) -> float:
    if not math.isfinite(metres):
        raise ValueError(f"{label}: {value!r} is not finite.")
    return metres


def _normalize_cuts_and_labels(value: object, *, key: str, kind: str) -> object:
    """Read the cuts ``key`` of a bands or rings table and trim its labels.

    A relative cut is a share in ]0, 1[. An absolute cut is a length read in
    meters, and it must be > 0.
    """
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    coordinate_mode = str(payload.get("coordinate_mode", "relative")).strip().lower()
    raw_cuts = payload.get(key) or []
    if not isinstance(raw_cuts, list):
        return payload
    normalized: list[float] = []
    for index, raw_cut in enumerate(raw_cuts):
        if coordinate_mode == "relative":
            value_m = float(raw_cut)
            if not 0.0 < value_m < 1.0:
                raise ValueError(f"Relative {kind} {key} must lie strictly between 0 and 1.")
        else:
            value_m = _to_meters(raw_cut, label=f"domain.supports.{key}[{index}]")
            if value_m <= 0.0:
                raise ValueError(f"Absolute {kind} {key} must be > 0.")
        normalized.append(value_m)
    payload[key] = normalized
    raw_labels = payload.get("labels") or []
    if isinstance(raw_labels, list):
        payload["labels"] = [str(raw).strip() for raw in raw_labels]
    return payload


class DomainSupportBaseConfig(HydroModelBase):
    """Base schema for one named spatial-support declaration.

    Concrete variants are unified through :data:`DomainSupportConfig`,
    a discriminated union over the ``kind`` literal.
    """


class GeneratedBandsSupportConfig(DomainSupportBaseConfig):
    """Analytical bands split along one cartesian axis."""

    kind: Annotated[Literal["generated_bands"], Profile.USER] = Field(
        description=(
            "What the zones of this support are: bands along an axis, concentric rings, "
            "the catchment zones, or the geology units."
        ),
    )
    axis: Annotated[Literal["x", "y"], Profile.USER] = Field(
        default="x",
        description="Axis the bands are cut along.",
        json_schema_extra={
            "value_docs": {
                "x": "Cuts bands across the west-east axis: each band spans a range of x.",
                "y": "Cuts bands across the south-north axis: each band spans a range of y.",
            }
        },
    )
    coordinate_mode: Annotated[Literal["relative", "absolute"], Profile.USER] = Field(
        default="relative",
        description=(
            "How the coordinates of this support are read: as shares of the domain from "
            "0 to 1 ('relative'), or as lengths converted to metres ('absolute')."
        ),
    )
    breaks: Annotated[list[float | str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered break coordinates delimiting consecutive bands. "
            "With coordinate_mode='relative', values are fractions in ]0,1[. "
            "With coordinate_mode='absolute', values are converted to metres."
        ),
    )
    labels: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Ordered band labels. Length must be len(breaks)+1.",
    )
    default_cell_samples_per_axis: Annotated[CellSamplingDensity, Profile.DEV] = Field(
        default=8,
        description="Sub-sampling resolution per cell axis used when rasterizing band masks.",
        json_schema_extra=field_metadata(unit="-"),
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_breaks_and_labels(cls, value):
        return _normalize_cuts_and_labels(value, key="breaks", kind="generated_bands")

    @model_validator(mode="after")
    def _validate_consistency(self) -> GeneratedBandsSupportConfig:
        if self.breaks != sorted(self.breaks):
            raise ValueError("domain.supports.<id>.breaks must be strictly increasing.")
        if len(set(self.breaks)) != len(self.breaks):
            raise ValueError("domain.supports.<id>.breaks cannot contain duplicates.")
        if any(label == "" for label in self.labels):
            raise ValueError("domain.supports.<id>.labels cannot contain empty values.")
        if len(self.labels) != len(self.breaks) + 1:
            raise ValueError("domain.supports.<id>.labels length must be len(breaks) + 1.")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("domain.supports.<id>.labels cannot contain duplicates.")
        return self


class GeneratedRingsSupportConfig(DomainSupportBaseConfig):
    """Analytical concentric rings centered on one cartesian point."""

    kind: Annotated[Literal["generated_rings"], Profile.USER] = Field(
        description=(
            "What the zones of this support are: bands along an axis, concentric rings, "
            "the catchment zones, or the geology units."
        ),
    )
    coordinate_mode: Annotated[Literal["relative", "absolute"], Profile.USER] = Field(
        default="relative",
        description=(
            "How the coordinates of this support are read: as shares of the domain from "
            "0 to 1 ('relative'), or as lengths converted to metres ('absolute')."
        ),
    )
    radii: Annotated[list[float | str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered ring radii delimiting consecutive concentric zones. "
            "With coordinate_mode='relative', values are fractions in ]0,1[ "
            "of the largest inscribed circle around the chosen center. "
            "With coordinate_mode='absolute', values are converted to metres."
        ),
    )
    labels: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Ordered ring labels. Length must be len(radii)+1.",
    )
    center_x: Annotated[LengthMeters | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional x coordinate of the ring center (projected metres). "
            "Defaults to the domain midpoint. Accepts inline units, e.g. '500 m'."
        ),
    )
    center_y: Annotated[LengthMeters | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional y coordinate of the ring center (projected metres). "
            "Defaults to the domain midpoint. Accepts inline units."
        ),
    )
    default_cell_samples_per_axis: Annotated[CellSamplingDensity, Profile.DEV] = Field(
        default=8,
        description="Sub-sampling resolution per cell axis used when rasterizing ring masks.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_radii_and_labels(cls, value):
        return _normalize_cuts_and_labels(value, key="radii", kind="generated_rings")

    @model_validator(mode="after")
    def _validate_rings_consistency(self) -> GeneratedRingsSupportConfig:
        if self.radii != sorted(self.radii):
            raise ValueError("domain.supports.<id>.radii must be strictly increasing.")
        if len(set(self.radii)) != len(self.radii):
            raise ValueError("domain.supports.<id>.radii cannot contain duplicates.")
        if any(label == "" for label in self.labels):
            raise ValueError("domain.supports.<id>.labels cannot contain empty values.")
        if len(self.labels) != len(self.radii) + 1:
            raise ValueError("domain.supports.<id>.labels length must be len(radii) + 1.")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("domain.supports.<id>.labels cannot contain duplicates.")
        return self


class CatchmentZonesSupportConfig(DomainSupportBaseConfig):
    """Support built from catchment/domain zonation already prepared in setup."""

    kind: Annotated[Literal["catchment_zones"], Profile.USER] = Field(
        description=(
            "What the zones of this support are: bands along an axis, concentric rings, "
            "the catchment zones, or the geology units."
        ),
    )
    source_zone_id: Annotated[NonEmptyStr, Profile.USER] = Field(
        default="catchment",
        description="Domain zone id providing the source catchment zonation.",
    )
    default_cell_samples_per_axis: Annotated[CellSamplingDensity, Profile.DEV] = Field(
        default=8,
        description="Sub-sampling resolution per cell axis used when rasterizing zone masks.",
    )


class GeologySupportConfig(DomainSupportBaseConfig):
    """Support backed by the geology data manager."""

    kind: Annotated[Literal["geology"], Profile.USER] = Field(
        description=(
            "What the zones of this support are: bands along an axis, concentric rings, "
            "the catchment zones, or the geology units."
        ),
    )


DomainSupportConfig = Annotated[
    GeneratedBandsSupportConfig
    | GeneratedRingsSupportConfig
    | CatchmentZonesSupportConfig
    | GeologySupportConfig,
    Field(
        discriminator="kind",
        description="Discriminated union of spatial-support kinds selected by kind tag.",
    ),
]
