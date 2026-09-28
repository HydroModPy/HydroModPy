"""What a calibration session says about itself, read once for every figure.

The trials say what was tried. The session says what was asked and what came
back: the unit of each parameter, the metric of each objective block, the
trial the calibration returned, the record of a root search, and the width
the calibration reads its interval with. Every calibration figure has to agree
on those, so they are read here and nowhere else.

The index row of a session carries part of it: no trial number, no root
search record, no search space. ``session.json`` carries all of it, so a
figure drawn from a run completes the row from the journal of the project
that holds the run. A run-shaped carrier with no project behind it, such as
the one the calibration report builds, keeps what it carries.

The interval is the calibration's own rule, restated here because ``display``
may not import ``calibration`` (``optim.tolerance``): the width written in
``[calibration.uncertainty]``, else one mesh cell on a search scored only on
network distances in metres, else five per cent of the best cost. It is the
range of the sampled values whose cost stays within that width of the lowest
cost. A value combined from two roots has none: its width is the spread of
the roots, ``Delta``, and the calibration reports no interval of trials.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.results.calibration_trials import calibration_sessions, calibration_trials
from hydromodpy.results.session_journal import find_session_dir, read_descriptor

if TYPE_CHECKING:
    from hydromodpy.display.figures._trial_diagnostics import TrialTable
    from hydromodpy.results.run import Run

NETWORK_METRICS: frozenset[str] = frozenset({"distance_gap", "distance_mean"})
"""Metrics scored on a network, in metres unless normalised."""

EFFICIENCIES: dict[str, str] = {
    "nse": "NSE",
    "nse_log": "NSElog",
    "kge": "KGE",
    "nse_delta": "NSE on increments",
    "nse_seasonal": "seasonal NSE",
    "reservoir": "reservoir score",
}
"""Scores that rise with agreement: the search minimises one minus the score."""

NETWORK_COSTS: dict[str, str] = {
    "distance_gap": "|D_so - D_os|",
    "distance_mean": "(D_so + D_os) / 2",
}

RESIDUAL_COSTS: dict[str, str] = {"rmse": "RMSE", "mae": "MAE"}

DEFAULT_TOLERANCE = 0.05
"""Width the calibration reads its interval with when nothing wrote one."""


# ---------------------------------------------------------------------------
# the session row, completed by its journal
# ---------------------------------------------------------------------------


def session_rows(sim: Run) -> dict[str, dict[str, Any]]:
    """Return the index rows of the sessions reachable from a run, keyed by bare id."""
    frame = calibration_sessions(sim)
    if frame.empty or "session_id" not in frame.columns:
        return {}
    return {bare_id(row["session_id"]): dict(row) for row in frame.to_dict("records")}


def chosen_session(sim: Run, session_id: str | None) -> str | None:
    """Return the session a figure draws, the latest one the run belongs to.

    A run reused from the cache can belong to several sessions of the same
    phase. The one that started last is the calibration the run was promoted
    from; drawing them all together would mix two searches on one axis.
    """
    if session_id is not None:
        return str(session_id)
    frame = calibration_trials(sim)
    if "session_id" not in frame.columns:
        return None
    seen = list(dict.fromkeys(str(value) for value in frame["session_id"] if text(value)))
    if len(seen) <= 1:
        return seen[0] if seen else None
    rows = session_rows(sim)
    started = {sid: str(rows.get(bare_id(sid), {}).get("started_at") or "") for sid in seen}
    return max(seen, key=lambda sid: (started[sid], seen.index(sid)))


def session_descriptor(sim: Run, session_id: Any) -> dict[str, Any]:
    """Return what one session recorded: its index row, completed by its journal."""
    if session_id is None:
        return {}
    row = session_rows(sim).get(bare_id(session_id), {})
    return completed_descriptor(sim, session_id, row)


def completed_descriptor(sim: Run, session_id: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``row`` with every key the session journal holds a value for.

    The journal is written first and the index mirrors it, so a value the
    journal holds wins. The session id keeps the spelling of the row, which
    is the one the trials name.
    """
    merged = dict(row)
    for key, value in journal_descriptor(sim, session_id).items():
        if key != "session_id" and value is not None:
            merged[key] = value
    return merged


def journal_descriptor(sim: Run, session_id: Any) -> dict[str, Any]:
    """Return ``session.json`` of one session, empty when no journal is reachable."""
    root = project_root(sim)
    if root is None or session_id is None:
        return {}
    directory = find_session_dir(root, str(session_id))
    if directory is None:
        return {}
    try:
        return asdict(read_descriptor(directory))
    except (OSError, ValueError):
        # A journal that no longer reads leaves the index row to speak alone.
        return {}


