"""
Synthetic chronicle builder for the transient 1D groundwater case.

This module creates:
- forcing series (constant h0 and transient R(t)),
- one "true" simulation h(x, t),
- noisy synthetic observations at selected x/t indices.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.cases.groundwater_1d.model import (
    Hydro1DNumerics,
    Hydro1DParameters,
    simulate,
)
from hydromodpy.hydrology.synthetic.forcing import (
    build_hydrological_step_series,
    build_hydrological_year_dates,
    build_recharge_from_reservoir_chronicle,
)

def _build_time_vector(*, n_days, dt_days):
    n_days = float(n_days)
    dt_days = float(dt_days)
    if n_days <= 0.0 or dt_days <= 0.0:
        raise ValueError("n_days and dt_days must be > 0")
    n_steps = int(np.floor(n_days / dt_days))
    return np.linspace(0.0, n_steps * dt_days, n_steps + 1, dtype=float)


def _nearest_indices(grid, values):
    grid = np.asarray(grid, dtype=float).ravel()
    values = np.asarray(values, dtype=float).ravel()
    indices = np.empty(values.size, dtype=int)
    for i, target in enumerate(values):
        indices[i] = int(np.argmin(np.abs(grid - target)))
    return indices


def _default_observation_locations(*, L, xi):
    """
    Return default observation x-locations at zone midpoints.
    """
    return np.asarray([0.5 * xi, 0.5 * (xi + L)], dtype=float)


def _build_recharge_series(chronicle_cfg, t):
    """
    Build recharge series with one of two reusable forcing modes.
    """
    n_forcing = int(np.asarray(t).size)
    start_year = int(chronicle_cfg.get("start_year", 2000))
    mode = str(chronicle_cfg["recharge_mode"]).strip().lower()

    if mode == "hydro_step":
        dates = build_hydrological_year_dates(n_days=n_forcing, start_year=start_year)
        recharge_series = build_hydrological_step_series(
            dates=dates,
            wet_months=tuple(chronicle_cfg["recharge_wet_months"]),
            wet_value=float(chronicle_cfg["recharge_wet_m_per_day"]),
            dry_value=float(chronicle_cfg["recharge_dry_m_per_day"]),
        )
        forcing_metadata = {
            "recharge_mode": mode,
            "dates": dates,
        }
        return dates, recharge_series, forcing_metadata

    if mode == "reservoir_chronicle":
        forcing_data = build_recharge_from_reservoir_chronicle(
            n_days=n_forcing,
            start_year=start_year,
            target_annual_precip_mm=float(chronicle_cfg["target_annual_precip_mm"]),
            precip_seed=int(chronicle_cfg["precip_seed"]),
            runoff_coeff=float(chronicle_cfg["runoff_coeff"]),
            losses_mm_day=float(chronicle_cfg["losses_mm_day"]),
            losses_months=tuple(chronicle_cfg["losses_months"]),
            scale_to_m_per_day=1.0e-3,
        )
        precip_mm_day = np.asarray(forcing_data["precip_mm_day"], dtype=float)
        peff_mm_day = np.asarray(forcing_data["peff_mm_day"], dtype=float)
        qin_mm_day = np.asarray(forcing_data["qin_mm_day"], dtype=float)
        forcing_metadata = {
            "recharge_mode": mode,
            "dates": forcing_data["dates"],
            "precip_mm_day": precip_mm_day,
            "peff_mm_day": peff_mm_day,
            # Actual losses applied by the simple bucket logic.
            "etr_mm_day": np.maximum(precip_mm_day - peff_mm_day, 0.0),
            # In this simplified forcing chain, runoff is the Qin term later
            # rescaled to become recharge for the groundwater case.
            "runoff_mm_day": qin_mm_day,
            "qin_mm_day": qin_mm_day,
        }
        return forcing_data["dates"], forcing_data["recharge_m_per_day"], forcing_metadata

    raise ValueError(f"Unsupported recharge_mode '{mode}'")


def build_synthetic_groundwater_chronicle(chronicle_cfg):
    """
    Build one synthetic calibration chronicle.

    Parameters
    ----------
    chronicle_cfg : Mapping[str, Any]
        Validated case config dictionary.

    Returns
    -------
    dict
        Structured payload used by workflow, plotting and case adapter.
    """
    n_days = float(chronicle_cfg["n_days"])
    dt_days = float(chronicle_cfg["dt_days"])
    t = _build_time_vector(n_days=n_days, dt_days=dt_days)

    h0_constant = float(chronicle_cfg["h0_m"])
    h0_series = np.full(t.size, h0_constant, dtype=float)
    dates, recharge_series, forcing_metadata = _build_recharge_series(chronicle_cfg, t=t)

    true_params = {
        "Kam": float(chronicle_cfg["Kam_true_m_per_day"]),
        "Kav": float(chronicle_cfg["Kav_true_m_per_day"]),
        "Syam": float(chronicle_cfg["Syam_true"]),
        "Syav": float(chronicle_cfg["Syav_true"]),
        "xi": float(chronicle_cfg["xi_true_m"]),
    }
    model_parameters = Hydro1DParameters(
        L=float(chronicle_cfg["L_m"]),
        xi=true_params["xi"],
        Kam=true_params["Kam"],
        Kav=true_params["Kav"],
        Syam=true_params["Syam"],
        Syav=true_params["Syav"],
        H=float(chronicle_cfg["H_linearized_m"]),
    )
    numerics = Hydro1DNumerics(
        nx=int(chronicle_cfg["nx"]),
        formulation=str(chronicle_cfg["formulation_true"]),
        max_picard_iterations=int(chronicle_cfg["picard_max_iter"]),
        picard_tolerance=float(chronicle_cfg["picard_tol"]),
        picard_relaxation=float(chronicle_cfg["picard_relaxation"]),
        head_floor=float(chronicle_cfg["head_floor_m"]),
    )

    obs_x_values = np.asarray(chronicle_cfg.get("obs_x_m", ()), dtype=float).ravel()
    if obs_x_values.size == 0:
        obs_x_values = _default_observation_locations(
            L=float(chronicle_cfg["L_m"]),
            xi=float(chronicle_cfg["xi_true_m"]),
        )

    # Initial condition requested for this case:
    # h(x,0) = h0 everywhere.
    h_init_value = h0_constant

    simulation_true = simulate(
        t=t,
        h0=h0_series,
        recharge=recharge_series,
        parameters=model_parameters,
        numerics=numerics,
        h_init=h_init_value,
        return_flux=True,
    )

    x = np.asarray(simulation_true["x"], dtype=float)
    h_true = np.asarray(simulation_true["h"], dtype=float)
    obs_nodes = _nearest_indices(x, obs_x_values)
    x_mid_upstream = 0.5 * float(true_params["xi"])
    x_mid_downstream = 0.5 * (float(model_parameters.L) + float(true_params["xi"]))
    midpoint_nodes = _nearest_indices(x, [x_mid_upstream, x_mid_downstream])
    obs_time_indices = np.arange(0, t.size, int(chronicle_cfg["obs_t_stride"]), dtype=int)
    if obs_time_indices[-1] != (t.size - 1):
        obs_time_indices = np.append(obs_time_indices, t.size - 1)

    obs_true_matrix = h_true[np.ix_(obs_time_indices, obs_nodes)]
    noise_std = float(chronicle_cfg["obs_noise_std_m"])
    rng = np.random.default_rng(int(chronicle_cfg["obs_seed"]))
    obs_noisy_matrix = obs_true_matrix + rng.normal(
        loc=0.0,
        scale=noise_std,
        size=obs_true_matrix.shape,
    )

    return {
        "t": t,
        "x": x,
        "x_face": np.asarray(simulation_true["x_face"], dtype=float),
        "h_true": h_true,
        "flux_true": None if simulation_true["flux_face"] is None else np.asarray(simulation_true["flux_face"], dtype=float),
        "dates": np.asarray(dates, dtype=object),
        "h0_series": np.asarray(h0_series, dtype=float),
        "recharge_series": np.asarray(recharge_series, dtype=float),
        "forcing_metadata": forcing_metadata,
        "obs_time_indices": obs_time_indices,
        "obs_node_indices": obs_nodes,
        "obs_time_days": t[obs_time_indices],
        "obs_x_m": x[obs_nodes],
        "midpoint_node_indices": midpoint_nodes,
        "midpoint_x_m": x[midpoint_nodes],
        "obs_true_matrix": obs_true_matrix,
        "obs_noisy_matrix": obs_noisy_matrix,
        "obs_true_vector": obs_true_matrix.ravel(order="C"),
        "obs_vector": obs_noisy_matrix.ravel(order="C"),
        "true_params": true_params,
        "fixed_model_parameters": {
            "L": float(model_parameters.L),
            "H": float(model_parameters.H),
            "formulation": str(numerics.formulation),
            "nx": int(numerics.nx),
            "recharge_mode": str(chronicle_cfg["recharge_mode"]),
            "h0_m": h0_constant,
            "h_init": h_init_value,
            "max_picard_iterations": int(numerics.max_picard_iterations),
            "picard_tolerance": float(numerics.picard_tolerance),
            "picard_relaxation": float(numerics.picard_relaxation),
            "head_floor": float(numerics.head_floor),
        },
    }


__all__ = ("build_synthetic_groundwater_chronicle",)

