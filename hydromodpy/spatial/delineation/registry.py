"""Registry of delineation backends.

Maps backend names to their implementation classes, with a graceful
fallback when a backend's optional dependency is missing. Concrete
backends stay lazy-imported so importing this module never pulls in
``whitebox_workflows`` or other heavy extras.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from typing import Any, Callable

_BACKEND_LOADERS: dict[str, Callable[[], type]] = {}


def _register(name: str, module: str, attribute: str) -> None:
    """Register a backend with a lazy importer."""

    def _loader() -> type:
        return getattr(import_module(module), attribute)

    _BACKEND_LOADERS[name] = _loader


def register_backend(name: str, loader: Callable[[], type]) -> None:
    """Public hook to register an additional backend at runtime.

    ``loader`` must return the backend class (import happens lazily).
    """
    _BACKEND_LOADERS[str(name).strip().lower()] = loader
    _get_cached_backend.cache_clear()


def available_backends() -> list[str]:
    """Return the list of registered backend names."""
    return sorted(_BACKEND_LOADERS.keys())


def _normalize(name: str | None) -> str:
    value = "whitebox_workflows" if name is None else str(name)
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "wbw": "whitebox_workflows",
        "whiteboxworkflow": "whitebox_workflows",
        "workflows": "whitebox_workflows",
        "whitebox_workflows": "whitebox_workflows",
        "whitebox": "whitebox_workflows",
        "cli": "whitebox_cli",
        "whitebox_cli": "whitebox_cli",
        "whiteboxtools": "whitebox_cli",
        "pysheds": "pysheds",
        "synthetic": "synthetic",
        "synthetic_bv": "synthetic",
    }
    if normalized not in aliases:
        raise ValueError(
            f"Unknown delineation backend {value!r}. "
            f"Available: {', '.join(sorted(set(aliases.values())))}."
        )
    return aliases[normalized]


@lru_cache(maxsize=None)
def _get_cached_backend(name: str) -> Any:
    loader = _BACKEND_LOADERS.get(name)
    if loader is None:
        raise ValueError(f"Backend {name!r} is not registered.")
    try:
        cls = loader()
    except ImportError as exc:
        raise ImportError(
            f"Backend {name!r} is not available: missing optional "
            f"dependency ({exc})."
        ) from exc
    return cls()


def get_backend(name: str | None = None) -> Any:
    """Return a cached backend instance by name.

    Names are case-insensitive and accept a small alias set (``wbw``,
    ``workflows``, ``whitebox_workflows`` all resolve to the same
    backend). Raises ``ValueError`` for unknown names and ``ImportError``
    when the backend's optional dependency is not installed.
    """
    return _get_cached_backend(_normalize(name))


def clear_backend_cache() -> None:
    """Release cached backend instances (used by tests)."""
    _get_cached_backend.cache_clear()


_register(
    "whitebox_workflows",
    "hydromodpy.spatial.delineation.whitebox_workflows_backend",
    "WhiteboxWorkflowsBackend",
)
_register(
    "whitebox_cli",
    "hydromodpy.spatial.delineation.whitebox_cli_backend",
    "WhiteboxCliBackend",
)
_register(
    "pysheds",
    "hydromodpy.spatial.delineation.pysheds_backend",
    "PyshedsBackend",
)
_register(
    "synthetic",
    "hydromodpy.spatial.delineation.synthetic_backend",
    "SyntheticBackend",
)
