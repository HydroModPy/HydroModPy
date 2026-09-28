"""Nelder-Mead simplex that can evaluate several candidates of one step at once.

A port of ``scipy.optimize._optimize._minimize_neldermead`` from SciPy 1.18.1.
The coefficients, the initial simplex, the ``np.argsort`` ordering, the
reflection, expansion, contraction and shrink rules and the stopping tests on
``xatol``, ``fatol``, ``maxiter`` and ``maxfev`` are SciPy's, line for line. The
objective calls it reads, their order, its final point and its ``success`` are
therefore SciPy's. SciPy's ``bounds``, ``callback``, ``disp`` and ``return_all``
options are not ported: a caller that wants bounds clips inside its objective.

What changes is who calls the objective. SciPy calls it one point at a time.
Here the simplex proposes points and receives their values in any order. Every
candidate of one step depends only on the simplex that step starts from: the
initial vertices, then the reflection, the expansion, both contractions and the
shrink points. :meth:`SpeculativeNelderMead.propose` hands out up to ``width``
of them at once: the point the rules need now, then the others in the order they
are most often needed (reflection, inside contraction, expansion, outside
contraction, shrink points). The rules read only the values SciPy would have
asked for. The other values were computed for nothing, and
:meth:`SpeculativeNelderMead.fate` says so.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Literal, NamedTuple

import numpy as np

CandidateKey = tuple[int, str, int]
"""``(step, role, index)``: the step that proposed a point, its role, its index.

Step 0 builds the initial simplex. The index is the vertex or the shrunk vertex
a point stands for, and 0 for the other roles.
"""

VERTEX = "vertex"
REFLECTION = "reflection"
EXPANSION = "expansion"
OUTSIDE_CONTRACTION = "outside_contraction"
INSIDE_CONTRACTION = "inside_contraction"
SHRINK = "shrink"

Fate = Literal["used", "unused", "open"]


class Proposal(NamedTuple):
    """One point to evaluate, as SciPy would hand it to the objective."""

    key: CandidateKey
    point: np.ndarray


class UsedCall(NamedTuple):
    """One objective call the rules read, in SciPy's order."""

    key: CandidateKey
    point: np.ndarray
    value: float


@dataclass(frozen=True)
class NelderMeadResult:
    """What SciPy's ``OptimizeResult`` reports for the same run."""

    x: np.ndarray
    fun: float
    nit: int
    nfev: int
    status: int
    """0 success, 1 ``maxfev`` reached, 2 ``maxiter`` reached, as in SciPy."""
    success: bool
    final_simplex: tuple[np.ndarray, np.ndarray]


class _MaxFuncCallError(RuntimeError):
    """SciPy's signal that one more objective call would pass ``maxfev``."""


