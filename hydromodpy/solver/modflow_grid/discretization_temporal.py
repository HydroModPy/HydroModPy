"""Common temporal discretization builders for MODFLOW-family solvers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.core.units import to_modflow_itmuni


@dataclass(slots=True)
class TemporalDiscretizationResult:
    """Typed temporal discretization container ready for solver assembly."""

    itmuni: int
    nper: int
    perlen: np.ndarray
    nstp: np.ndarray
    steady: np.ndarray
    start_datetime: object | None

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


def _coerce_itmuni(value: object, default_itmuni: int) -> int:
    """Convert temporal unit payload to MODFLOW ITMUNI integer code."""
    if value is None:
        return int(default_itmuni)
    text = str(value).strip()
    if text == "":
        return int(default_itmuni)
    try:
        return int(to_modflow_itmuni(value))
    except ValueError as exc:
        raise ValueError(
            f"Unsupported time_units value {value!r}. "
            "Expected ITMUNI code or unit label (seconds/minutes/hours/days/years)."
        ) from exc


def build_temporal_discretization_from_time_grid(
    *,
    time_grid: object,
    flow_regime: str,
    firstpersteady: bool,
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
    flow_regime_text = str(flow_regime).strip().lower()
    if flow_regime_text == "steady":
        steady = np.ones((nper,), dtype=bool)
    else:
        steady = np.zeros((nper,), dtype=bool)
        if firstpersteady:
            steady[0] = True

    window = getattr(time_grid, "window", None)
    start_datetime = getattr(window, "start", None)
    if start_datetime is not None and hasattr(start_datetime, "to_pydatetime"):
        start_datetime = start_datetime.to_pydatetime()

    return TemporalDiscretizationResult(
        itmuni=1,
        nper=nper,
        perlen=perlen,
        nstp=nstp,
        steady=steady,
        start_datetime=start_datetime,
    )


def build_temporal_discretization(
    *,
    tgrid_config: object,
    flow_regime: str,
    default_itmuni: int,
) -> TemporalDiscretizationResult:
    """Build normalized temporal discretization from typed ``tgrid`` config."""
    from hydromodpy.solver.utils.temporal.tmesh_generation import TmeshGenerator

    builder_kwargs = tgrid_config.to_builder_kwargs()
    builder_kwargs["flow_regime"] = flow_regime
    builder = TmeshGenerator(**builder_kwargs)
    tgrid = builder.run()

    dis_itmuni = _coerce_itmuni(
        getattr(tgrid, "time_units", default_itmuni),
        default_itmuni,
    )
    dis_perlen = np.asarray(getattr(tgrid, "perlen", []), dtype=float)
    dis_nper = int(dis_perlen.size)
    dis_nstp = np.asarray(getattr(tgrid, "nstp", []), dtype=int)
    dis_steady = np.asarray(getattr(tgrid, "steady_state", []), dtype=bool)
    dis_start_datetime = getattr(tgrid, "start_datetime", None)
    if dis_nper == 0:
        raise ValueError("modflownwt.tgrid produced an empty perlen vector.")

    return TemporalDiscretizationResult(
        itmuni=dis_itmuni,
        nper=dis_nper,
        perlen=dis_perlen,
        nstp=dis_nstp,
        steady=dis_steady,
        start_datetime=dis_start_datetime,
    )


__all__ = [
    "TemporalDiscretizationResult",
    "build_temporal_discretization",
    "build_temporal_discretization_from_time_grid",
]
