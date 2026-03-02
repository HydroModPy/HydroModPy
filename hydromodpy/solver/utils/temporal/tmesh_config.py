"""Pydantic configuration and TOML helpers for temporal mesh generation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import tomllib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """Resolve one nested section using dotted syntax (for example ``case.mesh``)."""
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def _resolve_path(path_value: str | Path, base_dir: Path) -> str:
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


class TMeshConfigModel(BaseModel):
    """Validated input model for ``TMesh_Generation`` settings."""

    model_config = ConfigDict(extra="forbid")

    itmuni: str = "d"
    flow_regime: Literal["steady", "transient"] = "transient"
    genmtd: Literal["synthetic_regular", "from_chron"] = "synthetic_regular"
    nper: int = 1
    lenper: float | int | None = 1
    chron_path: str | None = None
    chron_dateformat: str = "%Y-%m-%d %H:%M:%S"
    chron_colsep: str = "\t"
    chron_time_col: str = "Date"
    start_datetime: Any | None = None
    end_datetime: Any | None = None
    firstpersteady: bool = True
    tsmult: int | float | list[int] | list[float] = 1
    ntsp: int | list[int] = 1
    temporal_nodata: float = -9999.0

    @field_validator("itmuni", "chron_dateformat", "chron_time_col")
    @classmethod
    def _validate_non_empty_text(cls, value):
        text = str(value).strip()
        if text == "":
            raise ValueError("value cannot be empty")
        return text

    @field_validator("chron_colsep")
    @classmethod
    def _validate_non_empty_colsep(cls, value):
        text = str(value)
        if text == "":
            raise ValueError("value cannot be empty")
        return text

    @field_validator("chron_path")
    @classmethod
    def _validate_chron_path_text(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("chron_path cannot be empty when provided")
        return str(Path(text).expanduser())

    @field_validator("nper")
    @classmethod
    def _validate_positive_nper(cls, value):
        out = int(value)
        if out <= 0:
            raise ValueError("nper must be > 0")
        return out

    @field_validator("lenper")
    @classmethod
    def _validate_positive_lenper(cls, value):
        if value is None:
            return None
        out = float(value)
        if out <= 0.0:
            raise ValueError("lenper must be > 0")
        return out

    @field_validator("ntsp")
    @classmethod
    def _validate_ntsp(cls, value):
        if isinstance(value, list):
            if len(value) == 0:
                raise ValueError("ntsp list cannot be empty")
            out = [int(v) for v in value]
            if any(v <= 0 for v in out):
                raise ValueError("ntsp values must be > 0")
            return out
        out = int(value)
        if out <= 0:
            raise ValueError("ntsp must be > 0")
        return out

    @field_validator("tsmult")
    @classmethod
    def _validate_tsmult(cls, value):
        if isinstance(value, list):
            if len(value) == 0:
                raise ValueError("tsmult list cannot be empty")
            out = [float(v) for v in value]
            if any(v <= 0.0 for v in out):
                raise ValueError("tsmult values must be > 0")
            return out
        out = float(value)
        if out <= 0.0:
            raise ValueError("tsmult must be > 0")
        return out

    @model_validator(mode="after")
    def _validate_cross_fields(self):
        if self.genmtd == "synthetic_regular":
            if self.lenper is None:
                raise ValueError("lenper is required when genmtd='synthetic_regular'")
        if self.genmtd == "from_chron" and self.chron_path is None:
            raise ValueError("chron_path is required when genmtd='from_chron'")
        return self

    def to_builder_kwargs(self) -> dict[str, Any]:
        """
        Convert this validated model into constructor kwargs for ``TMesh_Generation``.

        Pedagogical intent
        ------------------
        ``TMeshConfigModel`` is the typed/validated contract (Pydantic side),
        while ``TMesh_Generation`` expects plain Python arguments (builder side).
        This method is the bridge between both layers.

        Why return a dict?
        ------------------
        The caller can pass the result directly with ``**kwargs``:
        ``TMesh_Generation(**cfg.to_builder_kwargs())``.
        This keeps the runtime path explicit and avoids duplicating field-by-field
        mapping logic at each call site.

        Normalization choices
        ---------------------
        - ``mode="python"`` returns Python-native values.
        - ``exclude_none=True`` drops optional keys not set by the user, so the
          builder uses its own defaults instead of receiving explicit ``None``.

        Notes
        -----
        Runtime-only overrides (for example ``flow_regime``) are intentionally
        injected by the caller after this conversion.
        """
        return self.model_dump(mode="python", exclude_none=True)

    @classmethod
    def from_mapping(cls, config_data: Mapping[str, Any]):
        """Validate and build from flat mapping or top-level ``tmesh`` mapping."""
        payload = dict(config_data.get("tmesh", config_data))
        return cls.model_validate(payload)

    @classmethod
    def from_toml(
        cls,
        config_path: str | Path,
        *,
        section: str = "tmesh",
    ):
        """Load TOML section, resolve relative paths, then validate."""
        path = Path(config_path).expanduser().resolve()
        payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        section_cfg = dict(_get_nested_section(payload, section))
        if section_cfg.get("chron_path") is not None:
            section_cfg["chron_path"] = _resolve_path(section_cfg["chron_path"], path.parent)
        return cls.model_validate(section_cfg)


def validate_tmesh_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one temporal mesh configuration mapping."""
    if not isinstance(config_data, Mapping):
        raise ValueError("tmesh configuration must be a mapping")
    try:
        parsed = TMeshConfigModel.from_mapping(config_data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def load_tmesh_toml(
    config_path: str | Path,
    *,
    section: str = "tmesh",
) -> dict[str, Any]:
    """Load and validate temporal mesh configuration from TOML."""
    path = Path(config_path).expanduser().resolve()
    try:
        parsed = TMeshConfigModel.from_toml(path, section=section)
    except ValidationError as exc:
        raise ValueError(f"Invalid tmesh configuration in {path}: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Invalid tmesh configuration in {path}: {exc}") from exc
    return parsed.model_dump(mode="python", exclude_none=True)
