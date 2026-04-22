"""Minimal :class:`DataSource` protocol + :func:`register_source` decorator.

Spec reference: ``architecture_cible/12_input_data_rethink.md`` §3. The
Protocol makes it easy to plug additional data sources without having
to subclass :class:`hydromodpy.data.base_manager.BaseVariableManager`
— a plain function or small class that exposes ``variable_type``,
``source_name`` and ``fetch()`` is enough.

The registry is intentionally a simple module-level dict keyed by the
``(variable_type, source_name)`` tuple. The registry is populated at
import time; the :func:`register_source` decorator is the canonical way
to add a source.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class DataSource(Protocol):
    """Minimal contract for a pluggable data source."""

    variable_type: str
    source_name: str

    def fetch(self, ctx: Any) -> Any:
        """Produce a ``LoadResult`` (or equivalent) for the given context."""
        ...


_REGISTRY: dict[tuple[str, str], Any] = {}


def register_source(source: Any | None = None) -> Any:
    """Register a :class:`DataSource` implementation.

    Usable both as a decorator::

        @register_source
        class MySource:
            variable_type = "piezometry"
            source_name = "custom"
            def fetch(self, ctx): ...

    and as a function called with an instance or class.
    """
    def _register(target: Any) -> Any:
        try:
            variable = getattr(target, "variable_type")
            name = getattr(target, "source_name")
        except AttributeError as exc:  # pragma: no cover - defensive
            raise TypeError(
                "register_source expected an object with 'variable_type' "
                "and 'source_name' attributes."
            ) from exc
        _REGISTRY[(str(variable), str(name))] = target
        return target

    if source is None:
        return _register
    return _register(source)


def get_source(variable_type: str, source_name: str) -> Any | None:
    """Lookup a registered source (return ``None`` if unknown)."""
    return _REGISTRY.get((variable_type, source_name))


def list_sources() -> list[tuple[str, str]]:
    """List every registered ``(variable_type, source_name)`` pair."""
    return sorted(_REGISTRY.keys())


def clear_registry() -> None:
    """Reset the registry (primarily for tests)."""
    _REGISTRY.clear()


__all__ = [
    "DataSource",
    "register_source",
    "get_source",
    "list_sources",
    "clear_registry",
]
