# -*- coding: utf-8 -*-
"""
Flow Sink/Source Models
=======================

Typed schemas for flow sink/source declarations.

Current scope:
- pumping/injection wells (`FlowWellConfig`),
- container model for process-level storage (`FlowSinksSourcesConfig`).
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

from pydantic import BaseModel, Field, field_validator


class FlowWellConfig(BaseModel):
    """
    Typed payload for one well source/sink definition.

    Conventions:
    - `cell` uses 0-based `(lay, row, col)` indexing.
    - `flux` may be scalar (constant in time) or vector (one value per stress period).
    """

    cell: tuple[int, int, int] = Field(
        ...,
        description="Cell indices as [lay, row, col] (0-based).",
    )
    flux: float | list[float] = Field(
        ...,
        description=(
            "Well rate [L3/T]. Scalar for constant rate, or one value per stress period."
        ),
    )
    units: str = Field(default="m3/s", description="Units of flux values.")
    description: str = Field(default="", description="Optional well description.")

    @field_validator("cell", mode="before")
    @classmethod
    def _validate_cell(cls, value):
        """Validate/normalize cell addressing into a `(lay, row, col)` tuple."""
        if isinstance(value, Mapping):
            try:
                raw_seq = [value["lay"], value["row"], value["col"]]
            except KeyError as exc:
                raise ValueError("well.cell mapping must define lay, row, and col") from exc
        elif isinstance(value, (list, tuple)):
            raw_seq = list(value)
        else:
            raise TypeError("well.cell must be a mapping or a 3-item list [lay, row, col]")

        if len(raw_seq) != 3:
            raise ValueError("well.cell must contain exactly 3 values: [lay, row, col]")

        parsed: list[int] = []
        for axis, raw_item in zip(("lay", "row", "col"), raw_seq):
            if isinstance(raw_item, bool):
                raise TypeError(f"well.cell.{axis} must be an integer")
            if isinstance(raw_item, Real):
                numeric = float(raw_item)
                if not numeric.is_integer():
                    raise TypeError(f"well.cell.{axis} must be an integer")
                index_value = int(numeric)
            else:
                raise TypeError(f"well.cell.{axis} must be an integer")
            if index_value < 0:
                raise ValueError(f"well.cell.{axis} must be >= 0")
            parsed.append(index_value)
        return tuple(parsed)

    @field_validator("flux", mode="before")
    @classmethod
    def _validate_flux(cls, value):
        """Validate scalar or vector flux payload."""
        if isinstance(value, bool):
            raise TypeError("well.flux must be numeric or a list of numeric values")
        if isinstance(value, Real):
            return float(value)
        if isinstance(value, (list, tuple)):
            if len(value) == 0:
                raise ValueError("well.flux list cannot be empty")
            parsed: list[float] = []
            for idx, raw_item in enumerate(value):
                if isinstance(raw_item, bool) or not isinstance(raw_item, Real):
                    raise TypeError(f"well.flux[{idx}] must be numeric")
                parsed.append(float(raw_item))
            return parsed
        raise TypeError("well.flux must be numeric or a list of numeric values")


class FlowSinksSourcesConfig(BaseModel):
    """Typed container for sinks/sources handled by Flow."""

    wells: dict[str, FlowWellConfig] = Field(
        default_factory=dict,
        description="Mapping of well ids to typed well payloads.",
    )

    @field_validator("wells", mode="before")
    @classmethod
    def _validate_wells(cls, value):
        """Validate wells mapping keys before per-item model validation."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources.wells must be a mapping payload")
        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            well_id = str(raw_key).strip()
            if well_id == "":
                raise ValueError("flow.sinks_sources.wells cannot contain empty well ids")
            out[well_id] = raw_payload
        return out

