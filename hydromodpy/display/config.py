"""Pydantic schema for the ``[display]`` TOML section.

Each value defaults to a non-interactive, save-enabled mode that is
safe for CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.config.base import HydroModelBase


class DisplayConfig(HydroModelBase):
    """Display behaviour resolved from the ``[display]`` TOML section."""

    model_config = ConfigDict(extra="ignore")

    enabled: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Master switch. When False, no figure is rendered or saved.",
    )
    backend: Annotated[Literal["agg", "qt5agg", "auto"], ParamLevel("dev")] = Field(
        default="auto",
        description=(
            "Matplotlib backend. 'auto' selects Agg in headless mode and a "
            "GUI backend when ``show`` is enabled."
        ),
    )
    preset: Annotated[Literal["default", "print", "dark"], ParamLevel("user")] = Field(
        default="default",
        description="Named theme applied before rendering any figure.",
    )
    show: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description="Open an interactive window via ``matplotlib.pyplot.show``.",
    )
    save: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Write rendered figures to disk under ``output_dir``.",
    )
    output_dir: Annotated[Path, ParamLevel("user")] = Field(
        default=Path("figures"),
        description="Directory (relative to project root) for saved figures.",
    )
    dpi: Annotated[int, ParamLevel("dev")] = Field(
        default=150,
        ge=1,
        description="DPI used when saving raster figures.",
    )
    cmap: Annotated[str, ParamLevel("user")] = Field(
        default="viridis",
        description="Default sequential colormap for spatial figures.",
    )
    figures: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Names of registered figures to render automatically after a "
            "simulation. Empty list disables auto-rendering."
        ),
    )
    overrides: Annotated[dict[str, dict], ParamLevel("expert")] = Field(
        default_factory=dict,
        description=(
            "Per-figure keyword overrides, keyed by figure name "
            "(e.g. ``{'piezometric_map': {'cmap': 'cividis', 'vmin': 0}}``)."
        ),
    )
