"""An observation, with everything the loader knew about it.

``PointRecord`` arrives from the data layer carrying the unit, the sampling
frequency, the station's position, the source, and a quality dictionary with the
completeness and the count of gaps. ``ObservedSeries``, the shape every cost read,
kept three of those: an id, a variable name, and a pandas series. The rest was
dropped one layer after it had been computed.

That loss has consequences a cost cannot recover from. A profile in metres below
ground scored against a head in absolute elevation is a defensible model compared
to the wrong reference, and nothing could notice because the unit was gone. And
the error model is what makes a weighted sum defensible at all: a residual
divided by what the instrument can resolve is a pure number, and only pure
numbers add up. A weight then says what the modeller privileges, which is a
different question and deserves its own multiplication.

Nothing here is inferred. An error model absent is absent, and asking for a sigma
without one is refused rather than answered with a default nobody chose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

Sampling = Literal["regular", "occasional"]


@dataclass(frozen=True)
class ObservationRecord:
    """One observed series and what is known about how it was measured."""

    station_id: str
    variable: str
    series: pd.Series

    unit: str | None = None
    """The unit the loader resolved. A cost that cannot check it cannot catch a
    depth compared to an elevation."""

    source: str | None = None
    frequency: str | None = None

    sampling: Sampling = "regular"
    """``occasional`` is a manual reading: paired to the nearest date within
    ``date_tolerance`` rather than expected on every step."""

    date_tolerance: pd.Timedelta | None = None

    error_relative: float | None = None
    """A share of the value. A gauge rated to eight per cent declares 0.08."""

    error_absolute: float | None = None
    """The same magnitude at every value, in the unit of the series."""

    error_floor: float | None = None
    """A lower bound on sigma, so a relative model does not collapse to zero at
    low flow and hand one sample an unbounded weight."""

    completeness_pct: float | None = None
    n_missing: int | None = None
    location: Any = None

    def __post_init__(self) -> None:
        for name in ("error_relative", "error_absolute", "error_floor"):
            value = getattr(self, name)
            if value is not None and float(value) < 0.0:
                raise ValueError(f"{name} cannot be negative, got {value!r}")
        if self.date_tolerance is not None and self.sampling != "occasional":
            raise ValueError(
                "date_tolerance is only read for sampling='occasional'; on a regular "
                "record every step is expected, so a tolerance would be a setting "
                "nothing reads."
            )

    @property
    def has_error_model(self) -> bool:
        """Whether this record can say what its own measurement resolves."""
        return self.error_relative is not None or self.error_absolute is not None

    def sigma_at(self, value: float) -> float:
        """Return what the instrument can resolve at ``value``.

        The larger of the relative and the absolute term, then raised to the
        floor. Taking the larger rather than adding them is the conservative
        reading: each is a statement about the same measurement, so the binding
        one wins instead of the two compounding.
        """
        if not self.has_error_model:
            raise ValueError(
                f"observation {self.station_id!r} declares no error model, so what its "
                "measurement resolves is unknown. Declare error_relative, "
                "error_absolute, or both."
            )
        candidates = [0.0]
        if self.error_relative is not None:
            candidates.append(abs(float(value)) * float(self.error_relative))
        if self.error_absolute is not None:
            candidates.append(float(self.error_absolute))
        sigma = max(candidates)
        if self.error_floor is not None:
            sigma = max(sigma, float(self.error_floor))
        return float(sigma)

    @classmethod
    def from_point_record(
        cls,
        record: Any,
        *,
        sampling: Sampling = "regular",
        date_tolerance: str | pd.Timedelta | None = None,
        error_relative: float | None = None,
        error_absolute: float | None = None,
        error_floor: float | None = None,
    ) -> ObservationRecord:
        """Build from what the data layer loaded, keeping all of it.

        The error model is not in a ``PointRecord``: no loader knows the rating
        curve of a gauge or the accuracy of a staff. It is declared beside the
        observation, which is why it arrives here as arguments.
        """
        frame = getattr(record, "data", None)
        index = pd.DatetimeIndex(pd.to_datetime(frame["datetime"]))
        series = pd.Series(
            frame["value"].astype("float64").to_numpy(),
            index=index,
            name=f"{record.variable}_obs",
        )
        quality = getattr(record, "quality", None) or {}
        return cls(
            station_id=str(record.station_id),
            variable=str(record.variable),
            series=series,
            unit=getattr(record, "unit", None),
            source=getattr(record, "source", None),
            frequency=getattr(record, "frequency", None),
            sampling=sampling,
            date_tolerance=None if date_tolerance is None else pd.Timedelta(date_tolerance),
            error_relative=error_relative,
            error_absolute=error_absolute,
            error_floor=error_floor,
            completeness_pct=quality.get("completeness_pct"),
            n_missing=quality.get("n_missing"),
            location=getattr(record, "location", None),
        )


__all__ = ["ObservationRecord", "Sampling"]