class SpeculativeNelderMead:
    """SciPy's Nelder-Mead driven by proposals and values instead of calls.

    ``propose(width)`` returns up to ``width`` points not handed out yet.
    ``receive(key, value)`` gives one value back, in any order. The simplex
    moves as soon as the value its rules need next is known. With ``width = 1``
    it proposes exactly the calls SciPy makes, in SciPy's order. A wider width
    adds candidates of the same step that may turn out unused.

    The options are those of ``scipy.optimize.minimize(method="Nelder-Mead")``
    with the same defaults.
    """

    def __init__(
        self,
        x0: np.ndarray,
        *,
        initial_simplex: np.ndarray | None = None,
        maxiter: float | None = None,
        maxfev: float | None = None,
        xatol: float = 1e-4,
        fatol: float = 1e-4,
        adaptive: bool = False,
    ) -> None:
        self._ncalls = 0
        self._maxfun: float = np.inf
        self._step = -1
        self._points: dict[CandidateKey, np.ndarray] = {}
        self._order: list[CandidateKey] = []
        self._ruled_out: set[CandidateKey] = set()
        self._proposed: set[CandidateKey] = set()
        self._received: set[CandidateKey] = set()
        self._values: dict[CandidateKey, float] = {}
        self._used: list[UsedCall] = []
        self._used_keys: set[CandidateKey] = set()
        self._needed: CandidateKey | None = None
        self._result: NelderMeadResult | None = None
        self._run = self._algorithm(
            x0,
            initial_simplex=initial_simplex,
            maxiter=maxiter,
            maxfev=maxfev,
            xatol=xatol,
            fatol=fatol,
            adaptive=adaptive,
        )
        try:
            self._needed = next(self._run)
        except StopIteration:
            self._needed = None

    # ------------------------------------------------------------------ #
    # What a caller reads
    # ------------------------------------------------------------------ #

    @property
    def finished(self) -> bool:
        """Whether the rules stopped. :attr:`result` is set from then on."""
        return self._needed is None

    @property
    def result(self) -> NelderMeadResult | None:
        """SciPy's result for this run, once :attr:`finished`."""
        return self._result

    @property
    def used(self) -> tuple[UsedCall, ...]:
        """Every call the rules read, in SciPy's order."""
        return tuple(self._used)

    def fate(self, key: CandidateKey) -> Fate:
        """Whether the rules read a proposed point, never will, or may still."""
        if key in self._used_keys:
            return "used"
        if self._needed is None or key[0] != self._step or key in self._ruled_out:
            return "unused"
        return "open"

    # ------------------------------------------------------------------ #
    # Proposals and values
    # ------------------------------------------------------------------ #

    def propose(self, width: int) -> list[Proposal]:
        """Return up to *width* points to evaluate, none handed out before.

        The point the rules need now comes first. The other candidates of the
        step follow, the most often needed first. Candidates of the next step
        are never proposed: they depend on values not known yet.
        """
        if self._needed is None or width < 1:
            return []
        chosen: list[CandidateKey] = []
        if self._needed not in self._proposed:
            chosen.append(self._needed)
        for key in self._order:
            if len(chosen) >= width:
                break
            if key in self._proposed or key in self._ruled_out or key in chosen:
                continue
            chosen.append(key)
        self._proposed.update(chosen)
        return [Proposal(key, self._points[key].copy()) for key in chosen]

    def receive(self, key: CandidateKey, value: float) -> None:
        """Give back the value of one proposed point and move the simplex."""
        if key not in self._proposed:
            raise ValueError(f"{key!r} was never proposed.")
        if key in self._received:
            raise ValueError(f"{key!r} already has a value.")
        self._received.add(key)
        if self.fate(key) == "open":
            self._values[key] = float(value)
        self._advance()

    def close(self) -> None:
        """Stop the rules where they are. Idempotent."""
        self._run.close()

    def _advance(self) -> None:
        """Feed the rules every value they need next, as long as it is known."""
        while self._needed is not None and self._needed in self._values:
            key = self._needed
            value = self._values.pop(key)
            self._used.append(UsedCall(key, self._points[key], value))
            self._used_keys.add(key)
            try:
                self._needed = self._run.send(value)
            except StopIteration:
                self._needed = None

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #

    def _open_step(self, candidates: list[tuple[str, int, np.ndarray, int]]) -> None:
        """Start a step with its candidates, most often needed first.

        Each candidate is ``(role, index, point, position)``. ``position`` is the
        rank of its call within the step when the rules need it. A candidate
        whose call SciPy's ``maxfev`` check would refuse is never proposed.
        """
        self._step += 1
        self._values.clear()
        self._ruled_out = set()
        self._points = {}
        self._order = []
        for role, index, point, position in candidates:
            key = (self._step, role, index)
            self._points[key] = np.array(point, copy=True)
            if self._ncalls + position - 1 < self._maxfun:
                self._order.append(key)

    def _rule_out(self, *roles: str) -> None:
        """Say which candidates of this step the rules will not read."""
        for key in self._points:
            if key[1] in roles:
                self._ruled_out.add(key)
                self._values.pop(key, None)

    def _func(self, role: str, index: int = 0) -> Generator[CandidateKey, float, float]:
        """SciPy's ``_wrap_scalar_function_maxfun_validation``, as a request."""
        if self._ncalls >= self._maxfun:
            raise _MaxFuncCallError("Too many function calls")
        self._ncalls += 1
        value = yield (self._step, role, index)
        return value

    def _algorithm(
        self,
        x0: np.ndarray,
        *,
        initial_simplex: np.ndarray | None,
        maxiter: float | None,
        maxfev: float | None,
        xatol: float,
        fatol: float,
        adaptive: bool,
    ) -> Generator[CandidateKey, float, None]:
        """SciPy 1.18.1 ``_minimize_neldermead``, each call a ``yield``.

        The statements follow SciPy's, in its order. The only additions are
        ``_open_step`` and ``_rule_out``, which tell the proposals what the
        step may still need and change nothing the rules compute.
        """
        maxfun = maxfev

        x0 = np.atleast_1d(x0).flatten()
        dtype = x0.dtype if np.issubdtype(x0.dtype, np.inexact) else np.float64
        x0 = np.asarray(x0, dtype=dtype)

        if adaptive:
            dim = float(len(x0))
            rho = 1
            chi = 1 + 2 / dim
            psi = 0.75 - 1 / (2 * dim)
            sigma = 1 - 1 / dim
        else:
            rho = 1
            chi = 2
            psi = 0.5
            sigma = 0.5

        nonzdelt = 0.05
        zdelt = 0.00025

        if initial_simplex is None:
            N = len(x0)

            sim = np.empty((N + 1, N), dtype=x0.dtype)
            sim[0] = x0
            for k in range(N):
                y = np.array(x0, copy=True)
                if y[k] != 0:
                    y[k] = (1 + nonzdelt) * y[k]
                else:
                    y[k] = zdelt
                sim[k + 1] = y
        else:
            sim = np.atleast_2d(initial_simplex).copy()
            dtype = sim.dtype if np.issubdtype(sim.dtype, np.inexact) else np.float64
            sim = np.asarray(sim, dtype=dtype)
            if sim.ndim != 2 or sim.shape[0] != sim.shape[1] + 1:
                raise ValueError("`initial_simplex` should be an array of shape (N+1,N)")
            if len(x0) != sim.shape[1]:
                raise ValueError("Size of `initial_simplex` is not consistent with `x0`")
            N = sim.shape[1]

        # If neither are set, then set both to default.
        if maxiter is None and maxfun is None:
            maxiter = N * 200
            maxfun = N * 200
        elif maxiter is None:
            # Convert remaining Nones to np.inf, unless the other is np.inf, in
            # which case use the default to avoid unbounded iteration.
            if maxfun == np.inf:
                maxiter = N * 200
            else:
                maxiter = np.inf
        elif maxfun is None:
            if maxiter == np.inf:
                maxfun = N * 200
            else:
                maxfun = np.inf
        self._maxfun = maxfun

        one2np1 = list(range(1, N + 1))
        fsim = np.full((N + 1,), np.inf, dtype=float)

        self._open_step([(VERTEX, k, sim[k], k + 1) for k in range(N + 1)])
        try:
            for k in range(N + 1):
                fsim[k] = yield from self._func(VERTEX, k)
        except _MaxFuncCallError:
            pass
        finally:
            ind = np.argsort(fsim)
            sim = np.take(sim, ind, 0)
            fsim = np.take(fsim, ind, 0)

        ind = np.argsort(fsim)
        fsim = np.take(fsim, ind, 0)
        # Sort so sim[0,:] has the lowest function value.
        sim = np.take(sim, ind, 0)

        iterations = 1

        while self._ncalls < maxfun and iterations < maxiter:
            try:
                if (
                    np.max(np.ravel(np.abs(sim[1:] - sim[0]))) <= xatol
                    and np.max(np.abs(fsim[0] - fsim[1:])) <= fatol
                ):
                    break

                xbar = np.add.reduce(sim[:-1], 0) / N
                xr = (1 + rho) * xbar - rho * sim[-1]
                # SciPy computes the points below only once the branch needs
                # them. Nothing it does in between changes xbar, sim[0] or the
                # vertex a point is built from, so each is the same array.
                xe = (1 + rho * chi) * xbar - rho * chi * sim[-1]
                xc = (1 + psi * rho) * xbar - psi * rho * sim[-1]
                xcc = (1 - psi) * xbar + psi * sim[-1]
                shrunk = {j: sim[0] + sigma * (sim[j] - sim[0]) for j in one2np1}
                self._open_step(
                    [
                        (REFLECTION, 0, xr, 1),
                        (INSIDE_CONTRACTION, 0, xcc, 2),
                        (EXPANSION, 0, xe, 2),
                        (OUTSIDE_CONTRACTION, 0, xc, 2),
                    ]
                    + [(SHRINK, j, shrunk[j], 2 + j) for j in one2np1]
                )
                fxr = yield from self._func(REFLECTION)
                doshrink = 0

                if fxr < fsim[0]:
                    self._rule_out(OUTSIDE_CONTRACTION, INSIDE_CONTRACTION, SHRINK)
                    fxe = yield from self._func(EXPANSION)

                    if fxe < fxr:
                        sim[-1] = xe
                        fsim[-1] = fxe
                    else:
                        sim[-1] = xr
                        fsim[-1] = fxr
                else:  # fsim[0] <= fxr
                    if fxr < fsim[-2]:
                        self._rule_out(EXPANSION, OUTSIDE_CONTRACTION, INSIDE_CONTRACTION, SHRINK)
                        sim[-1] = xr
                        fsim[-1] = fxr
                    else:  # fxr >= fsim[-2]
                        # Perform contraction.
                        if fxr < fsim[-1]:
                            self._rule_out(EXPANSION, INSIDE_CONTRACTION)
                            fxc = yield from self._func(OUTSIDE_CONTRACTION)

                            if fxc <= fxr:
                                self._rule_out(SHRINK)
                                sim[-1] = xc
                                fsim[-1] = fxc
                            else:
                                doshrink = 1
                        else:
                            # Perform an inside contraction.
                            self._rule_out(EXPANSION, OUTSIDE_CONTRACTION)
                            fxcc = yield from self._func(INSIDE_CONTRACTION)

                            if fxcc < fsim[-1]:
                                self._rule_out(SHRINK)
                                sim[-1] = xcc
                                fsim[-1] = fxcc
                            else:
                                doshrink = 1

                        if doshrink:
                            for j in one2np1:
                                sim[j] = shrunk[j]
                                fsim[j] = yield from self._func(SHRINK, j)
                iterations += 1
            except _MaxFuncCallError:
                pass
            ind = np.argsort(fsim)
            sim = np.take(sim, ind, 0)
            fsim = np.take(fsim, ind, 0)

        x = sim[0]
        fval = np.min(fsim)

        if self._ncalls >= maxfun:
            warnflag = 1
        elif iterations >= maxiter:
            warnflag = 2
        else:
            warnflag = 0

        self._result = NelderMeadResult(
            x=np.array(x, copy=True),
            fun=float(fval),
            nit=int(iterations),
            nfev=int(self._ncalls),
            status=warnflag,
            success=warnflag == 0,
            final_simplex=(sim, fsim),
        )


__all__ = [
    "CandidateKey",
    "NelderMeadResult",
    "Proposal",
    "SpeculativeNelderMead",
    "UsedCall",
]
