"""Pydantic schema for the ``[display]`` TOML section.

Each value defaults to a non-interactive, save-enabled mode that is
safe for CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.config.base import HydroModelBase


class DisplayConfig(HydroModelBase):
    """Display behaviour resolved from the ``[display]`` TOML section."""

    model_config = ConfigDict(extra="ignore")

    save: Annotated[bool, ParamLevel("user")] = Field(
        default=True,
        description="Write rendered figures to disk under ``output_dir``.",
    )
    interactive: Annotated[bool, ParamLevel("user")] = Field(
        default=False,
        description="Show figures interactively (matplotlib show()).",
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
    figures: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Names of registered figures to render automatically after a "
            "simulation. Empty list disables auto-rendering."
        ),
    )
