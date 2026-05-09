"""
Flow Initial Condition Models
=============================

Typed initial-condition structures for the flow process.

This module defines:
- `FlowInitialCondition`: one validated payload describing how head values are
  initialized (`top`, `top_offset`, `bottom`, `custom`, or `steady_state`).
- `FlowInitialConditions`: the runtime container currently exposing the `h`
  initial condition consumed by the flow process and solver adapters.

The flow process currently exposes one initial-condition variable (`h`) used
to initialize hydraulic heads before solver assembly.

Raw `[flow.ic]` configuration payloads are normalized separately in
`initial_conditions_config.py` before being validated against these models.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import Length, check_unit_compatible
from hydromodpy.physics.base import InitialCondition as BaseInitialCondition


class FlowInitialCondition(BaseInitialCondition):
    """
    Flow initial condition used by flow solver head initialization.

    Semantics
    ---------
    - `type="top"`: initialize head at top surface.
    - `type="top_offset"`: initialize head at top surface minus `value`.
    - `type="bottom"`: initialize head at bottom surface.
    - `type="custom"`: initialize with one explicit numeric value.
    - `type="steady_state"`: initialize a transient run from a same-solver
      steady solve using a documented forcing strategy.
    """

    # The flow process exposes a single IC variable always identified by "h";
    # users never set ``id`` themselves and the [flow.ic] normalizer actively
    # rejects it. Hide it from user-profile templates.
    id: Annotated[str, Profile.DEV] = Field(
        "h", description="id of the initial condition (forced to 'h' for flow)"
    )

    type: Annotated[
        Literal["top", "top_offset", "bottom", "custom", "steady_state"], Profile.USER
    ] = Field(
        "top",
        description=(
            "Type of initial condition ('top', 'top_offset', 'bottom', 'custom', "
            "or 'steady_state'). "
            "'top' means a full aquifer, 'top_offset' means top minus value, "
            "'bottom' means an empty aquifer, and 'steady_state' means a same-solver "
            "steady solve is used to initialize a transient run."
        ),
    )
    value: Annotated[Length | None, Profile.USER] = Field(
        None,
        description=(
            "Initial hydraulic-head value. Required when type='custom'; "
            "vertical offset below top when type='top_offset'; not accepted "
            "for top, bottom, or steady_state."
        ),
    )
    source: Annotated[Literal["recharge", "mean_recharge"] | None, Profile.USER] = (
        Field(
            None,
            description=(
                "For type='steady_state', forcing source used by the initialization "
                "solve. 'mean_recharge' is an alias for source='recharge' with "
                "recharge_statistic='time_mean'."
            ),
        )
    )
    recharge_statistic: Annotated[Literal["time_mean"] | None, Profile.USER] = Field(
        None,
        description="For type='steady_state', statistic applied to the recharge chronicle.",
    )
    boundary_condition_policy: Annotated[
        Literal["first_period"] | None, Profile.USER
    ] = Field(
        None,
        description=(
            "For type='steady_state', policy used for transient boundary-condition "
            "chronicles during the steady initialization solve."
        ),
    )

    @model_validator(mode="after")
    def _validate_custom_value(self) -> FlowInitialCondition:
        """Require `value` whenever the selected IC semantics needs it."""
        if self.type in {"custom", "top_offset"} and self.value is None:
            raise ValueError(
                f"flow.ic.value is required when flow.ic.type='{self.type}'"
            )
        if self.type in {"top", "bottom"} and self.value is not None:
            raise ValueError(
                "flow.ic.value is only supported when flow.ic.type is "
                "'custom' or 'top_offset'"
            )
        if self.type != "steady_state":
            if self.source is not None:
                raise ValueError(
                    "flow.ic.source is only supported when flow.ic.type='steady_state'"
                )
            if self.recharge_statistic is not None:
                raise ValueError(
                    "flow.ic.recharge_statistic is only supported when "
                    "flow.ic.type='steady_state'"
                )
            if self.boundary_condition_policy is not None:
                raise ValueError(
                    "flow.ic.boundary_condition_policy is only supported when "
                    "flow.ic.type='steady_state'"
                )
        elif self.value is not None:
            raise ValueError(
                "flow.ic.value is not supported when flow.ic.type='steady_state'"
            )
        raw_units = str(self.units).strip() or "m"
        # Runtime invariant: IC values are stored in meters (magnitude) and the
        # label must already reflect that; anything else is a normalization bug
        # upstream in ``initial_conditions_config``.
        check_unit_compatible(raw_units, canonical_unit="m", label="length")
        if raw_units != "m":
            raise ValueError(
                "flow.ic.units must be normalized to 'm' in runtime objects"
            )
        object.__setattr__(self, "units", "m")
        return self


class FlowInitialConditions(HydroModelBase):
    """
    Container for flow initial conditions stored in process runtime.

    Keeping one explicit container (instead of bare values) allows the process
    API to remain extensible when adding future IC variables.
    """

    model_config = ConfigDict(extra="forbid")

    # Tell the TOML generator to emit fields from the single nested model
    # directly at the parent section level ([flow.ic] instead of [flow.ic.h]).
    toml_flatten: ClassVar[bool] = True

    h: Annotated[FlowInitialCondition, Profile.USER] = Field(
        default_factory=lambda: FlowInitialCondition(
            type="top", id="h", units="m", description="Initial condition 'h'"
        ),
        description="Hydraulic-head initial condition payload.",
    )
