"""A terrain engine HydroModPy does not ship and can nevertheless run.

Nothing is imported here. The entry point names
``hydromodpy_terrain_scipy.engine:ScipyTerrainEngine`` directly, so a host that
scans the ``hydromodpy.terrain.engine`` group and resolves a different name
pulls in neither scipy nor rasterio through this package.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