def project_root(sim: Run) -> Path | None:
    """Return the project that holds a run, as its config snapshot names it.

    A run re-anchors ``[workspace] project_root`` on the project it is read
    from, so a copied or moved project reads its own journals.
    """
    snapshot = getattr(sim, "config_snapshot", None)
    workspace = snapshot.get("workspace") if isinstance(snapshot, Mapping) else None
    root = text(workspace.get("project_root")) if isinstance(workspace, Mapping) else None
    return Path(root) if root is not None else None


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
        if text(value) is not None and bare_id(value) == bare_id(best_sim)
    ]
    return promoted[0] if promoted else None


# ---------------------------------------------------------------------------
# the parameters and the cost
# ---------------------------------------------------------------------------


def parameter_declaration(
    table: TrialTable, descriptor: Mapping[str, Any], name: str
) -> dict[str, Any]:
    """Return what the session declared about one parameter: unit, bounds, transform.

    Read from the search space of the journal, the parameters of the recorded
    configuration and the block the first trial wrote, the last one winning.
    """
    space = as_mapping(descriptor.get("search_space")).get(name)
    declared = as_mapping(session_config(descriptor).get("parameters")).get(name)
    meta: Mapping[str, Any] = {}
    if "parameters" in table.frame.columns:
        for value in table.frame["parameters"]:
            block = as_mapping(value)
            if block:
                meta = as_mapping(block.get(name))
                break
    return {**as_mapping(space), **as_mapping(declared), **meta}


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
                transformed=str(block.get("transform") or "identity") != "identity",
                raw=table.diagnostic(column) if name and table.has_diagnostic(column) else None,
                output=str(uses[0]) if uses else None,
            )
        )
    return blocks


def metric_cost(block: CostBlock) -> str:
    """Return how the cost of one block reads, without its unit."""
    metric = block.metric or ""
    if metric in EFFICIENCIES:
        name = f"1 - {EFFICIENCIES[metric]}"
    elif metric in NETWORK_COSTS:
        name = NETWORK_COSTS[metric]
    elif metric in RESIDUAL_COSTS:
        name = RESIDUAL_COSTS[metric]
    else:
        name = f"cost of {block.name}" if block.name else "cost"
    if block.normalized and metric not in EFFICIENCIES:
        name = f"{name} / reference scale"
    return name


def metric_unit(block: CostBlock) -> str:
    """Return the unit of the cost of one block."""
    metric = block.metric or ""
    if block.normalized or block.transformed or metric in EFFICIENCIES:
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
            label = f"Normalised cost: {label}"
        return label
    if not blocks:
        return "Cost (-)"
    return "Weighted cost (-)"


def scored_on_distances(blocks: Sequence[CostBlock]) -> bool:
    """Whether every block is a network distance left in metres."""
    return bool(blocks) and all(
        block.metric in NETWORK_METRICS and not block.normalized and not block.transformed
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
    written = float_or(uncertainty.get("tolerance"), float("nan"))
    mode = text(uncertainty.get("mode")) or ("absolute" if on_distances else "relative")
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


def bare_id(session_id: Any) -> str:
    """Return a session id as bare hex, whichever way a table wrote it."""
    return str(session_id).replace("-", "").lower()


def as_mapping(value: Any) -> Mapping[str, Any]:
    """Read one nested block, a dict in the journal and JSON text in the index."""
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def float_or(value: Any, default: float) -> float:
    """Return ``value`` as a finite float, ``default`` when it is not one."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


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
    "DEFAULT_TOLERANCE",
    "EFFICIENCIES",
    "NETWORK_COSTS",
    "NETWORK_METRICS",
    "RESIDUAL_COSTS",
    "CostBlock",
    "Interval",
    "Tolerance",
    "as_mapping",
    "bare_id",
    "cell_spacing",
    "chosen_session",
    "completed_descriptor",
    "cost_blocks",
    "cost_label",
    "declared_units",
    "float_or",
    "int_or_none",
    "journal_descriptor",
    "metric_cost",
    "metric_unit",
    "parameter_declaration",
    "project_root",
    "read_tolerance",
    "returned_row",
    "scored_on_distances",
    "session_config",
    "session_descriptor",
    "session_rows",
    "text",
    "tolerance_interval",
    "two_roots",
]
