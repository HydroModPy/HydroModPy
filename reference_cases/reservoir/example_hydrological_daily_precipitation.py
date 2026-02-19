# -*- coding: utf-8 -*-
"""
Hydrological-style reservoir example with daily precipitation forcing.

Run from repository root:
    python reference_cases/reservoir/example_hydrological_daily_precipitation.py

Scenario summary
----------------
1. Build one hydrological year starting on October 1st.
2. Generate synthetic daily precipitation and rescale it to 800 mm/year.
3. Convert precipitation to inflow with:
   - runoff coefficient,
   - seasonal losses applied only from April to September.
4. Simulate a linear reservoir in water-depth units (mm and mm/day).
5. Plot precipitation, Qin/Qout, and storage trajectories.
"""

from __future__ import annotations

from datetime import date, timedelta

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from reservoir_equations import ReservoirModel


def generate_daily_precipitation(n_days: int = 365, seed: int = 42) -> np.ndarray:
    """
    Generate a synthetic daily precipitation series [mm/day].

    The signal mimics a temperate-climate seasonality + stochastic events:
    - markedly wetter winter/autumn,
    - drier summer,
    - occasional intense storms (more frequent in wet season).
    """
    rng = np.random.default_rng(seed)
    day = np.arange(n_days)

    # Stronger seasonal wet-day probability (winter wet, summer dry).
    wet_probability = 0.22 + 0.20 * np.cos(2.0 * np.pi * (day - 15.0) / 365.0)
    wet_probability = np.clip(wet_probability, 0.03, 0.62)
    wet_day = rng.random(n_days) < wet_probability

    # Seasonal event intensity: deeper events during wet season.
    seasonal_intensity = 0.70 + 0.55 * np.cos(2.0 * np.pi * (day - 20.0) / 365.0)
    seasonal_intensity = np.clip(seasonal_intensity, 0.25, None)
    event_depth = rng.gamma(shape=1.7, scale=7.0 * seasonal_intensity, size=n_days)
    precip = wet_day.astype(float) * event_depth

    # Add a few stronger storms, weighted toward wet season.
    storm_weights = wet_probability / np.sum(wet_probability)
    storm_days = rng.choice(n_days, size=6, replace=False, p=storm_weights)
    precip[storm_days] += rng.uniform(20.0, 55.0, size=storm_days.size)

    return precip


def enforce_annual_precipitation_total(
    precip_mm_day: np.ndarray,
    target_annual_mm: float = 800.0,
) -> np.ndarray:
    """
    Rescale daily precipitation so its annual cumulative total matches target.
    """
    precip = np.asarray(precip_mm_day, dtype=float).ravel()
    if precip.size == 0:
        raise ValueError("precip_mm_day cannot be empty")
    if target_annual_mm <= 0.0:
        raise ValueError("target_annual_mm must be > 0")

    current_total = float(np.sum(precip))
    if current_total <= 0.0:
        raise ValueError("Cannot rescale precipitation with non-positive total")

    scale = float(target_annual_mm) / current_total
    return precip * scale


def build_hydrological_year_dates(
    n_days: int,
    start_year: int = 2000,
) -> np.ndarray:
    """
    Build daily dates for a hydrological year starting on October 1st.
    """
    start = date(start_year, 10, 1)
    return np.array([start + timedelta(days=i) for i in range(n_days)], dtype=object)


def precipitation_to_inflow(
    precip_mm_day: np.ndarray,
    dates: np.ndarray,
    runoff_coeff: float = 0.15,
    losses_mm_day: float = 1.5,
    losses_months: tuple[int, ...] = (4, 5, 6, 7, 8, 9),
) -> tuple[np.ndarray, np.ndarray]:
    """
    Convert precipitation [mm/day] into inflow Qin [mm/day].

    A simple production rule is used:
    Peff = max(P - losses, 0)
    Qin = Peff * runoff_coeff

    Losses are applied only for selected calendar months (default: Apr-Sep).
    """
    if not (0.0 <= runoff_coeff <= 1.0):
        raise ValueError("runoff_coeff must be in [0, 1]")
    precip = np.asarray(precip_mm_day, dtype=float).ravel()
    dates = np.asarray(dates, dtype=object).ravel()
    if precip.size != dates.size:
        raise ValueError("precip_mm_day and dates must have the same length")

    losses_mask = np.array([int(d.month) in losses_months for d in dates], dtype=bool)
    losses_series = np.where(losses_mask, losses_mm_day, 0.0)

    peff_mm_day = np.maximum(precip - losses_series, 0.0)
    qin_mm_day = peff_mm_day * runoff_coeff
    return peff_mm_day, qin_mm_day


def make_piecewise_constant_daily_qin(qin_daily_mm_day: np.ndarray):
    """
    Build Qin(t) callable from daily values (piecewise-constant by day).

    Notes
    -----
    `t` is interpreted in day units from the start of the hydrological year
    (day 0 = 1st October).
    """
    qin_daily_mm_day = np.asarray(qin_daily_mm_day, dtype=float).ravel()
    if qin_daily_mm_day.size == 0:
        raise ValueError("qin_daily_mm_day cannot be empty")

    def qin_func(t):
        day_idx = int(np.floor(float(t)))
        day_idx = int(np.clip(day_idx, 0, qin_daily_mm_day.size - 1))
        return float(qin_daily_mm_day[day_idx])

    return qin_func


