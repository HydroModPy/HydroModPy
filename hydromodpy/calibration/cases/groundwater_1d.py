"""Transient 1D unconfined-aquifer analytical calibration case.

This module ports the ``groundwater_1d`` calibration case from the old
``hydromodpy.analysis.calibration.cases.groundwater_1d`` tree to the new
``hydromodpy.calibration`` engine API.

Physics
-------
The model solves a 1D Dupuit-Forchheimer unconfined aquifer with a material
interface at ``x = xi``. Two formulations are supported:

1) Linearized around mean saturated thickness ``H``::

       Sy * dh/dt = d/dx( K*H * dh/dx ) + R(t)

2) Nonlinear Boussinesq::

       Sy * dh/dt = d/dx( K*h * dh/dx ) + R(t)

Domain ``x in [0, L]`` with Dirichlet boundary at ``x=0`` and impermeable
(Neumann) at ``x=L``. The finite-difference implementation uses harmonic
means for face transmissivities, tridiagonal solves (Thomas algorithm),
and Picard fixed-point iterations for the nonlinear option.

Calibration
-----------
``build_noisy_groundwater_chronicle(config)`` forges a synthetic noisy
head chronicle from "true" parameters. ``make_groundwater_simulator``
returns a callable mapping ``{Kam, Kav, Syam, Syav, xi}`` to the flattened
observation vector. ``calibrate_groundwater`` wires these two pieces to
``CalibrationEngine`` with any registered optimizer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.calibration.engine import CalibrationEngine
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace
from hydromodpy.physics.hydrology.synthetic.forcing import (
    build_hydrological_step_series,
    build_hydrological_year_dates,
    build_recharge_from_reservoir_chronicle,
)
from hydromodpy.results.metrics import rmse

LINEARIZED_FORMULATION = "linearized"
BOUSSINESQ_FORMULATION = "boussinesq"
SUPPORTED_FORMULATIONS = (LINEARIZED_FORMULATION, BOUSSINESQ_FORMULATION)
SUPPORTED_RECHARGE_MODES = ("hydro_step", "reservoir_chronicle")

#: Canonical calibration parameter order for this case.
MODEL_PARAMETER_ORDER = ("Kam", "Kav", "Syam", "Syav", "xi")


# ---------------------------------------------------------------------------
# Physical / numerical parameter containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hydro1DParameters:
    """Physical parameters of the 1D aquifer model."""

    L: float
    xi: float
    Kam: float
    Kav: float
    Syam: float
    Syav: float
    H: float = 10.0

    def __post_init__(self):
        object.__setattr__(self, "L", float(self.L))
        object.__setattr__(self, "xi", float(self.xi))
        object.__setattr__(self, "Kam", float(self.Kam))
        object.__setattr__(self, "Kav", float(self.Kav))
        object.__setattr__(self, "Syam", float(self.Syam))
        object.__setattr__(self, "Syav", float(self.Syav))
        object.__setattr__(self, "H", float(self.H))
        if self.L <= 0.0:
            raise ValueError("L must be > 0")
        if not (0.0 < self.xi < self.L):
            raise ValueError("xi must satisfy 0 < xi < L")
        if self.Kam <= 0.0 or self.Kav <= 0.0:
            raise ValueError("Kam and Kav must be > 0")
        if self.Syam <= 0.0 or self.Syav <= 0.0:
            raise ValueError("Syam and Syav must be > 0")
        if self.H <= 0.0:
            raise ValueError("H must be > 0")


@dataclass(frozen=True)
class Hydro1DNumerics:
    """Numerical controls for the implicit solver."""

    nx: int = 51
    formulation: str = LINEARIZED_FORMULATION
    max_picard_iterations: int = 40
    picard_tolerance: float = 1.0e-7
    picard_relaxation: float = 1.0
    head_floor: float = 1.0e-6

    def __post_init__(self):
        key = str(self.formulation).strip().lower()
        if key not in SUPPORTED_FORMULATIONS:
            allowed = ", ".join(SUPPORTED_FORMULATIONS)
            raise ValueError(f"Unknown formulation '{self.formulation}'. Allowed: {allowed}")
        object.__setattr__(self, "formulation", key)
        object.__setattr__(self, "nx", int(self.nx))
        object.__setattr__(self, "max_picard_iterations", int(self.max_picard_iterations))
        object.__setattr__(self, "picard_tolerance", float(self.picard_tolerance))
        object.__setattr__(self, "picard_relaxation", float(self.picard_relaxation))
        object.__setattr__(self, "head_floor", float(self.head_floor))
        if self.nx < 3:
            raise ValueError("nx must be >= 3")
        if self.max_picard_iterations <= 0:
            raise ValueError("max_picard_iterations must be > 0")
        if self.picard_tolerance <= 0.0:
            raise ValueError("picard_tolerance must be > 0")
        if not (0.0 < self.picard_relaxation <= 1.0):
            raise ValueError("picard_relaxation must be in (0, 1]")
        if self.head_floor <= 0.0:
            raise ValueError("head_floor must be > 0")


# ---------------------------------------------------------------------------
# Core simulator (finite-difference, implicit Euler, tridiagonal)
# ---------------------------------------------------------------------------


def _piecewise_property(x: np.ndarray, xi: float, upstream: float, downstream: float) -> np.ndarray:
    return np.where(x < float(xi), float(upstream), float(downstream))


def _harmonic_mean(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    out = np.zeros_like(left, dtype=float)
    denom = left + right
    valid = (left > 0.0) & (right > 0.0) & (denom > 0.0)
    out[valid] = 2.0 * left[valid] * right[valid] / denom[valid]
    return out


def _assemble_tridiagonal(
    *,
    sy_nodes: np.ndarray,
    face_t: np.ndarray,
    h_prev: np.ndarray,
    h_left: float,
    recharge: float,
    dt: float,
    dx: float,
):
    nx = sy_nodes.size
    n_unknown = nx - 1
    lower = np.zeros(n_unknown, dtype=float)
    diag = np.zeros(n_unknown, dtype=float)
    upper = np.zeros(n_unknown, dtype=float)
    rhs = np.zeros(n_unknown, dtype=float)
    dx2 = float(dx * dx)
    for j in range(n_unknown):
        i = j + 1
        storage = float(sy_nodes[i] / dt)
        left_coeff = float(face_t[i - 1] / dx2)
        right_coeff = 0.0 if i == (nx - 1) else float(face_t[i] / dx2)
        diag[j] = storage + left_coeff + right_coeff
        rhs[j] = storage * float(h_prev[i]) + float(recharge)
        if j == 0:
            rhs[j] += left_coeff * float(h_left)
        else:
            lower[j] = -left_coeff
        if j < (n_unknown - 1):
            upper[j] = -right_coeff
    return lower, diag, upper, rhs


def _solve_thomas(
    lower: np.ndarray, diag: np.ndarray, upper: np.ndarray, rhs: np.ndarray
) -> np.ndarray:
    n = int(diag.size)
    a = np.asarray(lower, dtype=float).copy()
    b = np.asarray(diag, dtype=float).copy()
    c = np.asarray(upper, dtype=float).copy()
    d = np.asarray(rhs, dtype=float).copy()
    for i in range(1, n):
        factor = a[i] / b[i - 1]
        b[i] = b[i] - factor * c[i - 1]
        d[i] = d[i] - factor * d[i - 1]
    x = np.empty(n, dtype=float)
    x[-1] = d[-1] / b[-1]
    for i in range(n - 2, -1, -1):
        x[i] = (d[i] - c[i] * x[i + 1]) / b[i]
    return x


def simulate_heads(
    *,
    t: np.ndarray,
    h0_series: np.ndarray,
    recharge_series: np.ndarray,
    parameters: Hydro1DParameters,
    numerics: Hydro1DNumerics,
    h_init: float | None = None,
) -> dict[str, Any]:
    """Run the 1D transient simulation and return ``h(x, t)``.

    Parameters
    ----------
    t : np.ndarray
        Strictly increasing time vector (days).
    h0_series : np.ndarray
        Dirichlet head at ``x=0`` for each ``t[k]``.
    recharge_series : np.ndarray
        Uniform recharge ``R(t)`` applied at every node.
    parameters : Hydro1DParameters
        Physical parameters.
    numerics : Hydro1DNumerics
        Solver settings.
    h_init : float | None
        Initial head (uniform). Defaults to ``h0_series[0]``.

    Returns
    -------
    dict
        ``x``, ``t``, ``h`` (shape ``(nt, nx)``).
    """
    t = np.asarray(t, dtype=float).ravel()
    if t.size < 2 or np.any(np.diff(t) <= 0.0):
        raise ValueError("t must be strictly increasing with at least 2 values")
    h0_series = np.asarray(h0_series, dtype=float).ravel()
    recharge_series = np.asarray(recharge_series, dtype=float).ravel()
    if h0_series.size != t.size or recharge_series.size != t.size:
        raise ValueError("h0_series / recharge_series must match len(t)")

    x = np.linspace(0.0, parameters.L, numerics.nx, dtype=float)
    dx = float(x[1] - x[0])
    k_nodes = _piecewise_property(x, parameters.xi, parameters.Kam, parameters.Kav)
    sy_nodes = _piecewise_property(x, parameters.xi, parameters.Syam, parameters.Syav)

    h_init_val = float(h0_series[0]) if h_init is None else float(h_init)
    heads = np.empty((t.size, numerics.nx), dtype=float)
    heads[0, :] = max(h_init_val, numerics.head_floor)
    heads[0, 0] = float(h0_series[0])

    # Pre-compute constant transmissivity for the linearized case.
    t_lin_nodes = k_nodes * parameters.H
    t_lin_faces = _harmonic_mean(t_lin_nodes[:-1], t_lin_nodes[1:])

    for step in range(t.size - 1):
        dt = float(t[step + 1] - t[step])
        h_prev = heads[step].copy()
        h_left = float(h0_series[step + 1])
        rech = float(recharge_series[step + 1])

        if numerics.formulation == LINEARIZED_FORMULATION:
            lo, di, up, rh = _assemble_tridiagonal(
                sy_nodes=sy_nodes,
                face_t=t_lin_faces,
                h_prev=h_prev,
                h_left=h_left,
                recharge=rech,
                dt=dt,
                dx=dx,
            )
            unknown = _solve_thomas(lo, di, up, rh)
            h_new = np.empty(numerics.nx, dtype=float)
            h_new[0] = h_left
            h_new[1:] = np.maximum(unknown, numerics.head_floor)
            heads[step + 1] = h_new
            continue

        # Nonlinear Boussinesq: Picard fixed-point iterations.
        h_iter = np.maximum(h_prev, numerics.head_floor)
        h_iter[0] = h_left
        h_new = h_iter.copy()
        for _ in range(numerics.max_picard_iterations):
            t_nodes = k_nodes * np.maximum(h_iter, numerics.head_floor)
            face_t = _harmonic_mean(t_nodes[:-1], t_nodes[1:])
            lo, di, up, rh = _assemble_tridiagonal(
                sy_nodes=sy_nodes,
                face_t=face_t,
                h_prev=h_prev,
                h_left=h_left,
                recharge=rech,
                dt=dt,
                dx=dx,
            )
            unknown = _solve_thomas(lo, di, up, rh)
            h_trial = np.empty(numerics.nx, dtype=float)
            h_trial[0] = h_left
            h_trial[1:] = np.maximum(unknown, numerics.head_floor)
            delta = float(np.max(np.abs(h_trial - h_iter)))
            h_new = h_trial
            if delta <= numerics.picard_tolerance:
                break
            h_iter = (
                numerics.picard_relaxation * h_trial + (1.0 - numerics.picard_relaxation) * h_iter
            )
            h_iter[0] = h_left
            h_iter[1:] = np.maximum(h_iter[1:], numerics.head_floor)
        heads[step + 1] = h_new

    return {"x": x, "t": t, "h": heads}


# ---------------------------------------------------------------------------
# Synthetic chronicle builder
# ---------------------------------------------------------------------------


def _default_chronicle_config() -> dict[str, Any]:
    """Compact default configuration suitable for unit tests."""
    return {
        "n_days": 60,
        "dt_days": 1.0,
        "L_m": 500.0,
        "xi_true_m": 220.0,
        "nx": 31,
        "formulation_true": LINEARIZED_FORMULATION,
        "H_linearized_m": 12.0,
        "Kam_true_m_per_day": 5.0,
        "Kav_true_m_per_day": 1.2,
        "Syam_true": 0.18,
        "Syav_true": 0.10,
        "h0_m": 6.0,
        "recharge_mode": "hydro_step",
        "recharge_wet_m_per_day": 0.003,
        "recharge_dry_m_per_day": 0.0004,
        "recharge_wet_months": (10, 11, 12, 1, 2, 3),
        "start_year": 2000,
        "target_annual_precip_mm": 800.0,
        "precip_seed": 42,
        "runoff_coeff": 0.15,
        "losses_mm_day": 1.5,
        "losses_months": (4, 5, 6, 7, 8, 9),
        "obs_x_m": (),
        "obs_t_stride": 2,
        "obs_noise_std_m": 0.03,
        "obs_seed": 123,
        "picard_max_iter": 40,
        "picard_tol": 1.0e-7,
        "picard_relaxation": 1.0,
        "head_floor_m": 1.0e-6,
    }


def _resolve_config(user_config: Mapping[str, Any] | None) -> dict[str, Any]:
    cfg = _default_chronicle_config()
    if user_config:
        for key, value in user_config.items():
            if key not in cfg:
                raise KeyError(f"Unknown chronicle key: {key!r}")
            cfg[key] = value
    # Basic validation (lightweight; Pydantic schema omitted for self-containment).
    if cfg["formulation_true"] not in SUPPORTED_FORMULATIONS:
        raise ValueError(f"formulation_true must be one of {SUPPORTED_FORMULATIONS}")
    if cfg["recharge_mode"] not in SUPPORTED_RECHARGE_MODES:
        raise ValueError(f"recharge_mode must be one of {SUPPORTED_RECHARGE_MODES}")
    if not (0.0 < float(cfg["xi_true_m"]) < float(cfg["L_m"])):
        raise ValueError("xi_true_m must satisfy 0 < xi_true_m < L_m")
    return cfg


def _build_time_vector(n_days: float, dt_days: float) -> np.ndarray:
    if n_days <= 0.0 or dt_days <= 0.0:
        raise ValueError("n_days and dt_days must be > 0")
    n_steps = int(np.floor(float(n_days) / float(dt_days)))
    return np.linspace(0.0, n_steps * dt_days, n_steps + 1, dtype=float)


def _nearest_indices(grid: np.ndarray, targets: np.ndarray) -> np.ndarray:
    grid = np.asarray(grid, dtype=float).ravel()
    targets = np.asarray(targets, dtype=float).ravel()
    out = np.empty(targets.size, dtype=int)
    for i, v in enumerate(targets):
        out[i] = int(np.argmin(np.abs(grid - v)))
    return out


def _build_recharge_series(cfg: Mapping[str, Any], n_forcing: int) -> tuple[np.ndarray, np.ndarray]:
    mode = str(cfg["recharge_mode"]).strip().lower()
    start_year = int(cfg["start_year"])
    if mode == "hydro_step":
        dates = build_hydrological_year_dates(n_days=n_forcing, start_year=start_year)
        recharge = build_hydrological_step_series(
            dates=dates,
            wet_months=tuple(cfg["recharge_wet_months"]),
            wet_value=float(cfg["recharge_wet_m_per_day"]),
            dry_value=float(cfg["recharge_dry_m_per_day"]),
        )
        return dates, recharge
    if mode == "reservoir_chronicle":
        forcing = build_recharge_from_reservoir_chronicle(
            n_days=n_forcing,
            start_year=start_year,
            target_annual_precip_mm=float(cfg["target_annual_precip_mm"]),
            precip_seed=int(cfg["precip_seed"]),
            runoff_coeff=float(cfg["runoff_coeff"]),
            losses_mm_day=float(cfg["losses_mm_day"]),
            losses_months=tuple(cfg["losses_months"]),
            scale_to_m_per_day=1.0e-3,
        )
        return forcing["dates"], np.asarray(forcing["recharge_m_per_day"], dtype=float)
    raise ValueError(f"Unsupported recharge_mode: {mode!r}")


def build_noisy_groundwater_chronicle(
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one synthetic noisy head chronicle.

    Parameters
    ----------
    config : Mapping[str, Any] | None
        User overrides on top of :func:`_default_chronicle_config`. Pass
        ``None`` to use built-in defaults tuned for a fast unit test.

    Returns
    -------
    dict
        Keys of interest: ``t``, ``x``, ``h_true``, ``h0_series``,
        ``recharge_series``, ``obs_time_indices``, ``obs_node_indices``,
        ``obs_noisy_matrix`` / ``obs_vector``, ``true_params``,
        ``fixed_model_parameters``.
    """
    cfg = _resolve_config(config)
    t = _build_time_vector(n_days=float(cfg["n_days"]), dt_days=float(cfg["dt_days"]))
    h0_constant = float(cfg["h0_m"])
    h0_series = np.full(t.size, h0_constant, dtype=float)
    dates, recharge_series = _build_recharge_series(cfg, n_forcing=t.size)

    true_params = {
        "Kam": float(cfg["Kam_true_m_per_day"]),
        "Kav": float(cfg["Kav_true_m_per_day"]),
        "Syam": float(cfg["Syam_true"]),
        "Syav": float(cfg["Syav_true"]),
        "xi": float(cfg["xi_true_m"]),
    }
    parameters = Hydro1DParameters(
        L=float(cfg["L_m"]),
        xi=true_params["xi"],
        Kam=true_params["Kam"],
        Kav=true_params["Kav"],
        Syam=true_params["Syam"],
        Syav=true_params["Syav"],
        H=float(cfg["H_linearized_m"]),
    )
    numerics = Hydro1DNumerics(
        nx=int(cfg["nx"]),
        formulation=str(cfg["formulation_true"]),
        max_picard_iterations=int(cfg["picard_max_iter"]),
        picard_tolerance=float(cfg["picard_tol"]),
        picard_relaxation=float(cfg["picard_relaxation"]),
        head_floor=float(cfg["head_floor_m"]),
    )

    sim_true = simulate_heads(
        t=t,
        h0_series=h0_series,
        recharge_series=recharge_series,
        parameters=parameters,
        numerics=numerics,
        h_init=h0_constant,
    )
    x = sim_true["x"]
    h_true = sim_true["h"]

    obs_x_values = np.asarray(cfg.get("obs_x_m") or (), dtype=float).ravel()
    if obs_x_values.size == 0:
        mid_upstream = 0.5 * true_params["xi"]
        mid_downstream = 0.5 * (parameters.L + true_params["xi"])
        obs_x_values = np.asarray([mid_upstream, mid_downstream], dtype=float)
    obs_nodes = _nearest_indices(x, obs_x_values)
    stride = int(cfg["obs_t_stride"])
    obs_time_indices = np.arange(0, t.size, stride, dtype=int)
    if obs_time_indices[-1] != (t.size - 1):
        obs_time_indices = np.append(obs_time_indices, t.size - 1)

    obs_true_matrix = h_true[np.ix_(obs_time_indices, obs_nodes)]
    noise_std = float(cfg["obs_noise_std_m"])
    rng = np.random.default_rng(int(cfg["obs_seed"]))
    obs_noisy_matrix = obs_true_matrix + rng.normal(
        loc=0.0, scale=noise_std, size=obs_true_matrix.shape
    )

    return {
        "t": t,
        "x": x,
        "h_true": h_true,
        "h0_series": h0_series,
        "recharge_series": recharge_series,
        "dates": np.asarray(dates, dtype=object),
        "obs_time_indices": obs_time_indices,
        "obs_node_indices": obs_nodes,
        "obs_x_m": x[obs_nodes],
        "obs_time_days": t[obs_time_indices],
        "obs_true_matrix": obs_true_matrix,
        "obs_noisy_matrix": obs_noisy_matrix,
        "obs_vector": obs_noisy_matrix.ravel(order="C"),
        "true_params": true_params,
        "fixed_model_parameters": {
            "L": parameters.L,
            "H": parameters.H,
            "formulation": numerics.formulation,
            "nx": numerics.nx,
            "h0_m": h0_constant,
            "h_init": h0_constant,
            "max_picard_iterations": numerics.max_picard_iterations,
            "picard_tolerance": numerics.picard_tolerance,
            "picard_relaxation": numerics.picard_relaxation,
            "head_floor": numerics.head_floor,
        },
    }


