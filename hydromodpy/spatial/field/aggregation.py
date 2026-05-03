"""Aggregation helpers reducing gridded field records to scalar series.

Collected here so callers (forcing bridges, validators) can compute the
spatial mean of LoadResult-like objects without crossing into the
``spatial.mesh`` layer directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class _FieldRecordsContainer(Protocol):
    """Minimal structural view of LoadResult used by the aggregation helpers."""

    fields: list

    @property
    def has_fields(self) -> bool: ...


def extract_homogeneous_series_from_fields(
    result: _FieldRecordsContainer,
) -> pd.Series | None:
    """Compute the spatial mean of FieldRecords.

    Reduces gridded data (TIF, NC, xarray) to one scalar per time step
    by averaging all spatial cells. Returns a Series in the data-manager
    internal unit, or None when no field data is available.
    """
    from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
        spatial_mean_from_fields,
    )

    return spatial_mean_from_fields(result)


__all__ = ["extract_homogeneous_series_from_fields"]
