"""The generic initial-condition, boundary-condition and sink/source models, and their normalizers.

Process-specific schemas (``flow``, ``transport``) build on these three models.
Each normalizer turns a raw payload into its model, sets a default ``id`` and
reads ``unit`` as ``units``.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import Annotated, TypeVar

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class InitialCondition(HydroModelBase):
    id: Annotated[str, Profile.USER] = Field(
        ..., description="id of the initial condition (ex: h0, etc.)"
    )
    value: Annotated[object | None, Profile.USER] = Field(
        None,
        description="Process-specific initial-condition value payload.",
    )
    description: Annotated[str, Profile.USER] = Field(
        "", description="Description of the initial condition"
    )
    units: Annotated[str, Profile.USER] = Field("", description="Units of the initial condition")


class BoundaryCondition(HydroModelBase):
    id: Annotated[str, Profile.USER] = Field(
        ..., description="id of the boundary condition (ex: h_BC, etc.)"
    )
    value: Annotated[float, Profile.USER] = Field(
        ..., description="Value of the boundary condition"
    )
    description: Annotated[str, Profile.USER] = Field(
        "", description="Description of the boundary condition"
    )
    units: Annotated[str, Profile.DEV] = Field("", description="Units of the boundary condition")
    type: Annotated[str, Profile.USER] = Field(
        "Dirichlet",
        description="Type of the boundary condition (e.g., 'Dirichlet', 'Neumann', 'Cauchy')",
    )
    data_value: Annotated[bool, Profile.DEV] = Field(
        False,
        description="If True, boundary condition value is sourced from data",
    )


class SinkSource(HydroModelBase):
    id: Annotated[str, Profile.USER] = Field(
        ..., description="id of the sink/source (ex: Q_well, etc.)"
    )
    value: Annotated[float, Profile.USER] = Field(..., description="Value of the sink/source")
    description: Annotated[str, Profile.USER] = Field(
        "", description="Description of the sink/source"
    )
    units: Annotated[str, Profile.DEV] = Field("", description="Units of the sink/source")
    link_data: Annotated[list, Profile.DEV] = Field(
        default_factory=list,
        description="List of the id of the data linked to this parameter",
    )


def declared_unit(payload: Mapping[str, object]) -> str | None:
    """The unit a payload declares, under ``units`` or ``unit``, or None."""
    if "units" in payload:
        return str(payload["units"])
    if "unit" in payload:
        return str(payload["unit"])
    return None


_Model = TypeVar("_Model", InitialCondition, BoundaryCondition, SinkSource)


def _normalize(model: type[_Model], value: object, default_id: str, location_prefix: str) -> _Model:
    """Validate a mapping payload as ``model``, with a default ``id`` and ``unit`` read as ``units``."""
    if isinstance(value, model):
        return value
    if not isinstance(value, Mapping):
        raise TypeError(f"{location_prefix} must be a mapping payload")
    payload = dict(value)
    payload.setdefault("id", default_id)
    if "unit" in payload:
        payload.setdefault("units", payload.pop("unit"))
    return model.model_validate(payload)


def normalize_initial_condition_payload(
    value: object,
    *,
    default_id: str = "initial_condition",
    location_prefix: str = "process.ic",
) -> InitialCondition:
    """Normalize one generic initial-condition payload, a mapping or a number, into `InitialCondition`."""
    if isinstance(value, bool):
        raise TypeError(f"{location_prefix} must be a mapping or numeric value")
    if isinstance(value, Real):
        return InitialCondition(id=default_id, value=float(value))
    return _normalize(InitialCondition, value, default_id, location_prefix)


def normalize_boundary_condition_payload(
    value: object,
    *,
    default_id: str = "boundary_condition",
    location_prefix: str = "process.bc",
) -> BoundaryCondition:
    """Normalize one generic boundary-condition payload into `BoundaryCondition`."""
    return _normalize(BoundaryCondition, value, default_id, location_prefix)


def normalize_sink_source_payload(
    value: object,
    *,
    default_id: str = "sink_source",
    location_prefix: str = "process.sinks_sources",
) -> SinkSource:
    """Normalize one generic sink/source payload into `SinkSource`."""
    return _normalize(SinkSource, value, default_id, location_prefix)
