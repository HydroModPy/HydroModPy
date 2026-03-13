"""Pydantic models for the launcher recharge chronicle section."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.support.units import factor_to_m_per_s, normalize_m_per_s_unit, parse_scalar_and_unit


RechargeChronicleMode = Literal["observed_csv", "synthetic_generated", "synthetic_csv"]


def _normalize_rate_unit(raw_unit: object, *, location: str) -> str:
    try:
        return normalize_m_per_s_unit(str(raw_unit))
    except ValueError as exc:
        raise ValueError(
            f"{location} must be compatible with m/s "
            "(for example mm/day, m/day, m/s)."
        ) from exc


def _convert_rate_value_to_unit(
    raw_value: object,
    *,
    location: str,
    target_unit: str,
) -> float:
    scalar, source_unit = parse_scalar_and_unit(
        raw_value,
        location=location,
        default_unit=target_unit,
    )
    canonical_source = normalize_m_per_s_unit(source_unit)
    canonical_target = normalize_m_per_s_unit(target_unit)
    value_si = float(scalar) * factor_to_m_per_s(canonical_source)
    return value_si / factor_to_m_per_s(canonical_target)


def _normalize_rate_values_payload(
    raw_values: object,
    *,
    location: str,
    target_unit: str,
) -> float | list[float] | None:
    if raw_values is None:
        return None
    if isinstance(raw_values, (list, tuple)):
        return [
            _convert_rate_value_to_unit(
                value,
                location=f"{location}[{index}]",
                target_unit=target_unit,
            )
            for index, value in enumerate(raw_values)
        ]
    return _convert_rate_value_to_unit(
        raw_values,
        location=location,
        target_unit=target_unit,
    )


class SeasonalStepRechargeChronicleConfig(BaseModel):
    """Generator-specific settings for seasonal step forcing."""

    model_config = ConfigDict(extra="forbid")

    wet_months: list[int] = Field(
        default_factory=lambda: [10, 11, 12, 1, 2, 3],
        description="Months considered wet for the seasonal step forcing.",
    )
    wet_value: float | str = Field(
        default=0.003,
        description=(
            "Recharge applied during wet months. Accepts numeric values or "
            "inline unit strings like '5.0 mm/day'."
        ),
    )
    dry_value: float | str = Field(
        default=0.0004,
        description=(
            "Recharge applied outside wet months. Accepts numeric values or "
            "inline unit strings like '0.0 mm/day'."
        ),
    )

    @field_validator("wet_months", mode="before")
    @classmethod
    def _validate_wet_months(cls, value: object) -> list[int]:
        if value is None:
            return [10, 11, 12, 1, 2, 3]
        if not isinstance(value, (list, tuple)):
            raise ValueError(
                "recharge_chronicle.synthetic_generated.seasonal_step.wet_months must be a list."
            )
        months = [int(month) for month in value]
        if any(month < 1 or month > 12 for month in months):
            raise ValueError(
                "recharge_chronicle.synthetic_generated.seasonal_step.wet_months "
                "must contain values in [1, 12]."
            )
        return months


class SyntheticGeneratedRechargeChronicleConfig(BaseModel):
    """Config for inline or generated synthetic recharge chronicle payloads."""

    model_config = ConfigDict(extra="forbid")

    values: float | str | list[float | str] | None = Field(
        default=None,
        description=(
            "Legacy explicit recharge values. Accepts scalars/lists and optional "
            "inline units; values are normalized to `units`."
        ),
    )
    periods: int | None = Field(default=None)
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    freq: str | None = Field(default=None)
    units: str = Field(
        default="mm/day",
        description="Reference unit used to interpret or normalize generated recharge values.",
    )
    runoff_ratio: float = Field(default=0.1)
    generator: str | None = Field(default=None)
    generation_step: int | float | str = Field(default="1 day")
    seasonal_step: SeasonalStepRechargeChronicleConfig | None = Field(default=None)

    @model_validator(mode="after")
    def _normalize_generated_payload(self):
        self.units = _normalize_rate_unit(
            self.units,
            location="recharge_chronicle.synthetic_generated.units",
        )

        normalized_values = _normalize_rate_values_payload(
            self.values,
            location="recharge_chronicle.synthetic_generated.values",
            target_unit=self.units,
        )
        self.values = normalized_values

        if self.generator is None:
            return self

        self.generator = str(self.generator).strip().lower() or None
        if self.generator is None:
            return self

        if self.generator != "seasonal_step":
            raise ValueError(
                "recharge_chronicle.synthetic_generated.generator must be 'seasonal_step'."
            )

        seasonal = self.seasonal_step or SeasonalStepRechargeChronicleConfig()
        seasonal.wet_value = _convert_rate_value_to_unit(
            seasonal.wet_value,
            location="recharge_chronicle.synthetic_generated.seasonal_step.wet_value",
            target_unit=self.units,
        )
        seasonal.dry_value = _convert_rate_value_to_unit(
            seasonal.dry_value,
            location="recharge_chronicle.synthetic_generated.seasonal_step.dry_value",
            target_unit=self.units,
        )
        self.seasonal_step = seasonal
        return self


class ObservedRechargeChronicleConfig(BaseModel):
    """Config for observed recharge chronicle loading."""

    model_config = ConfigDict(extra="forbid")

    path_file: str = Field(default="")
    clim_mod: str = Field(default="REA")
    clim_sce: str = Field(default="historic")
    first_year: int | None = Field(default=None)
    last_year: int | None = Field(default=None)
    time_step: str | None = Field(default=None)
    sim_state: str = Field(default="transient")
    units: str = Field(...)
    runoff_units: str | None = Field(default=None)
    runoff_ratio: float = Field(default=0.1)

    @model_validator(mode="after")
    def _normalize_units(self):
        self.units = _normalize_rate_unit(
            self.units,
            location="recharge_chronicle.observed_csv.units",
        )
        if self.runoff_units is not None:
            self.runoff_units = _normalize_rate_unit(
                self.runoff_units,
                location="recharge_chronicle.observed_csv.runoff_units",
            )
        return self


class SyntheticCsvRechargeChronicleConfig(BaseModel):
    """Config for synthetic recharge chronicle loading from CSV."""

    model_config = ConfigDict(extra="forbid")

    path_file: str = Field(default="")
    sep: str = Field(default=",")
    date_column: str = Field(default="date")
    date_format: str | None = Field(default=None)
    recharge_column: str = Field(default="recharge_mm_day")
    units: str = Field(default="mm/day")
    runoff_column: str | None = Field(default=None)
    runoff_units: str | None = Field(default=None)
    runoff_ratio: float = Field(default=0.1)
    time_step: str | None = Field(default=None)

    @model_validator(mode="after")
    def _normalize_units(self):
        self.units = _normalize_rate_unit(
            self.units,
            location="recharge_chronicle.synthetic_csv.units",
        )
        if self.runoff_units is not None:
            self.runoff_units = _normalize_rate_unit(
                self.runoff_units,
                location="recharge_chronicle.synthetic_csv.runoff_units",
            )
        return self


class RechargeChronicleConfig(BaseModel):
    """Typed config for the launcher recharge chronicle section."""

    model_config = ConfigDict(extra="forbid")

    mode: RechargeChronicleMode = Field(default="synthetic_generated")
    observed_csv: ObservedRechargeChronicleConfig | None = Field(default=None)
    synthetic_generated: SyntheticGeneratedRechargeChronicleConfig | None = Field(default=None)
    synthetic_csv: SyntheticCsvRechargeChronicleConfig | None = Field(default=None)

    @model_validator(mode="after")
    def _ensure_mode_payload(self):
        if self.mode == "observed_csv" and self.observed_csv is None:
            raise ValueError("recharge_chronicle.mode='observed_csv' requires observed_csv")
        if self.mode == "synthetic_generated" and self.synthetic_generated is None:
            self.synthetic_generated = SyntheticGeneratedRechargeChronicleConfig()
        if self.mode == "synthetic_csv" and self.synthetic_csv is None:
            self.synthetic_csv = SyntheticCsvRechargeChronicleConfig()
        return self


def validate_recharge_chronicle_section(
    value: object | None,
) -> RechargeChronicleConfig | None:
    """Validate one raw `[recharge_chronicle]` section."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("recharge_chronicle must be a mapping")
    payload = dict(value)
    if not payload:
        return None
    try:
        return RechargeChronicleConfig.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors():
            location = tuple(error.get("loc", ()))
            if location == ("mode",):
                raise ValueError(
                    "recharge_chronicle.mode must be one of "
                    "'observed_csv', 'synthetic_generated', 'synthetic_csv'."
                ) from exc
            if location == ("synthetic_generated", "values_mm_day"):
                raise ValueError(
                    "recharge_chronicle.synthetic_generated.values must be "
                    "a scalar or a list of numeric values."
                ) from exc
            if location == ("observed_csv", "units"):
                raise ValueError(
                    "recharge_chronicle.observed_csv.units is required when "
                    "recharge_chronicle.mode='observed_csv'."
                ) from exc
        raise ValueError(str(exc)) from exc


__all__ = [
    "ObservedRechargeChronicleConfig",
    "RechargeChronicleConfig",
    "RechargeChronicleMode",
    "SeasonalStepRechargeChronicleConfig",
    "SyntheticCsvRechargeChronicleConfig",
    "SyntheticGeneratedRechargeChronicleConfig",
    "validate_recharge_chronicle_section",
]