def plot_hydrological_reservoir_response(
    dates: np.ndarray,
    precip_mm_day: np.ndarray,
    peff_mm_day: np.ndarray,
    qin_mm_day: np.ndarray,
    qout_mm_day: np.ndarray,
    storage_mm: np.ndarray,
    capacity_mm: float,
):
    """
    Plot precipitation forcing and reservoir response.

    Parameters
    ----------
    dates : np.ndarray
        Daily datetime-like values over one hydrological year.
    precip_mm_day : np.ndarray
        Raw precipitation [mm/day].
    peff_mm_day : np.ndarray
        Effective precipitation after losses [mm/day].
    qin_mm_day : np.ndarray
        Inflow to reservoir [mm/day].
    qout_mm_day : np.ndarray
        Outflow from reservoir [mm/day].
    storage_mm : np.ndarray
        Reservoir storage [mm].
    capacity_mm : float
        Maximum storage capacity [mm].
    """
    storage_ratio = storage_mm / capacity_mm
    annual_total_mm = float(np.sum(precip_mm_day))

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, dpi=130)

    # Panel 1: precipitation.
    ax0 = axes[0]
    ax0.bar(dates, precip_mm_day, width=1.0, color="tab:blue", alpha=0.7, label="P [mm/day]")
    ax0.plot(dates, peff_mm_day, color="tab:cyan", lw=1.4, label="Peff [mm/day]")
    ax0.set_ylabel("Precipitation [mm/day]")
    ax0.set_title(
        f"Daily precipitation forcing (annual total = {annual_total_mm:.1f} mm, losses Apr-Sep)"
    )
    ax0.grid(True, ls=":", alpha=0.4)
    ax0.legend(loc="upper right")

    # Panel 2: inflow vs outflow.
    ax1 = axes[1]
    ax1.plot(dates, qin_mm_day, color="tab:green", lw=1.8, label="Qin [mm/day]")
    ax1.plot(dates, qout_mm_day, color="tab:orange", lw=1.8, label="Qout [mm/day]")
    ax1.set_ylabel("Flow [mm/day]")
    ax1.grid(True, ls=":", alpha=0.4)
    ax1.legend(loc="upper right")

    # Panel 3: storage state.
    ax2 = axes[2]
    ax2.plot(dates, storage_mm, color="tab:purple", lw=1.9, label="S [mm]")
    ax2.axhline(capacity_mm, color="0.35", ls="--", lw=1.2, label="Capacity C")
    ax2_twin = ax2.twinx()
    ax2_twin.plot(dates, storage_ratio, color="0.2", ls=":", lw=1.4, label="S/C [-]")
    ax2.set_xlabel("Hydrological year (start: 1 Oct)")
    ax2.set_ylabel("Storage [mm]")
    ax2_twin.set_ylabel("Fill ratio")
    ax2.grid(True, ls=":", alpha=0.4)
    ax2.legend(loc="upper left")
    ax2_twin.legend(loc="upper right")

    month_locator = mdates.MonthLocator(interval=1)
    month_formatter = mdates.DateFormatter("%b")
    for ax in axes:
        ax.xaxis.set_major_locator(month_locator)
        ax.xaxis.set_major_formatter(month_formatter)
    fig.autofmt_xdate()

    fig.tight_layout()
    plt.show()


def main():
    """
    Run the full hydrological reservoir example.

    Design choices
    --------------
    - Hydrological year starts on October 1st.
    - Annual precipitation is normalized to 800 mm.
    - Runoff coefficient is set to 0.15.
    - Losses are applied only during April-September.
    - Initial storage is 0 mm at the start date.
    """
    # Daily forcing over one hydrological year.
    n_days = 365
    hydro_dates = build_hydrological_year_dates(n_days=n_days, start_year=2000)
    target_annual_precip_mm = 800.0
    precip_mm_day_raw = generate_daily_precipitation(n_days=n_days, seed=42)
    precip_mm_day = enforce_annual_precipitation_total(
        precip_mm_day=precip_mm_day_raw,
        target_annual_mm=target_annual_precip_mm,
    )

    # Simple rainfall-runoff conversion to reservoir inflow.
    runoff_coeff = 0.15
    losses_mm_day = 1.5
    peff_mm_day, qin_daily_mm_day = precipitation_to_inflow(
        precip_mm_day=precip_mm_day,
        dates=hydro_dates,
        runoff_coeff=runoff_coeff,
        losses_mm_day=losses_mm_day,
    )

    # Reservoir model parameters in water-depth units.
    capacity_mm = 10.0
    k_per_day = 0.04  # 3x slower emptying than previous value (0.12 / 3)
    s0_mm = 0.0  # Storage at 1st October

    model = ReservoirModel(capacity=capacity_mm, k=k_per_day)
    qin_func = make_piecewise_constant_daily_qin(qin_daily_mm_day)

    t_eval = np.arange(n_days, dtype=float)
    _, storage_mm, qout_mm_day = model.simulate(
        qin_func=qin_func,
        s0=s0_mm,
        t_span=(0.0, n_days - 1.0),
        t_eval=t_eval,
    )

    qin_mm_day = qin_daily_mm_day.copy()
    plot_hydrological_reservoir_response(
        dates=hydro_dates,
        precip_mm_day=precip_mm_day,
        peff_mm_day=peff_mm_day,
        qin_mm_day=qin_mm_day,
        qout_mm_day=qout_mm_day,
        storage_mm=storage_mm,
        capacity_mm=capacity_mm,
    )


if __name__ == "__main__":
    main()
