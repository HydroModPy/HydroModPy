"""Hierarchical visibility profiles for Pydantic config fields.

A field is visible when ``field_profile <= requested_profile``.
Lower value ⇒ more broadly visible.

Usage::

    from hydromodpy.core.config_kit.profile import Profile

    class FlowConfig(HydroModelBase):
        k_aquifer: Annotated[HydraulicConductivity, Profile.USER] = Field(...)
        solver_inner_tol: Annotated[float, Profile.DEV] = Field(default=1e-6, ...)
        pcg_relaxation: Annotated[float, Profile.EXPERT] = Field(default=0.97, ...)
"""

from __future__ import annotations

from enum import IntEnum


class Profile(IntEnum):
    """Visibility profile for a configuration field."""

    USER = 1  # hydrogeologist: physics, paths, project IO
    DEV = 2  # developer: tolerances, backends, cache flags
    EXPERT = 3  # MODFLOW/Boussinesq/pint internals


__all__ = ["Profile"]
