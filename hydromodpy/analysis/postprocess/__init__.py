"""Launcher-oriented postprocessing API."""

from hydromodpy.analysis.postprocess.postprocess_config import (
    FlowPostprocessConfig,
    FlowNetcdfPostprocessConfig,
    FlowTimeseriesPostprocessConfig,
    IntermittencyPostprocessConfig,
    PostprocessConfig,
    TransportPostprocessConfig,
    TransportNetcdfPostprocessConfig,
    TransportTimeseriesPostprocessConfig,
)

__all__ = [
    "PostprocessConfig",
    "FlowPostprocessConfig",
    "FlowNetcdfPostprocessConfig",
    "FlowTimeseriesPostprocessConfig",
    "IntermittencyPostprocessConfig",
    "TransportPostprocessConfig",
    "TransportNetcdfPostprocessConfig",
    "TransportTimeseriesPostprocessConfig",
]
