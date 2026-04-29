"""
Base Module: ProcessSpatial Runtime Base
========================================

Purpose
-------
Provide the abstract, process-agnostic runtime base used by concrete spatial
processes.

What it standardizes
--------------------
- Runtime containers:
  - `parameters`
  - `initial_conditions`
  - `boundary_conditions`
  - `sinks_sources`
- Parameter ingestion from config payloads through
  `set_parameters_from_config(...)`.
- Subclass contract for process-specific behavior:
  - `build_initial_conditions(...)`
  - `set_boundary_conditions(...)`
  - `set_sinks_sources(...)`

Design intent
-------------
Keep this layer generic: no domain-specific rules (flow, transport, etc.)
should be implemented here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import Generic, TypeVar

from hydromodpy.physics.base.boundary_conditions import BoundaryCondition
from hydromodpy.physics.base.initial_conditions import InitialCondition
from hydromodpy.physics.base.process_spatial_config import ProcessSpatialConfig
from hydromodpy.physics.base.sinks_sources import SinkSource

TInitialConditions = TypeVar("TInitialConditions")


def _coerce_field_param(parameter_id: str, raw_parameter: object) -> object:
    """Coerce one raw config value into a runtime parameter object.

    Uses the registered ``FieldParamLike`` factory so this module never
    imports the spatial package.
    """
    from hydromodpy.physics.contracts import FieldParamLike, get_field_param_factory

    if isinstance(raw_parameter, FieldParamLike):
        return raw_parameter
    if not isinstance(raw_parameter, Mapping):
        return raw_parameter

    payload = dict(raw_parameter)
    payload.setdefault("id", parameter_id)
    if "kind" not in payload and "mode" not in payload:
        return raw_parameter
    return get_field_param_factory()(payload)


class ProcessSpatial(ABC, Generic[TInitialConditions]):
    """
    Abstract base class for HydroModPy spatial processes.

    Containers:
    - `parameters`: process parameters (not limited to `FieldParam` objects).
    - `initial_conditions`: one process-specific typed structure.
    - `boundary_conditions`: boundary conditions (`BoundaryCondition`).
    - `sinks_sources`: sinks/sources (domain objects or compatible payloads).
    """

    def __init__(self):
        self.parameters: dict[str, object] = {}
        self.initial_conditions: TInitialConditions | None = None
        self.boundary_conditions: dict[str, BoundaryCondition] = {}
        self.sinks_sources: dict[str, object] = {}
        self.active_sinks_sources: list[str] = []
        self.active_bc: list[str] = []

    @staticmethod
    def _coerce_parameter_from_config(parameter_id: str, raw_parameter: object) -> object:
        """Coerce one raw config value into a runtime parameter object."""
        return _coerce_field_param(parameter_id, raw_parameter)

    def set_parameters_from_config(
        self,
        parameters: Mapping[str, object] | None = None,
        *,
        parameter_ids: Iterable[str] | None = None,
        context_label: str = "parameters",
    ) -> None:
        """
        Build and replace `self.parameters` from a configuration payload.
        """
        if parameters is None:
            self.parameters = {}
            return
        if not isinstance(parameters, Mapping):
            raise TypeError(f"{context_label} must be a mapping payload")

        normalized_parameters: dict[str, object] = {}
        for raw_id, raw_parameter in parameters.items():
            parameter_id = str(raw_id).strip()
            if parameter_id == "":
                raise ValueError(f"{context_label} cannot contain empty parameter ids")
            normalized_parameters[parameter_id] = raw_parameter

        if parameter_ids is None:
            declared_ids = list(normalized_parameters.keys())
        else:
            declared_ids: list[str] = []
            seen_ids: set[str] = set()
            for raw_declared_id in parameter_ids:
                parameter_id = str(raw_declared_id).strip()
                if parameter_id == "":
                    raise ValueError("parameter_ids cannot contain empty values")
                if parameter_id in seen_ids:
                    raise ValueError(f"parameter_ids cannot contain duplicates: {parameter_id}")
                seen_ids.add(parameter_id)
                declared_ids.append(parameter_id)

        selected_parameters: dict[str, object] = {}
        for parameter_id in declared_ids:
            if parameter_id not in normalized_parameters:
                raise KeyError(
                    f"Missing {context_label}.{parameter_id} payload for declared parameter id"
                )
            selected_parameters[parameter_id] = self._coerce_parameter_from_config(
                parameter_id,
                normalized_parameters[parameter_id],
            )
        self.parameters = selected_parameters

    def add_parameter(self, parameter_id: str, parameter: object) -> None:
        """Add or replace one single process parameter entry."""
        normalized_id = str(parameter_id).strip()
        if normalized_id == "":
            raise ValueError("parameter_id cannot be empty")
        self.parameters[normalized_id] = self._coerce_parameter_from_config(
            normalized_id,
            parameter,
        )

    def set_initial_conditions(self, initial_conditions: object | None) -> None:
        """Build and store one process-specific initial-condition structure."""
        self.initial_conditions = self.build_initial_conditions(initial_conditions)

    @abstractmethod
    def build_initial_conditions(
        self,
        initial_conditions: object | None,
    ) -> TInitialConditions | None:
        """Convert raw payload to one typed process-specific structure."""

    @abstractmethod
    def set_boundary_conditions(self, boundary_conditions: dict):
        """Define or update boundary conditions."""

    def add_boundary_condition(self, boundary_condition: BoundaryCondition):
        """Add one boundary condition object."""
        self.boundary_conditions[boundary_condition.id] = boundary_condition

    @abstractmethod
    def set_sinks_sources(self, sinks_sources: dict):
        """Define or update sinks/sources."""

    def add_sink_source(self, sink_source: SinkSource):
        """Add one sink/source object."""
        self.sinks_sources[sink_source.id] = sink_source


__all__ = [
    "InitialCondition",
    "BoundaryCondition",
    "SinkSource",
    "ProcessSpatialConfig",
    "TInitialConditions",
    "ProcessSpatial",
]
