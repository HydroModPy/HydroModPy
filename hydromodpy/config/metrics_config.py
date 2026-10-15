"""The ``[metrics]`` section: where and when a run is scored after it ends.

A score is a number with a station and a window, or no number. The NSE of a
run is computed on ``[metrics] window`` at ``[metrics] station`` (default
``[site] gauge``), never on an overlap deduced from the data; without a window
the score is left empty. Calibration scores its own window, which defaults to
this one.

TOML form::

    [metrics]
    station = "J0014010"                                   # optional, default [site] gauge
    window = { start = "2001-01-01", end = "2002-12-31" }  # the spin-up year stays out
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class MetricsWindow(HydroModelBase):
    """The dates a run is scored on, both included."""

    start: Annotated[date, Profile.USER] = Field(
        description="First day the scores count, as an ISO 8601 date.",
        examples=["2001-01-01"],
    )
    end: Annotated[date, Profile.USER] = Field(
        description="Last day the scores count, included, as an ISO 8601 date.",
        examples=["2002-12-31"],
    )

    @model_validator(mode="after")
    def _ordered(self) -> MetricsWindow:
        if self.end < self.start:
            raise ValueError(
                f"[metrics] window ends on {self.end} before it starts on {self.start}."
            )
        return self


class MetricsConfig(HydroModelBase):
    """The station and the window the scores of a run are computed on."""

    station: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=("Station the run is scored at. Unset, it is [site] gauge."),
        examples=["J0014010"],
    )
    window: Annotated[MetricsWindow | None, Profile.USER] = Field(
        default=None,
        description=(
            "Dates the run is scored on, as {start, end}. Unset, the scores are left "
            "empty: a score over an overlap the data happen to give is not comparable."
        ),
        examples=[{"start": "2001-01-01", "end": "2002-12-31"}],
    )


__all__ = ["MetricsConfig", "MetricsWindow"]