# ---------------------------------------------------------------------------
# Simulator factory (ParamSuggestion -> observation vector)
# ---------------------------------------------------------------------------


def _build_parameters_from_values(
    chronicle: Mapping[str, Any], values: Mapping[str, float]
) -> Hydro1DParameters:
    fixed = chronicle["fixed_model_parameters"]
    missing = [name for name in MODEL_PARAMETER_ORDER if name not in values]
    if missing:
        raise ValueError(f"Missing groundwater parameter(s): {missing}")
    return Hydro1DParameters(
        L=float(fixed["L"]),
        xi=float(values["xi"]),
        Kam=float(values["Kam"]),
        Kav=float(values["Kav"]),
        Syam=float(values["Syam"]),
        Syav=float(values["Syav"]),
        H=float(fixed["H"]),
    )


def _build_numerics_from_chronicle(chronicle: Mapping[str, Any]) -> Hydro1DNumerics:
    fixed = chronicle["fixed_model_parameters"]
    return Hydro1DNumerics(
        nx=int(fixed["nx"]),
        formulation=str(fixed["formulation"]),
        max_picard_iterations=int(fixed["max_picard_iterations"]),
        picard_tolerance=float(fixed["picard_tolerance"]),
        picard_relaxation=float(fixed["picard_relaxation"]),
        head_floor=float(fixed["head_floor"]),
    )


