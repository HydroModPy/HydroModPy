"""Synthetic geographic helpers for simple validation geometries.

This package provides a lightweight alternative to the full watershed-oriented
``hydromodpy.spatial.geographic`` stack when the model support can be defined
analytically.
"""

from __future__ import annotations

import importlib

from hydromodpy.spatial.geographic.synthetic.config import (
    SyntheticGeographicConfig,
    SyntheticGridConfig,
    SyntheticTopographyConfig,
)

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "SyntheticGeographic": (
        "hydromodpy.spatial.geographic.synthetic.synthetic_geographic",
        "SyntheticGeographic",
    ),
    "build_synthetic_geographic": (
        "hydromodpy.spatial.geographic.synthetic.synthetic_geographic",
        "build_synthetic_geographic",
    ),
}


def __getattr__(name: str):
    """Resolve runtime symbols lazily to avoid geographic import cycles."""
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    raise AttributeError(
        f"module 'hydromodpy.spatial.geographic.synthetic' has no attribute {name!r}"
    )


__all__ = [
    "SyntheticGeographicConfig",
    "SyntheticGridConfig",
    "SyntheticTopographyConfig",
    *_LAZY_EXPORTS,
]
