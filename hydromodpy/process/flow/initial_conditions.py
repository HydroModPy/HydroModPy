# -*- coding: utf-8 -*-
"""
Flow Initial Condition Models
=============================

Typed initial-condition structures for the flow process.

The flow process currently exposes one initial-condition variable (`h`) used
to initialize hydraulic heads before solver assembly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from hydromodpy.process.prototype import InitialCondition as BaseInitialCondition


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
        return self


class FlowInitialConditions(BaseModel):
    """
    Container for flow initial conditions stored in process runtime.

    Keeping one explicit container (instead of bare values) allows the process
    API to remain extensible when adding future IC variables.
    """

    h: FlowInitialCondition = Field(
        ...,
        description="Hydraulic-head initial condition payload.",
    )
