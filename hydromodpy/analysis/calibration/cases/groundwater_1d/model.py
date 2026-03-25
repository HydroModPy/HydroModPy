# -*- coding: utf-8 -*-
"""
Transient 1D unconfined-aquifer model (finite differences, implicit Euler).

Two formulations are supported:

1) Linearized around mean saturated thickness H:
       Sy * dh/dt = d/dx( K*H * dh/dx ) + R(t)

2) Nonlinear Boussinesq:
       Sy * dh/dt = d/dx( K*h * dh/dx ) + R(t)

Domain:
    x in [0, L], with a material interface at x = xi.

Boundary conditions:
    h(0, t) = h0(t)        (Dirichlet)
    dh/dx(L, t) = 0        (impermeable / Neumann)

The implementation uses:
- node-centered unknowns h_i,
- harmonic means for interface transmissivities,
- tridiagonal solves at each implicit step,
- Picard fixed-point iterations for the nonlinear option.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np


LINEARIZED_FORMULATION = "linearized"
BOUSSINESQ_FORMULATION = "boussinesq"
SUPPORTED_FORMULATIONS = (
    LINEARIZED_FORMULATION,
    BOUSSINESQ_FORMULATION,
)

# Canonical calibration vector order for this case.
MODEL_PARAMETER_ORDER = ("Kam", "Kav", "Syam", "Syav", "xi")


@dataclass(frozen=True)
class Hydro1DParameters:
    """
    Physical parameters of the 1D aquifer model.
    """

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
    """
    Numerical controls for the implicit solver.
    """

    nx: int = 101
    formulation: str = LINEARIZED_FORMULATION
    max_picard_iterations: int = 40
    picard_tolerance: float = 1.0e-7
    picard_relaxation: float = 1.0
    head_floor: float = 1.0e-6

    def __post_init__(self):
        object.__setattr__(self, "nx", int(self.nx))
        object.__setattr__(self, "formulation", normalize_formulation(self.formulation))
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


def normalize_formulation(value):
    """
    Normalize and validate formulation name.
    """
    key = str(value).strip().lower()
    if key not in SUPPORTED_FORMULATIONS:
        allowed = ", ".join(SUPPORTED_FORMULATIONS)
        raise ValueError(f"Unknown formulation '{value}'. Allowed: {allowed}")
    return key


def _coerce_parameters(parameters):
    if isinstance(parameters, Hydro1DParameters):
        return parameters
    if not isinstance(parameters, Mapping):
        raise TypeError("parameters must be Hydro1DParameters or a mapping")
    return Hydro1DParameters(
        L=parameters["L"],
        xi=parameters["xi"],
        Kam=parameters["Kam"],
        Kav=parameters["Kav"],
        Syam=parameters["Syam"],
        Syav=parameters["Syav"],
        H=parameters.get("H", 10.0),
    )


def _coerce_numerics(numerics):
    if numerics is None:
        return Hydro1DNumerics()
    if isinstance(numerics, Hydro1DNumerics):
        return numerics
    if not isinstance(numerics, Mapping):
        raise TypeError("numerics must be Hydro1DNumerics, mapping, or None")
    return Hydro1DNumerics(
        nx=numerics.get("nx", 101),
        formulation=numerics.get("formulation", LINEARIZED_FORMULATION),
        max_picard_iterations=numerics.get("max_picard_iterations", 40),
        picard_tolerance=numerics.get("picard_tolerance", 1.0e-7),
        picard_relaxation=numerics.get("picard_relaxation", 1.0),
        head_floor=numerics.get("head_floor", 1.0e-6),
    )


def _as_strictly_increasing_time_vector(t):
    values = np.asarray(t, dtype=float).ravel()
    if values.size < 2:
        raise ValueError("t must contain at least 2 values")
    if np.any(~np.isfinite(values)):
        raise ValueError("t contains non-finite values")
    dt = np.diff(values)
    if np.any(dt <= 0.0):
        raise ValueError("t must be strictly increasing")
    return values


def _as_time_series(values, t, *, name):
    """
    Convert scalar/callable/vector input into a 1D vector over `t`.
    """
    if callable(values):
        out = np.asarray([float(values(float(tt))) for tt in t], dtype=float)
        return out

    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        return np.full(t.size, float(arr), dtype=float)
    arr = arr.ravel()
    if arr.size != t.size:
        raise ValueError(f"{name} must be scalar, callable, or length len(t)")
    return arr


def _build_initial_head_profile(h_init, x, *, default_value):
    if h_init is None:
        return np.full(x.size, float(default_value), dtype=float)
    if callable(h_init):
        return np.asarray([float(h_init(float(xx))) for xx in x], dtype=float)

    arr = np.asarray(h_init, dtype=float)
    if arr.ndim == 0:
        return np.full(x.size, float(arr), dtype=float)
    arr = arr.ravel()
    if arr.size != x.size:
        raise ValueError("h_init must be scalar, callable, or length len(x)")
    return arr


def _piecewise_property(x, xi, upstream, downstream):
    return np.where(x < float(xi), float(upstream), float(downstream))


def _harmonic_mean(left, right):
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    out = np.zeros_like(left, dtype=float)
    denom = left + right
    valid = (left > 0.0) & (right > 0.0) & (denom > 0.0)
    out[valid] = 2.0 * left[valid] * right[valid] / denom[valid]
    return out


def _assemble_tridiagonal_system(
    *,
    sy_nodes,
    face_transmissivity,
    h_prev,
    boundary_head,
    recharge_value,
    dt,
    dx,
):
    """
    Assemble implicit-Euler tridiagonal system for unknown nodes i=1..nx-1.
    """
    nx = sy_nodes.size
    n_unknown = nx - 1
    if n_unknown < 1:
        raise ValueError("At least one unknown node is required")

    lower = np.zeros(n_unknown, dtype=float)
    diag = np.zeros(n_unknown, dtype=float)
    upper = np.zeros(n_unknown, dtype=float)
    rhs = np.zeros(n_unknown, dtype=float)
    dx2 = float(dx * dx)

    for j in range(n_unknown):
        i = j + 1
        storage = float(sy_nodes[i] / dt)
        left_coeff = float(face_transmissivity[i - 1] / dx2)
        right_coeff = 0.0 if i == (nx - 1) else float(face_transmissivity[i] / dx2)

        diag[j] = storage + left_coeff + right_coeff
        rhs[j] = storage * float(h_prev[i]) + float(recharge_value)

        if j == 0:
            # Left boundary (Dirichlet) contribution enters the RHS.
            rhs[j] += left_coeff * float(boundary_head)
        else:
            lower[j] = -left_coeff

        if j < (n_unknown - 1):
            upper[j] = -right_coeff

    return lower, diag, upper, rhs


def _solve_tridiagonal(lower, diag, upper, rhs):
    """
    Solve tridiagonal system with the Thomas algorithm.
    """
    n = int(diag.size)
    if n == 0:
        return np.asarray([], dtype=float)

    a = np.asarray(lower, dtype=float).copy()
    b = np.asarray(diag, dtype=float).copy()
    c = np.asarray(upper, dtype=float).copy()
    d = np.asarray(rhs, dtype=float).copy()

    if np.any(~np.isfinite(b)) or np.any(np.abs(b) <= 1.0e-20):
        raise ValueError("Invalid tridiagonal diagonal values")

    for i in range(1, n):
        factor = a[i] / b[i - 1]
        b[i] = b[i] - factor * c[i - 1]
        d[i] = d[i] - factor * d[i - 1]

    x = np.empty(n, dtype=float)
    x[-1] = d[-1] / b[-1]
    for i in range(n - 2, -1, -1):
        x[i] = (d[i] - c[i] * x[i + 1]) / b[i]
    return x


def _compute_face_fluxes(*, heads, k_nodes, numerics, dx, linearized_face_transmissivity):
    """
    Compute Darcy-like face flux q = -T * dh/dx for all times.
    """
    nt, nx = heads.shape
    flux = np.empty((nt, nx - 1), dtype=float)

    if numerics.formulation == LINEARIZED_FORMULATION:
        face_t = linearized_face_transmissivity
        grad = (heads[:, 1:] - heads[:, :-1]) / dx
        flux[:, :] = -face_t[None, :] * grad
        return flux

    for n in range(nt):
        t_nodes = k_nodes * np.maximum(heads[n], numerics.head_floor)
        face_t = _harmonic_mean(t_nodes[:-1], t_nodes[1:])
        grad = (heads[n, 1:] - heads[n, :-1]) / dx
        flux[n, :] = -face_t * grad
    return flux


def simulate(
    *,
    t,
    h0,
    recharge,
    parameters,
    numerics=None,
    h_init=None,
    return_flux=True,
):
    """
    Run transient 1D simulation.

    Parameters
    ----------
    t : array-like
        Time vector (strictly increasing).
    h0 : scalar | callable | array-like
        Boundary head at x=0.
    recharge : scalar | callable | array-like
        Recharge source term R(t) added uniformly in space.
    parameters : Hydro1DParameters | Mapping
        Physical parameters (`L`, `xi`, `Kam`, `Kav`, `Syam`, `Syav`, optional `H`).
    numerics : Hydro1DNumerics | Mapping | None
        Numerical settings (nx, formulation, Picard controls).
    h_init : scalar | callable | array-like | None
        Initial head profile at t[0]. If None, initialized from h0(t[0]).
    return_flux : bool
        If True, return face fluxes.

    Returns
    -------
    dict
        Structured output with:
        - `x`, `x_face`, `t`
        - `h` with shape (nt, nx)
        - `flux_face` with shape (nt, nx-1) when requested
        - `K_nodes`, `Sy_nodes`
        - forcing arrays `h0_series`, `recharge_series`
        - nonlinear iteration counts `picard_iterations`
    """
    p = _coerce_parameters(parameters)
    n = _coerce_numerics(numerics)
    t = _as_strictly_increasing_time_vector(t)

    x = np.linspace(0.0, p.L, n.nx, dtype=float)
    x_face = 0.5 * (x[:-1] + x[1:])
    dx = float(x[1] - x[0])

    h0_series = _as_time_series(h0, t, name="h0")
    recharge_series = _as_time_series(recharge, t, name="recharge")
    if np.any(~np.isfinite(h0_series)) or np.any(~np.isfinite(recharge_series)):
        raise ValueError("h0 and recharge must be finite")

    h_initial = _build_initial_head_profile(
        h_init,
        x,
        default_value=float(h0_series[0]),
    )
    h_initial = np.maximum(np.asarray(h_initial, dtype=float), n.head_floor)
    h_initial[0] = float(h0_series[0])

    k_nodes = _piecewise_property(x, p.xi, p.Kam, p.Kav)
    sy_nodes = _piecewise_property(x, p.xi, p.Syam, p.Syav)
    if np.any(sy_nodes <= 0.0):
        raise ValueError("Specific yield must stay positive over the domain")

    nt = t.size
    heads = np.empty((nt, n.nx), dtype=float)
    heads[0, :] = h_initial
    picard_iterations = np.zeros(nt - 1, dtype=int)

    # Constant transmissivity for the linearized option.
    transmissivity_linear_nodes = k_nodes * p.H
    transmissivity_linear_faces = _harmonic_mean(
        transmissivity_linear_nodes[:-1],
        transmissivity_linear_nodes[1:],
    )

    for step in range(nt - 1):
        dt = float(t[step + 1] - t[step])
        h_prev = heads[step].copy()
        boundary_head = float(h0_series[step + 1])
        recharge_value = float(recharge_series[step + 1])

        if n.formulation == LINEARIZED_FORMULATION:
            lower, diag, upper, rhs = _assemble_tridiagonal_system(
                sy_nodes=sy_nodes,
                face_transmissivity=transmissivity_linear_faces,
                h_prev=h_prev,
                boundary_head=boundary_head,
                recharge_value=recharge_value,
                dt=dt,
                dx=dx,
            )
            unknown = _solve_tridiagonal(lower, diag, upper, rhs)
            h_new = np.empty(n.nx, dtype=float)
            h_new[0] = boundary_head
            h_new[1:] = unknown
            h_new[1:] = np.maximum(h_new[1:], n.head_floor)
            heads[step + 1] = h_new
            continue

        # Nonlinear Boussinesq option: Picard fixed-point iterations.
        h_iter = np.maximum(h_prev, n.head_floor)
        h_iter[0] = boundary_head
        h_new = h_iter.copy()

        for picard_iter in range(n.max_picard_iterations):
            transmissivity_nodes = k_nodes * np.maximum(h_iter, n.head_floor)
            face_transmissivity = _harmonic_mean(
                transmissivity_nodes[:-1],
                transmissivity_nodes[1:],
            )
            lower, diag, upper, rhs = _assemble_tridiagonal_system(
                sy_nodes=sy_nodes,
                face_transmissivity=face_transmissivity,
                h_prev=h_prev,
                boundary_head=boundary_head,
                recharge_value=recharge_value,
                dt=dt,
                dx=dx,
            )
            unknown = _solve_tridiagonal(lower, diag, upper, rhs)

            h_trial = np.empty(n.nx, dtype=float)
            h_trial[0] = boundary_head
            h_trial[1:] = np.maximum(unknown, n.head_floor)

            delta = float(np.max(np.abs(h_trial - h_iter)))
            h_new = h_trial
            if delta <= n.picard_tolerance:
                picard_iterations[step] = picard_iter + 1
                break

            h_iter = n.picard_relaxation * h_trial + (1.0 - n.picard_relaxation) * h_iter
            h_iter[0] = boundary_head
            h_iter[1:] = np.maximum(h_iter[1:], n.head_floor)
        else:
            picard_iterations[step] = n.max_picard_iterations

        heads[step + 1] = h_new

    flux_face = None
    if return_flux:
        flux_face = _compute_face_fluxes(
            heads=heads,
            k_nodes=k_nodes,
            numerics=n,
            dx=dx,
            linearized_face_transmissivity=transmissivity_linear_faces,
        )

    return {
        "x": x,
        "x_face": x_face,
        "t": t,
        "h": heads,
        "flux_face": flux_face,
        "K_nodes": k_nodes,
        "Sy_nodes": sy_nodes,
        "h0_series": h0_series,
        "recharge_series": recharge_series,
        "formulation": n.formulation,
        "picard_iterations": picard_iterations,
    }


__all__ = (
    "LINEARIZED_FORMULATION",
    "BOUSSINESQ_FORMULATION",
    "SUPPORTED_FORMULATIONS",
    "MODEL_PARAMETER_ORDER",
    "Hydro1DParameters",
    "Hydro1DNumerics",
    "normalize_formulation",
    "simulate",
)
