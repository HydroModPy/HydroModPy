"""Common temporal discretization builders for MODFLOW-family solvers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from hydromodpy.core.time import SIMULATION_TIME_UNIT
from hydromodpy.core.units import to_modflow_itmuni
from hydromodpy.physics.flow.regime import normalize_flow_regime


@dataclass(slots=True)
class TemporalDiscretizationResult:
    """Typed temporal discretization container ready for solver assembly."""

    itmuni: int
    # Canonical text form of ``itmuni``. MF6 declares TDIS TIME_UNITS as text
    # and NWT declares DIS ITMUNI as a code, so both read the same field here
    # instead of restating the unit at their own call site.
    time_units: str
    nper: int
    perlen: np.ndarray
    nstp: np.ndarray
    steady: np.ndarray
    # A calendar anchor for TDIS START_DATE_TIME; pandas Timestamp is a datetime
    # subclass, so both builder paths land on datetime | None.
    start_datetime: datetime | None

    def as_dis_kwargs(self) -> dict[str, object]:
        """Return the exact key/value mapping consumed by FloPy packages."""
        return {
            "itmuni": self.itmuni,
            "nper": self.nper,
            "perlen": self.perlen,
            "nstp": self.nstp,
            "steady": self.steady,
            "start_datetime": self.start_datetime,
        }


def _coerce_first_period_steady(
    *,
    first_period_steady: bool | None,
) -> bool:
    if first_period_steady is not None:
        return bool(first_period_steady)
    return True


def _build_solver_steady_array(
    *,
    nper: int,
    flow_regime: str,
    first_period_steady: bool,
) -> np.ndarray:
    flow_regime_text = normalize_flow_regime(flow_regime)
    if flow_regime_text == "steady":
        return np.ones((nper,), dtype=bool)
    steady = np.zeros((nper,), dtype=bool)
    if first_period_steady and nper > 0:
        steady[0] = True
    return steady


def resolve_first_period_steady(
    *,
    flow: object | None = None,
    default: bool = True,
) -> bool:
    """Resolve the first-period steady policy from [flow]."""
    flow_config = getattr(flow, "config", None) if flow is not None else None
    if flow_config is not None and hasattr(flow_config, "first_period_steady"):
        return bool(flow_config.first_period_steady)
    if flow is not None and hasattr(flow, "first_period_steady"):
        return bool(flow.first_period_steady)
    return bool(default)


def build_temporal_discretization_from_time_grid(
    *,
    time_grid: object,
    flow_regime: str,
    first_period_steady: bool | None = None,
) -> TemporalDiscretizationResult:
    """Build solver temporal arrays directly from canonical launcher time-grid."""
    if time_grid is None:
        raise ValueError(
            "preprocess_options.time_grid derived from [simulation.time] is required "
            "for launcher flow preprocessing."
        )

    perlen = np.asarray(getattr(time_grid, "period_lengths_seconds", ()), dtype=float)
    nper = int(perlen.size)
    if nper == 0:
        raise ValueError("simulation.time grid produced an empty perlen vector.")

    nstp_per_period = int(getattr(time_grid, "nstp_per_period", 1) or 1)
    if nstp_per_period <= 0:
        raise ValueError("simulation.time.substeps_per_period must be a positive integer.")
    nstp = np.full((nper,), nstp_per_period, dtype=int)
    first_period_steady_value = _coerce_first_period_steady(
        first_period_steady=first_period_steady,
    )
    steady = _build_solver_steady_array(
        nper=nper,
        flow_regime=flow_regime,
        first_period_steady=first_period_steady_value,
    )

    window = getattr(time_grid, "window", None)
    start_datetime = getattr(window, "start", None)
    if start_datetime is not None and hasattr(start_datetime, "to_pydatetime"):
        start_datetime = start_datetime.to_pydatetime()

    return TemporalDiscretizationResult(
        itmuni=to_modflow_itmuni(SIMULATION_TIME_UNIT),
        time_units=SIMULATION_TIME_UNIT,
        nper=nper,
        perlen=perlen,
        nstp=nstp,
        steady=steady,
        start_datetime=start_datetime,
    )


__all__ = [
    "TemporalDiscretizationResult",
    "build_temporal_discretization_from_time_grid",
    "resolve_first_period_steady",
]
