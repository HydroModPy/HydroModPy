"""The file suffixes that make a shapefile reopenable."""

from __future__ import annotations

# A shapefile is a file only by convention: reopening it needs its sidecars.
SHAPEFILE_SIDECARS = (".shp", ".shx", ".dbf", ".prj", ".cpg")

__all__ = ("SHAPEFILE_SIDECARS",)
