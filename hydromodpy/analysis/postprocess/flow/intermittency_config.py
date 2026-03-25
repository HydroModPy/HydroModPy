"""Pydantic schema for intermittency postprocess options."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

class IntermittencyPostprocessConfig(BaseModel):
    """Intermittency indicators derived from flow accumulation flux."""

    model_config = ConfigDict(extra="forbid")

    yearly: bool = Field(
        default=False,
        description="Compute yearly intermittency indicators from accumulation flux.",
    )
    monthly: bool = Field(
        default=True,
        description="Compute monthly intermittency indicators from accumulation flux.",
    )
    weekly: bool = Field(
        default=False,
        description="Compute weekly intermittency indicators from accumulation flux.",
    )
    daily: bool = Field(
        default=False,
        description="Compute daily intermittency indicators from accumulation flux.",
    )


__all__ = ["IntermittencyPostprocessConfig"]
