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

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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


class FlowBoundaryConditionConfig(BaseModel):
    """
    Normalized flow boundary-condition payload.

    Expected usage:
    - produced by boundary-condition normalizers,
    - consumed by `Flow` runtime and solver adapter layers.
    """

    id: str = Field(..., description="Boundary-condition identifier.")
    value: float = Field(..., description="Boundary-condition value.")
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

