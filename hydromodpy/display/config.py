"""Pydantic schema for the ``[display]`` TOML section.

Each value defaults to a non-interactive, save-enabled mode that is
safe for CI.

A run renders exactly the figures listed in ``figures``. Whether one of
them applies is decided from the figure's own declared requirements
(:class:`hydromodpy.display.figure.FigureSpec`) against what the run
persisted, not from a second layer of per-family booleans.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


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
            "`hmp run` (and consumed by `hmp viz gallery`). Every name must "
            "exist in the figure registry; list them with `hmp viz list`. "
            "A figure whose requirements the run does not meet is skipped "
            "with an explicit reason. Empty list disables auto-rendering. "
            "Disable per-run via `hmp run --no-display` or for an entire "
            "Python Project via `Project(..., no_display=True)`."
        ),
    )
    on_error: Annotated[Literal["warn", "raise"], Profile.USER] = Field(
        default="warn",
        description=(
            "Behaviour when a figure that IS applicable fails while rendering. "
            "'warn' logs and continues (default, keeps a long run alive); "
            "'raise' propagates, which is what example and CI configs want so "
            "a broken figure cannot pass unnoticed."
        ),
    )
    overrides: Annotated[dict[str, dict], Profile.EXPERT] = Field(
        default_factory=dict,
        description=(
            "Per-figure keyword overrides, keyed by figure name "
            "(e.g. ``{'piezometric_map': {'cmap': 'cividis', 'vmin': 0}}``)."
        ),
    )

    @field_validator("figures", "overrides", mode="after")
    @classmethod
    def _validate_figure_names(cls, value, info):
        """Reject figure names that are not in the registry.

        Catching the typo here (config load) instead of at render time is
        what makes a project TOML self-checking: `hmp config check` fails
        loudly rather than a run silently producing one figure less.
        """
        from hydromodpy.display import figure_registry

        known = set(figure_registry.names())
        unknown = sorted(name for name in value if name not in known)
        if unknown:
            raise ValueError(
                f"display.{info.field_name} references unknown figure(s): "
                f"{', '.join(unknown)}. Registered figures: {', '.join(sorted(known))}"
            )
        return value
