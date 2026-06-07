"""Shared process contracts used by HydroModPy internals.

This module provides the explicit import path for generic process-layer
building blocks such as ``ProcessSpatial`` and ``ProcessSpatialConfig``,
plus structural Protocols (``LoadResultProto``, ``FieldParamLike``) used
to type spatial- and data-layer inputs without importing them.

The factory hooks defined here let physics-layer code consume spatial
field-parameter constructors without statically importing the spatial
package. The bootstrap layer (``hydromodpy._bootstrap``) registers the
concrete callables before any runtime use.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

from hydromodpy.physics.base import (
    BoundaryCondition,
    InitialCondition,
    ProcessSpatial,
    ProcessSpatialConfig,
    SinkSource,
)


@runtime_checkable
class LoadResultProto(Protocol):
    """Structural view of ``data.contracts.LoadResult`` used by physics.

    Physics-layer binders consume data-manager outputs through this
    Protocol so the physics package never imports the data package.
    """

    points: list
    fields: list

    @property
    def has_points(self) -> bool: ...

    @property
    def has_fields(self) -> bool: ...


@runtime_checkable
class FieldParamLike(Protocol):
    """Structural view of ``spatial.field.core.field_param.FieldParam``.

    Physics-layer code consumes field-parameter objects through this
    Protocol so the physics package never imports the spatial package.
    Concrete instances are built by the registered factory (see
    ``register_field_param_factory``).
    """

    identifier: str
    kind: str
    unit: str
    value: float | None


FieldParamFactory = Callable[[Mapping[str, Any]], FieldParamLike]
FieldParamPayloadResolver = Callable[..., dict[str, Any]]
FieldParamPayloadValidator = Callable[[Mapping[str, Any]], dict[str, Any]]
FieldAggregator = Callable[[LoadResultProto], Any]


_FIELD_PARAM_FACTORY: FieldParamFactory | None = None
_FIELD_PARAM_PAYLOAD_RESOLVER: FieldParamPayloadResolver | None = None
_FIELD_PARAM_PAYLOAD_VALIDATOR: FieldParamPayloadValidator | None = None
_FIELD_AGGREGATOR: FieldAggregator | None = None


def register_field_param_factory(factory: FieldParamFactory) -> None:
    """Register the concrete ``FieldParamLike`` factory used by physics."""
    global _FIELD_PARAM_FACTORY
    _FIELD_PARAM_FACTORY = factory


def register_field_param_payload_resolver(resolver: FieldParamPayloadResolver) -> None:
    """Register the concrete field-param TOML payload resolver."""
    global _FIELD_PARAM_PAYLOAD_RESOLVER
    _FIELD_PARAM_PAYLOAD_RESOLVER = resolver


def register_field_param_payload_validator(validator: FieldParamPayloadValidator) -> None:
    """Register the concrete resolved field-param payload validator."""
    global _FIELD_PARAM_PAYLOAD_VALIDATOR
    _FIELD_PARAM_PAYLOAD_VALIDATOR = validator


def register_field_aggregator(aggregator: FieldAggregator) -> None:
    """Register the concrete spatial-mean aggregator over LoadResult fields."""
    global _FIELD_AGGREGATOR
    _FIELD_AGGREGATOR = aggregator


def get_field_param_factory() -> FieldParamFactory:
    if _FIELD_PARAM_FACTORY is None:
        raise RuntimeError(
            "FieldParamLike factory is not registered. "
            "Call hydromodpy._bootstrap.bootstrap() before using physics runtime."
        )
    return _FIELD_PARAM_FACTORY


def get_field_param_payload_resolver() -> FieldParamPayloadResolver:
    if _FIELD_PARAM_PAYLOAD_RESOLVER is None:
        raise RuntimeError(
            "Field-param payload resolver is not registered. "
            "Call hydromodpy._bootstrap.bootstrap() before validating flow.param payloads."
        )
    return _FIELD_PARAM_PAYLOAD_RESOLVER


def get_field_param_payload_validator() -> FieldParamPayloadValidator:
    if _FIELD_PARAM_PAYLOAD_VALIDATOR is None:
        raise RuntimeError(
            "Field-param payload validator is not registered. "
            "Call hydromodpy._bootstrap.bootstrap() before validating flow.param payloads."
        )
    return _FIELD_PARAM_PAYLOAD_VALIDATOR


def get_field_aggregator() -> FieldAggregator:
    if _FIELD_AGGREGATOR is None:
        raise RuntimeError(
            "Field aggregator is not registered. "
            "Call hydromodpy._bootstrap.bootstrap() before using forcing bridges."
        )
    return _FIELD_AGGREGATOR


__all__ = [
    "BoundaryCondition",
    "FieldAggregator",
    "FieldParamFactory",
    "FieldParamLike",
    "FieldParamPayloadResolver",
    "FieldParamPayloadValidator",
    "InitialCondition",
    "LoadResultProto",
    "ProcessSpatial",
    "ProcessSpatialConfig",
    "SinkSource",
    "get_field_aggregator",
    "get_field_param_factory",
    "get_field_param_payload_resolver",
    "get_field_param_payload_validator",
    "register_field_aggregator",
    "register_field_param_factory",
    "register_field_param_payload_resolver",
    "register_field_param_payload_validator",
]
