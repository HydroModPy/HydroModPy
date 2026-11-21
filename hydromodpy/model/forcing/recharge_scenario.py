"""A recharge scenario built from the loaded recharge: the mean year, with dry years inserted.

Abherve (2022, section 5.3.5) tests how a catchment stands consecutive dry years.
The "normal" scenario repeats the mean year, month by month, over the whole
run. The "2-years" and "5-years" scenarios put 2 or 5 dry years in a row into
it, each equal month by month to the mean of chosen historical dry years (1975
and 1976 in the thesis). The run then reads the scenario in place of the loaded
recharge, so the volume of a normal year is kept and only the sequence changes.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.soil_grids import (
    _guard_dims,
    _open_field_dataset,
    _variable_array,
    grid_field_record,
)


class RechargeScenarioConfig(HydroModelBase):
    """Replace the loaded recharge by its mean year, with dry years put in a row."""

    dry_years: Annotated[list[int], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Historical years whose mean, month by month, makes the dry year, such as "
            "[1975, 1976]. Empty, the scenario is the mean year alone, repeated."
        ),
        examples=[[1975, 1976]],
    )
    repeat: Annotated[int, Profile.USER] = Field(
        default=0,
        ge=0,
        le=50,
        description="Number of dry years put in a row, 2 or 5 in the thesis; 0 with no dry_years.",
        json_schema_extra=field_metadata(unit="year"),
    )
    start: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description="Calendar year of the first dry year of the scenario.",
        json_schema_extra=field_metadata(unit="year"),
        examples=[1990],
    )

    @model_validator(mode="after")
    def _dry_years_come_with_their_sequence(self) -> RechargeScenarioConfig:
        if bool(self.dry_years) != (self.repeat > 0) or bool(self.dry_years) != (
            self.start is not None
        ):
            raise ValueError(
                "dry_years, repeat and start go together: write the three to insert dry "
                "years, or none of them for the mean year alone."
            )
        return self


def scenario_values(values: np.ndarray, stamps: pd.DatetimeIndex, config: RechargeScenarioConfig):
    """The scenario of ``values`` (T, N) stamped by ``stamps``, in the same unit and shape."""
    month = stamps.month.to_numpy() - 1
    year = stamps.year.to_numpy()
    if np.unique(month).size < 12:
        raise DataContractViolation(
            "[flow.sinks_sources.recharge.scenario] builds a mean year month by month, and "
            f"the loaded recharge covers {np.unique(month).size} of the 12 months: load a "
            "whole year at least."
        )
    normal = np.vstack([values[month == m].mean(axis=0) for m in range(12)])
    out = normal[month]
    if config.dry_years:
        in_dry_years = np.isin(year, config.dry_years)
        missing = sorted(set(config.dry_years) - set(year[in_dry_years]))
        if missing:
            raise DataContractViolation(
                f"[flow.sinks_sources.recharge.scenario] dry_years names {missing}, which "
                "the loaded recharge does not cover: load the recharge over those years."
            )
        dry = np.vstack([values[in_dry_years & (month == m)].mean(axis=0) for m in range(12)])
        sequence = (year >= config.start) & (year < config.start + config.repeat)
        if not sequence.any():
            raise DataContractViolation(
                f"[flow.sinks_sources.recharge.scenario] puts the dry years from "
                f"{config.start}, and the run covers {year.min()} to {year.max()}: start "
                "the dry years inside the run."
            )
        out[sequence] = dry[month[sequence]]
    return out


def recharge_scenario(recharge: LoadResultProto, config: RechargeScenarioConfig) -> LoadResultProto:
    """The loaded recharge replaced by its scenario, grids and stations alike."""
    if recharge.has_fields:
        fields = []
        for record in recharge.fields:
            da = _guard_dims(
                _variable_array(_open_field_dataset(record), record, section="[data.recharge]"),
                section="[data.recharge]",
            )
            stamps = pd.DatetimeIndex(da["time"].values)
            x, y = da["x"].values, da["y"].values
            values = np.asarray(da.values, dtype=np.float64).reshape(len(stamps), -1)
            fields.append(
                grid_field_record(
                    "recharge",
                    scenario_values(values, stamps, config),
                    x=x,
                    y=y,
                    days=stamps.values,
                    like=record,
                    source=f"{record.source} scenario",
                )
            )
        return type(recharge)(fields=fields)
    points = []
    for record in recharge.points:
        frame = record.data.sort_values("datetime").reset_index(drop=True)
        stamps = pd.DatetimeIndex(frame["datetime"])
        values = frame["value"].to_numpy(dtype=np.float64)[:, np.newaxis]
        frame = frame.assign(value=scenario_values(values, stamps, config)[:, 0])
        points.append(replace(record, data=frame, is_constant=False))
    return type(recharge)(points=points)


__all__ = ["RechargeScenarioConfig", "recharge_scenario", "scenario_values"]
