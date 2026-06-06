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

    Provides ``date_start`` / ``date_end`` fields with ISO validation,
    date-order checking, and ``from_toml()`` classmethod.

    Subclasses must set ``_TOML_SECTION`` (e.g. ``"precipitation"``).
    """

    _TOML_SECTION: ClassVar[str | None] = None

    date_start: Annotated[IsoDateStr, Profile.USER] = Field(
        default=None,
        description="Start date of the data extraction window (ISO format, e.g. '2019-01-01').",
        examples=["2019-01-01"],
    )
    date_end: Annotated[IsoDateStr, Profile.USER] = Field(
        default=None,
        description="End date of the data extraction window (ISO format, e.g. '2025-12-31').",
        examples=["2025-12-31"],
    )

    @model_validator(mode="after")
    def _check_date_order(self):
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
