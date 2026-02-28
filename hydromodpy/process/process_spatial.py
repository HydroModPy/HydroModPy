# -*- coding: utf-8 -*-
"""
Abstract base for HydroModPy spatial processes.

This module centralizes the main runtime containers:
- parameters
- variables
- initial_conditions
- boundary_conditions
- sinks_sources

Note:
The `parameters` container is intentionally generic. A parameter can be a
`FieldParam`, but it can also be another kind of field/metadata (for example a
velocity field produced by another process). Do not assume all
`parameters` entries are `FieldParam` instances.

During `set_parameters_from_config`, a compatible payload is converted to
`FieldParam`. If the payload is not compatible, it is preserved as-is.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, Field

from hydromodpy.field.core.field_param import FieldParam


class Variable(BaseModel):
    id: str = Field(..., description="id of the variable (ex: h, etc.)")
    value: float = Field(..., description="Value of the variable")
    description: str = Field("", description="Description of the variable")
    units: str = Field("", description="Units of the variable")


class InitialCondition(BaseModel):
    id: str = Field(..., description="id of the initial condition (ex: h0, etc.)")
    type: Literal["top", "bot", "custom"] = Field(
        "custom",
        description="Type of initial condition ('top', 'bot', or 'custom')",
    )
    value: float = Field(..., description="Value of the initial condition")
    description: str = Field("", description="Description of the initial condition")
    units: str = Field("", description="Units of the initial condition")


class BoundaryCondition(BaseModel):
    id: str = Field(..., description="id of the boundary condition (ex: h_BC, etc.)")
    value: float = Field(..., description="Value of the boundary condition")
    description: str = Field("", description="Description of the boundary condition")
    units: str = Field("", description="Units of the boundary condition")
    type: str = Field(
        "Dirichlet",
        description="Type of the boundary condition (e.g., 'Dirichlet', 'Neumann', 'Cauchy')",
    )
    data_value: bool = Field(
        False,
        description="If True, boundary condition value is sourced from data",
    )


class SinkSource(BaseModel):
    id: str = Field(..., description="id of the sink/source (ex: Q_well, etc.)")
    value: float = Field(..., description="Value of the sink/source")
    description: str = Field("", description="Description of the sink/source")
    units: str = Field("", description="Units of the sink/source")
    link_data: list = Field(
        default_factory=list,
        description="List of the id of the data linked to this parameter",
    )


class ProcessSpatial(ABC):
    """
    Abstract base class for HydroModPy spatial processes.

    This class factors common runtime containers shared by process
    implementations (flow, transport, etc.) and exposes a standard method to
    load parameters from configuration payloads.

    Containers are dictionaries keyed by identifier:
    - `parameters`: process parameters (not limited to `FieldParam` objects).
    - `variables`: state variables (`Variable`).
    - `initial_conditions`: initial conditions (`InitialCondition`).
    - `boundary_conditions`: boundary conditions (`BoundaryCondition`).
    - `sinks_sources`: sinks/sources (domain objects or compatible payloads).

    Extension contract:
    subclasses implement `set_variables`, `set_initial_conditions`,
    `set_boundary_conditions`, and `set_sinks_sources` for their domain logic.
    """

    def __init__(self):
        self.parameters: dict[str, object] = {}
        self.variables: dict[str, Variable] = {}
        self.initial_conditions: dict[str, InitialCondition] = {}
        self.boundary_conditions: dict[str, BoundaryCondition] = {}
        self.sinks_sources: dict[str, object] = {}

    @staticmethod
    def _coerce_parameter_from_config(parameter_id: str, raw_parameter: object) -> object:
        """
        Coerce one raw config value into a runtime parameter object.

        If `raw_parameter` is already a `FieldParam`, it is returned unchanged.
        If it is a mapping, an `id` is injected when missing and conversion via
        `FieldParam.from_dict` is attempted. On parsing failure (or for non-mapping
        values), the original object is returned unchanged.
        """
        if isinstance(raw_parameter, FieldParam):
            return raw_parameter
        if not isinstance(raw_parameter, Mapping):
            return raw_parameter

        payload = dict(raw_parameter)
        payload.setdefault("id", parameter_id)
        try:
            return FieldParam.from_dict(payload)
        except Exception:
            return raw_parameter

    def set_parameters_from_config(
        self,
        parameters: Mapping[str, object] | None = None,
        *,
        parameter_ids: Iterable[str] | None = None,
        context_label: str = "parameters",
    ) -> None:
        """
        Build and replace `self.parameters` from a configuration payload.

        This method is the canonical entry point to load process parameters from
        config. It enforces parameter id normalization/selection and applies a
        best-effort conversion to `FieldParam` for compatible mapping payloads.

        Parameters
        ----------
        parameters:
            Mapping `{parameter_id: payload}` coming from config.
            - If `None`, the container is cleared (`self.parameters = {}`).
            - Keys are normalized to stripped strings and must be non-empty.
            - Values can be:
              - a `FieldParam` instance (kept as-is),
              - a mapping compatible with `FieldParam.from_dict` (converted),
              - any other object (kept as-is).
        parameter_ids:
            Optional explicit ordered list of parameter ids to keep. When
            provided, only those ids are loaded and in the given order.
            Validation rules:
            - ids are stripped strings,
            - empty ids are rejected,
            - duplicate ids are rejected,
            - each declared id must exist in `parameters`.
        context_label:
            Human-readable label used in error messages to identify the config
            section (default: `"parameters"`).

        Raises
        ------
        TypeError
            If `parameters` is not a mapping.
        ValueError
            If a parameter id is empty, or `parameter_ids` contains empty/duplicate
            values.
        KeyError
            If `parameter_ids` declares an id that is missing from `parameters`.

        Notes
        -----
        Conversion is intentionally tolerant:
        if a mapping payload cannot be parsed as `FieldParam`, the original value
        is preserved instead of failing hard.
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

    @abstractmethod
    def set_variables(self, variables: dict):
        """Define or update state variables."""

    def add_variable(self, variable: Variable):
        """Add one variable object."""
        self.variables[variable.id] = variable

    @abstractmethod
    def set_initial_conditions(self, initial_conditions: dict):
        """Define or update initial conditions."""

    def add_initial_condition(self, initial_condition: InitialCondition):
        """Add one initial condition object."""
        self.initial_conditions[initial_condition.id] = initial_condition

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


# Backward-compatibility class alias; prefer ProcessSpatial in new code.
Process = ProcessSpatial
