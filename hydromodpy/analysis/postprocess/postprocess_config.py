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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import model_validator

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
    native_mesh_npz: bool = Field(
        default=False,
        description="Export native mesh cell-series as NPZ files.",
    )
    native_mesh_csv: bool = Field(
        default=False,
        description="Export native mesh cell-series as CSV tables.",
    )
    native_mesh_vtu: bool = Field(
        default=False,
        description="Export native mesh snapshots as VTU files.",
    )
    native_mesh_png: bool = Field(
        default=False,
        description="Export native mesh scalar snapshots as PNG figures.",
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

    profile: Literal["standard", "solver_only"] = Field(
        default="standard",
        description=(
            "Postprocess preset. Use 'standard' to honor nested options. "
            "Use 'solver_only' for profiling or benchmark runs: launcher-managed "
            "reports, displays, native mesh exports, NetCDF and timeseries exports "
            "are disabled while the numerical solvers still run."
        ),
    )
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

    @model_validator(mode="after")
    def _apply_profile_preset(self) -> "PostprocessConfig":
        """Apply high-level presets after nested config validation."""
        if self.profile != "solver_only":
            return self

        self.flow = self.flow.model_copy(
            update={
                "timeseries": self.flow.timeseries.model_copy(
                    update={"enabled": False}
                ),
                "netcdf": self.flow.netcdf.model_copy(update={"enabled": False}),
                "matching_streams": False,
                "display": False,
                "native_mesh_npz": False,
                "native_mesh_csv": False,
                "native_mesh_vtu": False,
                "native_mesh_png": False,
            }
        )
        self.transport = self.transport.model_copy(
            update={
                "timeseries": self.transport.timeseries.model_copy(
                    update={"enabled": False}
                ),
                "netcdf": self.transport.netcdf.model_copy(
                    update={"enabled": False}
                ),
                "display_particles": False,
                "display_transport": False,
            }
        )
        return self
