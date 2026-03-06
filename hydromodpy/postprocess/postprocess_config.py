"""Typed configuration for launcher-level postprocessing workflows.

The `[postprocess]` TOML section controls optional tasks executed after
process-family runs (`flow`, `transport`), such as:
- timeseries exports,
- netcdf exports,
- matching-stream diagnostics,
- display suites.

Default policy is conservative (`enabled = false`) to preserve backward
compatibility with projects that do not yet use launcher-managed postprocess.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.postprocess.flow.intermittency_config import (
    IntermittencyPostprocessConfig,
)
from hydromodpy.postprocess.netcdf.flow_netcdf_config import (
    FlowNetcdfPostprocessConfig,
)
from hydromodpy.postprocess.netcdf.transport_netcdf_config import (
    TransportNetcdfPostprocessConfig,
)
from hydromodpy.postprocess.timeseries.flow_timeseries_config import (
    FlowTimeseriesPostprocessConfig,
)
from hydromodpy.postprocess.timeseries.transport_timeseries_config import (
    TransportTimeseriesPostprocessConfig,
)


class FlowPostprocessConfig(BaseModel):
    """Postprocessing options for the flow process family."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable flow postprocessing after the flow process family.",
    )
    timeseries: FlowTimeseriesPostprocessConfig = Field(
        default_factory=FlowTimeseriesPostprocessConfig,
        description="Flow timeseries export options.",
    )
    netcdf: FlowNetcdfPostprocessConfig = Field(
        default_factory=FlowNetcdfPostprocessConfig,
        description="Flow NetCDF export options.",
    )
    intermittency: IntermittencyPostprocessConfig = Field(
        default_factory=IntermittencyPostprocessConfig,
        description="Intermittency indicator options.",
    )
    matching_streams: bool = Field(
        default=True,
        description="Run matching-stream diagnostics after flow postprocessing.",
    )
    display: bool = Field(
        default=True,
        description="Run the flow display suite after flow postprocessing.",
    )

class TransportPostprocessConfig(BaseModel):
    """Postprocessing options for the transport process family."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable transport postprocessing after transport runs.",
    )
    timeseries: TransportTimeseriesPostprocessConfig = Field(
        default_factory=TransportTimeseriesPostprocessConfig,
        description="Transport timeseries export options.",
    )
    netcdf: TransportNetcdfPostprocessConfig = Field(
        default_factory=TransportNetcdfPostprocessConfig,
        description="Transport NetCDF export options.",
    )
    intermittency: IntermittencyPostprocessConfig = Field(
        default_factory=IntermittencyPostprocessConfig,
        description="Intermittency indicator options.",
    )
    display_particles: bool = Field(
        default=True,
        description="Run particle display suite when a particle model is available.",
    )
    display_transport: bool = Field(
        default=True,
        description="Run transport display suite when a transport model is available.",
    )

class PostprocessConfig(BaseModel):
    """Top-level `[postprocess]` configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Enable launcher-managed postprocessing after process runs. "
            "Defaults to false for backward compatibility."
        ),
    )
    flow: FlowPostprocessConfig = Field(
        default_factory=FlowPostprocessConfig,
        description="Flow postprocessing configuration.",
    )
    transport: TransportPostprocessConfig = Field(
        default_factory=TransportPostprocessConfig,
        description="Transport postprocessing configuration.",
    )
