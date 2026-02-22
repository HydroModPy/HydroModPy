# -*- coding: utf-8 -*-
"""
One-reservoir equations for a linear storage-outflow model.

This module only contains model equations and simulation logic.
Plotting/demo concerns are intentionally kept outside this file.
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp


MODEL_NAME = "one_reservoir"
MODEL_DISPLAY_NAME = "one-reservoir"
PARAMETER_ORDER = ("C", "k")


def _require_float(config_section, key):
    """Read one required float key from a chronicle config mapping."""
    if key not in config_section:
        raise KeyError(f"Missing required chronicle key: {key}")
    return float(config_section[key])


def parse_chronicle_parameters(chronicle_cfg):
    """
    Parse one-reservoir true parameters and initial state from chronicle config.

    Returns
    -------
    tuple[dict[str, float], dict[str, float]]
        `(true_params, initial_state)` where:
        - `true_params = {"C": ..., "k": ...}`
        - `initial_state = {"s0": ...}`
    """
    true_params = {
        "C": _require_float(chronicle_cfg, "capacity_mm_true"),
        "k": _require_float(chronicle_cfg, "k_per_day_true"),
    }
    initial_state = {
        "s0": float(chronicle_cfg.get("s0_mm", 0.0)),
    }
    return true_params, initial_state


class ReservoirModel:
    """
    Linear reservoir model with finite storage capacity.

    Core mass balance with bounds
    -----------------------------
    Storage is physically constrained:

        0 <= S(t) <= C

    Interior dynamics:

        dS/dt = Qin(t) - k S(t)
        Qout(t) = k S(t)

    Boundary guards:
    - if `S=0` and derivative is negative, clamp derivative to 0,
    - if `S=C` and derivative is positive, clamp derivative to 0.
    """

    def __init__(self, capacity: float, k: float):
        """
        Parameters
        ----------
        capacity : float
            Maximum storage `C` [mm], must be > 0.
        k : float
            Linear outflow coefficient in `Qout = k * S` [1/time], must be >= 0.
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
        """Return outflow for one storage value `S` [mm]."""
        return self.k * float(storage)

    def dynamics(self, t, state, qin_func):
        """
        ODE right-hand side for `solve_ivp`.

        Parameters
        ----------
        t : float
            Current time.
        state : sequence
            Current state vector, expected as `[S]`.
        qin_func : callable
            Inflow function `Qin(t)`.
        """
        storage = float(np.clip(state[0], 0.0, self.C))
        qin = float(qin_func(t))
        qout = self.qout(storage)

        dstorage_dt = qin - qout

        # Enforce physical bounds through derivative guards.
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
            Inflow function `Qin(t)`.
        s0 : float
            Initial storage [mm].
        t_span : tuple(float, float)
            Integration interval `(t0, tf)`.
        t_eval : array-like
            Times where the solution is sampled.

        Returns
        -------
        tuple(np.ndarray, np.ndarray, np.ndarray)
            `(time, storage, qout)`.

        Notes
        -----
        Integration uses SciPy `solve_ivp(..., method="RK45")`:
        - explicit embedded Runge-Kutta method,
        - adaptive step size control,
        - suitable for this non-stiff first-order ODE.
        """
        s0 = float(s0)
        t_eval = np.asarray(t_eval, dtype=float)
        if t_eval.ndim != 1 or t_eval.size == 0:
            raise ValueError("t_eval must be a non-empty 1D array")

        # Solve one-state ODE on requested sampling points.
        solution = solve_ivp(
            self.dynamics,
            t_span,
            [s0],
            t_eval=t_eval,
            args=(qin_func,),
            method="RK45",
        )

        # Final clipping protects against tiny numerical overshoots.
        storage = np.clip(solution.y[0], 0.0, self.C)
        qout = self.k * storage
        return solution.t, storage, qout


def simulate_outflow(params, initial_state, forcing_func, t_span, t_eval):
    """
    Simulate one-reservoir outflow from parameters and forcing callable.

    Parameters
    ----------
    params : dict
        Must provide `C` and `k`.
    initial_state : dict
        Must provide `s0`.
    forcing_func : callable
        `Qin(t)` forcing [mm/time].
    t_span : tuple(float, float)
        Integration interval.
    t_eval : array-like
        Sampling times.

    Returns
    -------
    dict
        `{"qout": qout, "storage": storage}`.
    """
    # Normalize incoming mappings to plain float dictionaries.
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
