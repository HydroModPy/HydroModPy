"""Storage backend adapters for Zarr stores."""

from hydromodpy.results.zarr_store.adapters.fsspec_store import FsspecZarrStore

__all__ = ["FsspecZarrStore"]
