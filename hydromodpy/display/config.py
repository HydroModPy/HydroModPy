"""Pydantic schema for the ``[display]`` TOML section.

Each value defaults to a non-interactive, save-enabled mode that is
safe for CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class DisplayFlowConfig(HydroModelBase):
    """Display switches for flow figures."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Master switch for flow figures.",
    )
    cross_section: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render the flow cross-section plot.",
    )
    streamflow: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render the streamflow comparison plot.",
    )
    piezometry: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render the piezometry plot.",
    )
    watertable_map: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render water-table maps.",
    )
    dem_map: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render a DEM overview map.",
    )
    budget: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Render groundwater budget figures.",
    )
    hydrography: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render hydrography maps.",
    )
    boussinesq_state: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render the Boussinesq state figure.",
    )
    boussinesq_diagnostics: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render Boussinesq diagnostics.",
    )
    boussinesq_mass_balance: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render Boussinesq mass-balance diagnostics.",
    )
    boussinesq_probes: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render Boussinesq probe time series.",
    )
    boussinesq_edge_flux: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Render final Boussinesq edge fluxes.",
    )


class DisplayParticlesConfig(HydroModelBase):
    """Display switches for particle figures."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Master switch for particle figures.",
    )
    pathlines: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Render particle pathlines.",
    )


class DisplayTransportConfig(HydroModelBase):
    """Display switches for transport figures."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Master switch for transport figures.",
    )
    concentration: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Render concentration plots.",
    )
    gif: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Export concentration GIF animation.",
    )
    web_animation: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Export browser-friendly concentration animation.",
    )


class DisplayConfig(HydroModelBase):
    """Display behaviour resolved from the ``[display]`` TOML section."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Master switch. When False, no figure is rendered or saved.",
    )
    backend: Annotated[Literal["agg", "qt5agg", "auto"], Profile.DEV] = Field(
        default="auto",
        description=(
            "Matplotlib backend. 'auto' selects Agg in headless mode and a "
            "GUI backend when ``show`` is enabled."
        ),
    )
    preset: Annotated[Literal["default", "print", "dark"], Profile.USER] = Field(
        default="default",
        description="Named theme applied before rendering any figure.",
    )
    show: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Open an interactive window via ``matplotlib.pyplot.show``.",
    )
    save: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write rendered figures to disk under ``output_dir``.",
    )
    output_dir: Annotated[Path, Profile.USER] = Field(
        default=Path("figures"),
        description="Directory (relative to project root) for saved figures.",
    )
    dpi: Annotated[int, Profile.DEV] = Field(
        default=150,
        ge=1,
        description="DPI used when saving raster figures.",
    )
    cmap: Annotated[str, Profile.USER] = Field(
        default="viridis",
        description="Default sequential colormap for spatial figures.",
    )
    figures: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Names of registered figures to auto-render at the end of "
            "`hmp run` (and consumed by `hmp display`). Empty list disables "
            "auto-rendering; figures can still be produced later with "
            "`hmp display <toml>`. Disable per-run via `hmp run --no-display` "
            "or for an entire Python Project via `Project(..., no_display=True)`."
        ),
    )
    overrides: Annotated[dict[str, dict], Profile.EXPERT] = Field(
        default_factory=dict,
        description=(
            "Per-figure keyword overrides, keyed by figure name "
            "(e.g. ``{'piezometric_map': {'cmap': 'cividis', 'vmin': 0}}``)."
        ),
    )
    flow: Annotated[DisplayFlowConfig, Profile.USER] = Field(
        default_factory=DisplayFlowConfig,
        description="Flow figure switches.",
    )
    particles: Annotated[DisplayParticlesConfig, Profile.USER] = Field(
        default_factory=DisplayParticlesConfig,
        description="Particle figure switches.",
    )
    transport: Annotated[DisplayTransportConfig, Profile.USER] = Field(
        default_factory=DisplayTransportConfig,
        description="Transport figure switches.",
    )
