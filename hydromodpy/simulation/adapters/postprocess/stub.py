"""Placeholder postprocess adapters.

These stubs define the adapter interface for post-processing phases.
Concrete implementations will wrap the existing ``postprocess/`` modules
(timeseries, netcdf, etc.) into the simulation pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult


class TimeseriesPostprocessAdapter:
    """Adapter for ``postprocess/timeseries`` runs (stub)."""

    process_type = "postprocess"
    solver_name = "timeseries"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for the timeseries postprocess stub."""

    def cleanup(self, ctx: RunContext) -> None:
        """Stub adapters write no scratch files."""

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        raise NotImplementedError(
            "TimeseriesPostprocessAdapter is a stub. "
            "Implement by wrapping FlowTimeseriesPostprocess / TransportTimeseriesPostprocess."
        )

    def extract_calibration_series(
        self,
        ctx: RunContext,
        store: Any,
        *,
        variable: str,
        station_cells: Mapping[str, tuple[int, int, int]] | None = None,
        time_index: pd.DatetimeIndex | None = None,
    ) -> pd.Series:
        """Postprocess runs are not calibration targets; return empty series."""
        del ctx, store, station_cells, time_index
        return pd.Series(dtype=float, name=variable)


class NetcdfPostprocessAdapter:
    """Adapter for ``postprocess/netcdf`` runs (stub)."""

    process_type = "postprocess"
    solver_name = "netcdf"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for the NetCDF postprocess stub."""

    def cleanup(self, ctx: RunContext) -> None:
        """Stub adapters write no scratch files."""

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        raise NotImplementedError(
            "NetcdfPostprocessAdapter is a stub. "
            "Implement by wrapping FlowNetcdfPostprocess / TransportNetcdfPostprocess."
        )

    def extract_calibration_series(
        self,
        ctx: RunContext,
        store: Any,
        *,
        variable: str,
        station_cells: Mapping[str, tuple[int, int, int]] | None = None,
        time_index: pd.DatetimeIndex | None = None,
    ) -> pd.Series:
        """Postprocess runs are not calibration targets; return empty series."""
        del ctx, store, station_cells, time_index
        return pd.Series(dtype=float, name=variable)
