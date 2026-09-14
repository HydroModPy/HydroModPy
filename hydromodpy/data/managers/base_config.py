"""Shared Pydantic base classes for variable config files.

Eliminates ~1500 lines of duplicated validators, TOML loading logic,
and path resolution boilerplate across all variable config.py files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IsoDateStr
from hydromodpy.core.toml_io.loader import validate_toml
from hydromodpy.core.toml_io.paths import resolve_declared_path


class BaseVariableConfig(HydroModelBase):
    """Base for top-level variable configs (``XxxConfig``).

    Provides an optional ``date_start`` / ``date_end`` window with ISO
    validation, window checking, and a ``from_toml()`` classmethod.

    The window is optional because the runtime loader inherits it from
    ``[simulation.time]`` when the section declares neither bound. Declaring
    it is an override, and it must be declared as a pair.

    Subclasses must set ``_TOML_SECTION`` (e.g. ``"precipitation"``).
    """

    _TOML_SECTION: ClassVar[str | None] = None

    date_start: Annotated[IsoDateStr, Profile.USER] = Field(
        default=None,
        description=(
            "Start of the data window (ISO date, e.g. '2019-01-01'). Optional: "
            "when neither bound is declared, the loader inherits "
            "[simulation.time].start_datetime, or [overview].date_start in "
            "overview mode. Declare it only to fetch a window WIDER than the "
            "simulation, typically a cache shared by several runs. Must be "
            "declared together with date_end."
        ),
        examples=["2019-01-01"],
    )
    date_end: Annotated[IsoDateStr, Profile.USER] = Field(
        default=None,
        description=(
            "End of the data window (ISO date, e.g. '2025-12-31'). Optional: "
            "when neither bound is declared, the loader inherits "
            "[simulation.time].end_datetime, or [overview].date_end in "
            "overview mode. Declare it only to fetch a window WIDER than the "
            "simulation, typically a cache shared by several runs. Must be "
            "declared together with date_start."
        ),
        examples=["2025-12-31"],
    )

    @model_validator(mode="after")
    def _check_date_window(self):
        if bool(self.date_start) != bool(self.date_end):
            missing = "date_end" if self.date_start else "date_start"
            where = f"data.{self._TOML_SECTION}: " if self._TOML_SECTION else ""
            raise ValueError(
                f"{where}{missing} is missing: declare date_start and date_end together, "
                "or declare neither and inherit the window from [simulation.time]"
            )
        if self.date_start and self.date_end:
            from datetime import datetime

            if datetime.fromisoformat(self.date_start) >= datetime.fromisoformat(self.date_end):
                raise ValueError("date_start must be before date_end")
        return self

    @classmethod
    def from_toml(cls, path: str | Path):
        """Load config from a TOML file.

        Relative paths (``path``, ``mask_path``) in the TOML are resolved
        relative to the TOML file's directory, not the CWD.
        """
        if cls._TOML_SECTION is None:
            raise NotImplementedError(f"{cls.__name__} must define _TOML_SECTION")
        return validate_toml(
            cls,
            path,
            section=cls._TOML_SECTION,
            base_dir_resolver=_resolve_source_paths,
        )


def _resolve_source_paths(cfg: BaseVariableConfig, toml_dir: Path) -> BaseVariableConfig:
    """Resolve ``path`` and ``mask_path`` on each source relative to *toml_dir*."""
    sources = getattr(cfg, "sources", [])
    for src in sources:
        if getattr(src, "path", None) is not None:
            src.path = resolve_declared_path(src.path, base_dir=toml_dir)
        if getattr(src, "mask_path", None) is not None:
            src.mask_path = resolve_declared_path(src.mask_path, base_dir=toml_dir)
    return cfg
