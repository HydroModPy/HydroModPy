# -*- coding: utf-8 -*-
"""
One-reservoir equations for a linear storage-outflow model.

This module contains only model equations and simulation logic.
Plotting and demonstration scenarios are intentionally kept out of this file.
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp


MODEL_NAME = "one_reservoir"
MODEL_DISPLAY_NAME = "one-reservoir"
PARAMETER_ORDER = ("C", "k")


def _get_float_value(config_section, keys, *, default=None):
    """Read first available key among aliases and cast to float."""
    for key in keys:
        if key in config_section:
            return float(config_section[key])
    if default is not None:
        return float(default)
    aliases_txt = ", ".join(keys)
    raise KeyError(f"Missing required chronicle key among: {aliases_txt}")


def parse_chronicle_parameters(chronicle_cfg):
    """
    Parse one-reservoir true parameters and initial state from chronicle config.
    """
    true_params = {
        "C": _get_float_value(chronicle_cfg, ("capacity_mm_true",)),
        "k": _get_float_value(chronicle_cfg, ("k_per_day_true",)),
    }
    initial_state = {
        "s0": _get_float_value(chronicle_cfg, ("s0_mm",), default=0.0),
    }
    return true_params, initial_state


class ReservoirModel:
    """
    Linear reservoir model with finite storage capacity (lame d'eau).

    Core mass balance with bounds
    ------------------------------
    The storage is physically constrained:

        0 ≤ S(t) ≤ C

    Governing equation (interior domain):

        dS/dt = Qin(t) - k S(t)
        Qout(t) = k S(t)

    Boundary conditions:

    - If S(t) = 0 and Qin(t) - k S(t) < 0:
        dS/dt = 0        (storage cannot become negative)

    - If S(t) = C and Qin(t) - k S(t) > 0:
        dS/dt = 0        (storage cannot exceed capacity)

    """

    def __init__(self, capacity: float, k: float):
        """
        Parameters
        ----------
        capacity : float
            Maximum storage C [mm].
        k : float
            Linear outflow coefficient in Qout = k * S [1/time].
        """
        capacity = float(capacity)
        k = float(k)
        if capacity <= 0.0:
            raise ValueError("capacity must be > 0")
        if k < 0.0:
            raise ValueError("k must be >= 0")

        self.C = capacity
        self.k = k

    def qout(self, storage: float) -> float:
        """Return outflow for a given storage S [mm]."""
        return self.k * float(storage)

    def dynamics(self, t, state, qin_func):
        """
        ODE right-hand side for solve_ivp.

        Parameters
        ----------
        t : float
            Current time.
        state : sequence
            Current state vector, expected as [S] with S in [mm].
        qin_func : callable
            Inflow function Qin(t).
        """
        storage = float(np.clip(state[0], 0.0, self.C))
        qin = float(qin_func(t))
        qout = self.qout(storage)

        dstorage_dt = qin - qout

        # Physical saturation guards.
        if storage <= 0.0 and dstorage_dt < 0.0:
            dstorage_dt = 0.0
        if storage >= self.C and dstorage_dt > 0.0:
            dstorage_dt = 0.0

        return [dstorage_dt]

    def simulate(self, qin_func, s0, t_span, t_eval):
        """
        Simulate reservoir dynamics over a time window.

        Parameters
        ----------
        qin_func : callable
            Inflow function Qin(t).
        s0 : float
            Initial storage [mm].
        t_span : tuple(float, float)
            Time interval (t0, tf).
        t_eval : array-like
            Times where the solution is sampled.

        Returns
        -------
        tuple(np.ndarray, np.ndarray, np.ndarray)
            (time, storage, qout) with storage in [mm] and flow in [mm/time].

        integrated using SciPy's `solve_ivp` with the explicit 
        Runge–Kutta method "RK45" (Dormand–Prince 5(4)).

            Key properties of RK45:
            - Explicit embedded Runge–Kutta scheme
            - Adaptive time stepping
            - 5th-order solution with 4th-order error estimator
            - Automatic step-size control based on local truncation error

            Reasons for this choice:
            - The reservoir equation is first-order and non-stiff.
            - Adaptive stepping improves numerical accuracy without manual tuning.
            - Robust handling of irregular forcing Qin(t).
            - Avoids stability constraints associated with fixed-step Euler schemes.
            - Well-tested and reliable implementation in SciPy.
        """
        s0 = float(s0)
        t_eval = np.asarray(t_eval, dtype=float)
        if t_eval.ndim != 1 or t_eval.size == 0:
            raise ValueError("t_eval must be a non-empty 1D array")

        solution = solve_ivp(
            self.dynamics,
            t_span,
            [s0],
            t_eval=t_eval,
            args=(qin_func,),
            method="RK45",
        )

        storage = np.clip(solution.y[0], 0.0, self.C)
        qout = self.k * storage
        return solution.t, storage, qout


def simulate_outflow(params, initial_state, forcing_func, t_span, t_eval):
    """
    Simulate one-reservoir outflow from model parameters and forcing callable.

    Parameters
    ----------
    params : dict
        Must provide `C` and `k`.
    initial_state : dict
        Must provide `s0`.
    forcing_func : callable
        Qin(t) forcing [mm/time].
    t_span : tuple(float, float)
        Integration time interval.
    t_eval : array-like
        Sampling times.

    Returns
    -------
    dict
        `{"qout": qout, "storage": storage}`.
    """
    params_all = {str(k): float(v) for k, v in params.items()}
    missing = [name for name in PARAMETER_ORDER if name not in params_all]
    if missing:
        raise ValueError(f"Missing one-reservoir parameter(s): {missing}")

    state = {str(k): float(v) for k, v in initial_state.items()}
    if "s0" not in state:
        raise ValueError("Missing initial state key 's0' for one_reservoir")

    model = ReservoirModel(
        capacity=float(params_all["C"]),
        k=float(params_all["k"]),
    )
    _, storage, qout = model.simulate(
        qin_func=forcing_func,
        s0=float(state["s0"]),
        t_span=t_span,
        t_eval=t_eval,
    )
    return {
        "qout": qout,
        "storage": storage,
    }
