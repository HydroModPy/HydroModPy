"""What a calibration session says about itself, read once for every figure.

The trials say what was tried. The session says what was asked and what came
back: the unit of each parameter, the metric of each objective block, the
trial the calibration returned, the record of a root search, and the width
the calibration reads its interval with. Every calibration figure has to agree
on those, so they are read here and nowhere else.

A figure draws a :class:`~hydromodpy.results.session.view.Session`.
``session.json`` carries the session as a whole (its best trial, its root
search, its search space), ``config.toml`` the configuration it ran and
``phases/*/session.json`` one row per phase of a staged search. The dict
returned by :func:`session_descriptor` joins the first two under the keys the
figures read.

The interval is the calibration's own rule, restated here because ``display``
may not import ``calibration`` (``optim.cost_margin``): the ``cost_margin`` written in
``[calibration.uncertainty]``, else one mesh cell on a search scored only on
network distances in meters, else five per cent of the best cost. It is the
range of the sampled values whose cost stays within that width of the lowest
cost. A value combined from two roots has none: its width is the spread of
the roots, ``Delta``, and the calibration reports no interval of trials.

It reads the unit of each parameter (the journal bounds first, then the frozen
configuration), the metric of each objective block, the trial the search returned, the
roots record, and the width the calibration reads its interval with. ``display`` may not
import ``calibration``, so that width is restated here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.core.scoring.cost_margin import CostMargin, parse_cost_margin
from hydromodpy.core.scoring.metric_table import METRIC_SENSE, NETWORK_METRIC_NAMES

if TYPE_CHECKING:
    from hydromodpy.display.figures._trial_diagnostics import TrialTable
    from hydromodpy.results.session.view import Session

METRIC_LABELS: dict[str, str] = {
    "nse": "NSE",
    "nse_log": "NSElog",
    "kge": "KGE",
    "nse_delta": "NSE on increments",
    "nse_seasonal": "seasonal NSE",
    "reservoir": "reservoir score",
}
"""How the figures name a score. Whether it rises with the fit is ``METRIC_SENSE``'s to say."""

NETWORK_COSTS: dict[str, str] = {
    "distance_gap": "|D_so - D_os|",
    "distance_mean": "(D_so + D_os) / 2",
}

RESIDUAL_COSTS: dict[str, str] = {"rmse": "RMSE", "mae": "MAE"}

DEFAULT_TOLERANCE = 0.05
"""Width the calibration reads its interval with when nothing wrote one."""


# ---------------------------------------------------------------------------
# the session descriptor
# ---------------------------------------------------------------------------


def session_descriptor(session: Session) -> dict[str, Any]:
    """Return what the session recorded: ``session.json`` and the calibration block.

    The best trial is flattened into ``best_trial`` and ``best_sim_id``, and
    the ``[calibration]`` table of the frozen configuration is under
    ``config``.
    """
    descriptor = session.descriptor
    payload = descriptor.model_dump(mode="json")
    best = descriptor.best
    payload["best_trial"] = best.trial if best is not None else None
    run = descriptor.only_run
    payload["best_sim_id"] = None if run is None else run.sim_id
    payload["config"] = dict(as_mapping(session.config.get("calibration")))
    return payload


def phase_descriptors(session: Session) -> dict[str | None, dict[str, Any]]:
    """Return one descriptor per phase of a staged search, keyed by phase name.

    Each row is the descriptor of the session with the status, the best trial
    and the frozen values of its phase. A search that ran no phase gives the
    descriptor under the key ``None``.
    """
    base = session_descriptor(session)
    phases = session.phases
    if not phases:
        return {None: base}
    rows: dict[str | None, dict[str, Any]] = {}
    for phase in phases:
        best = phase.best
        only = None if best is None or len(best.cases) != 1 else next(iter(best.cases.values()))
        rows[phase.name] = {
            **base,
            "status": phase.status,
            "phase_name": phase.name,
            "phase_index": phase.index,
            "frozen": {name: value.model_dump(mode="json") for name, value in phase.frozen.items()},
            "best_trial": None if best is None else best.trial,
            "best_sim_id": None if only is None else only.sim_id,
        }
    return rows


