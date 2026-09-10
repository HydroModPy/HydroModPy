"""
Flow Initial Condition Models
=============================

Typed initial-condition structures for the flow process.

This module defines:

- `FlowICTop`, `FlowICTopOffset`, `FlowICBottom`, `FlowICCustom`,
  `FlowICSteadyState`: the five discriminated variants describing how head
  values are initialized.
- `FlowInitialCondition`: discriminated union (on the `type` field) over the
  five variants above.
- `FlowInitialConditions`: the runtime container currently exposing the `h`
  initial condition consumed by the flow process and solver adapters.

The flow process currently exposes one initial-condition variable (`h`) used
to initialize hydraulic heads before solver assembly.

Raw `[flow.ic]` configuration payloads are normalized separately in
`initial_conditions_config.py` before being validated against these models.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, ClassVar, Literal, TypeAlias

from pydantic import Field, TypeAdapter, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import FluxDensityMPerS, Length, check_unit_compatible
from hydromodpy.physics.base import InitialCondition as BaseInitialCondition


class _FlowICBase(BaseInitialCondition):
    """Shared metadata fields and validators for flow IC variants."""

    # The flow process exposes a single IC variable always identified by "h";
    # users never set ``id`` themselves and the [flow.ic] normalizer actively
    # rejects it. Hide it from user-profile templates.
    id: Annotated[str, Profile.DEV] = Field(
        "h",
        description="id of the initial condition (forced to 'h' for flow)",
        json_schema_extra=field_metadata(toml_exclude=True),
    )

    @field_validator("units", mode="before")
    @classmethod
    def _normalize_units(cls, value) -> str:
        """Runtime invariant: IC values are stored in meters; reject anything else."""
        raw_units = str(value).strip() if value is not None else ""
        raw_units = raw_units or "m"
        check_unit_compatible(raw_units, canonical_unit="m", label="length")
        if raw_units != "m":
            raise ValueError("flow.ic.units must be normalized to 'm' in runtime objects")
        return "m"


class FlowICTop(_FlowICBase):
    """Initialize head at the top surface (full aquifer)."""

    units: Annotated[str, Profile.DEV] = Field(
        "m",
        description="Runtime unit for the initial hydraulic-head field.",
        json_schema_extra=field_metadata(toml_exclude=True),
    )
    type: Annotated[Literal["top"], Profile.USER] = Field(
        "top",
        description="Initialize head at the top surface (full aquifer).",
    )


class FlowICTopOffset(_FlowICBase):
    """Initialize head at the top surface minus a vertical offset `value`."""

    type: Annotated[Literal["top_offset"], Profile.USER] = Field(
        "top_offset",
        description="Initialize head at the top surface minus `value`.",
    )
    value: Annotated[Length, Profile.USER] = Field(
        ...,
        description="Vertical offset below the top surface.",
    )


class FlowICBottom(_FlowICBase):
    """Initialize head at the bottom surface (empty aquifer)."""

    units: Annotated[str, Profile.DEV] = Field(
        "m",
        description="Runtime unit for the initial hydraulic-head field.",
        json_schema_extra=field_metadata(toml_exclude=True),
    )
    type: Annotated[Literal["bottom"], Profile.USER] = Field(
        "bottom",
        description="Initialize head at the bottom surface (empty aquifer).",
    )


class FlowICCustom(_FlowICBase):
    """Initialize head with one explicit numeric value."""

    type: Annotated[Literal["custom"], Profile.USER] = Field(
        "custom",
        description="Initialize head with one explicit numeric value.",
    )
    value: Annotated[Length, Profile.USER] = Field(
        ...,
        description="Initial hydraulic-head value.",
    )


class FlowICSteadyState(_FlowICBase):
    """Initialize a transient run from a same-solver steady solve."""

    units: Annotated[str, Profile.DEV] = Field(
        "m",
        description="Runtime unit for the initial hydraulic-head field.",
        json_schema_extra=field_metadata(toml_exclude=True),
    )
    type: Annotated[Literal["steady_state"], Profile.USER] = Field(
        "steady_state",
        description=(
            "Initialize a transient run from a same-solver steady solve using "
            "a documented forcing strategy."
        ),
    )
    source: Annotated[Literal["recharge", "mean_recharge", "prescribed"] | None, Profile.USER] = (
        Field(
            None,
            description=(
                "Forcing source used by the initialization solve. "
                "'mean_recharge' is an alias for source='recharge' with "
                "recharge_statistic='time_mean'. 'prescribed' holds the solve at "
                "the single rate given by `rate` instead of reading the chronicle."
            ),
        )
    )
    recharge_statistic: Annotated[Literal["time_mean"] | None, Profile.USER] = Field(
        None,
        description="Statistic applied to the recharge chronicle.",
    )
    rate: Annotated[FluxDensityMPerS | None, Profile.USER] = Field(
        None,
        description=(
            "Recharge rate the initialization solve is held at, in m/s. "
            "Carries its own unit: '500 mm/yr', '2 mm/day', 1.6e-8. "
            "Required by source='prescribed' and refused by any other source."
        ),
    )
    boundary_condition_policy: Annotated[Literal["first_period"] | None, Profile.USER] = Field(
        None,
        description=(
            "Policy used for transient boundary-condition chronicles during "
            "the steady initialization solve."
        ),
    )

    @model_validator(mode="after")
    def _check_rate_matches_source(self) -> FlowICSteadyState:
        """A prescribed rate and the source that reads it travel together."""
        if self.source == "prescribed" and self.rate is None:
            raise ValueError(
                "flow.ic.rate is required when flow.ic.source='prescribed'; "
                "write the equilibrium rate with its unit, for example rate = '500 mm/yr'"
            )
        if self.rate is not None and self.source != "prescribed":
            raise ValueError(
                "flow.ic.rate is only read when flow.ic.source='prescribed'; "
                f"got source={self.source!r}, which reads the recharge chronicle instead"
            )
        if self.source == "prescribed" and self.recharge_statistic is not None:
            raise ValueError(
                "flow.ic.recharge_statistic describes the chronicle, which "
                "flow.ic.source='prescribed' does not read"
            )
        return self


FlowInitialCondition: TypeAlias = Annotated[
    FlowICTop | FlowICTopOffset | FlowICBottom | FlowICCustom | FlowICSteadyState,
    Field(discriminator="type", description="Flow initial-condition type discriminator."),
]
"""Discriminated union of flow initial-condition variants."""


_FLOW_IC_ADAPTER: TypeAdapter[FlowInitialCondition] = TypeAdapter(FlowInitialCondition)


class FlowInitialConditions(HydroModelBase):
    """
    Container for flow initial conditions stored in process runtime.

    Keeping one explicit container (instead of bare values) allows the process
    API to remain extensible when adding future IC variables.
    """

    # Tell the TOML generator to emit fields from the single nested model
    # directly at the parent section level ([flow.ic] instead of [flow.ic.h]).
    toml_flatten: ClassVar[bool] = True

    h: Annotated[FlowInitialCondition, Profile.USER] = Field(
        default_factory=lambda: FlowICTop(id="h", units="m", description="Initial condition 'h'"),
        description="Hydraulic-head initial condition payload.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_payload(cls, value):
        """Accept a flat IC payload without the `h` wrapper for backward-compat."""
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        if "h" in payload:
            return payload
        if any(key in payload for key in ("type", "value", "units", "unit", "description")):
            return {"h": payload}
        return payload


__all__ = [
    "FlowICBottom",
    "FlowICCustom",
    "FlowICSteadyState",
    "FlowICTop",
    "FlowICTopOffset",
    "FlowInitialCondition",
    "FlowInitialConditions",
]
