"""Shared Pydantic base classes for variable config files.

Eliminates ~1500 lines of duplicated validators, TOML loading logic,
and path resolution boilerplate across all variable config.py files.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.config.path_resolution import resolve_declared_path


def _load_toml(path: Path) -> dict:
    """Load a TOML file, with Python 3.10 fallback to ``tomli``."""
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)


class BaseVariableConfig(BaseModel):
    """Base for top-level variable configs (``XxxConfig``).

    Provides ``date_start`` / ``date_end`` fields with ISO validation,
    date-order checking, and ``from_toml()`` classmethod.

    Subclasses must set ``_TOML_SECTION`` (e.g. ``"precipitation"``).
    """

    model_config = ConfigDict(extra="forbid")

    _TOML_SECTION: str = ""

    date_start: Optional[str] = Field(
        default=None, description="Project start date (ISO format, e.g. '2019-01-01').",
    )
    date_end: Optional[str] = Field(
        default=None, description="Project end date (ISO format, e.g. '2025-12-31').",
    )

    @field_validator("date_start", "date_end", mode="after")
    @classmethod
    def _validate_iso_date(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            from datetime import datetime
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Invalid ISO date: '{v}'. Expected YYYY-MM-DD.")
        return v

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
        path = Path(path).resolve()
        data = _load_toml(path)
        section = data.get(cls._TOML_SECTION, data) if cls._TOML_SECTION else data
        cfg = cls.model_validate(section)
        _resolve_source_paths(cfg, path.parent)
        return cfg


def _resolve_source_paths(cfg: BaseVariableConfig, toml_dir: Path) -> None:
    """Resolve ``path`` and ``mask_path`` on each source relative to *toml_dir*."""
    sources = getattr(cfg, "sources", [])
    for src in sources:
        if getattr(src, "path", None) is not None:
            src.path = resolve_declared_path(src.path, base_dir=toml_dir)
        if getattr(src, "mask_path", None) is not None:
            src.mask_path = resolve_declared_path(src.mask_path, base_dir=toml_dir)