def make_groundwater_simulator(
    chronicle: Mapping[str, Any],
) -> Callable[..., np.ndarray]:
    """Build a simulator callable ``simulate(**params) -> observation vector``.

    The returned callable accepts either a mapping (``simulate(values)``)
    or keyword arguments (``simulate(Kam=..., Kav=..., ...)``). It runs
    the 1D model for the given parameters and returns the heads sampled
    at ``(obs_time_indices, obs_node_indices)`` flattened row-major.
    """
    t = np.asarray(chronicle["t"], dtype=float)
    h0_series = np.asarray(chronicle["h0_series"], dtype=float)
    recharge_series = np.asarray(chronicle["recharge_series"], dtype=float)
    h_init = chronicle["fixed_model_parameters"].get("h_init")
    time_idx = np.asarray(chronicle["obs_time_indices"], dtype=int)
    node_idx = np.asarray(chronicle["obs_node_indices"], dtype=int)
    numerics = _build_numerics_from_chronicle(chronicle)

    def _simulator(values: Mapping[str, float] | None = None, **kwargs) -> np.ndarray:
        if values is None:
            values = kwargs
        elif kwargs:
            values = {**dict(values), **kwargs}
        parameters = _build_parameters_from_values(chronicle, values)
        sim = simulate_heads(
            t=t,
            h0_series=h0_series,
            recharge_series=recharge_series,
            parameters=parameters,
            numerics=numerics,
            h_init=h_init,
        )
        h = np.asarray(sim["h"], dtype=float)
        return h[np.ix_(time_idx, node_idx)].ravel(order="C")

    return _simulator


