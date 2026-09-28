"""Pydantic schema for the ``[display]`` TOML section.

Each value defaults to a non-interactive, save-enabled mode that is
safe for CI.

A run renders exactly the figures listed in ``figures``. Whether one of
them applies is decided from the figure's own declared requirements
(:class:`hydromodpy.display.figure.FigureSpec`) against what the run
persisted, not from a second layer of per-family booleans.
"""

from __future__ import annotations

import datetime as _dt
import warnings
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning, HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

# What a figure option names an instant with, and what it used to be called.
TIME_KEY = "time"
_FORMER_TIME_KEY = "timestep"
_TIME_FORMS = 'a date (YYYY-MM-DD), "first" or "last"'


def time_selector(value: Any, where: str) -> str | int | None:
    """Return a ``time`` value in the form the display resolves, or refuse it.

    Only the shape is checked here. Whether the date falls inside the record
    needs ``[simulation.time]``, which the validate step checks. A bare TOML
    date reads as a ``date`` and is kept as its ISO text. An integer stays a
    period index. One instant only: a list is refused.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{where} = {value!r} is not a time; write {_TIME_FORMS}.")
    if isinstance(value, int):
        return value
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        raise ValueError(
            f"{where} = {list(value)!r}: a figure draws one instant, so write one "
            f"value, {_TIME_FORMS}, not a list."
        )
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in ("first", "last"):
            return text.lower()
        if text[:1].isdigit():
            import pandas as pd

            try:
                stamp = pd.Timestamp(text)
            except (TypeError, ValueError):
                stamp = None
            if stamp is not None and not pd.isna(stamp):
                return text
    raise ValueError(f"{where} = {value!r} is not a time; write {_TIME_FORMS}.")


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
        json_schema_extra={
            "value_docs": {
                "default": (
                    "Uses a colorful sans-serif palette on a white background, for screen viewing."
                ),
                "print": ("Uses a grayscale serif palette sized for black-and-white print output."),
                "dark": ("Uses a bright palette on a dark background, for dark-themed displays."),
            }
        },
    )
    show: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Open an interactive window via ``matplotlib.pyplot.show``.",
    )
    save: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write rendered figures to disk under ``output_dir``.",
    )
    output_dir: Annotated[str, Profile.USER] = Field(
        default="figures",
        description=(
            "Name of the figures directory inside the run directory "
            "(<project>/runs/<run>/<output_dir>/). Declared as a name, not a "
            "path, so it stays anchored to the run it describes."
        ),
    )
    dpi: Annotated[int, Profile.DEV] = Field(
        default=150,
        ge=1,
        description="DPI used when saving raster figures.",
    )
    cmap: Annotated[str, Profile.USER] = Field(
        default="viridis",
        description=(
            "Force ONE colormap onto every spatial figure. Writing it at all is the "
            "decision, not the value: each figure otherwise picks a scale suited to "
            "what it shows, reversed for a depth, diverging for a difference, discrete "
            "for an indicator, and this replaces all of them. Writing the default "
            "spelled out is therefore NOT a no-op, unlike everywhere else. Leave it "
            "out unless one scale for everything is what you want."
        ),
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
    time: Annotated[str | int | None, Profile.USER] = Field(
        default=None,
        description=(
            "The instant every figure that draws one instant shows: a date "
            '("2002-10-15"), "first" or "last". Each such figure draws the stress '
            "period that holds the date, so the same date names the same month on a "
            "monthly, a daily or a one-period steady run. A `time` in "
            "`[display.overrides.<figure>]` wins over it. Unset, each figure picks its "
            "own instant: the last period, or for the stream-network maps the state "
            "their calibration criterion read. A date outside a run skips the figure "
            "with the reason."
        ),
    )
    overrides: Annotated[dict[str, dict], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Per-figure options, keyed by figure name "
            "(e.g. ``{'piezometric_map': {'cmap': 'cividis', 'vmin': 0}}``). "
            "A key the figure does not take is refused at load, with the list of "
            "the keys it takes. A figure that draws one instant takes `time`."
        ),
    )

    @field_validator("time", mode="before")
    @classmethod
    def _check_time_shape(cls, value: Any) -> Any:
        return time_selector(value, "display.time")

    @field_validator("overrides", mode="before")
    @classmethod
    def _rename_former_time_key(cls, value: Any) -> Any:
        """Read the old per-figure ``timestep`` as ``time``, with a warning.

        ``overrides`` is a dict, not a model, so ``model_legacy_keys`` cannot
        carry this rename. The policy is the same: the old key loads and
        warns, and both keys in one table are refused. A project TOML reaches
        this validator already renamed: ``config_migration`` renames the key on
        load and logs it. This validator serves a ``DisplayConfig`` built from
        a dict, and the pair of keys it refuses is left untouched by the
        migration.
        """
        if not isinstance(value, Mapping):
            return value
        migrated: dict[Any, Any] = {}
        for figure, options in value.items():
            if not isinstance(options, Mapping) or _FORMER_TIME_KEY not in options:
                migrated[figure] = options
                continue
            table = f"[display.overrides.{figure}]"
            if TIME_KEY in options:
                raise ValueError(
                    f"{table} was given both {_FORMER_TIME_KEY!r} and {TIME_KEY!r}; "
                    f"{_FORMER_TIME_KEY!r} is the old spelling of {TIME_KEY!r}, so delete "
                    f"the {_FORMER_TIME_KEY!r} line. A calibration phase override "
                    f'"display.overrides.{figure}.{_FORMER_TIME_KEY}" writes that line '
                    "too: delete it, a date needs no phase override."
                )
            # stacklevel=1 names this file, as base.py does: the caller is
            # pydantic, which the console routing hides.
            warnings.warn(
                f"{_FORMER_TIME_KEY!r} is now called {TIME_KEY!r} ({table}); the old "
                "spelling still loads and will stop being read in a later version.",
                ConfigKeyRenamedWarning,
                stacklevel=1,
            )
            renamed = {k: v for k, v in options.items() if k != _FORMER_TIME_KEY}
            renamed[TIME_KEY] = options[_FORMER_TIME_KEY]
            migrated[figure] = renamed
        return migrated

    @field_validator("figures", "overrides", mode="after")
    @classmethod
    def _validate_figure_names(cls, value, info):
        """Reject figure names that are not in the registry.

        Catching the typo here (config load) instead of at render time is
        what makes a project TOML self-checking: `hmp config check` fails
        loudly rather than a run silently producing one figure less.
        """
        from hydromodpy.display.figure_registry import names, resolve

        known = set(names())
        current: dict[str, str] = {}
        unknown: list[str] = []
        for name in value:
            try:
                # A name a figure used to carry resolves to the current one and
                # warns; downstream then only ever sees one spelling.
                current[name] = resolve(name)
            except KeyError:
                unknown.append(name)
        if unknown:
            raise ValueError(
                f"display.{info.field_name} references unknown figure(s): "
                f"{', '.join(sorted(unknown))}. Registered figures: {', '.join(sorted(known))}"
            )
        if isinstance(value, dict):
            return _checked_options({current[name]: options for name, options in value.items()})
        return [current[name] for name in value]


def _checked_options(overrides: dict[str, dict]) -> dict[str, dict]:
    """Refuse a key a figure does not take, and check the shape of each ``time``.

    Every figure ``render`` ends with a ``**`` parameter, so a misspelt key
    would otherwise be swallowed and the figure drawn with its default.
    """
    from hydromodpy.display.figure_registry import figure_option_names

    problems: list[str] = []
    checked: dict[str, dict] = {}
    for figure, options in overrides.items():
        accepted = figure_option_names(figure)
        unknown = sorted(str(key) for key in options if key not in accepted)
        if unknown:
            problems.append(
                f"[display.overrides.{figure}] has no option {', '.join(map(repr, unknown))}; "
                f"{figure} takes: {', '.join(sorted(accepted))}."
            )
            continue
        options = dict(options)
        if TIME_KEY in options:
            options[TIME_KEY] = time_selector(
                options[TIME_KEY], f"display.overrides.{figure}.{TIME_KEY}"
            )
        checked[figure] = options
    if problems:
        raise ValueError(" ".join(problems))
    return checked
