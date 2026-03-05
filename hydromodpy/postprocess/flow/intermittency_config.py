"""Pydantic schema and migration helpers for intermittency postprocess options."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


def promote_legacy_intermittency_settings(value: dict) -> dict:
    """Lift legacy ``timeseries.intermittency_*`` keys to ``intermittency``."""

    raw = dict(value)
    timeseries = dict(raw.get("timeseries") or {})
    intermittency = dict(raw.get("intermittency") or {})

    legacy_to_new = {
        "intermittency_yearly": "yearly",
        "intermittency_monthly": "monthly",
        "intermittency_weekly": "weekly",
        "intermittency_daily": "daily",
    }
    moved = False
    for legacy_key, new_key in legacy_to_new.items():
        if legacy_key in timeseries and new_key not in intermittency:
            intermittency[new_key] = timeseries.pop(legacy_key)
            moved = True

    if moved:
        raw["timeseries"] = timeseries
    if intermittency:
        raw["intermittency"] = intermittency
    return raw


class IntermittencyPostprocessConfig(BaseModel):
    """Intermittency indicators derived from flow accumulation flux."""

    model_config = ConfigDict(extra="forbid")

    yearly: bool = Field(
        default=False,
        description="Compute yearly intermittency indicators from accumulation flux.",
    )
    monthly: bool = Field(
        default=True,
        description="Compute monthly intermittency indicators from accumulation flux.",
    )
    weekly: bool = Field(
        default=False,
        description="Compute weekly intermittency indicators from accumulation flux.",
    )
    daily: bool = Field(
        default=False,
        description="Compute daily intermittency indicators from accumulation flux.",
    )


__all__ = [
    "IntermittencyPostprocessConfig",
    "promote_legacy_intermittency_settings",
]
