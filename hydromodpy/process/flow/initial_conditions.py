# -*- coding: utf-8 -*-
"""Typed flow initial-condition models."""

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
        if self.type == "custom" and self.value is None:
            raise ValueError("flow.ic.value is required when flow.ic.type='custom'")
        return self


class FlowInitialConditions(BaseModel):
    """Flow initial-condition structure stored on ProcessSpatial."""

    h: FlowInitialCondition = Field(
        ...,
        description="Hydraulic-head initial condition payload.",
    )
