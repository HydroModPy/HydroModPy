"""Placeholder postprocess adapters.

These stubs define the adapter interface for post-processing phases.
Concrete implementations will wrap the existing ``postprocess/`` modules
(timeseries, netcdf, etc.) into the simulation pipeline.
"""

from __future__ import annotations

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult


class TimeseriesPostprocessAdapter:
    """Adapter for ``postprocess/timeseries`` runs (stub)."""

    process_type = "postprocess"
    solver_name = "timeseries"
    requires: tuple[tuple[str, str], ...] = ()

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        raise NotImplementedError(
            "TimeseriesPostprocessAdapter is a stub. "
            "Implement by wrapping FlowTimeseriesPostprocess / TransportTimeseriesPostprocess."
        )


class NetcdfPostprocessAdapter:
    """Adapter for ``postprocess/netcdf`` runs (stub)."""

    process_type = "postprocess"
    solver_name = "netcdf"
    requires: tuple[tuple[str, str], ...] = ()

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        raise NotImplementedError(
            "NetcdfPostprocessAdapter is a stub. "
            "Implement by wrapping FlowNetcdfPostprocess / TransportNetcdfPostprocess."
        )
