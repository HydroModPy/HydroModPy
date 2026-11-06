"""Shared process contracts used by HydroModPy internals.

This module holds the structural Protocols (``LoadResultProto``, ``FieldParamLike``) used
to type spatial- and data-layer inputs without importing them.

The factory hooks defined here let physics-layer code consume spatial
field-parameter constructors without statically importing the spatial
package. The bootstrap layer (``hydromodpy._bootstrap``) registers the
concrete callables before any runtime use.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable


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


class FieldRecordProto(Protocol):
    """Structural view of ``data.contracts.FieldRecord``, one gridded dataset."""

    variable: str
    data: Any
    bbox: tuple
    crs: str
    date_start: Any
    date_end: Any
    metadata: dict[str, object]


@runtime_checkable
class FieldParamLike(Protocol):
    """Structural view of ``spatial.field.field_param.FieldParam``.

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
FieldAggregator = Callable[[LoadResultProto], Any]


_FIELD_PARAM_FACTORY: FieldParamFactory | None = None
_FIELD_AGGREGATOR: FieldAggregator | None = None


def register_field_param_factory(factory: FieldParamFactory) -> None:
    """Register the concrete ``FieldParamLike`` factory used by physics."""
    global _FIELD_PARAM_FACTORY
    _FIELD_PARAM_FACTORY = factory


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


def get_field_aggregator() -> FieldAggregator:
    if _FIELD_AGGREGATOR is None:
        raise RuntimeError(
            "Field aggregator is not registered. "
            "Call hydromodpy._bootstrap.bootstrap() before using forcing bridges."
        )
    return _FIELD_AGGREGATOR


__all__ = [
    "FieldAggregator",
    "FieldParamFactory",
    "FieldParamLike",
    "FieldRecordProto",
    "LoadResultProto",
    "get_field_aggregator",
    "get_field_param_factory",
    "register_field_aggregator",
    "register_field_param_factory",
]
