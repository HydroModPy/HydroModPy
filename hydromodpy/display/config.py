"""Pydantic schema for the ``[display]`` TOML section.

A run draws the figures listed in ``[[display.figure]]``, each one a request that
names a variable, a preset or panels. ``theme`` sets the look of every figure and
``presets`` holds the user's own presets.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import FigureRequest, check_stems, expand, named

DEFAULT_THEME = "default"


class DisplayConfig(HydroModelBase):
    """Display behavior resolved from the ``[display]`` TOML section."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "output_dir": (
            "figures are always written under figures/ of the run directory "
            "(runs/<run>/figures/). Delete the line."
        ),
    }

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Master switch. When False, no figure is rendered or saved.",
    )
    dpi: Annotated[int, Profile.DEV] = Field(
        default=300,
        ge=1,
        description="DPI used when saving raster figures.",
        json_schema_extra=field_metadata(unit="dpi"),
    )
    theme: Annotated[str, Profile.USER] = Field(
        default=DEFAULT_THEME,
        description=("Named theme applied before rendering any figure: default, print or dark."),
    )
    figure: Annotated[list[FigureRequest], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Figures to draw, one ``[[display.figure]]`` table each. A figure names a "
            "variable or a preset, or lists panels, with the fields of a panel. "
            "``when`` says when it is drawn (``end`` by default). Two figures that "
            "would write the same file are refused: give each one its own ``name``."
        ),
    )
    presets: Annotated[dict[str, FigureRequest], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Your own presets, one ``[display.presets.NAME]`` table each, written like "
            "a figure. A figure then names one with ``preset = NAME``. A name of a "
            "shipped preset is refused."
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

    @field_validator("theme", mode="after")
    @classmethod
    def _check_theme(cls, value: str) -> str:
        """Refuse a theme name unknown to the themes table.

        The table lives in ``theme``, which loads matplotlib. The default needs no
        look-up, so a config that keeps it loads without matplotlib.
        """
        if value != DEFAULT_THEME:
            from hydromodpy.display.theme import get_theme

            get_theme(value)
        return value

    @model_validator(mode="after")
    def _check_figures_and_themes(self) -> DisplayConfig:
        check_stems(self.figure)
        if not (self.figure or self.presets):
            return self
        shipped = sorted(set(self.presets) & set(PRESETS))
        if shipped:
            raise ValueError(
                f"display.presets names the shipped preset {', '.join(shipped)}. "
                "Give your preset another name."
            )
        own = named(self.presets)
        known = {**PRESETS, **own}
        for name, preset in own.items():
            if preset.preset is not None:
                raise ValueError(f"Preset {name!r} names another preset; a preset is one request.")
            expand(preset, known)
        for figure in self.figure:
            expand(figure, known)
        return self
