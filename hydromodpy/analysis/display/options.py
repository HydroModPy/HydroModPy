"""Configuration models for optional display and export features.

This module converts the raw ``[display]`` section of the project TOML file
into small typed objects that are easy to query from plotting code.

Instead of passing dictionaries everywhere, the rest of the display package can
ask simple questions such as:
- "is display globally enabled?"
- "should this run show figures, save them, or both?"
- "is the transport GIF export enabled?"
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FlowDisplayConfig(BaseModel):
    """Validated ``[display.flow]`` subsection."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Master switch for the flow plotting group.",
    )
    cross_section: bool = Field(
        default=True,
        description="Render the flow cross-section plot.",
    )
    streamflow: bool = Field(
        default=True,
        description="Render the streamflow comparison plot.",
    )
    piezometry: bool = Field(
        default=True,
        description="Render the piezometry plot.",
    )
    watertable_map: bool = Field(
        default=True,
        description="Render water-table depth and elevation maps.",
    )
    dem_map: bool = Field(
        default=True,
        description="Render a DEM overview map with watershed contour.",
    )
    budget: bool = Field(
        default=False,
        description="Render groundwater budget bar chart.",
    )
    hydrography: bool = Field(
        default=True,
        description="Render hydrography map (stream network or flow accumulation drainage pattern).",
    )

    def to_section_options(self) -> "DisplaySectionOptions":
        """Convert validated flow flags into the lightweight runtime container."""

        return DisplaySectionOptions(
            enabled=self.enabled,
            flags={
                "cross_section": self.cross_section,
                "streamflow": self.streamflow,
                "piezometry": self.piezometry,
                "watertable_map": self.watertable_map,
                "dem_map": self.dem_map,
                "hydrography": self.hydrography,
                "budget": self.budget,
            },
        )


class ParticlesDisplayConfig(BaseModel):
    """Validated ``[display.particles]`` subsection."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Master switch for the particle plotting group.",
    )
    pathlines: bool = Field(
        default=False,
        description="Render particle pathlines.",
    )

    def to_section_options(self) -> "DisplaySectionOptions":
        """Convert validated particle flags into the lightweight runtime container."""

        return DisplaySectionOptions(
            enabled=self.enabled,
            flags={
                "pathlines": self.pathlines,
            },
        )


class TransportDisplayConfig(BaseModel):
    """Validated ``[display.transport]`` subsection."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Master switch for the transport plotting group.",
    )
    concentration: bool = Field(
        default=False,
        description="Render concentration plots.",
    )
    gif: bool = Field(
        default=False,
        description="Export concentration GIF animation.",
    )
    web_animation: bool = Field(
        default=False,
        description="Export browser-friendly web animation for concentration outputs.",
    )

    def to_section_options(self) -> "DisplaySectionOptions":
        """Convert validated transport flags into the lightweight runtime container."""

        return DisplaySectionOptions(
            enabled=self.enabled,
            flags={
                "concentration": self.concentration,
                "gif": self.gif,
                "web_animation": self.web_animation,
            },
        )


