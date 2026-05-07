"""
Flow Boundary Condition Models
==============================

Typed boundary-condition schema used by the flow process.

This module defines:
- allowed application domains,
- canonical Dirichlet identifiers,
- the normalized Pydantic model used across config and runtime parsing.

Mini schema
-----------
Input key (Dirichlet)          -> Canonical application domain
`ocean`, `stream`              -> `top`
`north_side`                   -> `north side`
`south_side`                   -> `south side`
`east_side`                    -> `east side`
`west_side`                    -> `west side`

Validation flow:
`[flow.bc.*]` payload -> `FlowBoundaryConditionConfig` -> runtime `Flow.boundary_conditions`
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr
from hydromodpy.core.units import (
    Length,
    canonical_unit_short_form,
    check_unit_compatible,
    parse_to_canonical_magnitude,
)
from hydromodpy.physics.base.forcing import FlowTimeAggregate, FlowTimeFillMethod

ALLOWED_BC_APPLICATION_DOMAINS = {
    "top",
    "north side",
    "west side",
    "east side",
    "south side",
}
"""Supported target domains for boundary-condition application.

These values are used by validators and normalizers to reject unsupported
domains early. If one payload defines `application_domain`, the value must be
in this set.
"""

DIRICHLET_BC_CANONICAL_DOMAINS: dict[str, str] = {
    "ocean": "top",
    "stream": "top",
    "north_side": "north side",
    "south_side": "south side",
    "east_side": "east side",
    "west_side": "west side",
}
"""Mapping from canonical Dirichlet identifiers to their implied domain.

This table encodes the process convention:
- key is the boundary-condition id expected in `[flow.bc.dirichlet.<id>]`,
- value is the unique `application_domain` allowed for this id.

