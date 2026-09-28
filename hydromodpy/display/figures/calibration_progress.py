"""How a calibration search converged, run after run, on one slide.

The trace and convergence figures answer a developer: which value went in,
which number came out. An audience asks something else: did the search get
better, how fast, and better at what. This figure answers in the words of the
phase it draws.

- The value tried at each run, on the axis the search walked (a log axis for
  a log-transformed parameter), each marker coloured by the cost it earned.
  The best run is marked, the range of runs within tolerance of the best is a
  band, and the bracket of a bisection is shaded as it closes.
- The cost of each run and the best reached so far, a staircase that only
  goes down, labelled with the metric and its unit, with the run from which
  the search stays within tolerance of its best.
- What the search improves: the cells the simulated seepage network gets
  right, adds and misses against the mapped streams, and the efficiency of the
  hydrograph, per run.
- With two parameters, the search in the parameter plane: a simplex walks
  downhill, a sampler explores then concentrates.

The tolerance is read the way the calibration reads it: one mesh cell for a
search scored on network distances in metres, five per cent of the best cost
otherwise, unless ``[calibration.uncertainty]`` wrote another width. A value
combined from two roots gets no interval, as in the calibration summary. The
run marked is the one the calibration returned, as the session journal names
it. A failed run keeps its place on the run axis and carries no cost.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._calibration_session import (
    EFFICIENCIES,
    NETWORK_METRICS,
    RESIDUAL_COSTS,
    CostBlock,
    as_mapping,
    chosen_session,
    cost_blocks,
    cost_label,
    float_or,
    metric_cost,
    metric_unit,
    parameter_declaration,
    read_tolerance,
    returned_row,
    session_config,
    session_descriptor,
    text,
    tolerance_interval,
)
from hydromodpy.display.figures._trial_diagnostics import TrialTable, trial_table
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET, get_cmap

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.colors import Normalize
    from matplotlib.figure import Figure as MplFigure
    from matplotlib.figure import SubFigure

    from hydromodpy.results.run import Run

_BLUE, _SAND, _RED = HIGH_CONTRAST_TRIPLET
_GREY = "0.55"

_METHOD_NAMES: dict[str, str] = {
    "bisection": "bisection",
    "scipy_nelder_mead": "Nelder-Mead simplex",
    "nelder_mead": "Nelder-Mead simplex",
    "optuna": "Optuna sampler",
    "cmaes": "CMA-ES",
    "grid": "grid sweep",
    "random_search": "random search",
    "emcee": "emcee sampler",
}

_PARAMETER_NAMES: dict[str, str] = {
    "K": "Hydraulic conductivity K",
    "Sy": "Specific yield Sy",
    "Ss": "Specific storage Ss",
    "T": "Transmissivity T",
    "K_over_R": "Ratio K/R",
    "R": "Recharge R",
}

_DECADES = 10.0
"""A positive cost spanning more than a decade is drawn on a log axis."""

_SLIDE_RC: dict[str, Any] = {
    "font.size": 13,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "axes.labelsize": 13,
    "xtick.labelsize": 11.5,
    "ytick.labelsize": 11.5,
    "legend.fontsize": 10.5,
    "legend.framealpha": 0.92,
}
"""Font sizes a 16:9 slide still reads from the back of a room."""


# ---------------------------------------------------------------------------
# what one session holds
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Parameter:
    """One calibrated parameter, its values per run and how the search walked it."""

    name: str
    values: np.ndarray
    log: bool
    units: str
    bounds: tuple[float, float] | None

    @property
    def label(self) -> str:
        """Return the axis label, in words, with its unit."""
        return f"{_PARAMETER_NAMES.get(self.name, self.name)} ({self.units})"

    def value_text(self, value: float) -> str:
        """Return one value with its unit, as a slide writes it."""
        unit = "" if self.units in ("", "-") else f" {self.units}"
        return f"{self.name} = {value:.3g}{unit}"


@dataclass(frozen=True, slots=True)
class _Network:
    """The confusion counts of the simulated network against the map, per run."""

    output: str
    valid: np.ndarray
    excess: np.ndarray
    missing: np.ndarray
    mapped: float


@dataclass(slots=True)
class _Search:
    """Everything the figure draws, read once from one session."""

    runs: np.ndarray
    cost: np.ndarray
    parameters: list[_Parameter]
    blocks: list[CostBlock]
    network: _Network | None
    method: str
    phase: str | None
    output_variable: str | None
    threshold: float | None = None
    tolerance_text: str = ""
    missing: str = ""
    returned: int | None = None
    intervals: dict[str, tuple[float, float]] = field(default_factory=dict)
    bracket: tuple[np.ndarray, np.ndarray] | None = None
    weights_verified: bool = False

    @property
    def best_so_far(self) -> np.ndarray:
        """Return the lowest cost reached up to each run, NaN before the first."""
        return _best_so_far(self.cost)

    @property
    def lowest(self) -> int | None:
        """Return the row of the lowest cost, None when no run produced a cost."""
        finite = np.flatnonzero(np.isfinite(self.cost))
        if not finite.size:
            return None
        return int(finite[np.argmin(self.cost[finite])])

    @property
    def best(self) -> int | None:
        """Return the row of the run the calibration returned, else of the lowest cost.

        A search combining two roots returns a value between them, where the
        cost is not the lowest: the run marked is the one it returned.
        """
        if self.returned is not None and np.isfinite(self.cost[self.returned]):
            return self.returned
        return self.lowest

    @property
    def best_word(self) -> str:
        """Return how the marked run is named: best, or returned when it is not the lowest."""
        return "best" if self.best == self.lowest else "returned"

    @property
    def first_within(self) -> int | None:
        """Return the first row whose cost is within tolerance of the best."""
        if self.threshold is None:
            return None
        rows = np.flatnonzero(np.isfinite(self.cost) & (self.cost <= self.threshold))
        return int(rows[0]) if rows.size else None


def _best_so_far(cost: np.ndarray) -> np.ndarray:
    """Return the running minimum, skipping failed runs, NaN before any cost.

    A failed run publishes no cost. Carrying its NaN forward would break the
    staircase from that run on, so it is read as no improvement.
    """
    best = np.fmin.accumulate(np.where(np.isfinite(cost), cost, np.inf))
    return np.where(np.isfinite(best), best, np.nan)


# ---------------------------------------------------------------------------
# the figure
# ---------------------------------------------------------------------------


@register
class CalibrationProgressFigure(BaseFigure):
    """How a calibration search converged, run after run, for any method.

    ``session_id`` picks one session when the run belongs to several.
    ``output`` names the network output to count when the phase scores more
    than one. ``render`` draws the cost panel alone; ``plot`` draws the slide.
    """

    spec = FigureSpec(
        name="calibration_progress",
        title="How the search converged",
        kind="timeseries",
        required_tables=("calibration_iterations",),
        default_figsize=(16.0, 9.0),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Refuse a run whose session recorded no cost, before drawing."""
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        try:
            table = trial_table(sim, session_id=chosen_session(sim, None))
        except ValueError as exc:
            return str(exc)
        if not table.has_objective():
            return "the calibration session recorded no cost per run."
        return None

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        session_id: str | None = None,
        output: str | None = None,
        **_,
    ) -> Axes:
        search = _read_search(sim, session_id=session_id, output=output)
        norm, cmap = _cost_colours(search.cost)
        _draw_cost(ax, search, norm=norm, cmap=cmap)
        return ax

    def plot(
        self,
        sim: Run,
        *,
        session_id: str | None = None,
        output: str | None = None,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib as mpl
        import matplotlib.pyplot as plt

        search = _read_search(sim, session_id=session_id, output=output)
        with mpl.rc_context(_SLIDE_RC):
            fig = plt.figure(
                figsize=figsize or self.spec.default_figsize,
                dpi=dpi,
                layout="constrained",
            )
            _draw_slide(fig, search)
            if save_path is not None:
                from pathlib import Path

                self._save(fig, Path(save_path), dpi=dpi, sim=sim)
        return fig


# ---------------------------------------------------------------------------
# reading the session
# ---------------------------------------------------------------------------


def _read_search(sim: Run, *, session_id: str | None, output: str | None) -> _Search:
    """Read one session into what the slide draws."""
    chosen = chosen_session(sim, session_id)
    table = trial_table(sim, session_id=chosen)
    descriptor = session_descriptor(sim, chosen)
    config = session_config(descriptor)

    cost = table.objective_values()[1]
    if "status" in table.frame.columns:
        completed = table.frame["status"].astype(str).str.lower().to_numpy() == "completed"
        cost = np.where(completed, cost, np.nan)

    blocks = cost_blocks(table, config)
    search = _Search(
        runs=table.iterations(),
        cost=cost,
        parameters=_parameters(table, descriptor),
        blocks=blocks,
        network=_network(table, config, output),
        method=str(descriptor.get("method") or config.get("method") or ""),
        phase=text(descriptor.get("phase_name")),
        output_variable=_series_variable(config, blocks),
        returned=returned_row(table, descriptor),
    )
    _read_tolerance(search, table, descriptor)
    search.bracket = _bracket(table, search, output)
    search.weights_verified = _weights_match(search)
    return search


def _parameters(table: TrialTable, descriptor: Mapping[str, Any]) -> list[_Parameter]:
    """Return the calibrated parameters in the order the session declared them."""
    declared = as_mapping(session_config(descriptor).get("parameters"))
    names = [name for name in declared if name in table.parameters]
    names += [name for name in table.parameters if name not in names]
    if not names:
        raise ValueError("the calibration session recorded no sampled parameter.")
    parameters = []
    for name in names:
        _, values = table.parameter_values(name)
        info = parameter_declaration(table, descriptor, name)
        bounds = _bounds(info.get("bounds"))
        positive = bool(np.all(values[np.isfinite(values)] > 0.0))
        transform = str(info.get("transform") or "").lower()
        log = positive and (transform == "log" or (not transform and _spans_decades(values)))
        parameters.append(
            _Parameter(
                name=name,
                values=values,
                log=log,
                units=text(info.get("units")) or "-",
                bounds=bounds,
            )
        )
    return parameters


def _network(table: TrialTable, config: Mapping[str, Any], output: str | None) -> _Network | None:
    """Return the confusion counts of the network output, None when none was scored."""
    outputs = config.get("outputs")
    declared = [
        str(name)
        for name, spec in (outputs.items() if isinstance(outputs, Mapping) else ())
        if isinstance(spec, Mapping) and spec.get("support") == "network"
    ]
    published = sorted(
        str(column)[: -len(".n_valid")]
        for column in table.frame.columns
        if str(column).endswith(".n_valid")
    )
    candidates = [output] if output is not None else [*declared, *published]
    name = next((item for item in candidates if item in published), None)
    if name is None:
        return None
    valid = table.diagnostic("n_valid", output=name)
    excess = _counts(table, "n_excess", name, valid.size)
    missing = _counts(table, "n_missing", name, valid.size)
    mapped = float("nan")
    for key in ("n_network_obs", "n_observed_cells"):
        if table.has_diagnostic(key, output=name):
            values = table.diagnostic(key, output=name)
            values = values[np.isfinite(values)]
            if values.size:
                mapped = float(np.median(values))
                break
    if not np.isfinite(mapped):
        total = valid + missing
        mapped = float(np.nanmedian(total)) if np.any(np.isfinite(total)) else float("nan")
    return _Network(output=name, valid=valid, excess=excess, missing=missing, mapped=mapped)


def _counts(table: TrialTable, key: str, output: str, size: int) -> np.ndarray:
    """Return one confusion count per run, NaN when the output never published it."""
    if table.has_diagnostic(key, output=output):
        return table.diagnostic(key, output=output)
    return np.full(size, np.nan)


def _series_variable(config: Mapping[str, Any], blocks: Sequence[CostBlock]) -> str | None:
    """Return the variable the series blocks compare, discharge for a gauge."""
    outputs = config.get("outputs")
    if not isinstance(outputs, Mapping):
        return None
    for block in blocks:
        spec = as_mapping(outputs.get(block.output)) if block.output else {}
        if spec.get("support") != "network" and spec.get("variable"):
            return str(spec["variable"])
    return None


def _read_tolerance(search: _Search, table: TrialTable, descriptor: Mapping[str, Any]) -> None:
    """Set the cost the best is told apart from, and the interval it gives.

    The width and the interval are the calibration's own, read by the helper
    every calibration figure shares, so the slide and the cost profile never
    report two intervals for one answer.
    """
    tolerance = read_tolerance(search.cost, search.blocks, table, descriptor)
    search.threshold = tolerance.threshold
    search.tolerance_text = tolerance.text
    search.missing = tolerance.missing
    if tolerance.threshold is None:
        return
    for parameter in search.parameters:
        interval = tolerance_interval(parameter.values, search.cost, tolerance.threshold)
        if interval is not None:
            search.intervals[parameter.name] = (interval.low, interval.high)


def _bracket(
    table: TrialTable, search: _Search, output: str | None
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return the tightest sign-changing interval known after each run, if any.

    Only a one-parameter search that published a signed residual has one; it is
    the interval a bisection halves.
    """
    if len(search.parameters) != 1:
        return None
    network = search.network.output if search.network is not None else output
    try:
        residual = table.diagnostic("J_signed", output=network)
    except ValueError:
        return None
    values = search.parameters[0].values
    if np.any(np.isfinite(values) & (values <= 0.0)):
        return None
    low = np.full(values.size, np.nan)
    high = np.full(values.size, np.nan)
    known: list[tuple[float, float]] = []
    for row in range(values.size):
        if np.isfinite(values[row]) and np.isfinite(residual[row]):
            known.append((float(values[row]), float(residual[row])))
        points = sorted(known)
        pairs = [
            (left[0], right[0])
            for left, right in zip(points[:-1], points[1:], strict=False)
            if left[1] * right[1] < 0.0
        ]
        if pairs:
            low[row], high[row] = min(pairs, key=lambda pair: pair[1] / pair[0])
    return (low, high) if np.any(np.isfinite(low)) else None


def _weights_match(search: _Search) -> bool:
    """Whether the declared weights rebuild the recorded cost of every run.

    A phase can weigh its blocks with its own shares, and the session may have
    recorded the section's weights instead. The label writes the weights only
    when they are the ones the cost was computed with.
    """
    if len(search.blocks) < 2:
        return True
    parts = []
    for block in search.blocks:
        if block.raw is None:
            return False
        parts.append(block.weight * block.raw)
    total = np.sum(parts, axis=0)
    weight = sum(block.weight for block in search.blocks)
    rows = np.isfinite(search.cost) & np.isfinite(total)
    if not np.any(rows) or weight <= 0.0:
        return False
    for candidate in (total, total / weight):
        if np.allclose(candidate[rows], search.cost[rows], rtol=1e-6, atol=1e-9):
            return True
    return False


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------


def _cost_formula(search: _Search) -> str:
    """Return how the weighted cost of several blocks is built, in words."""
    total = sum(block.weight for block in search.blocks)
    if search.weights_verified and total > 0.0:
        terms = [f"{block.weight / total:.2g} x ({metric_cost(block)})" for block in search.blocks]
    else:
        terms = [f"({metric_cost(block)})" for block in search.blocks]
    return " + ".join(terms)


def _cost_short(search: _Search) -> str:
    """Return the cost as a colorbar names it."""
    if len(search.blocks) == 1:
        block = search.blocks[0]
        return f"{metric_cost(block)} ({metric_unit(block)})"
    return "weighted cost (-)"


def _method_text(method: str) -> str:
    """Return the method as a hydrogeologist names it."""
    key = method.lower()
    if key in _METHOD_NAMES:
        return _METHOD_NAMES[key]
    return key.removeprefix("scipy_").replace("_", " ") or "calibration"


def _subtitle(search: _Search) -> str:
    """Return the line under the title: phase, method, parameters, runs."""
    phase = f"{search.phase.replace('_', ' ')} phase" if search.phase else "Calibration"
    names = " and ".join(parameter.name for parameter in search.parameters)
    runs = int(search.runs.size)
    failed = int(np.sum(~np.isfinite(search.cost)))
    tail = f", {failed} failed" if failed else ""
    line = f"{phase[:1].upper()}{phase[1:]}: {_method_text(search.method)} on {names}, {runs} runs{tail}"
    best = search.best
    if best is not None:
        values = ", ".join(
            parameter.value_text(float(parameter.values[best])) for parameter in search.parameters
        )
        line += f". {search.best_word.capitalize()} at run {int(search.runs[best])}: {values}"
    return line


def _better_text(search: _Search) -> str:
    """Say in words what "better" means for this phase."""
    sentences: list[str] = []
    for block in search.blocks:
        metric = block.metric or ""
        if metric == "distance_gap":
            sentences.append(
                "Better, for the stream network: a smaller gap between D_so, how far the "
                "simulated seepage cells sit from the mapped streams, and D_os, how far the "
                "mapped streams sit from the seepage cells. At zero the simulated network "
                "neither spills past the map nor falls short of it."
            )
        elif metric == "distance_mean":
            sentences.append(
                "Better, for the stream network: a smaller mean of D_so and D_os, the two "
                "distances between the simulated seepage cells and the mapped streams."
            )
        elif metric in EFFICIENCIES:
            name = EFFICIENCIES[metric]
            where = "at the gauge" if search.output_variable == "discharge" else ""
            detail = (
                ", computed on log discharge so that low flows weigh as much as floods"
                if metric == "nse_log"
                else ""
            )
            sentences.append(
                f"Better, for the {_series_noun(search)}: a higher {name} {where}{detail} "
                f"(1 is a perfect fit). The search minimises 1 - {name}.".replace("  ", " ")
            )
        elif metric in RESIDUAL_COSTS:
            sentences.append(
                f"Better: a smaller {RESIDUAL_COSTS[metric]} between the simulated and the "
                "observed values."
            )
    if len(search.blocks) > 1:
        sentences = [f"The search minimises one cost: {_cost_formula(search)}.", *sentences]
    if not sentences:
        sentences.append("Better means a lower cost: the search minimises it.")
    if search.threshold is not None and search.tolerance_text:
        sentences.append(
            f"A run whose cost is within {search.tolerance_text} of the best is not told "
            "apart from it."
        )
    elif search.missing:
        sentences.append(f"{search.missing[:1].upper()}{search.missing[1:]}.")
    return " ".join(sentences)


def _series_noun(search: _Search) -> str:
    """Return what the series blocks compare, in one word."""
    return "discharge" if search.output_variable == "discharge" else "observed series"


# ---------------------------------------------------------------------------
# the slide
# ---------------------------------------------------------------------------


def _draw_slide(fig: MplFigure, search: _Search) -> None:
    """Lay the panels out on one 16:9 figure, the story read left to right."""
    series = [
        block
        for block in search.blocks
        if block.raw is not None and block.metric not in NETWORK_METRICS
    ]
    two = len(search.parameters) == 2
    improvement = int(search.network is not None) + int(bool(series))

    top_count = len(search.parameters) + (1 if len(search.parameters) == 1 else int(two))
    bottom_count = (0 if len(search.parameters) == 1 else 1) + improvement
    better = textwrap.fill(_better_text(search), 175)
    lines = better.count("\n") + 1
    rows = [0.17, 1.0] + ([1.0] if bottom_count else []) + [0.045 * lines + 0.02]
    header, top, *rest = fig.subfigures(len(rows), 1, height_ratios=rows)
    bottom = rest[0] if bottom_count else None
    footer = rest[-1]

    header.text(
        0.5, 0.95, "How the search converged", ha="center", va="top", fontsize=22, weight="bold"
    )
    header.text(0.5, 0.02, _subtitle(search), ha="center", va="bottom", fontsize=13.5, color="0.25")
    footer.text(
        0.5,
        0.5,
        better,
        ha="center",
        va="center",
        fontsize=12,
        color="0.2",
    )

    norm, cmap = _cost_colours(search.cost)
    top_axes = top.subplots(1, top_count, squeeze=False)[0]
    parameter_axes = list(top_axes[: len(search.parameters)])
    for ax, parameter in zip(parameter_axes, search.parameters, strict=False):
        _draw_parameter(ax, search, parameter, norm=norm, cmap=cmap)
    colorbar = top.colorbar(
        _mappable(norm, cmap), ax=parameter_axes, pad=0.01, fraction=0.04, aspect=25
    )
    colorbar.set_label(f"Cost of the run: {_cost_short(search)}\ndarker is better")

    bottom_axes = list(bottom.subplots(1, bottom_count, squeeze=False)[0]) if bottom else []
    if len(search.parameters) == 1:
        cost_ax = top_axes[1]
    else:
        cost_ax = bottom_axes.pop(0)
        if two:
            _draw_plane(top, top_axes[-1], search)
    _draw_cost(cost_ax, search, norm=norm, cmap=cmap)

    if search.network is not None:
        _draw_network(bottom_axes.pop(0), search, search.network)
    if series:
        _draw_series(bottom_axes.pop(0), search, series)


def _cost_colours(cost: np.ndarray) -> tuple[Normalize, Any]:
    """Return the colour scale of the cost: log when it spans decades, dark is low."""
    from matplotlib.colors import LogNorm, Normalize

    finite = cost[np.isfinite(cost)]
    cmap = get_cmap("viridis")
    if not finite.size:
        return Normalize(0.0, 1.0), cmap
    low, high = float(finite.min()), float(finite.max())
    if low > 0.0 and high / low > _DECADES:
        return LogNorm(low, high), cmap
    if high <= low:
        high = low + (abs(low) or 1.0) * 1e-6
    return Normalize(low, high), cmap


def _mappable(norm: Normalize, cmap: Any) -> Any:
    """Return a colour source a colorbar can read."""
    from matplotlib.cm import ScalarMappable

    mappable = ScalarMappable(norm=norm, cmap=cmap)
    mappable.set_array([])
    return mappable


def _run_axis(ax: Axes, search: _Search) -> None:
    """Put the run numbers on x, as integers, with half a run of margin."""
    from matplotlib.ticker import MaxNLocator

    runs = search.runs
    ax.set_xlim(float(np.nanmin(runs)) - 0.6, float(np.nanmax(runs)) + 0.6)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=12))
    ax.set_xlabel("Run number")
    ax.grid(True, ls=":", lw=0.5)


def _draw_parameter(
    ax: Axes, search: _Search, parameter: _Parameter, *, norm: Normalize, cmap: Any
) -> None:
    """Panel 1: the value tried at each run, coloured by the cost it earned."""
    runs, values, cost = search.runs, parameter.values, search.cost
    if parameter.log:
        ax.set_yscale("log")
    if search.bracket is not None:
        low, high = search.bracket
        ax.fill_between(
            np.append(runs, runs[-1] + 0.6),
            np.append(low, low[-1]),
            np.append(high, high[-1]),
            step="post",
            color=_GREY,
            alpha=0.28,
            lw=0.0,
            zorder=1,
            label="bisection bracket: the balance J = 0 lies inside",
        )
    interval = search.intervals.get(parameter.name)
    if interval is not None and interval[1] > interval[0]:
        ax.axhspan(
            interval[0],
            interval[1],
            color=_SAND,
            alpha=0.3,
            lw=0.0,
            zorder=0,
            label=f"within tolerance: {_span_text(parameter, interval)}",
        )
    ax.plot(runs, values, color="0.6", lw=1.0, zorder=2)
    done = np.isfinite(cost) & np.isfinite(values)
    ax.scatter(
        runs[done],
        values[done],
        c=cost[done],
        cmap=cmap,
        norm=norm,
        s=90,
        edgecolor="white",
        linewidth=0.8,
        zorder=4,
    )
    failed = ~np.isfinite(cost) & np.isfinite(values)
    if np.any(failed):
        ax.scatter(
            runs[failed],
            values[failed],
            marker="x",
            s=70,
            color="0.35",
            zorder=4,
            label="failed run: no cost",
        )
    best = search.best
    if best is not None:
        value = float(values[best])
        ax.axhline(value, color=_RED, ls="--", lw=1.4, zorder=3)
        ax.scatter(
            [runs[best]],
            [value],
            marker="*",
            s=420,
            color=_RED,
            edgecolor="black",
            linewidth=0.8,
            zorder=5,
            label=f"{search.best_word}: {parameter.value_text(value)}",
        )
    _value_limits(ax, parameter, interval)
    _run_axis(ax, search)
    ax.set_ylabel(parameter.label)
    ax.set_title(f"{parameter.name} tried at each run")
    ax.legend(loc="best", fontsize=10.5 if len(search.parameters) == 1 else 9.5)


def _draw_cost(ax: Axes, search: _Search, *, norm: Normalize, cmap: Any) -> None:
    """Panel 2: the cost of each run, and the best reached so far."""
    runs, cost = search.runs, search.cost
    best_so_far = search.best_so_far
    finite = np.isfinite(cost)
    ax.plot(runs[finite], cost[finite], color="0.7", lw=1.0, zorder=1)
    ax.scatter(
        runs[finite],
        cost[finite],
        c=cost[finite],
        cmap=cmap,
        norm=norm,
        s=70,
        edgecolor="white",
        linewidth=0.8,
        zorder=3,
        label="cost of the run",
    )
    ax.step(runs, best_so_far, where="post", color=_BLUE, lw=2.8, zorder=4, label="best so far")
    _scale_cost(ax, cost)
    if np.any(~finite):
        ax.scatter(
            runs[~finite],
            np.full(int(np.sum(~finite)), 0.03),
            transform=ax.get_xaxis_transform(),
            marker="x",
            s=70,
            color="0.35",
            zorder=4,
            clip_on=False,
            label="failed run: no cost",
        )
    first = search.first_within
    if search.threshold is not None:
        reached = "" if first is None else f"\nreached at run {int(runs[first])} of {runs.size}"
        ax.axhline(
            search.threshold,
            color=_SAND,
            ls="--",
            lw=2.0,
            zorder=2,
            label=f"within {search.tolerance_text} of the best{reached}",
        )
        if first is not None:
            ax.axvline(runs[first], color=_SAND, ls=":", lw=2.0, zorder=2)
        low, high = ax.get_ylim()
        if search.threshold >= high:
            # Keep the tolerance in view: a search whose every run sits inside it
            # has to show that, not hide the line above the frame.
            ax.set_ylim(low, search.threshold + 0.6 * (search.threshold - low))
    best = search.best
    if best is not None:
        ax.scatter(
            [runs[best]],
            [cost[best]],
            marker="*",
            s=420,
            color=_RED,
            edgecolor="black",
            linewidth=0.8,
            zorder=5,
            label=f"{search.best_word}: {cost[best]:.4g} at run {int(runs[best])}",
        )
    _run_axis(ax, search)
    ax.set_ylabel(cost_label(search.blocks))
    ax.set_title("Cost of each run, and the best so far")
    ax.legend(loc="upper right")


def _scale_cost(ax: Axes, cost: np.ndarray) -> None:
    """Draw the cost on a log axis when it spans decades, symlog across zero."""
    finite = cost[np.isfinite(cost)]
    if not finite.size:
        return
    low, high = float(finite.min()), float(finite.max())
    if low > 0.0 and high / low > _DECADES:
        ax.set_yscale("log")
        # Room for the key grows slowly with the span, so the runs keep the panel.
        headroom = min(0.3 + 0.15 * np.log10(high / low), 1.0)
        ax.set_ylim(low / 2.5, high * 10.0**headroom)
    elif low <= 0.0 < high and high / max(abs(low), 1e-12) > _DECADES:
        ax.set_yscale("symlog", linthresh=max(abs(low), high / 1e3))
    else:
        span = high - low or abs(high) or 1.0
        ax.set_ylim(low - 0.15 * span, high + 1.1 * span)


def _value_limits(ax: Axes, parameter: _Parameter, interval: tuple[float, float] | None) -> None:
    """Frame the values tried, never wider than the search bounds.

    A bisection starts on its bounds and fills the frame. A local search that
    stays in a corner of wide bounds would sit on one line if the frame were
    the bounds, so the frame follows the runs.
    """
    values = parameter.values[np.isfinite(parameter.values)]
    if interval is not None:
        values = np.append(values, interval)
    if not values.size:
        return
    low, high = float(values.min()), float(values.max())
    if parameter.log and low > 0.0:
        factor = max((high / low) ** 0.12, 1.25)
        low, high = low / factor, high * factor
    else:
        pad = 0.12 * (high - low or abs(high) or 1.0)
        low, high = low - pad, high + pad
    if parameter.bounds is not None:
        lower, upper = parameter.bounds
        margin = 1.6 if parameter.log and lower > 0.0 else 1.0
        low = max(low, lower / margin) if margin > 1.0 else max(low, lower - 0.05 * (upper - lower))
        high = (
            min(high, upper * margin) if margin > 1.0 else min(high, upper + 0.05 * (upper - lower))
        )
    ax.set_ylim(low, high)
    if parameter.log and low > 0.0 and high / low < 100.0:
        _plain_log_ticks(ax.yaxis)


def _plain_log_ticks(axis: Any) -> None:
    """Label a log axis narrower than two decades in plain numbers, at 1, 2 and 5."""
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    axis.set_major_locator(LogLocator(base=10.0, subs=(1.0, 2.0, 5.0)))
    axis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.3g}"))
    axis.set_minor_formatter(NullFormatter())


def _span_text(parameter: _Parameter, interval: tuple[float, float]) -> str:
    """Return the range of values within tolerance, with its unit."""
    unit = "" if parameter.units in ("", "-") else f" {parameter.units}"
    return f"{interval[0]:.3g} to {interval[1]:.3g}{unit}"


def _draw_network(ax: Axes, search: _Search, network: _Network) -> None:
    """Panel 3: the simulated seepage network against the mapped streams, per run.

    A network many times the map would flatten every later bar. Above a little
    over twice the map a bar is broken and grows with the log of its count, so
    bars ten times apart still differ. Its count is written on top.
    """
    from matplotlib.ticker import FuncFormatter

    runs = search.runs
    valid = np.nan_to_num(network.valid)
    excess = np.nan_to_num(network.excess)
    missing = np.nan_to_num(network.missing)
    total = valid + excess
    mapped = network.mapped
    reference = mapped if np.isfinite(mapped) else float(np.max(total) or 1.0)
    cap = 2.2 * reference
    cut = total > cap
    # A fixed stub keeps a bar just over the cap visible above its break.
    decades = np.log10(np.maximum(total, cap) / cap)
    shown = np.where(cut, cap + 0.2 * reference + 1.5 * reference * decades, total)
    crowded = runs.size > 20
    width = 0.72 if runs.size <= 30 else 0.85
    ax.bar(runs, valid, width, color=_BLUE, label="found: on the map and simulated", zorder=3)
    ax.bar(
        runs,
        np.maximum(shown - valid, 0.0),
        width,
        bottom=valid,
        color=_SAND,
        label="extra: simulated, not on the map",
        zorder=3,
    )
    ax.bar(runs, -missing, width, color=_RED, label="missed: on the map, not simulated", zorder=3)
    ax.axhline(0.0, color="black", lw=0.8, zorder=4)
    if np.isfinite(mapped):
        ax.axhline(
            mapped,
            color="black",
            ls="--",
            lw=1.6,
            zorder=4,
            label=f"mapped streams: {mapped:.0f} cells",
        )
    if np.any(cut):
        _mark_cut_bars(
            ax,
            runs[cut],
            total[cut],
            shown[cut],
            cap,
            width=width,
            reference=reference,
            counts=not crowded,
        )

    # A narrow crowded panel has a taller key, so its bars keep lower.
    top = max(float(np.max(shown)), reference) * (2.2 if crowded else 1.8)
    bottom = -max(float(np.max(missing)), 0.08 * reference) * 1.25
    ax.set_ylim(bottom, top)
    best = search.best
    if best is not None:
        ax.bar(
            [runs[best]],
            [shown[best] + missing[best]],
            width + 0.12,
            bottom=-missing[best],
            fill=False,
            edgecolor=_RED,
            lw=2.4,
            zorder=5,
            label=(
                f"{search.best_word} run {int(runs[best])}: {valid[best]:.0f} found, "
                f"{excess[best]:.0f} extra, {missing[best]:.0f} missed"
            ),
        )
    # Above the break the axis no longer counts cells, so it carries no number.
    ceiling = cap if np.any(cut) else np.inf
    ax.yaxis.set_major_formatter(
        FuncFormatter(
            lambda value, _: "" if value > ceiling else f"{abs(value):,.0f}".replace(",", " ")
        )
    )
    _run_axis(ax, search)
    ax.set_ylabel("Stream cells (-)")
    ax.set_title("Seepage network against the map")
    ax.legend(loc="upper right", fontsize=9.5 if crowded else 10.5)


def _mark_cut_bars(
    ax: Axes,
    runs: np.ndarray,
    totals: np.ndarray,
    heights: np.ndarray,
    cap: float,
    *,
    width: float,
    reference: float,
    counts: bool,
) -> None:
    """Break each cut bar at the cap, mark its top, and write its count when there is room."""
    gap = 0.05 * reference
    ax.bar(runs, 2.0 * gap, width * 1.04, bottom=cap - gap, color="white", zorder=4)
    ax.scatter(
        runs,
        heights,
        marker="^",
        s=50,
        color="black",
        zorder=6,
        label="broken bar: taller network, log scale above the white gap",
    )
    if not counts:
        return
    for run, count, height in zip(runs, totals, heights, strict=False):
        ax.annotate(
            f"{count:,.0f}".replace(",", " "),
            xy=(run, height),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=10,
            color="black",
            zorder=6,
        )


def _draw_series(ax: Axes, search: _Search, blocks: Sequence[CostBlock]) -> None:
    """Panel 3, series half: the efficiency itself per run, rising toward its best."""
    runs = search.runs
    colours = (_BLUE, _RED, _SAND)
    names = []
    for index, block in enumerate(blocks):
        colour = colours[index % len(colours)]
        metric = block.metric or ""
        raw = np.asarray(block.raw, dtype=float)
        efficiency = metric in EFFICIENCIES and not block.transformed
        values = 1.0 - raw if efficiency else raw
        name = EFFICIENCIES[metric] if efficiency else metric_cost(block)
        names.append(name)
        prefix = f"{block.name}: " if len(blocks) > 1 else ""
        finite = np.isfinite(values)
        ax.plot(runs[finite], values[finite], color=colour, lw=1.0, alpha=0.5, zorder=2)
        ax.scatter(
            runs[finite],
            values[finite],
            s=60,
            color=colour,
            alpha=0.75,
            edgecolor="white",
            linewidth=0.8,
            zorder=3,
            label=f"{prefix}{name} of the run",
        )
        running = -_best_so_far(-values) if efficiency else _best_so_far(values)
        ax.step(
            runs,
            running,
            where="post",
            color=colour,
            lw=2.8,
            zorder=4,
            label=f"{prefix}best so far",
        )
        best = search.best
        if best is not None and np.isfinite(values[best]):
            ax.scatter(
                [runs[best]],
                [values[best]],
                marker="*",
                s=420,
                color=_RED,
                edgecolor="black",
                linewidth=0.8,
                zorder=5,
                label=f"{prefix}{search.best_word} run: {name} = {values[best]:.3f}",
            )
    finite = np.concatenate(
        [(1.0 - b.raw if (b.metric in EFFICIENCIES) else b.raw)[np.isfinite(b.raw)] for b in blocks]
    )
    if finite.size:
        low, high = float(finite.min()), float(finite.max())
        span = high - low or abs(high) or 1.0
        ax.set_ylim(low - 0.6 * span, high + 0.25 * span)
    _run_axis(ax, search)
    unit = "-" if all(block.metric in EFFICIENCIES for block in blocks) else metric_unit(blocks[0])
    rises = all(block.metric in EFFICIENCIES for block in blocks)
    way = "higher" if rises else "lower"
    ax.set_ylabel(f"{' / '.join(dict.fromkeys(names))} ({unit}), {way} is better")
    noun = "gauged discharge" if search.output_variable == "discharge" else "observed series"
    ax.set_title(f"Fit to the {noun}")
    ax.legend(loc="lower right")


def _draw_plane(sub: SubFigure, ax: Axes, search: _Search) -> None:
    """Panel 4: every run in the plane of the two parameters, the best path joined."""
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    first, second = search.parameters
    x, y, runs = first.values, second.values, search.runs
    if first.log:
        ax.set_xscale("log")
    if second.log:
        ax.set_yscale("log")
    base = get_cmap("Blues")
    order_cmap = LinearSegmentedColormap.from_list("run_order", base(np.linspace(0.3, 1.0, 256)))
    order_norm = Normalize(float(np.nanmin(runs)), float(np.nanmax(runs)))
    done = np.isfinite(x) & np.isfinite(y)
    ax.scatter(
        x[done],
        y[done],
        c=runs[done],
        cmap=order_cmap,
        norm=order_norm,
        s=80,
        edgecolor="0.3",
        linewidth=0.5,
        zorder=3,
    )

    best_so_far = search.best_so_far
    improved = [0] if np.isfinite(search.cost[0]) else []
    improved += [
        row
        for row in range(1, search.cost.size)
        if np.isfinite(best_so_far[row])
        and (not np.isfinite(best_so_far[row - 1]) or best_so_far[row] < best_so_far[row - 1])
    ]
    if len(improved) > 1:
        ax.plot(
            x[improved], y[improved], color=_RED, lw=2.0, zorder=4, label="each new best, in order"
        )
        for start, end in zip(improved[:-1], improved[1:], strict=False):
            ax.annotate(
                "",
                xy=(x[end], y[end]),
                xytext=(x[start], y[start]),
                arrowprops={"arrowstyle": "->", "color": _RED, "lw": 2.0},
                zorder=4,
            )
    if done.any():
        start = int(np.flatnonzero(done)[0])
        ax.annotate(
            "run 1" if runs[start] == 1 else f"run {int(runs[start])}",
            xy=(x[start], y[start]),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=11,
        )
    best = search.best
    if best is not None:
        ax.scatter(
            [x[best]],
            [y[best]],
            marker="*",
            s=480,
            color=_RED,
            edgecolor="black",
            linewidth=0.8,
            zorder=5,
            label=f"{search.best_word} run {int(runs[best])}",
        )
    for parameter, setter in ((first, ax.set_xlim), (second, ax.set_ylim)):
        if parameter.bounds is not None:
            low, high = parameter.bounds
            if parameter.log and low > 0.0:
                setter(low / 1.3, high * 1.3)
            else:
                pad = 0.04 * (high - low)
                setter(low - pad, high + pad)
    colorbar = sub.colorbar(
        _mappable(order_norm, order_cmap), ax=ax, pad=0.01, fraction=0.05, aspect=25
    )
    colorbar.set_label("Run number: darker is later")
    ax.set_xlabel(first.label)
    ax.set_ylabel(second.label)
    ax.grid(True, which="major", ls=":", lw=0.5)
    ax.set_title(f"The search in the {first.name} - {second.name} plane")
    ax.legend(loc="best")


# ---------------------------------------------------------------------------
# small readers
# ---------------------------------------------------------------------------


def _bounds(value: Any) -> tuple[float, float] | None:
    """Return the search bounds as two finite floats, None otherwise."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, Sequence) or len(value) != 2:
        return None
    low, high = float_or(value[0], np.nan), float_or(value[1], np.nan)
    if not (np.isfinite(low) and np.isfinite(high)) or high <= low:
        return None
    return low, high


def _spans_decades(values: np.ndarray) -> bool:
    """Whether positive samples span more than a decade: a search in log space."""
    finite = values[np.isfinite(values)]
    return bool(finite.size) and float(finite.max() / finite.min()) > 10.0
