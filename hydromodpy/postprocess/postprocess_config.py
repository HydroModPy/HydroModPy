"""Typed configuration for launcher-level postprocessing workflows.

The `[postprocess]` TOML section controls optional tasks executed after
process-family runs (`flow`, `transport`), such as:
- timeseries exports,
- matching-stream diagnostics,
- display suites.

Default policy is conservative (`enabled = false`) to preserve backward
compatibility with projects that still rely on custom `hooks.py` files.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _promote_legacy_intermittency_settings(value: dict) -> dict:
    """Lift legacy ``timeseries.intermittency_*`` keys to ``intermittency``."""

    raw = dict(value)
    timeseries = dict(raw.get("timeseries") or {})
    intermittency = dict(raw.get("intermittency") or {})

    legacy_to_new = {
        "intermittency_yearly": "yearly",
        "intermittency_monthly": "monthly",
        "intermittency_weekly": "weekly",
        "intermittency_daily": "daily",
    }
    moved = False
    for legacy_key, new_key in legacy_to_new.items():
        if legacy_key in timeseries and new_key not in intermittency:
            intermittency[new_key] = timeseries.pop(legacy_key)
            moved = True

    if moved:
        raw["timeseries"] = timeseries
    if intermittency:
        raw["intermittency"] = intermittency
    return raw


class IntermittencyPostprocessConfig(BaseModel):
    """Intermittency indicators derived from flow accumulation flux."""

    model_config = ConfigDict(extra="forbid")

    yearly: bool = Field(
        default=False,
        description="Compute yearly intermittency indicators from accumulation flux.",
    )
    monthly: bool = Field(
        default=True,
        description="Compute monthly intermittency indicators from accumulation flux.",
    )
    weekly: bool = Field(
        default=False,
        description="Compute weekly intermittency indicators from accumulation flux.",
    )
    daily: bool = Field(
        default=False,
        description="Compute daily intermittency indicators from accumulation flux.",
    )


class FlowTimeseriesPostprocessConfig(BaseModel):
    """Flow-timeseries export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable flow timeseries export after the flow process family.",
    )
    datetime_format: bool = Field(
        default=True,
        description="Format exported timeseries index as datetimes when possible.",
    )
    subbasin_results: bool = Field(
        default=True,
        description="Also export one timeseries file per available subbasin.",
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

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_intermittency(
        cls,
        value: object,
    ) -> object:
        if not isinstance(value, dict):
            return value
        return _promote_legacy_intermittency_settings(value)


class TransportTimeseriesPostprocessConfig(BaseModel):
    """Transport-timeseries export options."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable transport timeseries export after transport runs.",
    )
    suffix_name: str = Field(
        default="s1",
        description=(
            "Suffix appended to transport timeseries filenames "
            "(legacy default: 's1')."
        ),
    )
    datetime_format: bool = Field(
        default=True,
        description="Format exported timeseries index as datetimes when possible.",
    )
    subbasin_results: bool = Field(
        default=True,
        description="Also export one timeseries file per available subbasin.",
    )
    residence_times: bool = Field(
        default=True,
        description="Export residence-time indicators from particle tracking outputs.",
    )
    concentration_seepage: bool = Field(
        default=True,
        description="Export seepage concentration indicators from transport outputs.",
    )
    mass_accumulated: bool = Field(
        default=True,
        description="Export accumulated-mass indicators from transport outputs.",
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

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_intermittency(
        cls,
        value: object,
    ) -> object:
        if not isinstance(value, dict):
            return value
        return _promote_legacy_intermittency_settings(value)


class PostprocessConfig(BaseModel):
    """Top-level `[postprocess]` configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Enable launcher-managed postprocessing after process runs. "
            "Defaults to false for backward compatibility with hook-driven projects."
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