Example:
- `north_side` must map to `north side` and cannot target any other domain.
"""

SIDE_DIRICHLET_BC_IDS = {
    "north_side",
    "south_side",
    "east_side",
    "west_side",
}
"""Dirichlet ids eligible for launcher-managed transient forcing."""


_BOUNDARY_UNIT_TARGETS: dict[str, tuple[str, str]] = {
    "m": ("m", "length"),
    "m2/s": ("m**2/s", "hydraulic-conductance"),
}

BoundaryKind: TypeAlias = Literal["dirichlet", "cauchy", "robin"]


def _extract_explicit_boundary_units(payload: Mapping[str, object]) -> str | None:
    """Resolve explicitly declared units from payload."""
    if "units" in payload:
        return str(payload["units"])
    if "unit" in payload:
        return str(payload["unit"])
    return None


def _coerce_boundary_value_and_units(
    *,
    payload: Mapping[str, object],
    location_prefix: str,
    default_units: str,
) -> tuple[float, str]:
    if "value" not in payload:
        raise ValueError(f"{location_prefix}.value is required")
    target = _BOUNDARY_UNIT_TARGETS.get(default_units)
    if target is None:
        raise ValueError(f"Unsupported boundary unit target: {default_units}")
    canonical_unit, label = target
    value_si = parse_to_canonical_magnitude(
        payload["value"],
        location=f"{location_prefix}.value",
        canonical_unit=canonical_unit,
        explicit_unit=_extract_explicit_boundary_units(payload),
        length_label=label,
    )
    return value_si, default_units


def _normalize_dirichlet_forcing_units(
    *,
    payload: Mapping[str, object],
    location_prefix: str,
) -> str:
    explicit_units = _extract_explicit_boundary_units(payload)
    forcing_payload = payload.get("forcing")
    forcing_units: str | None = None
    if isinstance(forcing_payload, Mapping):
        raw_forcing_units = forcing_payload.get("units")
        if raw_forcing_units is not None:
            forcing_units = str(raw_forcing_units)
    if explicit_units is None and forcing_units is None:
        return "m"
    try:
        normalized_parent_units = (
            canonical_unit_short_form(explicit_units, canonical_unit="m", label="length")
            if explicit_units is not None
            else None
        )
        normalized_forcing_units = (
            canonical_unit_short_form(forcing_units, canonical_unit="m", label="length")
            if forcing_units is not None
            else None
        )
    except ValueError as exc:
        raise ValueError(
            f"{location_prefix}.units and {location_prefix}.forcing.units must be compatible "
            "with meters (for example m, cm, mm, km)."
        ) from exc
    if (
        normalized_parent_units is not None
        and normalized_forcing_units is not None
        and normalized_parent_units != normalized_forcing_units
    ):
        raise ValueError(f"{location_prefix}.units conflicts with {location_prefix}.forcing.units")
    return normalized_forcing_units or normalized_parent_units or "m"


def _extract_support_label(payload: Mapping[str, object]) -> str | None:
    """Return one optional explicit support label."""
    raw_value = payload.get("support_label")
    if raw_value is None:
        return None
    return str(raw_value)


class FlowBoundaryForcingConstantConfig(HydroModelBase):
    """One constant head forcing applied to every stress period."""

    value: Annotated[Length, Profile.USER] = Field(
        ...,
        description="Constant boundary head in the same units as the parent boundary.",
    )


class FlowBoundaryForcingCsvConfig(HydroModelBase):
    """CSV-backed boundary forcing resolved at runtime against simulation.time."""

    path_file: Annotated[Path, Profile.DEV] = Field(
        ..., description="Path to the CSV chronicle file."
    )
    sep: Annotated[NonEmptyStr, Profile.DEV] = Field(default=",", description="CSV delimiter.")
    date_column: Annotated[NonEmptyStr, Profile.DEV] = Field(
        default="date", description="CSV column containing timestamps."
    )
    date_format: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Optional datetime format passed to pandas.to_datetime.",
    )
    value_column: Annotated[NonEmptyStr, Profile.DEV] = Field(
        default="value",
        description="CSV column containing boundary head values.",
    )
    fill_method: Annotated[FlowTimeFillMethod, Profile.DEV] = Field(
        default="ffill",
        description="Gap-filling policy used when a stress period has no direct sample.",
    )
    aggregate: Annotated[FlowTimeAggregate, Profile.DEV] = Field(
        default="mean",
        description="Stress-period aggregation method.",
    )


class FlowBoundaryForcingConfig(HydroModelBase):
    """Launcher-facing boundary forcing declaration."""

    mode: Annotated[Literal["constant", "csv"], Profile.USER] = Field(
        ...,
        description="Boundary forcing mode consumed by launcher runtime.",
    )
    units: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Source units of forcing values before runtime conversion.",
    )
    value: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Constant boundary head value used when mode='constant'.",
    )
    path_file: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description="CSV file path containing time-series boundary head values when mode='csv'.",
    )
    sep: Annotated[str, Profile.DEV] = Field(
        default=",",
        description="CSV column separator.",
    )
    date_column: Annotated[str, Profile.DEV] = Field(
        default="date",
        description="CSV column containing timestamps.",
    )
    date_format: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Optional datetime format passed to pandas.to_datetime.",
    )
    value_column: Annotated[str, Profile.DEV] = Field(
        default="value",
        description="CSV column containing boundary head values.",
    )
    fill_method: Annotated[FlowTimeFillMethod, Profile.DEV] = Field(
        default="ffill",
        description="Gap-filling policy used when a stress period has no direct sample.",
    )
    aggregate: Annotated[FlowTimeAggregate, Profile.DEV] = Field(
        default="mean",
        description="Stress-period aggregation method.",
    )

    @model_validator(mode="after")
    def _validate_mode_payload(self):
        if self.mode == "constant":
            if self.value is None:
                raise ValueError("boundary.forcing.mode='constant' requires value")
            return self
        if self.path_file is None:
            raise ValueError("boundary.forcing.mode='csv' requires path_file")
        return self

    def as_constant(self) -> FlowBoundaryForcingConstantConfig:
        if self.mode != "constant":
            raise ValueError("boundary forcing is not in constant mode")
        return FlowBoundaryForcingConstantConfig(value=self.value)

    def as_csv(self) -> FlowBoundaryForcingCsvConfig:
        if self.mode != "csv":
            raise ValueError("boundary forcing is not in csv mode")
        return FlowBoundaryForcingCsvConfig(
            path_file=self.path_file,
            sep=self.sep,
            date_column=self.date_column,
            date_format=self.date_format,
            value_column=self.value_column,
            fill_method=self.fill_method,
            aggregate=self.aggregate,
        )


class FlowBoundaryConditionConfig(HydroModelBase):
    """
    Normalized flow boundary-condition payload.

    Expected usage:
    - produced by boundary-condition normalizers,
    - consumed by `Flow` runtime and solver adapter layers.
    """

    id: Annotated[str, Profile.USER] = Field(..., description="Boundary-condition identifier.")
    value: Annotated[float | list[float] | None, Profile.USER] = Field(
        default=None,
        description="Boundary-condition value, scalar or one value per stress period.",
    )
    description: Annotated[str, Profile.USER] = Field(
        "", description="Boundary-condition description."
    )
    units: Annotated[str, Profile.DEV] = Field("", description="Boundary-condition units.")
    kind: Annotated[BoundaryKind, Profile.USER] = Field(
        "dirichlet",
        description="Boundary-condition kind discriminator.",
    )
    data_value: Annotated[bool, Profile.DEV] = Field(
        False,
        description="If True, boundary-condition values are sourced from data.",
    )
    forcing: Annotated[FlowBoundaryForcingConfig | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional runtime forcing declaration for lateral Dirichlet boundaries. "
            "Supported modes: 'constant' and 'csv'. The launcher resolves this "
            "payload to boundary.value using [simulation.time]."
        ),
    )
    application_domain: Annotated[str | None, Profile.USER] = Field(
        None,
        description=(
            "Boundary-application domain. Supported values are: top, north side, "
            "south side, east side, west side."
        ),
    )
    support_label: Annotated[NonEmptyStr | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional explicit runtime support label used by unstructured backends "
            "to select one target support independently from the canonical boundary id."
        ),
    )

    @field_validator("application_domain")
    @classmethod
    def _validate_application_domain(cls, value: str | None) -> str | None:
        """Ensure provided application domain belongs to the supported set."""
        if value is None:
            return None
        domain = str(value).strip()
        if domain == "":
            raise ValueError("application_domain cannot be empty")
        if domain not in ALLOWED_BC_APPLICATION_DOMAINS:
            raise ValueError(f"invalid application_domain: {domain}")
        return domain

    @field_validator("value", mode="before")
    @classmethod
    def _validate_value(cls, value):
        """Normalize scalar or vector boundary-head values."""
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError("boundary.value must be numeric or a list of numeric values")
        if isinstance(value, Real):
            return float(value)
        if isinstance(value, (list, tuple)):
            if len(value) == 0:
                raise ValueError("boundary.value list cannot be empty")
            parsed: list[float] = []
            for idx, raw_item in enumerate(value):
                if isinstance(raw_item, bool) or not isinstance(raw_item, Real):
                    raise TypeError(f"boundary.value[{idx}] must be numeric")
                parsed.append(float(raw_item))
            return parsed
        raise TypeError("boundary.value must be numeric or a list of numeric values")

    @model_validator(mode="after")
    def _validate_runtime_payload(self):
        """Enforce one coherent value/forcing grammar."""
        if self.forcing is not None and self.value is not None:
            raise ValueError("boundary.value and boundary.forcing are mutually exclusive")
        if self.forcing is not None and self.data_value:
            raise ValueError("boundary.forcing cannot be combined with data_value=True")
        if self.kind != "dirichlet" and self.forcing is not None:
            raise ValueError("boundary.forcing is only supported for Dirichlet boundaries")
        if self.forcing is not None and self.id not in SIDE_DIRICHLET_BC_IDS:
            raise ValueError(
                "boundary.forcing is only supported for side Dirichlet boundaries: "
                "north_side, south_side, east_side, west_side"
            )
        if self.value is None and self.forcing is None:
            raise ValueError("boundary requires either value or forcing")
        if self.kind == "dirichlet":
            if self.forcing is None:
                raw_units = str(self.units).strip() or "m"
                check_unit_compatible(raw_units, canonical_unit="m", label="length")
                if raw_units != "m":
                    raise ValueError(
                        "boundary.units must be normalized to 'm' for runtime Dirichlet values"
                    )
                object.__setattr__(self, "units", "m")
            else:
                parent_units = str(self.units).strip() or "m"
                forcing_units = getattr(self.forcing, "units", None)
                parent_units_explicit = "units" in self.model_fields_set
                forcing_units_explicit = "units" in self.forcing.model_fields_set
                if forcing_units_explicit:
                    normalized_forcing_units = canonical_unit_short_form(
                        str(forcing_units).strip() or "m",
                        canonical_unit="m",
                        label="length",
                    )
                    if parent_units_explicit:
                        normalized_parent_units = canonical_unit_short_form(
                            parent_units, canonical_unit="m", label="length"
                        )
                        if (
                            normalized_parent_units != "m"
                            and normalized_parent_units != normalized_forcing_units
                        ):
                            raise ValueError("boundary.units conflicts with boundary.forcing.units")
                else:
                    normalized_forcing_units = canonical_unit_short_form(
                        parent_units, canonical_unit="m", label="length"
                    )
                object.__setattr__(
                    self,
                    "forcing",
                    self.forcing.model_copy(update={"units": normalized_forcing_units}),
                )
                object.__setattr__(self, "units", "m")
        else:
            raw_units = str(self.units).strip() or "m2/s"
            check_unit_compatible(raw_units, canonical_unit="m**2/s", label="hydraulic-conductance")
            if raw_units != "m2/s":
                raise ValueError(
                    "boundary.units must be normalized to 'm2/s' for runtime Cauchy/Robin values"
                )
            object.__setattr__(self, "units", "m2/s")
        return self


class DirichletBC(FlowBoundaryConditionConfig):
    """Dirichlet flow boundary condition."""

    kind: Annotated[Literal["dirichlet"], Profile.USER] = Field(
        default="dirichlet",
        description="Boundary-condition kind discriminator.",
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_payload(cls, data):
        if not isinstance(data, Mapping):
            raise TypeError("Dirichlet boundary payload must be a mapping")
        payload = dict(data)
        location_prefix = str(payload.pop("_location_prefix", "flow.bc"))

        bc_id = str(payload.get("id", "")).strip()
        if bc_id == "":
            raise ValueError(f"{location_prefix}.id is required")
        payload["id"] = bc_id

        raw_kind = str(payload.get("kind", "dirichlet")).strip().lower()
        if raw_kind != "dirichlet":
            raise ValueError(f"{location_prefix}.kind must be 'dirichlet'")
        payload["kind"] = "dirichlet"

        forcing_payload = payload.get("forcing")
        if forcing_payload is not None:
            if payload.get("value") is not None:
                raise ValueError(
                    f"{location_prefix}.value and {location_prefix}.forcing are mutually exclusive"
                )
            if not isinstance(forcing_payload, Mapping):
                raise TypeError(f"{location_prefix}.forcing must be a mapping")
            source_units = _normalize_dirichlet_forcing_units(
                payload=payload,
                location_prefix=location_prefix,
            )
            forcing = dict(forcing_payload)
            forcing["units"] = source_units
            payload["forcing"] = forcing
            payload["value"] = None
            payload["units"] = "m"
        else:
            value, units = _coerce_boundary_value_and_units(
                payload=payload,
                location_prefix=location_prefix,
                default_units="m",
            )
            payload["value"] = value
            payload["units"] = units

        if "unit" in payload:
            payload.pop("unit")

        inferred_application_domain = DIRICHLET_BC_CANONICAL_DOMAINS.get(bc_id)
        raw_application_domain = payload.get("application_domain")
        if inferred_application_domain is not None:
            if raw_application_domain is None:
                payload["application_domain"] = inferred_application_domain
            else:
                if not isinstance(raw_application_domain, str):
                    raise TypeError(f"{location_prefix}.application_domain must be a string")
                application_domain = raw_application_domain.strip()
                if application_domain == "":
                    raise ValueError(f"{location_prefix}.application_domain cannot be empty")
                if application_domain not in ALLOWED_BC_APPLICATION_DOMAINS:
                    raise ValueError(
                        f"{location_prefix}.application_domain contains an invalid value: "
                        f"{application_domain}"
                    )
                if application_domain != inferred_application_domain:
                    raise ValueError(
                        f"{location_prefix}.application_domain='{application_domain}' "
                        f"does not match inferred domain '{inferred_application_domain}' "
                        f"for key '{bc_id}'"
                    )
                payload["application_domain"] = application_domain
        elif raw_application_domain is not None:
            if not isinstance(raw_application_domain, str):
                raise TypeError(f"{location_prefix}.application_domain must be a string")
            application_domain = raw_application_domain.strip()
            if application_domain == "":
                raise ValueError(f"{location_prefix}.application_domain cannot be empty")
            if application_domain not in ALLOWED_BC_APPLICATION_DOMAINS:
                raise ValueError(
                    f"{location_prefix}.application_domain contains an invalid value: "
                    f"{application_domain}"
                )
            payload["application_domain"] = application_domain

        payload["data_value"] = bool(payload.get("data_value", False))
        description = str(
            payload.get(
                "description",
                f"Dirichlet boundary condition '{bc_id}' on "
                f"{payload.get('application_domain', 'unspecified domain')}",
            )
        )
        if payload["data_value"] and "(data_value=True)" not in description:
            description = f"{description} (data_value=True)"
        payload["description"] = description
        payload["support_label"] = _extract_support_label(payload)
        return payload


class _DrainageBC(FlowBoundaryConditionConfig):
    """Shared Cauchy/Robin boundary payload behavior."""

    @classmethod
    def _canonicalize_drainage_payload(cls, data, *, expected_kind: str):
        if not isinstance(data, Mapping):
            raise TypeError(f"{expected_kind.capitalize()} boundary payload must be a mapping")
        payload = dict(data)
        location_prefix = str(payload.pop("_location_prefix", "flow.bc"))

        bc_id = str(payload.get("id", "drainage")).strip()
        if bc_id == "":
            raise ValueError(f"{location_prefix}.id cannot be empty")
        payload["id"] = bc_id

        raw_kind = str(payload.get("kind", expected_kind)).strip().lower()
        if raw_kind != expected_kind:
            raise ValueError(f"{location_prefix}.kind must be '{expected_kind}'")
        payload["kind"] = expected_kind

        value, units = _coerce_boundary_value_and_units(
            payload=payload,
            location_prefix=location_prefix,
            default_units="m2/s",
        )
        payload["value"] = value
        payload["units"] = units
        if "unit" in payload:
            payload.pop("unit")

        raw_application_domain = payload.get("application_domain")
        if not isinstance(raw_application_domain, str):
            raise TypeError(f"{location_prefix}.application_domain must be a string")
        application_domain = raw_application_domain.strip()
        if application_domain == "":
            raise ValueError(f"{location_prefix}.application_domain cannot be empty")
        if application_domain not in ALLOWED_BC_APPLICATION_DOMAINS:
            raise ValueError(
                f"{location_prefix}.application_domain contains an invalid value: "
                f"{application_domain}"
            )
        payload["application_domain"] = application_domain
        payload["description"] = str(
            payload.get(
                "description",
                f"{expected_kind.capitalize()} drainage boundary condition on {application_domain}",
            )
        )
        payload["data_value"] = bool(payload.get("data_value", False))
        payload["support_label"] = _extract_support_label(payload)
        return payload


class CauchyBC(_DrainageBC):
    """Cauchy flow boundary condition."""

    kind: Annotated[Literal["cauchy"], Profile.USER] = Field(
        default="cauchy",
        description="Boundary-condition kind discriminator.",
    )
    forcing: Annotated[None, Profile.DEV] = Field(
        default=None,
        exclude=True,
        description="Cauchy boundaries do not support runtime head forcing.",
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_payload(cls, data):
        return cls._canonicalize_drainage_payload(data, expected_kind="cauchy")


class RobinBC(_DrainageBC):
    """Robin flow boundary condition."""

    kind: Annotated[Literal["robin"], Profile.USER] = Field(
        default="robin",
        description="Boundary-condition kind discriminator.",
    )
    forcing: Annotated[None, Profile.DEV] = Field(
        default=None,
        exclude=True,
        description="Robin boundaries do not support runtime head forcing.",
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_payload(cls, data):
        return cls._canonicalize_drainage_payload(data, expected_kind="robin")


BCEntry: TypeAlias = Annotated[
    DirichletBC | CauchyBC | RobinBC,
    Field(discriminator="kind"),
]
