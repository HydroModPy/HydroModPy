"""Pydantic configuration and TOML helpers for temporal mesh generation."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io.paths import get_nested_section, resolve_path
from hydromodpy.physics.flow.regime import FlowRegimeInput, normalize_flow_regime


class TMeshConfig(HydroModelBase):
    """Validated input model for ``TmeshGenerator`` settings."""

    # ``chron_colsep`` accepts single whitespace separators (e.g. ``"\t"``) so
    # we opt out of the HydroModelBase ``str_strip_whitespace`` default.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    itmuni: Annotated[str, Profile.DEV] = Field(
        default="d",
        description=(
            "Time unit used to interpret lenper values. In launcher mode stress periods "
            "come from [simulation.time], so this field is mirrored only for compatibility."
        ),
    )
    flow_regime: Annotated[FlowRegimeInput, Profile.USER] = Field(
        default="transient",
        description=(
            "Flow regime used to derive the steady/transient stress-period flags. "
            "In launcher mode this field is generally derived from [flow].flow_regime. "
            "'permanent' is accepted as a public alias for 'steady'."
        ),
    )
    genmtd: Annotated[Literal["synthetic_regular", "from_chron"], Profile.USER] = Field(
        default="synthetic_regular",
        description=(
            "Temporal generation method. In launcher mode stress periods come from "
            "[simulation.time], so this field is mirrored only for compatibility."
        ),
    )
    nper: Annotated[int, Profile.USER] = Field(
        default=1,
        description=(
            "Stress-period count. In launcher mode this is mirrored from [simulation.time] "
            "and is not the authoritative source."
        ),
    )
    lenper: Annotated[float | int | list[int] | list[float] | None, Profile.USER] = Field(
        default=1,
        description=(
            "Stress-period length(s) interpreted with itmuni. Scalar means one regular "
            "step length repeated nper times; list means one explicit value per stress period. "
            "In launcher mode this is mirrored from [simulation.time] and is not the "
            "authoritative source."
        ),
    )
    chron_path: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Chronicle file path used when genmtd='from_chron'. In launcher mode this field "
            "is generally not used."
        ),
    )
    chron_dateformat: Annotated[str, Profile.DEV] = Field(
        default="%Y-%m-%d %H:%M:%S",
        description="Date format string used to parse the chronicle file.",
    )
    chron_colsep: Annotated[str, Profile.DEV] = Field(
        default="\t",
        description="Column separator used in the chronicle file.",
    )
    chron_time_col: Annotated[str, Profile.DEV] = Field(
        default="Date",
        description="Name of the time/date column in the chronicle file.",
    )
    start_datetime: Annotated[Any | None, Profile.USER] = Field(
        default=None,
        description=(
            "Lower datetime bound used by the temporal mesh. In launcher mode this field is "
            "mirrored from [simulation.time] and is not the authoritative source."
        ),
    )
    end_datetime: Annotated[Any | None, Profile.USER] = Field(
        default=None,
        description=(
            "Upper datetime bound used by the temporal mesh. In launcher mode this field is "
            "mirrored from [simulation.time] and is not the authoritative source."
        ),
    )
    firstpersteady: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Whether the first stress period is treated as steady-state.",
    )
    tsmult: Annotated[int | float | list[int] | list[float], Profile.DEV] = Field(
        default=1,
        description=(
            "Time-step multiplier per stress period (scalar or list). In launcher mode this "
            "field is currently forced to 1.0 and generally not intended for manual editing."
        ),
    )
    ntsp: Annotated[int | list[int], Profile.DEV] = Field(
        default=1,
        description=(
            "Number of time steps per stress period (scalar or list). In launcher mode this "
            "field is currently forced to 1 and generally not intended for manual editing."
        ),
    )
    temporal_nodata: Annotated[float, Profile.DEV] = Field(
        default=-9999.0,
        description="No-data sentinel value for temporal data.",
    )

    @field_validator("itmuni", "chron_dateformat", "chron_time_col")
    @classmethod
    def _validate_non_empty_text(cls, value):
        text = str(value).strip()
        if text == "":
            raise ValueError("value cannot be empty")
        return text

    @field_validator("flow_regime", mode="before")
    @classmethod
    def _validate_flow_regime(cls, value):
        return normalize_flow_regime(value)

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
        if isinstance(value, list):
            if len(value) == 0:
                raise ValueError("lenper list cannot be empty")
            out = [float(v) for v in value]
            if any(v <= 0.0 for v in out):
                raise ValueError("lenper values must be > 0")
            return out
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
            if isinstance(self.lenper, list) and int(self.nper) != len(self.lenper):
                raise ValueError("nper must match lenper list length when lenper is a list.")
        if self.genmtd == "from_chron" and self.chron_path is None:
            raise ValueError("chron_path is required when genmtd='from_chron'")
        if self.start_datetime is not None and self.end_datetime is not None:
            try:
                start = pd.Timestamp(self.start_datetime)
                end = pd.Timestamp(self.end_datetime)
            except Exception as exc:
                raise ValueError(
                    "start_datetime and end_datetime must be valid datetime values."
                ) from exc
            if pd.isna(start) or pd.isna(end):
                raise ValueError("start_datetime and end_datetime must be valid datetime values.")
            if end < start:
                raise ValueError("end_datetime must be greater than or equal to start_datetime")
        return self

    def to_builder_kwargs(self) -> dict[str, Any]:
        """
        Convert this validated model into constructor kwargs for ``TmeshGenerator``.

        Pedagogical intent
        ------------------
        ``TMeshConfig`` is the typed/validated contract (Pydantic side),
        while ``TmeshGenerator`` expects plain Python arguments (builder side).
        This method is the bridge between both layers.

        Why return a dict?
        ------------------
        The caller can pass the result directly with ``**kwargs``:
        ``TmeshGenerator(**cfg.to_builder_kwargs())``.
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
        section_cfg = dict(get_nested_section(payload, section))
        if section_cfg.get("chron_path") is not None:
            section_cfg["chron_path"] = resolve_path(section_cfg["chron_path"], path.parent)
        return cls.model_validate(section_cfg)


def validate_tmesh_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one temporal mesh configuration mapping."""
    if not isinstance(config_data, Mapping):
        raise ValueError("tmesh configuration must be a mapping")
    try:
        parsed = TMeshConfig.from_mapping(config_data)
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
        parsed = TMeshConfig.from_toml(path, section=section)
    except ValidationError as exc:
        raise ValueError(f"Invalid tmesh configuration in {path}: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Invalid tmesh configuration in {path}: {exc}") from exc
    return parsed.model_dump(mode="python", exclude_none=True)
