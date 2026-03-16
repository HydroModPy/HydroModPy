# -*- coding: utf-8 -*-
"""
Flow Boundary Condition Models
=============================

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

from numbers import Real
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from hydromodpy.support.units import normalize_length_unit, normalize_m2_per_s_unit

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


class FlowBoundaryForcingConstantConfig(BaseModel):
    """One constant head forcing applied to every stress period."""

    value: float = Field(
        ...,
        description="Constant boundary head in the same units as the parent boundary.",
    )

    @field_validator("value", mode="before")
    @classmethod
    def _validate_value(cls, value):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("boundary.forcing.value must be numeric")
        return float(value)


class FlowBoundaryForcingCsvConfig(BaseModel):
    """CSV-backed boundary forcing resolved at runtime against simulation.time."""

    path_file: Path = Field(..., description="Path to the CSV chronicle file.")
    sep: str = Field(default=",", description="CSV delimiter.")
    date_column: str = Field(default="date", description="CSV column containing timestamps.")
    date_format: str | None = Field(
        default=None,
        description="Optional datetime format passed to pandas.to_datetime.",
    )
    value_column: str = Field(
        default="value",
        description="CSV column containing boundary head values.",
    )
    fill_method: Literal["ffill", "bfill"] = Field(
        default="ffill",
        description="Gap-filling policy used when a stress period has no direct sample.",
    )
    aggregate: Literal["mean", "last"] = Field(
        default="mean",
        description="Stress-period aggregation method.",
    )

    @field_validator("sep", "date_column", "value_column", mode="before")
    @classmethod
    def _validate_text_fields(cls, value, info):
        text = str(value).strip()
        if text == "":
            raise ValueError(f"boundary.forcing.{info.field_name} cannot be empty")
        return text


class FlowBoundaryForcingConfig(BaseModel):
    """Launcher-facing boundary forcing declaration."""

    mode: Literal["constant", "csv"] = Field(
        ...,
        description="Boundary forcing mode consumed by launcher runtime.",
    )
    units: str | None = Field(
        default=None,
        description="Source units of forcing values before runtime conversion.",
    )
    value: float | None = Field(default=None)
    path_file: Path | None = Field(default=None)
    sep: str = Field(default=",")
    date_column: str = Field(default="date")
    date_format: str | None = Field(default=None)
    value_column: str = Field(default="value")
    fill_method: Literal["ffill", "bfill"] = Field(default="ffill")
    aggregate: Literal["mean", "last"] = Field(default="mean")

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


class FlowBoundaryConditionConfig(BaseModel):
    """
    Normalized flow boundary-condition payload.

    Expected usage:
    - produced by boundary-condition normalizers,
    - consumed by `Flow` runtime and solver adapter layers.
    """

    id: str = Field(..., description="Boundary-condition identifier.")
    value: float | list[float] | None = Field(
        default=None,
        description="Boundary-condition value, scalar or one value per stress period.",
    )
    description: str = Field("", description="Boundary-condition description.")
    units: str = Field("", description="Boundary-condition units.")
    type: Literal["dirichlet", "cauchy", "robin"] = Field(
        "dirichlet",
        description="Boundary-condition type.",
    )
    data_value: bool = Field(
        False,
        description="If True, boundary-condition values are sourced from data.",
    )
    forcing: FlowBoundaryForcingConfig | None = Field(
        default=None,
        description=(
            "Optional runtime forcing declaration for lateral Dirichlet boundaries. "
            "Supported modes: 'constant' and 'csv'. The launcher resolves this "
            "payload to boundary.value using [simulation.time]."
        ),
    )
    application_domain: str | None = Field(
        None,
        description=(
            "Boundary-application domain. Supported values are: top, north side, "
            "south side, east side, west side."
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
        if self.type != "dirichlet" and self.forcing is not None:
            raise ValueError("boundary.forcing is only supported for Dirichlet boundaries")
        if self.forcing is not None and self.id not in SIDE_DIRICHLET_BC_IDS:
            raise ValueError(
                "boundary.forcing is only supported for side Dirichlet boundaries: "
                "north_side, south_side, east_side, west_side"
            )
        if self.value is None and self.forcing is None:
            raise ValueError("boundary requires either value or forcing")
        if self.type == "dirichlet":
            if self.forcing is None:
                normalized_units = normalize_length_unit(str(self.units).strip() or "m")
                if normalized_units != "m":
                    raise ValueError(
                        "boundary.units must be normalized to 'm' for runtime Dirichlet values"
                    )
                self.units = "m"
            else:
                parent_units = str(self.units).strip() or "m"
                forcing_units = getattr(self.forcing, "units", None)
                parent_units_explicit = "units" in self.model_fields_set
                forcing_units_explicit = "units" in self.forcing.model_fields_set
                if forcing_units_explicit:
                    normalized_forcing_units = normalize_length_unit(
                        str(forcing_units).strip() or "m"
                    )
                    if parent_units_explicit:
                        normalized_parent_units = normalize_length_unit(parent_units)
                        if (
                            normalized_parent_units != "m"
                            and normalized_parent_units != normalized_forcing_units
                        ):
                            raise ValueError(
                                "boundary.units conflicts with boundary.forcing.units"
                            )
                else:
                    normalized_forcing_units = normalize_length_unit(parent_units)
                self.forcing = self.forcing.model_copy(
                    update={"units": normalized_forcing_units}
                )
                self.units = "m"
        else:
            normalized_units = normalize_m2_per_s_unit(str(self.units).strip() or "m2/s")
            if normalized_units != "m2/s":
                raise ValueError(
                    "boundary.units must be normalized to 'm2/s' for runtime Cauchy/Robin values"
                )
            self.units = "m2/s"
        return self

