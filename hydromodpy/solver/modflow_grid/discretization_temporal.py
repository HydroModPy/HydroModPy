"""Common temporal discretization builders for MODFLOW-family solvers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.core.units import to_modflow_itmuni
from hydromodpy.physics.flow.regime import normalize_flow_regime


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


_MISSING = object()


def _field_was_set(model: object, field: str) -> bool:
    fields_set = getattr(model, "model_fields_set", None)
    if fields_set is None:
        return False
    return field in set(fields_set)


def _coerce_first_period_steady(
    *,
    first_period_steady: bool | None,
    firstpersteady: bool | None,
) -> bool:
    if first_period_steady is not None and firstpersteady is not None:
        if bool(first_period_steady) != bool(firstpersteady):
            raise ValueError(
                "first_period_steady conflicts with deprecated firstpersteady."
            )
        return bool(first_period_steady)
    if first_period_steady is not None:
        return bool(first_period_steady)
    if firstpersteady is not None:
        return bool(firstpersteady)
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
    legacy_tgrid: object | None = None,
    default: bool = True,
) -> bool:
    """Resolve the first-period steady policy from [flow], with legacy fallback."""
    flow_config = getattr(flow, "config", None) if flow is not None else None
    flow_value = _MISSING
    if flow_config is not None and _field_was_set(flow_config, "first_period_steady"):
        flow_value = getattr(flow_config, "first_period_steady")
    elif flow_config is None and flow is not None and hasattr(flow, "first_period_steady"):
        flow_value = getattr(flow, "first_period_steady")

    legacy_value = _MISSING
    if legacy_tgrid is not None and hasattr(legacy_tgrid, "firstpersteady"):
        legacy_value = getattr(legacy_tgrid, "firstpersteady")

    if flow_value is not _MISSING and legacy_value is not _MISSING:
        if bool(flow_value) != bool(legacy_value):
            raise ValueError(
                "flow.first_period_steady conflicts with legacy tgrid.firstpersteady."
            )
        return bool(flow_value)
    if flow_value is not _MISSING:
        return bool(flow_value)
    if legacy_value is not _MISSING:
        return bool(legacy_value)
    return bool(default)


def build_temporal_discretization_from_time_grid(
    *,
    time_grid: object,
    flow_regime: str,
    first_period_steady: bool | None = None,
    firstpersteady: bool | None = None,
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
        firstpersteady=firstpersteady,
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
    first_period_steady: bool | None = None,
) -> TemporalDiscretizationResult:
    """Build normalized temporal discretization from typed ``tgrid`` config."""
    from hydromodpy.discretization.time.tmesh_generation import TmeshGenerator

    builder_kwargs = tgrid_config.to_builder_kwargs()
    builder = TmeshGenerator(**builder_kwargs)
    tgrid = builder.run()

    dis_itmuni = _coerce_itmuni(
        getattr(tgrid, "time_units", default_itmuni),
        default_itmuni,
    )
    dis_perlen = np.asarray(getattr(tgrid, "perlen", []), dtype=float)
    dis_nper = int(dis_perlen.size)
    dis_nstp = np.asarray(getattr(tgrid, "nstp", []), dtype=int)
    first_period_steady_value = _coerce_first_period_steady(
        first_period_steady=first_period_steady,
        firstpersteady=getattr(tgrid_config, "firstpersteady", None),
    )
    dis_steady = _build_solver_steady_array(
        nper=dis_nper,
        flow_regime=flow_regime,
        first_period_steady=first_period_steady_value,
    )
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
    "resolve_first_period_steady",
]
