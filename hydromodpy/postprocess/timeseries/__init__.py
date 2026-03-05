"""Timeseries-oriented postprocess helpers.

Imports stay lazy so config modules can be imported without loading optional
runtime dependencies (e.g. geopandas/rasterio).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "FlowTimeseriesPostprocess",
    "TransportTimeseriesPostprocess",
    "Timeseries",
    "apply_intermittency_columns",
    "FlowTimeseriesPostprocessConfig",
    "TransportTimeseriesPostprocessConfig",
]


def __getattr__(name: str) -> Any:
    if name == "FlowTimeseriesPostprocess":
        from hydromodpy.postprocess.timeseries.flow_timeseries import (
            FlowTimeseriesPostprocess,
        )

        return FlowTimeseriesPostprocess

    if name == "TransportTimeseriesPostprocess":
        from hydromodpy.postprocess.timeseries.transport_timeseries import (
            TransportTimeseriesPostprocess,
        )

        return TransportTimeseriesPostprocess

    if name == "Timeseries":
        from hydromodpy.postprocess.timeseries.timeseries import Timeseries

        return Timeseries

    if name == "apply_intermittency_columns":
        from hydromodpy.postprocess.flow.intermittency import apply_intermittency_columns

        return apply_intermittency_columns

    if name == "FlowTimeseriesPostprocessConfig":
        from hydromodpy.postprocess.timeseries.flow_timeseries_config import (
            FlowTimeseriesPostprocessConfig,
        )

        return FlowTimeseriesPostprocessConfig

    if name == "TransportTimeseriesPostprocessConfig":
        from hydromodpy.postprocess.timeseries.transport_timeseries_config import (
            TransportTimeseriesPostprocessConfig,
        )

        return TransportTimeseriesPostprocessConfig

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
