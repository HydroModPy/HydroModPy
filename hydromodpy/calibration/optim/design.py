"""Space-filling designs: points of the unit cube for a calibration or an experiment plan.

:func:`draw_unit` is the one place that turns a method name, a size, a seed and the
options of the method into points of the unit cube. The Latin hypercube adapter of a
calibration and the ``[sites.design]`` plan of a campaign both call it. The methods
are the entries of :data:`SAMPLERS`. A scrambled Sobol sequence is nested, so its first
``n`` points do not change when ``n`` grows, and a plan can double its size and keep
the cases it has already run. A Latin hypercube is not nested, so a plan grows it by
lots, each lot drawn on its own seed (:func:`lot_seed`). :func:`design_points` maps the
unit points to physical values and names them.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel

from hydromodpy.calibration.optim.adapters.grid_adapter import grid_axes_sizes
from hydromodpy.calibration.optim.method_config import (
    GridMethodConfig,
    LhsOptions,
    SobolOptions,
)

Draw = Callable[[int | None, int, int | None, BaseModel], np.ndarray]


@dataclass(frozen=True, slots=True)
class Sampler:
    """One design method: how it draws, what it reads and what it needs."""

    name: str
    options: type[BaseModel]
    draw: Draw
    needs_n: bool
    needs_seed: bool
    nested: bool
    summary: str


def _sobol(n: int | None, dim: int, seed: int | None, options: BaseModel) -> np.ndarray:
    from scipy.stats import qmc

    # A power of two is the size scipy keeps balanced. Another size takes the head of the
    # next power of two, the same points scipy would give, without its warning.
    exponent = max(0, math.ceil(math.log2(n)))
    sampler = qmc.Sobol(d=dim, scramble=True, seed=None if seed is None else int(seed))
    return sampler.random_base2(m=exponent)[:n]


def _lhs(n: int | None, dim: int, seed: int | None, options: BaseModel) -> np.ndarray:
    from scipy.stats import qmc

    sampler = qmc.LatinHypercube(
        d=dim,
        optimization=getattr(options, "optimization", None),
        seed=None if seed is None else int(seed),
    )
    return sampler.random(n=n)


def grid_size(dim: int, options: BaseModel) -> int:
    """Return how many points a grid of *dim* axes holds."""
    return math.prod(grid_axes_sizes(dim, getattr(options, "points_per_dim", None)))


def _grid(n: int | None, dim: int, seed: int | None, options: BaseModel) -> np.ndarray:
    sizes = grid_axes_sizes(dim, getattr(options, "points_per_dim", None))
    axes = [np.linspace(0.0, 1.0, size) for size in sizes]
    return np.asarray(list(itertools.product(*axes)), dtype=float).reshape(-1, dim)


SAMPLERS: dict[str, Sampler] = {
    "sobol": Sampler(
        "sobol",
        SobolOptions,
        _sobol,
        needs_n=True,
        needs_seed=True,
        nested=True,
        summary="scrambled Sobol sequence, nested: doubling n keeps the first points",
    ),
    "lhs": Sampler(
        "lhs",
        LhsOptions,
        _lhs,
        needs_n=True,
        needs_seed=True,
        nested=False,
        summary="Latin hypercube, one point per stratum, grown by independent lots",
    ),
    "grid": Sampler(
        "grid",
        GridMethodConfig,
        _grid,
        needs_n=False,
        needs_seed=False,
        nested=False,
        summary="regular grid, its size is the product of points_per_dim",
    ),
}
"""The design methods by name, ``lhs`` and ``grid`` being the names of the calibration methods."""


def sampler_options(method: str, options: Mapping[str, object] | BaseModel | None) -> BaseModel:
    """Return *options* as the option model of *method*; an option it has not raises."""
    model = SAMPLERS[method].options
    if isinstance(options, BaseModel):
        return options if isinstance(options, model) else model()
    return model.model_validate(dict(options or {}))


def draw_unit(
    method: str,
    n: int | None,
    dim: int,
    seed: int | None,
    options: Mapping[str, object] | BaseModel | None = None,
) -> np.ndarray:
    """Return ``(n, dim)`` points of the unit cube drawn by *method*.

    The seed is the only source of randomness, no global generator is read. A grid takes no
    *n*: its size follows ``points_per_dim``, and an *n* that disagrees is refused.
    """
    if method not in SAMPLERS:
        raise ValueError(f"unknown design method {method!r}, known: {', '.join(SAMPLERS)}")
    sampler = SAMPLERS[method]
    model = sampler_options(method, options)
    if sampler.needs_n:
        if n is None or n <= 0:
            raise ValueError(f"n must be positive for {method}, got {n!r}")
    elif n is not None and n != grid_size(dim, model):
        raise ValueError(f"{method} holds {grid_size(dim, model)} points, not n = {n}")
    return sampler.draw(n, dim, seed, model)


def lot_seed(seed: int, lot: int) -> int:
    """Return the seed of lot number *lot* (1-based), derived from the plan seed."""
    return int(np.random.SeedSequence([int(seed), int(lot)]).generate_state(1)[0])


def to_physical(unit: np.ndarray, lower: float, upper: float, sampling: str) -> np.ndarray:
    """Map a column of the unit interval into ``[lower, upper]``, stratification kept."""
    if sampling == "log_uniform":
        from scipy.stats import loguniform

        return np.asarray(loguniform.ppf(unit, float(lower), float(upper)), dtype=float)
    if sampling != "uniform":
        raise ValueError(f"sampling {sampling!r} has no design, use 'uniform' or 'log_uniform'")
    return lower + unit * (upper - lower)


@dataclass(frozen=True, slots=True)
class DesignParameter:
    """One drawn parameter: its name, its physical bounds and its sampling."""

    name: str
    lower: float
    upper: float
    sampling: str


@dataclass(frozen=True, slots=True)
class DesignPoint:
    """One point of a plan: the recipe name it takes and its physical values."""

    recipe: str
    values: Mapping[str, float]


def design_lots(method: str, n: int | Sequence[int] | None) -> tuple[int, ...]:
    """Return the sizes of the lots of a plan: one for sobol and grid, a list for lhs."""
    if method == "lhs":
        return (n,) if isinstance(n, int) else tuple(n or ())
    return (n,) if isinstance(n, int) else ()


def design_points(
    method: str,
    n: int | Sequence[int] | None,
    seed: int | None,
    parameters: Sequence[DesignParameter],
    options: Mapping[str, object] | BaseModel | None = None,
) -> list[DesignPoint]:
    """Return the named points of a plan, in physical values.

    Sobol and grid points are ``p0001``, ``p0002`` and so on. A Latin hypercube plan is a
    list of lots and its points are ``b1p0001`` for the first point of lot 1, each lot drawn
    on ``lot_seed(seed, lot)``, so a lot added at the end leaves the earlier ones as they are.
    """
    dim = len(parameters)
    if method == "lhs":
        lots = design_lots(method, n)
        units = [
            draw_unit(method, size, dim, lot_seed(seed, i), options)
            for i, size in enumerate(lots, 1)
        ]
        names = [[f"b{i}p{j:04d}" for j in range(1, len(u) + 1)] for i, u in enumerate(units, 1)]
    else:
        size = None if method == "grid" else n
        units = [draw_unit(method, size, dim, seed, options)]
        names = [[f"p{j:04d}" for j in range(1, len(units[0]) + 1)]]
    points: list[DesignPoint] = []
    for unit, labels in zip(units, names, strict=True):
        columns = [
            to_physical(unit[:, k], p.lower, p.upper, p.sampling) for k, p in enumerate(parameters)
        ]
        for row, label in enumerate(labels):
            values = {p.name: float(columns[k][row]) for k, p in enumerate(parameters)}
            points.append(DesignPoint(label, values))
    return points


__all__ = [
    "SAMPLERS",
    "DesignParameter",
    "DesignPoint",
    "Sampler",
    "design_lots",
    "design_points",
    "draw_unit",
    "grid_size",
    "lot_seed",
    "sampler_options",
    "to_physical",
]
