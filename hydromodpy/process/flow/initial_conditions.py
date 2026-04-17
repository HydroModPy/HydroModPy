# -*- coding: utf-8 -*-
"""
Flow Initial Condition Models
=============================

Typed initial-condition structures for the flow process.

This module defines:
- `FlowInitialCondition`: one validated payload describing how head values are
  initialized (`top`, `bottom`, or `custom`).
- `FlowInitialConditions`: the runtime container currently exposing the `h`
  initial condition consumed by the flow process and solver adapters.

The flow process currently exposes one initial-condition variable (`h`) used
to initialize hydraulic heads before solver assembly.

Raw `[flow.ic]` configuration payloads are normalized separately in
`initial_conditions_config.py` before being validated against these models.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from hydromodpy.process.contracts import InitialCondition as BaseInitialCondition
from hydromodpy.core.units import normalize_length_unit


class FlowInitialCondition(BaseInitialCondition):
    """
    Flow initial condition used by MODFLOW head initialization.

    Semantics
    ---------
    - `type="top"`: initialize head at top surface.
    - `type="bottom"`: initialize head at bottom surface.
    - `type="custom"`: initialize with one explicit numeric value.
    """

    type: Literal["top", "bottom", "custom"] = Field(
        "custom",
        description=(
            "Type of initial condition ('top', 'bottom', or 'custom'). "
            "'top' means a full aquifer, 'bottom' means an empty aquifer."
        ),
    )
    value: float | None = Field(
        None,
        description="Initial hydraulic-head value. Required when type='custom'.",
    )

    @model_validator(mode="after")
    def _validate_custom_value(self) -> "FlowInitialCondition":
        """Require `value` whenever `type='custom'`."""
        if self.type == "custom" and self.value is None:
            raise ValueError("flow.ic.value is required when flow.ic.type='custom'")
        normalized_units = normalize_length_unit(str(self.units).strip() or "m")
        if normalized_units != "m":
            raise ValueError("flow.ic.units must be normalized to 'm' in runtime objects")
        self.units = "m"
        return self


class FlowInitialConditions(BaseModel):
    """
    Container for flow initial conditions stored in process runtime.

    Keeping one explicit container (instead of bare values) allows the process
    API to remain extensible when adding future IC variables.
    """

    # Tell the TOML generator to emit fields from the single nested model
    # directly at the parent section level ([flow.ic] instead of [flow.ic.h]).
    toml_flatten: ClassVar[bool] = True

    h: FlowInitialCondition = Field(
        default_factory=lambda: FlowInitialCondition(type="top", id="h", units="m", description="Initial condition 'h'"),
        description="Hydraulic-head initial condition payload.",
    )
