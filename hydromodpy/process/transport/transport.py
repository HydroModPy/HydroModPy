# -*- coding: utf-8 -*-

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hydromodpy.process.process import Process
from hydromodpy.process.transport.transport_config import TransportConfig


@dataclass
class _TransportComponent:
    """Simple container exposing a `.parameters` mapping."""

    parameters: dict[str, Any] = field(default_factory=dict)

    def set_parameters(self, parameters: Mapping[str, Any] | None = None, **kwargs) -> None:
        if parameters is not None:
            self.parameters.update(dict(parameters))
        if kwargs:
            self.parameters.update(kwargs)

class Transport(Process):
    def __init__(self, config: TransportConfig | Mapping[str, object] | None = None):
        super().__init__()
        self.config: TransportConfig | None = None
        self.particle = _TransportComponent()
        self.conc = _TransportComponent()
        if config is not None:
            self.set_config(config)

    def set_config(self, config: TransportConfig | Mapping[str, object]) -> None:
        if isinstance(config, TransportConfig):
            transport_cfg = config
        elif isinstance(config, Mapping):
            transport_cfg = TransportConfig.model_validate(dict(config))
        else:
            raise TypeError("Transport config must be a TransportConfig instance or a mapping")

        self.config = transport_cfg
        self.particle.set_parameters(transport_cfg.particle.parameters.model_dump())
        self.conc.set_parameters(transport_cfg.conc.parameters.model_dump())

        self.parameters["particle"] = self.particle.parameters
        self.parameters["conc"] = self.conc.parameters

    def set_parameters(self, parameters: dict):
        if not isinstance(parameters, Mapping):
            raise TypeError("Transport parameters must be provided as a mapping")

        particle_payload = parameters.get("particle")
        if isinstance(particle_payload, Mapping):
            nested = particle_payload.get("parameters", particle_payload)
            if isinstance(nested, Mapping):
                self.particle.set_parameters(nested)

        conc_payload = parameters.get("conc")
        if isinstance(conc_payload, Mapping):
            nested = conc_payload.get("parameters", conc_payload)
            if isinstance(nested, Mapping):
                self.conc.set_parameters(nested)

        self.parameters.update(dict(parameters))
        self.parameters["particle"] = self.particle.parameters
        self.parameters["conc"] = self.conc.parameters

    def set_variables(self, variables: dict):
        self.variables.update(variables)

    def set_initial_conditions(self, initial_conditions: dict):
        self.initial_conditions.update(initial_conditions)

    def set_boundary_conditions(self, boundary_conditions: dict):
        self.boundary_conditions.update(boundary_conditions)

    def set_sinks_sources(self, sinks_sources: dict):
        self.sinks_sources.update(sinks_sources)

    def update_particle_parameters(self, **kwargs) -> None:
        """Compatibility helper to update `transport.particle.parameters`."""
        self.particle.set_parameters(kwargs)
        self.parameters["particle"] = self.particle.parameters

    def update_conc_parameters(self, **kwargs) -> None:
        """Compatibility helper to update `transport.conc.parameters`."""
        self.conc.set_parameters(kwargs)
        self.parameters["conc"] = self.conc.parameters

    def update_mt3dms_parameters(self, **kwargs) -> None:
        """Backward-compatible alias now routed to `transport.conc.parameters`."""
        self.update_conc_parameters(**kwargs)

