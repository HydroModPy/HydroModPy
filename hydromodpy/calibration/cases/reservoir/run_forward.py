# -*- coding: utf-8 -*-
"""
Unified hydrological reservoir example driven by TOML configuration.

Run from repository root:
    python hydromodpy/calibration2/cases/reservoir/run_forward.py

This script supports:
- one linear reservoir (`one_reservoir`),
- two linear reservoirs with precipitation split (`two_reservoir`).

Didactic workflow
-----------------
1) Read and validate the forward TOML configuration.
2) Build one synthetic hydrological forcing chronicle.
3) Run either one-reservoir or two-reservoir forward simulation.
4) Plot forcing/response diagnostics.
5) Save and optionally display the figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import tomllib

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.cases.utils.forcing import (
    build_hydrological_year_dates,
    enforce_annual_precipitation_total,
    generate_daily_precipitation,
    make_piecewise_constant_daily_qin,
    precipitation_to_inflow,
)
from hydromodpy.calibration.cases.reservoir.models.one_reservoir import (
    simulate_outflow as simulate_one_outflow,
)
from hydromodpy.calibration.cases.reservoir.models.two_reservoirs import (
    simulate_outflow as simulate_two_outflow,
)
from hydromodpy.calibration.cases.reservoir.workflow import (
    DEFAULT_MODEL_NAME,
    MODEL_REGISTRY,
    get_model_display_name,
)


DEFAULT_CONFIG_FILE = "config_forward.toml"


@dataclass
class ForcingConfig:
    """Hydrological forcing controls shared by both model variants."""

    n_days: int
    start_year: int
    target_annual_precip_mm: float
    precip_seed: int
    runoff_coeff: float
    losses_mm_day: float
    losses_months: tuple[int, ...]


@dataclass
class OneReservoirConfig:
    """Configuration for one-reservoir simulation."""

    capacity_mm: float
    k_per_day: float
    s0_mm: float


@dataclass
class TwoReservoirConfig:
    """Configuration for two-reservoir simulation."""

    a: float
    kq_days: float
    ks_days: float
    sq0_mm: float
    ss0_mm: float


def load_example_config(config_path):
    """
    Load forward TOML configuration and check required sections.

    This is a lightweight section-presence validation; value-level validation is
    handled by parser functions below.
    """
    path = Path(config_path)
    with path.open("rb") as stream:
        config = tomllib.load(stream)

    for section in ("forcing", "model", "one_reservoir", "two_reservoir"):
        if section not in config:
            raise KeyError(f"Missing [{section}] section in {path}")
    return config


def resolve_model_name(config, model_name_override=None):
    """
    Resolve model selector from TOML or optional function override.

    Only canonical names registered in `MODEL_REGISTRY` are accepted.
    """
    if model_name_override is None:
        raw = str(config["model"].get("model_name", DEFAULT_MODEL_NAME)).strip().lower()
    else:
        raw = str(model_name_override).strip().lower()

    if raw not in MODEL_REGISTRY:
        allowed_txt = ", ".join(sorted(MODEL_REGISTRY))
        raise ValueError(f"Unknown model_name '{raw}'. Allowed canonical names: {allowed_txt}")
    return raw


def resolve_solver_backend(model_cfg):
    """
    Resolve numerical backend from `[model]` section.

    Supported values:
    - ``analytic``: exact discrete update for piecewise-constant forcing.
    - ``ode``: SciPy ODE integration.
    """
    raw = str(model_cfg.get("solver_backend", "analytic")).strip().lower()
    if raw not in {"analytic", "ode"}:
        raise ValueError("model.solver_backend must be 'analytic' or 'ode'")
    return raw


def parse_forcing_config(forcing_cfg):
    """Parse `[forcing]` section into a typed config."""
    return ForcingConfig(
        n_days=int(forcing_cfg.get("n_days", 365)),
        start_year=int(forcing_cfg.get("start_year", 2000)),
        target_annual_precip_mm=float(forcing_cfg.get("target_annual_precip_mm", 800.0)),
        precip_seed=int(forcing_cfg.get("precip_seed", 42)),
        runoff_coeff=float(forcing_cfg.get("runoff_coeff", 0.15)),
        losses_mm_day=float(forcing_cfg.get("losses_mm_day", 1.5)),
        losses_months=tuple(forcing_cfg.get("losses_months", (4, 5, 6, 7, 8, 9))),
    )


def parse_one_reservoir_config(one_cfg):
    """Parse `[one_reservoir]` section into a typed config."""
    return OneReservoirConfig(
        capacity_mm=float(one_cfg.get("capacity_mm", 10.0)),
        k_per_day=float(one_cfg.get("k_per_day", 0.04)),
        s0_mm=float(one_cfg.get("s0_mm", 0.0)),
    )


def parse_two_reservoir_config(two_cfg):
    """Parse `[two_reservoir]` section into a typed config."""
    return TwoReservoirConfig(
        a=float(two_cfg.get("a", 0.35)),
        kq_days=float(two_cfg.get("kq_days", 3.0)),
        ks_days=float(two_cfg.get("ks_days", 45.0)),
        sq0_mm=float(two_cfg.get("sq0_mm", 0.0)),
        ss0_mm=float(two_cfg.get("ss0_mm", 0.0)),
    )


def build_hydrological_forcing(cfg: ForcingConfig):
    """
    Generate forcing chronicle shared by both model variants.

    Returns
    -------
    tuple
        `(dates, precip_mm_day, peff_mm_day, qin_mm_day)`.
    """
    # Build dates over one hydrological year.
    dates = build_hydrological_year_dates(n_days=cfg.n_days, start_year=cfg.start_year)
    # Generate synthetic precipitation and enforce exact annual total.
    precip_mm_day = enforce_annual_precipitation_total(
        precip_mm_day=generate_daily_precipitation(n_days=cfg.n_days, seed=cfg.precip_seed),
        target_annual_mm=cfg.target_annual_precip_mm,
    )
    # Convert precipitation to effective rainfall and inflow.
    peff_mm_day, qin_mm_day = precipitation_to_inflow(
        precip_mm_day=precip_mm_day,
        dates=dates,
        runoff_coeff=cfg.runoff_coeff,
        losses_mm_day=cfg.losses_mm_day,
        losses_months=cfg.losses_months,
    )
    return dates, precip_mm_day, peff_mm_day, qin_mm_day


def _apply_month_axis(axes):
    """Apply monthly ticks shared by all reservoir plots."""
    month_locator = mdates.MonthLocator(interval=1)
    month_formatter = mdates.DateFormatter("%b")
    for ax in axes:
        ax.xaxis.set_major_locator(month_locator)
        ax.xaxis.set_major_formatter(month_formatter)


def plot_one_reservoir_response(
    dates,
    precip_mm_day,
    peff_mm_day,
    qin_mm_day,
    qout_mm_day,
    storage_mm,
    capacity_mm,
):
    """Plot forcing and response for one-reservoir model."""
    storage_ratio = storage_mm / capacity_mm
    annual_total_mm = float(np.sum(precip_mm_day))

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, dpi=130)

    ax0 = axes[0]
    ax0.bar(dates, precip_mm_day, width=1.0, color="tab:blue", alpha=0.7, label="P [mm/day]")
    ax0.plot(dates, peff_mm_day, color="tab:cyan", lw=1.4, label="Peff [mm/day]")
    ax0.set_ylabel("Precipitation [mm/day]")
    ax0.set_title(
        f"One linear reservoir (annual P = {annual_total_mm:.1f} mm, losses Apr-Sep)"
    )
    ax0.grid(True, ls=":", alpha=0.4)
    ax0.legend(loc="upper right")

    ax1 = axes[1]
    ax1.plot(dates, qin_mm_day, color="tab:green", lw=1.8, label="Qin [mm/day]")
    ax1.plot(dates, qout_mm_day, color="tab:orange", lw=1.8, label="Qout [mm/day]")
    ax1.set_ylabel("Flow [mm/day]")
    ax1.grid(True, ls=":", alpha=0.4)
    ax1.legend(loc="upper right")

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

    _apply_month_axis(axes)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def plot_two_reservoir_response(
    dates,
    precip_mm_day,
    qq_mm_day,
    qs_mm_day,
    q_total_mm_day,
    sq_mm,
    ss_mm,
):
    """Plot forcing and response for two-reservoir model."""
    s_total_mm = sq_mm + ss_mm
    annual_total_mm = float(np.sum(precip_mm_day))

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, dpi=130)

    ax0 = axes[0]
    ax0.bar(dates, precip_mm_day, width=1.0, color="tab:blue", alpha=0.7, label="P [mm/day]")
    ax0.set_ylabel("Precipitation [mm/day]")
    ax0.set_title(f"Two linear reservoirs with precipitation split (annual P = {annual_total_mm:.1f} mm)")
    ax0.grid(True, ls=":", alpha=0.4)
    ax0.legend(loc="upper right")

    ax1 = axes[1]
    ax1.plot(dates, qq_mm_day, color="tab:orange", lw=1.7, label="Qq (quick) [mm/day]")
    ax1.plot(dates, qs_mm_day, color="tab:green", lw=1.7, label="Qs (slow) [mm/day]")
    ax1.plot(dates, q_total_mm_day, color="0.15", lw=2.0, label="Q = Qq + Qs [mm/day]")
    ax1.set_ylabel("Flow [mm/day]")
    ax1.grid(True, ls=":", alpha=0.4)
    ax1.legend(loc="upper right")

    ax2 = axes[2]
    ax2.plot(dates, sq_mm, color="tab:red", lw=1.7, label="Sq [mm]")
    ax2.plot(dates, ss_mm, color="tab:purple", lw=1.7, label="Ss [mm]")
    ax2.plot(dates, s_total_mm, color="0.2", ls="--", lw=1.7, label="Sq + Ss [mm]")
    ax2.set_xlabel("Hydrological year (start: 1 Oct)")
    ax2.set_ylabel("Storage [mm]")
    ax2.grid(True, ls=":", alpha=0.4)
    ax2.legend(loc="upper right")

    _apply_month_axis(axes)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def _save_if_requested(fig, output_cfg, model_name):
    """
    Save figure if requested in `[output]`.

    Returns
    -------
    pathlib.Path | None
        Saved path when `save_figure=true`, else `None`.
    """
    save_figure = bool(output_cfg.get("save_figure", False))
    if not save_figure:
        return None

    output_dir = str(output_cfg.get("output_dir", "outputs"))
    default_name = f"hydrological_reservoir_{model_name}.png"
    figure_name = str(output_cfg.get("figure_name", default_name))
    output_path = Path(__file__).resolve().parent / output_dir / figure_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    return output_path


def run_hydrological_example(config, model_name_override=None):
    """
    Run one/two-reservoir hydrological simulation based on TOML choice.

    This function contains the full forward workflow used by `main()`.
    """
    # Step 1: resolve model and forcing configuration.
    model_name = resolve_model_name(config, model_name_override=model_name_override)
    solver_backend = resolve_solver_backend(config["model"])
    forcing_cfg = parse_forcing_config(config["forcing"])
    # Step 2: build shared forcing chronicle.
    dates, precip_mm_day, peff_mm_day, qin_mm_day = build_hydrological_forcing(forcing_cfg)
    t_eval = np.arange(forcing_cfg.n_days, dtype=float)

    if model_name == "one_reservoir":
        # Step 3a: one-reservoir forward simulation driven by Qin(t).
        one_cfg = parse_one_reservoir_config(config["one_reservoir"])
        qin_func = make_piecewise_constant_daily_qin(qin_mm_day)
        simulation = simulate_one_outflow(
            params={"C": one_cfg.capacity_mm, "k": one_cfg.k_per_day},
            initial_state={"s0": one_cfg.s0_mm},
            forcing_func=qin_func,
            t_span=(0.0, forcing_cfg.n_days - 1.0),
            t_eval=t_eval,
            solver_backend=solver_backend,
        )
        storage_mm = np.asarray(simulation["storage"], dtype=float)
        qout_mm_day = np.asarray(simulation["qout"], dtype=float)
        fig = plot_one_reservoir_response(
            dates=dates,
            precip_mm_day=precip_mm_day,
            peff_mm_day=peff_mm_day,
            qin_mm_day=qin_mm_day,
            qout_mm_day=qout_mm_day,
            storage_mm=storage_mm,
            capacity_mm=one_cfg.capacity_mm,
        )
    else:
        # Step 3b: two-reservoir forward simulation driven by precipitation P(t).
        two_cfg = parse_two_reservoir_config(config["two_reservoir"])
        precip_func = make_piecewise_constant_daily_qin(precip_mm_day)
        simulation = simulate_two_outflow(
            params={"a": two_cfg.a, "Kq": two_cfg.kq_days, "Ks": two_cfg.ks_days},
            initial_state={"sq0": two_cfg.sq0_mm, "ss0": two_cfg.ss0_mm},
            forcing_func=precip_func,
            t_span=(0.0, forcing_cfg.n_days - 1.0),
            t_eval=t_eval,
            solver_backend=solver_backend,
        )
        sq_mm = np.asarray(simulation["sq"], dtype=float)
        ss_mm = np.asarray(simulation["ss"], dtype=float)
        qq_mm_day = sq_mm / float(two_cfg.kq_days)
        qs_mm_day = ss_mm / float(two_cfg.ks_days)
        q_total_mm_day = np.asarray(simulation["qout"], dtype=float)
        fig = plot_two_reservoir_response(
            dates=dates,
            precip_mm_day=precip_mm_day,
            qq_mm_day=qq_mm_day,
            qs_mm_day=qs_mm_day,
            q_total_mm_day=q_total_mm_day,
            sq_mm=sq_mm,
            ss_mm=ss_mm,
        )

    # Step 4: save and/or show figure according to `[output]`.
    output_cfg = config.get("output", {})
    output_path = _save_if_requested(fig, output_cfg, model_name=model_name)
    show_plot = bool(output_cfg.get("show_plot", True))
    if show_plot:
        plt.show()
    else:
        plt.close(fig)

    if output_path is not None:
        print(f"Saved figure: {output_path}")
    print(f"Hydrological example completed with model={get_model_display_name(model_name)}")


def main(model_name_override=None):
    """Entry point for the TOML-driven forward reservoir example."""
    # Keep `main()` intentionally short: config load + workflow call.
    config_path = Path(__file__).with_name(DEFAULT_CONFIG_FILE)
    config = load_example_config(config_path)
    run_hydrological_example(config, model_name_override=model_name_override)


if __name__ == "__main__":
    main()