# ---------------------------------------------------------------------------
# Default ParameterSpace and calibration entry point
# ---------------------------------------------------------------------------


_DEFAULT_BOUNDS: dict[str, tuple[float, float, str]] = {
    # (lower, upper, transform)
    "Kam": (1.0, 10.0, "identity"),
    "Kav": (0.2, 5.0, "identity"),
    "Syam": (0.05, 0.35, "identity"),
    "Syav": (0.03, 0.30, "identity"),
    "xi": (50.0, 450.0, "identity"),
}


def default_parameter_space(
    overrides: Mapping[str, tuple[float, float]] | None = None,
) -> ParameterSpace:
    """Build the default ``ParameterSpace`` for the groundwater_1d case."""
    overrides = overrides or {}
    params: list[CalibParameter] = []
    for name in MODEL_PARAMETER_ORDER:
        low, high, transform = _DEFAULT_BOUNDS[name]
        if name in overrides:
            ov = overrides[name]
            low, high = float(ov[0]), float(ov[1])
        params.append(
            CalibParameter(
                name=name,
                lower=low,
                upper=high,
                transform=transform,
            )
        )
    return ParameterSpace(params)


def _make_tracking_evaluator(
    simulator: Callable[..., np.ndarray],
    observed: np.ndarray,
    log: dict[int, dict[str, float]],
) -> Callable[[ParamSuggestion], EvaluationResult]:
    """Build an evaluator that records the ``values`` behind each trial.

    Parameters
    ----------
    simulator : Callable
        Output of :func:`make_groundwater_simulator`.
    observed : np.ndarray
        Flattened noisy observation vector.
    log : dict[int, dict[str, float]]
        Mutable mapping populated with ``{trial_id -> values}``. The caller
        uses this mapping to recover ``params_best`` once the engine has
        finished running.
    """
    observed = np.asarray(observed, dtype=float)

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        log[sugg.trial_id] = dict(sugg.values)
        try:
            simulated = simulator(dict(sugg.values))
        except Exception as exc:  # pragma: no cover - defensive
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                objective_value=float("inf"),
                status="crashed",
                metadata={"error": repr(exc)},
            )
        cost = float(rmse(np.asarray(simulated, dtype=float), observed))
        if not np.isfinite(cost):
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                objective_value=float("inf"),
                status="failed",
            )
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=cost,
            status="completed",
        )

    return evaluator


