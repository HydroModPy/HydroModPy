"""
Base Module: Boundary-Condition Normalization Helpers
=====================================================

Provides utility functions to convert raw configuration payloads into validated
`BoundaryCondition` instances.
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.physics.base.boundary_conditions import BoundaryCondition


def normalize_boundary_condition_payload(
    value: object,
    *,
    default_id: str = "boundary_condition",
    location_prefix: str = "process.bc",
) -> BoundaryCondition:
    """Normalize one generic boundary-condition payload into `BoundaryCondition`."""
    if isinstance(value, BoundaryCondition):
        return value
    if not isinstance(value, Mapping):
        raise TypeError(f"{location_prefix} must be a mapping payload")

    payload = dict(value)
    payload.setdefault("id", default_id)
    if "unit" in payload:
        payload.setdefault("units", payload["unit"])
        payload.pop("unit", None)
    return BoundaryCondition.model_validate(payload)