class DisplayConfig(BaseModel):
    """Validated ``[display]`` section used by launcher plotting suites."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Master switch for all optional plotting suites.",
    )
    show: bool = Field(
        default=True,
        description="Show interactive figures/windows when rendering is enabled.",
    )
    save: bool = Field(
        default=False,
        description="Save figures/animations to disk when rendering is enabled.",
    )
    dpi: int = Field(
        default=300,
        ge=1,
        description="Output resolution used when saving raster figures.",
    )
    respect_env_no_display: bool = Field(
        default=True,
        description="If true, honor HYDROMODPY_NO_DISPLAY=1 by forcing show=false in headless runs.",
    )
    respect_env_no_save: bool = Field(
        default=True,
        description="If true, honor HYDROMODPY_NO_SAVE=1 by forcing save=false in headless runs.",
    )
    flow: FlowDisplayConfig = Field(
        default_factory=FlowDisplayConfig,
        description="Display flags for flow plots.",
    )
    particles: ParticlesDisplayConfig = Field(
        default_factory=ParticlesDisplayConfig,
        description="Display flags for particle plots.",
    )
    transport: TransportDisplayConfig = Field(
        default_factory=TransportDisplayConfig,
        description="Display flags for transport plots.",
    )

    @classmethod
    def from_raw_toml(cls, raw_toml: Mapping[str, Any]) -> "DisplayConfig":
        """Build a validated display config from the raw project TOML mapping."""

        if not isinstance(raw_toml, Mapping):
            raise TypeError("raw_toml must be a mapping")

        raw_display = raw_toml.get("display")
        if isinstance(raw_display, Mapping):
            payload = dict(raw_display)
        elif raw_display is None:
            payload: dict[str, Any] = {}
        else:
            raise TypeError("TOML section [display] must be a mapping")

        return cls.model_validate(payload)

    def to_runtime_options(self) -> "DisplayOptions":
        """Convert the validated config into runtime display options."""

        show = self.show
        save = self.save
        if self.respect_env_no_display and os.environ.get("HYDROMODPY_NO_DISPLAY") == "1":
            # Allow CI/headless runs to keep saving figures while disabling windows.
            show = False
        if self.respect_env_no_save and os.environ.get("HYDROMODPY_NO_SAVE") == "1":
            # Allow headless runs to skip file exports when requested.
            save = False

        return DisplayOptions(
            enabled=self.enabled,
            show=show,
            save=save,
            dpi=self.dpi,
            respect_env_no_display=self.respect_env_no_display,
            flow=self.flow.to_section_options(),
            particles=self.particles.to_section_options(),
            transport=self.transport.to_section_options(),
        )


@dataclass(slots=True)
class DisplaySectionOptions:
    """Toggle state for one display subsection.

    A subsection represents one family of outputs, for example ``flow`` or
    ``transport``.

    ``enabled`` acts as a master switch for the whole subsection.
    ``flags`` contains the individual feature switches inside that subsection,
    such as ``streamflow``, ``pathlines``, or ``gif``.
    """

    enabled: bool = True
    flags: dict[str, bool] = field(default_factory=dict)

    def is_enabled(self, name: str, default: bool = False) -> bool:
        """Return the effective state of one named feature flag.

        This method is the safe way for plotting code to ask whether one
        feature should run:
- if the whole subsection is disabled, the answer is always ``False``;
- otherwise the named flag is read from ``flags``;
- if the flag is absent, ``default`` is used.
        """

        if not self.enabled:
            return False
        return bool(self.flags.get(name, default))


@dataclass(slots=True)
class DisplayOptions:
    """Top-level display policy shared by all plotting suites.

    This object gathers the decisions that affect all display functions:
- whether the display layer is enabled at all;
- whether figures should be shown interactively;
- whether figures should be written to disk;
- the output DPI used for saved figures;
- the subsection toggles for flow, particles, and transport.

    In practice, plotting suites receive one ``DisplayOptions`` instance and
    use it as their single source of truth for rendering behavior.
    """

    enabled: bool = True
    show: bool = True
    save: bool = False
    dpi: int = 300
    respect_env_no_display: bool = True
    flow: DisplaySectionOptions = field(default_factory=DisplaySectionOptions)
    particles: DisplaySectionOptions = field(default_factory=DisplaySectionOptions)
    transport: DisplaySectionOptions = field(default_factory=DisplaySectionOptions)

    def should_render(self) -> bool:
        """Return ``True`` when plotting should produce a visible side effect.

        This method is a coarse, fast guard used by the suite functions.
        Rendering is only meaningful if display is globally enabled and at
        least one output channel is active: on-screen display or file export.
        """

        return self.enabled and (self.show or self.save)


def display_options_from_raw_toml(raw_toml: dict) -> DisplayOptions:
    """Parse the raw project TOML payload into :class:`DisplayOptions`.

    The function reads the optional ``[display]`` block, applies default values
    for missing keys, and normalizes nested sections into ``DisplaySectionOptions``.

    It also supports a practical headless override: when
    ``HYDROMODPY_NO_DISPLAY=1`` and ``respect_env_no_display`` is enabled, the
    returned options will disable interactive display while still allowing file
    export.
    """

    return DisplayConfig.from_raw_toml(raw_toml).to_runtime_options()