def calibrate_groundwater(
    method: str = "optuna",
    *,
    chronicle: Mapping[str, Any] | None = None,
    chronicle_config: Mapping[str, Any] | None = None,
    space: ParameterSpace | None = None,
    bounds: Mapping[str, tuple[float, float]] | None = None,
    max_iter: int = 50,
    seed: int | None = None,
    optimizer_kwargs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a calibration of the groundwater_1d case and return a summary.

    Parameters
    ----------
    method : str
        Optimizer identifier registered with
        :func:`hydromodpy.calibration.build_optimizer`. Typical values:
        ``"optuna"``, ``"grid"``, ``"scipy_de"``, ``"scipy_nelder_mead"``.
    chronicle : Mapping[str, Any] | None
        Pre-built chronicle (output of :func:`build_noisy_groundwater_chronicle`).
        When ``None``, a fresh chronicle is built from ``chronicle_config``.
    chronicle_config : Mapping[str, Any] | None
        Overrides for the chronicle builder.
    space : ParameterSpace | None
        Explicit parameter space. Defaults to :func:`default_parameter_space`.
    bounds : Mapping[str, tuple[float, float]] | None
        Alternative to a full ``space``: tweak bounds of default parameters.
    max_iter : int
        Maximum number of evaluations (ask/tell rounds) for the engine.
    seed : int | None
        Seed forwarded to the optimizer factory when it accepts one.
    optimizer_kwargs : Mapping[str, Any] | None
        Extra keyword arguments passed to :func:`build_optimizer`.

    Returns
    -------
    dict
        ``session`` (``CalibrationSession``), ``best`` (``EvaluationResult``),
        ``params_best``, ``params_true``, ``rmse_best``, ``chronicle``,
        ``method``, and ``space``.
    """
    chronicle = chronicle or build_noisy_groundwater_chronicle(chronicle_config)
    if space is None:
        space = default_parameter_space(bounds)
    simulator = make_groundwater_simulator(chronicle)
    suggestion_log: dict[int, dict[str, float]] = {}
    evaluator = _make_tracking_evaluator(simulator, chronicle["obs_vector"], suggestion_log)

    factory_kwargs: dict[str, Any] = dict(optimizer_kwargs or {})
    if seed is not None and "seed" not in factory_kwargs:
        factory_kwargs["seed"] = seed
    optimizer = build_optimizer(method, space, **factory_kwargs)

    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=evaluator,
        max_iter=int(max_iter),
    )
    session = engine.run()
    best = session.best
    params_best: dict[str, float] = {}
    if best is not None:
        params_best = dict(suggestion_log.get(best.trial_id, {}))

    params_true = dict(chronicle["true_params"])
    rmse_best = float(best.objective_value) if best is not None else float("nan")
    return {
        "session": session,
        "best": best,
        "params_best": params_best,
        "params_true": params_true,
        "rmse_best": rmse_best,
        "chronicle": chronicle,
        "method": method,
        "space": space,
    }


__all__ = [
    "MODEL_PARAMETER_ORDER",
    "LINEARIZED_FORMULATION",
    "BOUSSINESQ_FORMULATION",
    "SUPPORTED_FORMULATIONS",
    "SUPPORTED_RECHARGE_MODES",
    "Hydro1DParameters",
    "Hydro1DNumerics",
    "simulate_heads",
    "build_noisy_groundwater_chronicle",
    "make_groundwater_simulator",
    "default_parameter_space",
    "calibrate_groundwater",
]
