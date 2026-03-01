# -*- coding: utf-8 -*-
"""Typed flow boundary-condition models and constants."""

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

DIRICHLET_BC_CANONICAL_DOMAINS: dict[str, str] = {
    "ocean": "top",
    "stream": "top",
    "north_side": "north side",
    "south_side": "south side",
    "east_side": "east side",
    "west_side": "west side",
}

DIRICHLET_BC_LEGACY_ALIASES: dict[str, str] = {
    "north_boundary": "north_side",
    "south_boundary": "south_side",
    "east_boundary": "east_side",
    "west_boundary": "west_side",
}


class FlowBoundaryConditionConfig(BaseModel):
    """Normalized flow boundary-condition payload."""

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
        if value is None:
            return None
        domain = str(value).strip()
        if domain == "":
            raise ValueError("application_domain cannot be empty")
        if domain not in ALLOWED_BC_APPLICATION_DOMAINS:
            raise ValueError(f"invalid application_domain: {domain}")
        return domain