def frozen_values(session: Session) -> dict[str, dict[str, float]]:
    """Return the values each phase carried from earlier ones, by phase then parameter.

    A phase journals only the parameters it samples, so a figure reads the
    others from here.
    """
    return {
        phase.name: {name: float(frozen.value) for name, frozen in phase.frozen.items()}
        for phase in session.phases
    }


def session_config(descriptor: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the configuration a session recorded, a dict or index text alike."""
    return as_mapping(descriptor.get("config"))


def two_roots(descriptor: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the roots record of a search that closed one root per bound, or None."""
    roots = as_mapping(descriptor.get("root_search")).get("roots")
    return roots if isinstance(roots, Mapping) else None


def returned_row(table: TrialTable, descriptor: Mapping[str, Any]) -> int | None:
    """Return the row of the trial the calibration returned, None when unknown.

    A search combining two roots returns its combined trial, any other search
    the best trial it declared. The index keeps no trial number but the run it
    promoted, so that run is matched to the trial carrying it.
    """
    roots = two_roots(descriptor) or {}
    for trial in (roots.get("combined_trial_id"), descriptor.get("best_trial")):
        number = int_or_none(trial)
        row = None if number is None else table.row_of_trial(number)
        if row is not None:
            return row
    best_sim = text(descriptor.get("best_sim_id"))
    if best_sim is None or "sim_id" not in table.frame.columns:
        return None
    promoted = [
        index
        for index, value in enumerate(table.frame["sim_id"])
        if text(value) is not None and _bare(value) == _bare(best_sim)
    ]
    return promoted[0] if promoted else None


# ---------------------------------------------------------------------------
# the parameters and the cost
# ---------------------------------------------------------------------------


def parameter_declaration(
    table: TrialTable, descriptor: Mapping[str, Any], name: str
) -> dict[str, Any]:
    """Return what the session declared about one parameter: unit, bounds, search space.

    Read from the parameters of the recorded configuration, the search space
    of the journal and the block the first trial wrote, the last one winning.
    """
    space = dict(as_mapping(as_mapping(descriptor.get("bounds")).get(name)))
    if "lower" in space:
        space["bounds"] = [space["lower"], space["upper"]]
    declared = as_mapping(session_config(descriptor).get("parameters")).get(name)
    meta: Mapping[str, Any] = {}
    if "parameters" in table.frame.columns:
        for value in table.frame["parameters"]:
            block = as_mapping(value)
            if block:
                meta = as_mapping(block.get(name))
                break
    return {**as_mapping(declared), **space, **meta}


def declared_units(table: TrialTable, descriptor: Mapping[str, Any], name: str) -> str:
    """Return the unit of one parameter, ``-`` when the session declared none."""
    return text(parameter_declaration(table, descriptor, name).get("units")) or "-"


@dataclass(frozen=True, slots=True)
class CostBlock:
    """One objective block: its metric, its weight and its cost per trial."""

    name: str
    metric: str | None
    weight: float
    normalized: bool
    transformed: bool
    raw: np.ndarray | None
    output: str | None


def cost_blocks(table: TrialTable, config: Mapping[str, Any]) -> list[CostBlock]:
    """Return the objective blocks, as declared, else as the trials name them."""
    declared = [
        block for block in config.get("objective_blocks") or () if isinstance(block, Mapping)
    ]
    if not declared:
        prefixes = sorted(
            {
                str(column)[: -len(".raw_cost")]
                for column in table.frame.columns
                if str(column).endswith(".raw_cost")
            }
        )
        declared = [{"name": name} for name in prefixes]
        if not declared and config.get("objective"):
            declared = [{"name": "", "metric": config.get("objective")}]
    blocks = []
    for block in declared:
        name = str(block.get("name") or "")
        column = f"{name}.raw_cost"
        uses = block.get("uses_outputs") or ()
        blocks.append(
            CostBlock(
                name=name,
                metric=text(block.get("metric")),
                weight=float_or(block.get("weight"), 1.0),
                normalized=bool(block.get("normalize_cost")),
                transformed=str(block.get("cost_transform") or "identity") != "identity",
                raw=table.diagnostic(column) if name and table.has_diagnostic(column) else None,
                output=str(uses[0]) if uses else None,
            )
        )
    return blocks


def rises_with_fit(metric: str | None) -> bool:
    """Whether ``metric`` rises with the fit, so the search minimizes one minus it."""
    return METRIC_SENSE.get(str(metric or "")) == "max"


def score_label(metric: str) -> str:
    """Return how the figures name the score ``metric``."""
    return METRIC_LABELS.get(metric, metric)


def metric_cost(block: CostBlock) -> str:
    """Return how the cost of one block reads, without its unit."""
    metric = block.metric or ""
    if rises_with_fit(metric):
        name = f"1 - {score_label(metric)}"
    elif metric in NETWORK_COSTS:
        name = NETWORK_COSTS[metric]
    elif metric in RESIDUAL_COSTS:
        name = RESIDUAL_COSTS[metric]
    else:
        name = f"cost of {block.name}" if block.name else "cost"
    if block.normalized and not rises_with_fit(metric):
        name = f"{name} / reference scale"
    return name


def metric_unit(block: CostBlock) -> str:
    """Return the unit of the cost of one block."""
    metric = block.metric or ""
    if block.normalized or block.transformed or rises_with_fit(metric):
        return "-"
    if metric in NETWORK_COSTS:
        return "m"
    if metric in RESIDUAL_COSTS:
        return "observed unit"
    return "-"


def cost_label(blocks: Sequence[CostBlock]) -> str:
    """Return the label of the cost: the metric and its unit, never a column name."""
    if len(blocks) == 1:
        block = blocks[0]
        label = f"{metric_cost(block)} ({metric_unit(block)})"
        if block.normalized:
            label = f"Normalized cost: {label}"
        return label
    if not blocks:
        return "Cost (-)"
    return "Weighted cost (-)"


def scored_on_distances(blocks: Sequence[CostBlock]) -> bool:
    """Whether every block is a network distance left in meters."""
    return bool(blocks) and all(
        block.metric in NETWORK_METRIC_NAMES and not block.normalized and not block.transformed
        for block in blocks
    )


def cell_spacing(table: TrialTable) -> float:
    """Return the mesh cell the network criterion measured, NaN when none did."""
    for column in table.frame.columns:
        if str(column).endswith(".cell_spacing_m"):
            values = pd.to_numeric(table.frame[column], errors="coerce").to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            if values.size:
                return float(values[0])
    return float("nan")


# ---------------------------------------------------------------------------
# the interval the calibration reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tolerance:
    """The cost a trial stays under to be told apart from the best by nothing.

    ``threshold`` is None when the calibration reports no interval, and
    ``missing`` then says why, in the words a figure prints. ``text`` names
    the width the way the calibration summary does.
    """

    threshold: float | None
    text: str = ""
    missing: str = ""


@dataclass(frozen=True, slots=True)
class Interval:
    """The range of sampled values whose cost stayed under the threshold."""

    low: float
    high: float
    n_within: int
    n_trials: int


def read_tolerance(
    cost: np.ndarray,
    blocks: Sequence[CostBlock],
    table: TrialTable,
    descriptor: Mapping[str, Any],
) -> Tolerance:
    """Return the width the calibration reads its interval with, applied to ``cost``."""
    roots = two_roots(descriptor)
    if roots is not None:
        delta = float_or(roots.get("delta_log10"), float("nan"))
        spread = f", Delta = {delta:.3g} decade(s)" if np.isfinite(delta) else ""
        return Tolerance(
            None,
            missing=(
                "no interval of trials around a value combined from two roots: "
                f"its width is the spread between them{spread}"
            ),
        )
    finite = cost[np.isfinite(cost)]
    if not finite.size:
        return Tolerance(None, missing="no trial produced a cost")
    best_cost = float(finite.min())
    uncertainty = as_mapping(session_config(descriptor).get("uncertainty"))
    on_distances = scored_on_distances(blocks)
    margin = _written_margin(uncertainty.get("cost_margin"))
    written = float("nan") if margin is None else margin.value
    mode = "absolute" if on_distances else "relative"
    if margin is not None:
        mode = margin.kind
    tolerance = written
    if not np.isfinite(tolerance):
        tolerance = (
            cell_spacing(table) if mode == "absolute" and on_distances else DEFAULT_TOLERANCE
        )
    if not np.isfinite(tolerance):
        return Tolerance(None, missing="the width is one mesh cell, and no trial measured the mesh")
    if mode == "absolute":
        unit = " m" if on_distances else ""
        width = f"{tolerance:.3g}{unit}"
        if on_distances and not np.isfinite(written):
            width = f"one mesh cell ({width})"
        return Tolerance(best_cost + tolerance, text=width)
    if on_distances:
        return Tolerance(
            None,
            missing="a relative width means nothing on network distances in metres",
        )
    if best_cost <= 0.0:
        return Tolerance(
            None,
            missing=(f"a relative width is a fraction of the best cost, which is {best_cost:.4g}"),
        )
    return Tolerance(best_cost * (1.0 + tolerance), text=f"{tolerance:.0%}")


def _written_margin(value: Any) -> CostMargin | None:
    """Return the margin a session wrote, ``None`` when it wrote none or one that does not read."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse_cost_margin(value)
    except ValueError:
        return None


def tolerance_interval(values: np.ndarray, cost: np.ndarray, threshold: float) -> Interval | None:
    """Return the range of sampled values whose cost stayed under ``threshold``."""
    finite = np.isfinite(cost)
    within = finite & np.isfinite(values) & (cost <= threshold)
    if not np.any(within):
        return None
    selected = values[within]
    return Interval(
        low=float(selected.min()),
        high=float(selected.max()),
        n_within=int(selected.size),
        n_trials=int(np.count_nonzero(finite)),
    )


# ---------------------------------------------------------------------------
# small readers
# ---------------------------------------------------------------------------


def _bare(sim_id: Any) -> str:
    """Return a run id as bare lower-case hex, whichever way a table wrote it."""
    return str(sim_id).replace("-", "").lower()


def as_mapping(value: Any) -> Mapping[str, Any]:
    """Read one nested block of the journal, empty when it is not a mapping."""
    return value if isinstance(value, Mapping) else {}


def float_or(value: Any, default: float) -> float:
    """Return ``value`` as a finite float, ``default`` when it is not one."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def search_bounds(value: Any) -> tuple[float, float] | None:
    """Return the declared search bounds as two finite floats, None otherwise."""
    if not isinstance(value, Sequence) or len(value) != 2:
        return None
    low, high = float_or(value[0], np.nan), float_or(value[1], np.nan)
    if not (np.isfinite(low) and np.isfinite(high)) or high <= low:
        return None
    return low, high


def int_or_none(value: Any) -> int | None:
    """Return ``value`` as an integer, None when a table left it empty."""
    number = float_or(value, float("nan"))
    return int(number) if np.isfinite(number) else None


def text(value: Any) -> str | None:
    """Return a non-empty string, None for anything a table left empty."""
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    result = str(value).strip()
    return result or None


__all__ = [
    "search_bounds",
    "frozen_values",
    "phase_descriptors",
    "DEFAULT_TOLERANCE",
    "NETWORK_COSTS",
    "METRIC_LABELS",
    "RESIDUAL_COSTS",
    "CostBlock",
    "Interval",
    "Tolerance",
    "as_mapping",
    "cell_spacing",
    "cost_blocks",
    "cost_label",
    "declared_units",
    "float_or",
    "int_or_none",
    "metric_cost",
    "metric_unit",
    "parameter_declaration",
    "read_tolerance",
    "returned_row",
    "rises_with_fit",
    "score_label",
    "scored_on_distances",
    "session_config",
    "session_descriptor",
    "text",
    "tolerance_interval",
    "two_roots",
]
