"""Outlet, mover, spillway and per-period forcing helpers for the LAK builder.

Private helpers behind ``build_lake_outlets`` / ``build_lake_mover_records`` /
``build_lake_period_data`` / ``build_lake_obs_spec`` / ``resolve_spillway_*``:
outlet geometry and destination resolution, per-period forcing emission (inline
or TS6), the steady-period neutralisation policy and the obs id lookup.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow6.builders._lake_definitions import _lake_attr, _scalar
from hydromodpy.solver.modflow6.builders.period_forcing import (
    constant_forcing_value,
    forcing_to_si,
    forcing_unit,
    resolve_use_ts6,
    ts6_times_and_values,
)
from hydromodpy.solver.modflow6.support.time_series import Ts6Series


def _forcing_si_per_period(
    model, forcing: object, *, volumetric: bool, label: str, nper: int
) -> tuple[float, ...]:
    """Per-period SI values for a lake forcing, mirroring ``_emit_forcing_rows``.

    Resolves a typed ``FlowWellForcingConfig`` (or a mapping) through the same
    unit-conversion path the LAK PERIOD rows use, so the exposed-band callback
    reads the same SI values MF6 gets instead of ``0`` (and never mis-scaled).
    """
    if forcing is None:
        return ()
    raw = (
        forcing.get("values") if isinstance(forcing, Mapping) else getattr(forcing, "values", None)
    )
    if isinstance(raw, (list, tuple, np.ndarray)) and len(raw) > 0:
        # Explicit per-period values: take them directly and convert units.
        unit = forcing_unit(forcing)
        return tuple(
            float(forcing_to_si(v, forcing, f"{label}[{idx}]", volumetric, explicit_unit=unit))
            for idx, v in enumerate(raw)
        )
    value = constant_forcing_value(forcing)
    if value is not None:
        si_value = float(forcing_to_si(value, forcing, label, volumetric))
        return (si_value,) * max(1, int(nper)) if int(nper) > 0 else (si_value,)
    if int(nper) <= 0:
        return ()
    per_period = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=None if model.time_grid is None else model.time_grid.window,
        nper=nper,
        label=label,
    )
    unit = forcing_unit(forcing)
    return tuple(
        float(forcing_to_si(v, forcing, f"{label}[{idx}]", volumetric, explicit_unit=unit))
        for idx, v in enumerate(per_period)
    )


# --------------------------------------------------------------------------- #
# Outlets (surverse / spillway), forcings and unit conversions.
# --------------------------------------------------------------------------- #

# Config lakeout: 0 = external boundary, N = the Nth lake (1-based). FloPy stores
# the destination 0-based and writes +1, so external is -1 and lake N is N - 1.
_EXTERNAL_LAKEOUT = -1

# couttype labels accepted by MF6 (FloPy passes the string straight through).
_OUTLET_COUTTYPES = ("WEIR", "MANNING", "SPECIFIED")


def _outlet_couttype(lake_id: str, outlet: object) -> str:
    raw = _lake_attr(outlet, "couttype")
    couttype = str(raw).strip().upper() if raw is not None else ""
    if couttype not in _OUTLET_COUTTYPES:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet couttype must be one of "
            f"{', '.join(_OUTLET_COUTTYPES)}; got {raw!r}."
        )
    return couttype


def _resolve_lakeout(
    lake_id: str,
    outlet: object,
    lake_index_by_id: Mapping[str, int],
) -> int:
    """Translate the config 1-based ``lakeout`` into the FloPy destination index."""
    raw = _lake_attr(outlet, "lakeout")
    value = int(_scalar(raw)) if raw is not None else 0
    if value < 0:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet lakeout must be >= 0 "
            f"(0 = external boundary); got {value}."
        )
    if value == 0:
        return _EXTERNAL_LAKEOUT
    nlakes = len(lake_index_by_id)
    if value > nlakes:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet lakeout={value} has no "
            f"matching downstream lake ({nlakes} lakes declared)."
        )
    if value == lake_index_by_id[lake_id] + 1:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet lakeout={value} routes the lake to itself."
        )
    return value - 1


def _outlet_geometry(
    lake_id: str,
    couttype: str,
    outlet: object,
) -> tuple[float, float, float, float]:
    """Return ``(invert, width, rough, slope)`` for one outlet, validated."""
    if couttype == "SPECIFIED":
        # A specified outlet has no weir/channel geometry; MF6 ignores these.
        return 0.0, 0.0, 0.0, 0.0

    invert = _lake_attr(outlet, "invert")
    width = _lake_attr(outlet, "width")
    if invert is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet '{couttype}' requires an invert "
            "(crest / channel-bottom elevation)."
        )
    if width is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet '{couttype}' requires a width."
        )

    if couttype == "MANNING":
        rough = _lake_attr(outlet, "rough")
        slope = _lake_attr(outlet, "slope")
        if rough is None or _scalar(rough) <= 0.0:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} MANNING outlet requires a positive "
                "rough (Manning n)."
            )
        if slope is None or _scalar(slope) <= 0.0:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} MANNING outlet requires a positive slope."
            )
        return _scalar(invert), _scalar(width), _scalar(rough), _scalar(slope)

    # WEIR: rough / slope are unused by MF6.
    return _scalar(invert), _scalar(width), 0.0, 0.0


def _downstream_spillway_ref(
    definition: Mapping[str, Any], outlet_xy: tuple[float, float] | None
) -> tuple[float, float] | None:
    """Reference point for a lake's dam foot, or ``None`` if it has no auto spillway.

    Scans the lake outlets for one whose mover asks to auto-route to the downstream reach;
    returns that mover's explicit ``discharge_xy`` when given, else the domain ``outlet_xy``.
    """
    for outlet in definition.get("outlets") or []:
        mover = _lake_attr(outlet, "mover")
        if mover is None or not bool(_lake_attr(mover, "to_downstream_reach")):
            continue
        discharge_xy = _lake_attr(mover, "discharge_xy")
        if discharge_xy is not None:
            return (float(discharge_xy[0]), float(discharge_xy[1]))
        return outlet_xy
    return None


def _resolve_receiver_lake(lake_id: str, mover: object, lake_count: int) -> int:
    """Translate a ``mover.lake`` (1-based) to its 0-based receiver lake index."""
    raw = _lake_attr(mover, "lake")
    if raw is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover requires a 'lake' "
            "(1-based downstream receiving lake)."
        )
    value = int(_scalar(raw))
    if value < 1:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover lake must be >= 1 "
            f"(1-based downstream lake); got {value}."
        )
    if value > lake_count:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover lake={value} has no "
            f"matching downstream lake ({lake_count} lakes declared)."
        )
    return value - 1


# Managed transfers, as opposed to natural fluxes (runoff/rainfall/evaporation).
# A steady spin-up has no lake storage term, so a managed flux that does not
# balance the natural lake budget has no equilibrium stage and the solve
# diverges. These are neutralized on steady periods; the transient periods keep
# their real values. Mirrors the ``first_clim`` policy recharge uses on steady
# periods, except managed transfers spin up at zero, not their time-mean.
_MANAGED_FORCINGS = ("inflow", "withdrawal")


def _steady_period_flags(model) -> tuple[bool, ...]:
    """Return the per-period steady-state flags, or () when none are declared."""
    steady = getattr(model, "steady", None)
    if steady is None:
        return ()
    return tuple(bool(flag) for flag in steady)


def _neutralize_managed_on_steady(
    model, keyword: str, values: tuple[float, ...]
) -> tuple[float, ...]:
    """Zero managed lake transfers (inflow/withdrawal) on steady spin-up periods."""
    if keyword not in _MANAGED_FORCINGS:
        return values
    steady = _steady_period_flags(model)
    if not any(steady):
        return values
    return tuple(
        0.0 if (kper < len(steady) and steady[kper]) else value for kper, value in enumerate(values)
    )


def _emit_outlet_rate_rows(
    model,
    *,
    lakes: Mapping[str, dict[str, Any]],
    mode: str,
    min_periods: int,
    nper: int,
    period_rows: dict[int, list[list[Any]]],
    ts_series: list[Ts6Series],
) -> None:
    """Emit the PERIOD ``rate`` rows for SPECIFIED outlets.

    A SPECIFIED outlet releases a controlled flow supplied through perioddata; the
    PERIOD ``number`` is the (global 0-based) outlet number for outlet settings.
    Without this, MF6 initializes the outlet rate to zero and the outlet releases
    nothing. Both a constant ``rate`` and a transient ``forcing`` are handled.
    """
    outletno = 0
    for lake_id, definition in lakes.items():
        for outlet in definition.get("outlets") or []:
            couttype = str(_lake_attr(outlet, "couttype") or "").strip().upper()
            if couttype == "SPECIFIED":
                forcing = _lake_attr(outlet, "forcing")
                rate = _lake_attr(outlet, "rate")
                if forcing is not None:
                    _emit_forcing_rows(
                        model,
                        lake_index=outletno,
                        lake_id=f"{lake_id}.outlet[{outletno}]",
                        keyword="rate",
                        forcing=forcing,
                        volumetric=True,
                        mode=mode,
                        min_periods=min_periods,
                        nper=nper,
                        period_rows=period_rows,
                        ts_series=ts_series,
                    )
                elif rate is not None:
                    rate_si = (
                        float(rate.to("m**3/s").magnitude) if hasattr(rate, "to") else float(rate)
                    )
                    period_rows.setdefault(0, []).append([int(outletno), "rate", rate_si])
            outletno += 1


def _emit_steady_stage_hold_rows(
    model,
    *,
    lake_index: int,
    definition: Mapping[str, Any],
    period_rows: dict[int, list[list[Any]]],
) -> None:
    """Hold the lake CONSTANT at its starting stage over the steady warm-up.

    Opt-in through ``steady_stage_hold``: a managed reservoir's observed initial
    level is rarely the natural steady equilibrium, so the warm-up equilibrates
    the aquifer AROUND ``stageinit`` (LAK status CONSTANT) instead of solving a
    free stage that would override it. The lake re-activates on the first
    transient period and starts the chronicle exactly at ``stageinit``.
    """
    if not definition.get("steady_stage_hold"):
        return
    steady = _steady_period_flags(model)
    if not steady or not steady[0]:
        return
    period_rows.setdefault(0, []).append([int(lake_index), "status", "CONSTANT"])
    first_transient = next((k for k, flag in enumerate(steady) if not flag), None)
    if first_transient is not None:
        period_rows.setdefault(first_transient, []).append([int(lake_index), "status", "ACTIVE"])


def _emit_forcing_rows(
    model,
    *,
    lake_index: int,
    lake_id: str,
    keyword: str,
    forcing: object,
    volumetric: bool,
    mode: str,
    min_periods: int,
    nper: int,
    period_rows: dict[int, list[list[Any]]],
    ts_series: list[Ts6Series],
) -> None:
    """Append LAK PERIOD rows (inline floats or a TS6 name) for one forcing.

    A constant forcing emits a single inline ``[i, kw, float]`` row in period 0.
    A non-constant forcing routes to a TS6 series when ``resolve_use_ts6`` opts
    in (one period-0 row carrying the series name). Otherwise it is expanded
    inline: one ``[i, kw, float]`` row per stress period whenever the value
    changes (period 0 always), so a time-varying forcing is never dropped.
    """
    if forcing is None:
        return
    location = f"flow.sinks_sources.lakes.{lake_id}.{keyword}"
    value = constant_forcing_value(forcing)
    use_ts6 = resolve_use_ts6(forcing, mode=mode, nper=nper, min_periods=min_periods)
    if value is not None and not use_ts6:
        si_value = float(forcing_to_si(value, forcing, location, volumetric))
        steady = _steady_period_flags(model)
        if keyword in _MANAGED_FORCINGS and steady and steady[0]:
            # Constant managed transfer: hold it at zero through the steady spin-up,
            # then apply the configured value from the first transient period on.
            period_rows.setdefault(0, []).append([int(lake_index), keyword, 0.0])
            first_transient = next((k for k, flag in enumerate(steady) if not flag), None)
            if first_transient is not None:
                period_rows.setdefault(first_transient, []).append(
                    [int(lake_index), keyword, si_value]
                )
        else:
            period_rows.setdefault(0, []).append([int(lake_index), keyword, si_value])
        return

    # A non-constant forcing needs the solver period grid to expand. Without a
    # model (nper unknown) there is nothing to resolve, so emit nothing.
    if nper <= 0:
        return

    per_period = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=None if model.time_grid is None else model.time_grid.window,
        nper=nper,
        label=location,
    )
    unit = forcing_unit(forcing)
    per_period_si = tuple(
        float(forcing_to_si(raw, forcing, f"{location}[{idx}]", volumetric, explicit_unit=unit))
        for idx, raw in enumerate(per_period)
    )
    per_period_si = _neutralize_managed_on_steady(model, keyword, per_period_si)

    if use_ts6:
        series_name = _ts6_series_name(lake_index, keyword)
        period_rows.setdefault(0, []).append([int(lake_index), keyword, series_name])
        times, values = ts6_times_and_values(model, per_period_si)
        ts_series.append(
            Ts6Series(
                name=series_name,
                times=times,
                values=values,
                interpolation="stepwise",
            )
        )
        return

    # Inline expansion: one row per stress period whenever the value changes. MF6
    # carries each value forward until the next row, so a constant tail collapses
    # to a single row while every genuine change is preserved.
    previous: float | None = None
    for kper, si_value in enumerate(per_period_si):
        if previous is None or si_value != previous:
            period_rows.setdefault(kper, []).append([int(lake_index), keyword, si_value])
            previous = si_value


def _ts6_series_name(lake_index: int, keyword: str) -> str:
    """Return a unique, MF6-length-safe TS6 series name for one lake forcing."""
    return f"lak{int(lake_index)}_{keyword}"[:16]


def _lake_id_for_index(lake_conn_info: Sequence[Mapping[str, Any]], lake_index: int) -> str:
    """Return the lake id for one 0-based lake index."""
    for info in lake_conn_info:
        if int(info["lake_index"]) == lake_index:
            return str(info["lake_id"])
    raise ValueError(f"No lake registered for lake index {lake_index}.")
