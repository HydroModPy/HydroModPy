from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.model.process_spatial import ProcessSpatial
from hydromodpy.model.transport.transport_config import TransportConfig


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

    payload: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="Transport-specific initial-condition mapping.",
    )


_ENGINES: tuple[str, ...] = ("modpath", "mt3dms", "modflow6gwt", "modflow6prt")
"""The transport engines, each with its own ``[transport.<engine>.parameters]``."""


class Transport(ProcessSpatial[TransportInitialConditions]):
    def __init__(self, config: TransportConfig | Mapping[str, object] | None = None):
        super().__init__()
        self.config: TransportConfig | None = None
        self.modpath = _TransportComponent()
        self.mt3dms = _TransportComponent()
        self.modflow6gwt = _TransportComponent()
        self.modflow6prt = _TransportComponent()
        if config is not None:
            self.set_config(config)

    def set_config(self, config: TransportConfig | Mapping[str, object]) -> None:
        """Take the ``[transport]`` section and copy the parameters of each engine.

        Parameters
        ----------
        config
            A :class:`TransportConfig`, or a mapping validated into one.

        Raises
        ------
        TypeError
            If ``config`` is neither.
        pydantic.ValidationError
            If the mapping is not a valid ``[transport]`` section.
        """
        if isinstance(config, TransportConfig):
            transport_cfg = config
        elif isinstance(config, Mapping):
            transport_cfg = TransportConfig.model_validate(dict(config))
        else:
            raise TypeError("Transport config must be a TransportConfig instance or a mapping")

        self.config = transport_cfg
        for engine in _ENGINES:
            component = getattr(self, engine)
            component.set_parameters(getattr(transport_cfg, engine).parameters.model_dump())
            self.parameters[engine] = component.parameters

    def set_parameters(self, parameters: dict):
        """Merge parameters into the engines they name.

        Parameters
        ----------
        parameters
            Mapping keyed by engine: ``modpath``, ``mt3dms``, ``modflow6gwt`` or
            ``modflow6prt``. Each value is the engine's parameters, or a mapping
            holding them under ``parameters``. Other keys are kept as they are.

        Raises
        ------
        TypeError
            If ``parameters`` is not a mapping.
        """
        if not isinstance(parameters, Mapping):
            raise TypeError("Transport parameters must be provided as a mapping")

        for engine in _ENGINES:
            payload = parameters.get(engine)
            if isinstance(payload, Mapping):
                nested = payload.get("parameters", payload)
                if isinstance(nested, Mapping):
                    getattr(self, engine).set_parameters(nested)

        self.parameters.update(dict(parameters))
        for engine in _ENGINES:
            self.parameters[engine] = getattr(self, engine).parameters

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

    def set_boundary_conditions(self, boundary_conditions: dict):
        self.boundary_conditions.update(boundary_conditions)

    def set_sinks_sources(self, sinks_sources: dict):
        self.sinks_sources.update(sinks_sources)
