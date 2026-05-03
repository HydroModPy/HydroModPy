from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import ConfigDict, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.base import ProcessSpatial
from hydromodpy.physics.transport.transport_config import TransportConfig


@dataclass
class _TransportComponent:
    """Simple container exposing a `.parameters` mapping."""

    parameters: dict[str, Any] = field(default_factory=dict)

    def set_parameters(self, parameters: Mapping[str, Any] | None = None, **kwargs) -> None:
        if parameters is not None:
            self.parameters.update(dict(parameters))
        if kwargs:
            self.parameters.update(kwargs)


class TransportInitialConditions(HydroModelBase):
    """Transport initial-condition wrapper."""

    model_config = ConfigDict(extra="forbid")

    payload: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="Transport-specific initial-condition mapping.",
    )


class Transport(ProcessSpatial[TransportInitialConditions]):
    def __init__(self, config: TransportConfig | Mapping[str, object] | None = None):
        super().__init__()
        self.config: TransportConfig | None = None
        self.modpath = _TransportComponent()
        self.mt3dms = _TransportComponent()
        self.modflow6gwt = _TransportComponent()
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
        self.modpath.set_parameters(transport_cfg.modpath.parameters.model_dump())
        self.mt3dms.set_parameters(transport_cfg.mt3dms.parameters.model_dump())
        self.modflow6gwt.set_parameters(transport_cfg.modflow6gwt.parameters.model_dump())

        self.parameters["modpath"] = self.modpath.parameters
        self.parameters["mt3dms"] = self.mt3dms.parameters
        self.parameters["modflow6gwt"] = self.modflow6gwt.parameters

    def set_parameters(self, parameters: dict):
        if not isinstance(parameters, Mapping):
            raise TypeError("Transport parameters must be provided as a mapping")

        modpath_payload = parameters.get("modpath")
        if isinstance(modpath_payload, Mapping):
            nested = modpath_payload.get("parameters", modpath_payload)
            if isinstance(nested, Mapping):
                self.modpath.set_parameters(nested)

        mt3dms_payload = parameters.get("mt3dms")
        if isinstance(mt3dms_payload, Mapping):
            nested = mt3dms_payload.get("parameters", mt3dms_payload)
            if isinstance(nested, Mapping):
                self.mt3dms.set_parameters(nested)

        modflow6gwt_payload = parameters.get("modflow6gwt")
        if isinstance(modflow6gwt_payload, Mapping):
            nested = modflow6gwt_payload.get("parameters", modflow6gwt_payload)
            if isinstance(nested, Mapping):
                self.modflow6gwt.set_parameters(nested)

        self.parameters.update(dict(parameters))
        self.parameters["modpath"] = self.modpath.parameters
        self.parameters["mt3dms"] = self.mt3dms.parameters
        self.parameters["modflow6gwt"] = self.modflow6gwt.parameters

    def build_initial_conditions(
        self,
        initial_conditions: object | None,
    ) -> TransportInitialConditions | None:
        if initial_conditions is None:
            return None
        if isinstance(initial_conditions, TransportInitialConditions):
            return initial_conditions
        if not isinstance(initial_conditions, Mapping):
            raise TypeError("Transport initial conditions must be provided as a mapping")
        return TransportInitialConditions(payload=dict(initial_conditions))

    def set_initial_conditions(self, initial_conditions: object | None) -> None:
        super().set_initial_conditions(initial_conditions)

    def set_boundary_conditions(self, boundary_conditions: dict):
        self.boundary_conditions.update(boundary_conditions)

    def set_sinks_sources(self, sinks_sources: dict):
        self.sinks_sources.update(sinks_sources)

    def update_modpath_parameters(self, **kwargs) -> None:
        """Update `transport.modpath.parameters`."""
        self.modpath.set_parameters(kwargs)
        self.parameters["modpath"] = self.modpath.parameters

    def update_mt3dms_parameters(self, **kwargs) -> None:
        """Update `transport.mt3dms.parameters`."""
        self.mt3dms.set_parameters(kwargs)
        self.parameters["mt3dms"] = self.mt3dms.parameters

    def update_modflow6gwt_parameters(self, **kwargs) -> None:
        """Update `transport.modflow6gwt.parameters`."""
        self.modflow6gwt.set_parameters(kwargs)
        self.parameters["modflow6gwt"] = self.modflow6gwt.parameters
