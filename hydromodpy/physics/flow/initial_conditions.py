"""
Flow Initial Condition Models
=============================

Typed initial-condition structures for the flow process.

This module defines:

- `FlowICTop`, `FlowICTopOffset`, `FlowICBottom`, `FlowICCustom`,
  `FlowICSteadyState`: the five discriminated variants describing how head
  values are initialized.
- `FlowInitialCondition`: discriminated union (on the `kind` field) over the
  five variants above.
- `FlowInitialConditions`: the runtime container currently exposing the `h`
  initial condition consumed by the flow process and solver adapters.

The flow process currently exposes one initial-condition variable (`h`) used
to initialize hydraulic heads before solver assembly.

`normalize_flow_initial_conditions` turns a raw flat `[flow.ic]` payload into
`FlowInitialConditions`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, ClassVar, Literal, TypeAlias

from pydantic import Field, TypeAdapter, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import (
    FluxDensityMPerS,
    Length,
    check_unit_compatible,
    parse_to_canonical_magnitude,
)
from hydromodpy.physics.base import InitialCondition as BaseInitialCondition
from hydromodpy.physics.base.payloads import declared_unit


class _FlowICBase(BaseInitialCondition):
    """Shared metadata fields and validators for flow IC variants."""

    value: Annotated[object | None, Profile.USER] = Field(
        None,
        description=(
            "Number the starting state reads, in metres: the head for kind 'custom', "
            "the depth below the top for kind 'top_offset'. The other kinds refuse it."
        ),
        json_schema_extra=field_metadata(unit="m"),
    )
    description: Annotated[str, Profile.USER] = Field(
        "",
        description=(
            "Free text about the starting state, kept with the configuration. Unset, it "
            "reads \"Initial condition 'h'\"."
        ),
    )

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
    kind: Annotated[Literal["top"], Profile.USER] = Field(
        "top",
        description="Initialize head at the top surface (full aquifer).",
    )


class FlowICTopOffset(_FlowICBase):
    """Initialize head at the top surface minus a vertical offset `value`."""

    kind: Annotated[Literal["top_offset"], Profile.USER] = Field(
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
    kind: Annotated[Literal["bottom"], Profile.USER] = Field(
        "bottom",
        description="Initialize head at the bottom surface (empty aquifer).",
    )


class FlowICCustom(_FlowICBase):
    """Initialize head with one explicit numeric value."""

    kind: Annotated[Literal["custom"], Profile.USER] = Field(
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
    kind: Annotated[Literal["steady_state"], Profile.USER] = Field(
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


class FlowICSpinupCyclic(_FlowICBase):
    """Initialize a transient run by repeating it until the state stops moving.

    A steady solve carries the forcing's mean and nothing of its history, which is
    the right start for an aquifer whose response time is short against the record.
    It is the wrong one for a deep aquifer, or a lake whose storage integrates
    several seasons: the state those reach depends on the sequence, not the average.

    So the run's own period is repeated, each cycle starting from the head field the
    previous one ended on, until the largest change between two cycles falls below
    ``tol_head``. The cycle is the simulated period itself rather than a window
    chosen separately, which is what makes the antecedent consistent with the
    forcing that is scored, and what lets a calibration trial use it: the cycles are
    auxiliary solves inside one run, exactly as ``steady_state`` already is.

    It costs one extra solve per cycle, per run. Inside a calibration that is per
    trial, so a five-cycle spin-up multiplies a hundred-evaluation phase by six.
    """

    units: Annotated[str, Profile.DEV] = Field(
        "m",
        description="Runtime unit for the initial hydraulic-head field.",
        json_schema_extra=field_metadata(toml_exclude=True),
    )
    kind: Annotated[Literal["spinup_cyclic"], Profile.USER] = Field(
        "spinup_cyclic",
        description=(
            "Repeat the simulated period, each cycle starting from the state the "
            "previous one ended on, until the head field stops moving."
        ),
    )
    max_cycles: Annotated[int, Profile.USER] = Field(
        4,
        ge=1,
        le=50,
        description=(
            "Most cycles the loop may run. A loop that runs out of cycles still hands "
            "back its last state and says so, rather than reporting a convergence that "
            "did not happen. A count."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )
    tol_head: Annotated[Length, Profile.USER] = Field(
        "0.01 m",
        description=(
            "Largest head change between two cycles that counts as settled, anywhere in "
            "the domain. One centimetre is a starting point; the honest check is to "
            "loosen it and see whether what you report moves."
        ),
    )
    first_cycle_from: Annotated[Literal["top", "steady_state"], Profile.USER] = Field(
        "top",
        description=(
            "Where cycle one starts. 'top' is the water table at the surface, which the "
            "cycling then drains. 'steady_state' starts from the equilibrium under the "
            "mean forcing, which is closer and usually saves a cycle."
        ),
    )


FlowInitialCondition: TypeAlias = Annotated[
    FlowICTop
    | FlowICTopOffset
    | FlowICBottom
    | FlowICCustom
    | FlowICSteadyState
    | FlowICSpinupCyclic,
    Field(discriminator="kind", description="Flow initial-condition kind discriminator."),
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
        if any(key in payload for key in ("kind", "value", "units", "unit", "description")):
            return {"h": payload}
        return payload


_IC_VARIANTS = (
    FlowICTop,
    FlowICTopOffset,
    FlowICBottom,
    FlowICCustom,
    FlowICSteadyState,
    FlowICSpinupCyclic,
)
"""Every variant of the flow initial-condition union, in declaration order."""


def normalize_flow_initial_conditions(
    value: object | None,
    *,
    location_prefix: str = "flow.ic",
) -> FlowInitialConditions | None:
    """
    Normalize one flow initial-condition payload into `FlowInitialConditions`.

    Accepted input shapes
    ---------------------
    - `None` or `{}` -> `None`
    - `FlowInitialConditions` -> passthrough
    - any concrete `FlowInitialCondition` variant -> wrapped as `{"h": ...}`
    - flat mapping with keys `kind`, `value`, `unit|units`, `description`,
      `source`, `recharge_statistic`, `rate`, `boundary_condition_policy`;
      `kind` is required for any non-empty mapping;
      `value` and `unit|units` are accepted only for `custom` and
      `top_offset`, and `value` can be numeric or a string like `"12.5 m"`
    """
    if value is None:
        return None
    if isinstance(value, FlowInitialConditions):
        return value
    if isinstance(value, _IC_VARIANTS):
        return FlowInitialConditions(h=value)
    if not isinstance(value, Mapping):
        raise TypeError(
            f"{location_prefix} must be a mapping, FlowInitialCondition, or FlowInitialConditions"
        )

    payload = dict(value)
    if len(payload) == 0:
        return None
    if set(payload) == {"h"} and isinstance(payload["h"], Mapping):
        return FlowInitialConditions.model_validate(payload)

    # Flow IC is intentionally kept flat in TOML (`[flow.ic]`), hence only direct
    # keys are accepted here. The set is DERIVED from the variants of the union,
    # not retyped: a hand-written list is an assertion about the models rather
    # than a fact about them, and it silently refused a new variant's own fields
    # the first time one was added.
    direct_keys = _direct_ic_keys()
    unknown_keys = [str(key).strip() for key in payload if str(key).strip() not in direct_keys]
    if unknown_keys:
        unknown_text = ", ".join(unknown_keys)
        accepted = ", ".join(sorted(direct_keys))
        raise ValueError(
            f"{location_prefix} accepts only direct keys [{accepted}]. Unknown keys: {unknown_text}"
        )

    normalized = _normalize_single_ic_payload(payload, location_prefix=location_prefix)
    return FlowInitialConditions(h=_FLOW_IC_ADAPTER.validate_python(normalized))


def known_ic_types() -> frozenset[str]:
    """Return every ``kind`` discriminator the union declares.

    Derived for the same reason the key set is: the hand-written list refused a
    variant that had just been added to the union, which is a contradiction a reader
    cannot see.
    """
    return frozenset(str(variant.model_fields["kind"].default) for variant in _IC_VARIANTS)


def _direct_ic_keys() -> frozenset[str]:
    """Return every field any initial-condition variant declares."""
    keys: set[str] = set()
    for variant in _IC_VARIANTS:
        keys.update(variant.model_fields)
    # `unit` is the singular spelling the normaliser folds into `units`; it is not a
    # field on any variant, so deriving the set would silently stop accepting it.
    return frozenset(keys | {"unit"})


def _normalize_single_ic_payload(
    payload: Mapping[str, object],
    *,
    location_prefix: str,
) -> dict[str, object]:
    """
    Normalize one single flow initial-condition payload.

    Output keys are aligned with `FlowInitialCondition`.
    """
    payload_dict = dict(payload)

    if "kind" not in payload_dict:
        raise ValueError(f"{location_prefix}.kind is required when {location_prefix} is not empty")
    raw_type = payload_dict.get("kind")
    ic_type = str(raw_type).strip().lower()
    if ic_type not in known_ic_types():
        raise ValueError(
            f"{location_prefix}.kind must be one of: "
            + ", ".join(repr(name) for name in sorted(known_ic_types()))
        )

    explicit_units = declared_unit(payload_dict)
    if ic_type in {"custom", "top_offset"}:
        if "value" not in payload_dict:
            raise ValueError(f"{location_prefix}.value is required when kind='{ic_type}'")
        payload_dict["value"] = parse_to_canonical_magnitude(
            payload_dict["value"],
            location=f"{location_prefix}.value",
            canonical_unit="m",
            explicit_unit=explicit_units,
            length_label="length",
        )
        payload_dict["units"] = "m"
    elif ic_type == "steady_state":
        if "value" in payload_dict:
            raise ValueError(f"{location_prefix}.value is not supported when kind='steady_state'")
        if explicit_units is not None:
            raise ValueError(
                f"{location_prefix}.unit/units is not supported when kind='steady_state'"
            )
        payload_dict.pop("unit", None)
        payload_dict.pop("units", None)
        payload_dict.setdefault("source", "mean_recharge")
        if str(payload_dict.get("source", "")).strip() != "prescribed":
            payload_dict.setdefault("recharge_statistic", "time_mean")
        payload_dict.setdefault("boundary_condition_policy", "first_period")
    else:
        if "value" in payload_dict:
            raise ValueError(
                f"{location_prefix}.value is only supported when kind='custom' or kind='top_offset'"
            )
        if explicit_units is not None:
            raise ValueError(
                f"{location_prefix}.unit/units is only supported when kind='custom' "
                "or kind='top_offset'"
            )
        payload_dict.pop("value", None)
        payload_dict.pop("unit", None)
        payload_dict.pop("units", None)
        for strategy_key in (
            "source",
            "recharge_statistic",
            "rate",
            "boundary_condition_policy",
        ):
            if strategy_key in payload_dict:
                raise ValueError(
                    f"{location_prefix}.{strategy_key} is only supported when kind='steady_state'"
                )

    # Normalize unit alias and apply process defaults.
    if "units" not in payload_dict and "unit" in payload_dict:
        payload_dict["units"] = payload_dict.pop("unit")
    else:
        payload_dict.pop("unit", None)
    payload_dict.setdefault("id", "h")
    payload_dict.setdefault("units", "m")
    payload_dict.setdefault("description", "Initial condition 'h'")
    payload_dict["kind"] = ic_type
    return payload_dict


__all__ = [
    "FlowICBottom",
    "FlowICCustom",
    "FlowICSpinupCyclic",
    "FlowICSteadyState",
    "FlowICTop",
    "FlowICTopOffset",
    "FlowInitialCondition",
    "FlowInitialConditions",
]
