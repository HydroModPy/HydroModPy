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

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel

from hydromodpy.analysis.postprocess.flow.intermittency_config import (
    IntermittencyPostprocessConfig,
)
from hydromodpy.analysis.postprocess.netcdf.flow_netcdf_config import (
    FlowNetcdfPostprocessConfig,
)
from hydromodpy.analysis.postprocess.netcdf.transport_netcdf_config import (
    TransportNetcdfPostprocessConfig,
)
from hydromodpy.analysis.postprocess.timeseries.flow_timeseries_config import (
    FlowTimeseriesPostprocessConfig,
)
from hydromodpy.analysis.postprocess.timeseries.transport_timeseries_config import (
    TransportTimeseriesPostprocessConfig,
)


class FlowPostprocessConfig(BaseModel):
    """Postprocessing options for the flow process family."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Enable flow postprocessing after the flow process family.",
    )
    timeseries: Annotated[FlowTimeseriesPostprocessConfig, ParamLevel("user")] = Field(
        default_factory=FlowTimeseriesPostprocessConfig,
        description="Flow timeseries export options.",
    )
    netcdf: Annotated[FlowNetcdfPostprocessConfig, ParamLevel("user")] = Field(
        default_factory=FlowNetcdfPostprocessConfig,
        description="Flow NetCDF export options.",
    )
    intermittency: Annotated[IntermittencyPostprocessConfig, ParamLevel("user")] = Field(
        default_factory=IntermittencyPostprocessConfig,
        description="Intermittency indicator options.",
    )
    matching_streams: Annotated[bool, ParamLevel("dev")] = Field(
        default=True,
        description="Run matching-stream diagnostics after flow postprocessing.",
    )
    display: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Run the flow display suite after flow postprocessing.",
    )

class TransportPostprocessConfig(BaseModel):
    """Postprocessing options for the transport process family."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Enable transport postprocessing after transport runs.",
    )
    timeseries: Annotated[TransportTimeseriesPostprocessConfig, ParamLevel("user")] = Field(
        default_factory=TransportTimeseriesPostprocessConfig,
        description="Transport timeseries export options.",
    )
    netcdf: Annotated[TransportNetcdfPostprocessConfig, ParamLevel("user")] = Field(
        default_factory=TransportNetcdfPostprocessConfig,
        description="Transport NetCDF export options.",
    )
    intermittency: Annotated[IntermittencyPostprocessConfig, ParamLevel("user")] = Field(
        default_factory=IntermittencyPostprocessConfig,
        description="Intermittency indicator options.",
    )
    display_particles: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Run particle display suite when a particle model is available.",
    )
    display_transport: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Run transport display suite when a transport model is available.",
    )

class PostprocessConfig(BaseModel):
    """Top-level `[postprocess]` configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description=(
            "Enable launcher-managed postprocessing after process runs. "
            "Defaults to false for backward compatibility."
        ),
    )
    flow: Annotated[FlowPostprocessConfig, ParamLevel("user")] = Field(
        default_factory=FlowPostprocessConfig,
        description="Flow postprocessing configuration.",
    )
    transport: Annotated[TransportPostprocessConfig, ParamLevel("user")] = Field(
        default_factory=TransportPostprocessConfig,
        description="Transport postprocessing configuration.",
    )
