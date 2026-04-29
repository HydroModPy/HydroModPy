"""Pydantic schema for the ``[display]`` TOML section.

Each value defaults to a non-interactive, save-enabled mode that is
safe for CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.master_config.base import HydroModelBase
from hydromodpy.master_config.profile import Profile


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
