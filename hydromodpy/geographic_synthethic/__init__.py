"""Synthetic geographic helpers for simple validation geometries.

This package provides a lightweight alternative to the full watershed-oriented
``hydromodpy.geographic`` stack when the model support can be defined
analytically.
"""

from hydromodpy.geographic_synthethic.config import (
    SyntheticGeographicConfig,
    SyntheticGridConfig,
    SyntheticTopographyConfig,
)
from hydromodpy.geographic_synthethic.synthetic_geographic import (
    SyntheticGeographic,
    build_synthetic_geographic,
)

__all__ = [
    "SyntheticGeographic",
    "SyntheticGeographicConfig",
    "SyntheticGridConfig",
    "SyntheticTopographyConfig",
    "build_synthetic_geographic",
]
