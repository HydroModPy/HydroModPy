"""The reads a frame or an overlay makes of a subject, and nothing else.

A frame never touches a ``Run``, a ``RunSet`` or a ``Session``. It calls these
functions, which absorb the traps of the readers: one or two dimensional arrays,
stamps that close their period, steady runs, cell areas held by the mesh. Each read
raises ``FigureNotApplicable`` when the thing is absent, with a sentence that says
what is missing and what the subject holds instead.

Values come back in the stored unit of the variable. ``variables.to_display``
converts them. A later version gives these functions a second family of
implementations for the state of a running simulation, so the signatures below
are the whole contract between a subject and the drawing code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.core.time.instant import TIME_WORDS
from hydromodpy.display.request import (
    COLUMN_SEPARATOR,
    PANEL_FIELDS,
    PARAMETER_TOKEN,
    TRIALS,
    ZONE_PREFIX,
    ZONES,
    Instant,
    PanelRequest,
)
from hydromodpy.display.theme import unit_text
from hydromodpy.results.derive.time_alignment import (
    read_pair,
    run_period_edges,
    time_method_for,
)
from hydromodpy.results.field_registry import (
    BUDGET_GROUP,
    FIELD_REGISTRY,
    NOT_AQUIFER_TERMS,
    REBUILT_FIELDS,
    kind_of,
)
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session


class FigureNotApplicable(DisplayError, ValueError):
    """A figure, or one of its panels, cannot be drawn from this subject.

    The message names the panel and what is missing. The batch renderer skips the
    figure with the message as its reason, whatever ``on_error`` says.
    """


def refuse_fields(frame: str, panel: PanelRequest, used: tuple[str, ...]) -> None:
    """Refuse a panel field that means nothing to ``frame``, naming the frame and the field.

    ``used`` lists the fields the frame reads. A field is set when its value is not
    None, False or an empty list. ``type`` and ``holes`` belong to every frame.
    """
    for field in PANEL_FIELDS:
        if field not in used and field != "type" and _is_set(getattr(panel, field)):
            raise FigureNotApplicable(
                f"A {frame} panel does not take {field!r}. It takes: {', '.join(used)}."
            )


def _is_set(value: Any) -> bool:
    return not (value is None or value is False or (isinstance(value, list) and not value))


def refuse_set(frame: str, panel: PanelRequest, field: str, why: str) -> None:
    """Refuse a field the frame lists but cannot read on this branch, with the reason."""
    if _is_set(getattr(panel, field)):
        raise FigureNotApplicable(f"A {frame} panel does not take {field!r} here: {why}.")


@dataclass(frozen=True, slots=True)
class MeshView:
    """The geometry a frame draws on, one row per mesh face.

    ``faces`` holds node indices padded with -1, so cells may be mixed polygons.
    ``areas`` is in m2 and NaN for a face with fewer than three corners. ``zones``
    maps each name of ``request.ZONES`` to a boolean mask over the faces. ``outlet`` is the
    outlet point in the mesh CRS, None when the run has none. ``interfaces`` is float64
    ``(n_layers + 1, n_faces)`` in m, row 0 the model top and row ``k + 1`` the bottom of
    layer ``k``, None when the mesh holds none.
    """

    centres: np.ndarray
    vertices: np.ndarray
    faces: np.ndarray
    areas: np.ndarray
    zones: dict[str, np.ndarray]
    crs: str | None
    n_layers: int
    outlet: tuple[float, float] | None
    interfaces: np.ndarray | None = None


GEOGRAPHIC_ROLES = ("watershed", "barrier")
"""Persisted vector layers of a run an overlay draws, besides the hydrographic networks."""

DRY_LIMIT = 1.0e20
"""A stored magnitude from this value up is a solver dry or inactive marker, read as NaN."""


MAX_LISTED = 10


def _listed(names: list[str] | tuple[str, ...]) -> str:
    """Return at most ten names, then how many more there are."""
    shown = ", ".join(names[:MAX_LISTED])
    return shown if len(names) <= MAX_LISTED else f"{shown} and {len(names) - MAX_LISTED} more"


def _refuse(run: Run, text: str) -> FigureNotApplicable:
    return FigureNotApplicable(f"Run {run.name!r}: {text}")


def _cube(values: np.ndarray, dims: tuple[str, ...]) -> np.ndarray:
    """Return ``values`` as ``(time, layer, cell)`` float64, a missing axis having length 1."""
    order = [name for name in ("time", "layer", "cell") if name in dims]
    cube = np.transpose(np.asarray(values, dtype=float), [dims.index(name) for name in order])
    for axis, name in enumerate(("time", "layer", "cell")):
        if name not in order:
            cube = np.expand_dims(cube, axis)
    return np.where(np.abs(cube) >= DRY_LIMIT, np.nan, cube)


def _layer_rule(variable: str, layer: int | str | None, run: Run, n_layers: int) -> int | str:
    """Return a layer index or the name of a reduction, after checking it against the run."""
    held = FIELD_REGISTRY.get(variable) or REBUILT_FIELDS.get(variable)
    shape = "" if held is None else held.shape
    if isinstance(layer, bool) or not isinstance(layer, int | str | None):
        raise _refuse(run, f"layer {layer!r} is not an index, 'sum' or 'top'.")
    if isinstance(layer, str) and layer not in ("sum", "top"):
        raise _refuse(run, f"layer {layer!r} is not an index, 'sum' or 'top'.")
    if layer == "sum" and kind_of(variable).layers == "top":
        raise _refuse(
            run, f"{variable!r} is a state, so its layers are not summed. Ask a layer index."
        )
    if isinstance(layer, int):
        if "layer" not in shape:
            raise _refuse(run, f"{variable!r} has no layer axis, so layer {layer} does not exist.")
        if not 0 <= layer < n_layers:
            raise _refuse(run, f"layer {layer} is outside the {n_layers} layers of the run.")
        return layer
    return layer or kind_of(variable).layers or "top"


def _reduce_layers(cube: np.ndarray, rule: int | str) -> np.ndarray:
    """Reduce ``(time, layer, cell)`` to ``(time, cell)`` by an index, ``sum`` or ``top``."""
    if isinstance(rule, int):
        return cube[:, rule, :]
    finite = np.isfinite(cube)
    seen = finite.any(axis=1)
    if rule == "sum":
        return np.where(seen, np.nansum(cube, axis=1), np.nan)
    first = finite.argmax(axis=1)
    top = np.take_along_axis(cube, first[:, None, :], axis=1)[:, 0, :]
    return np.where(seen, top, np.nan)


def read_field(
    run: Run, variable: str, *, time: Instant = "last", layer: int | str | None = None
) -> np.ndarray:
    """Return one value per cell of ``variable`` at one instant, float64, shape ``(n_cells,)``.

    The cell order is the order of ``read_mesh(run).faces``. Values are in the stored
    unit of the registry, inactive and dry cells are NaN. ``time`` names one period
    through ``run.periods``: a date picks the period ``(start, end]`` that holds it, so
    the first day of a month picks the month before, and a static field ignores it. ``layer`` is a layer
    index, ``"sum"`` (NaN-sum over layers, NaN where all are NaN) or ``"top"`` (the
    uppermost finite value). None applies the rule of the quantity kind,
    ``QuantityKind.layers``. A field without a layer axis ignores ``layer`` = None
    and refuses an index.

    Raises ``FigureNotApplicable`` when the run holds no such field, when ``time``
    falls outside the record or the run has no dates for a date, and when ``layer``
    exceeds the layers of the run.
    """
    if not run.has_field(variable):
        raise _refuse(run, f"it holds no field {variable!r}.")
    try:
        raw = run.field(variable, time=time)
    except (ValueError, IndexError) as error:
        if isinstance(time, int) and not isinstance(time, bool):
            raise _refuse(
                run, f"period {time} is outside the {run.n_timesteps} periods of the run."
            ) from error
        raise _refuse(run, f"cannot read {variable!r} at time {time!r}: {error}") from error
    raw = np.asarray(raw)
    cube = _cube(raw, ("cell",) if raw.ndim == 1 else ("layer", "cell"))
    rule = _layer_rule(variable, layer, run, cube.shape[1])
    return _reduce_layers(cube, rule)[0]


def _stamps_to_index(run: Run, stamps: pd.DatetimeIndex | None, n: int, variable: str):
    """Return the output index, the period number of each entry and the period count.

    ``stamps`` are the END stamps of the entries. A mean over the period (a flux)
    is indexed on the period START, and a state valid at the stamp (``time: point``,
    read by ``time_method_for``) on the period END. The index is named ``time``, or
    ``period`` with the period numbers for a run without dates.
    """
    edges = run_period_edges(run)
    if edges is None or stamps is None:
        return pd.RangeIndex(n, name="period"), np.arange(n), n
    numbers = np.clip(edges.searchsorted(stamps, side="left") - 1, 0, len(edges) - 2)
    shift = 1 if time_method_for(variable) == "point" else 0
    return pd.DatetimeIndex(edges[numbers + shift], name="time"), numbers, len(edges) - 1


def _step_of(run: Run, instant: Instant, n_periods: int) -> int:
    if instant == "first":
        return 0
    if instant == "last":
        return n_periods - 1
    if isinstance(instant, int):
        step = instant + n_periods if instant < 0 else instant
        if not 0 <= step < n_periods:
            raise _refuse(run, f"period {instant} is outside the {n_periods} periods of the run.")
        return step
    try:
        return int(run.periods.step_at(instant))
    except ValueError as error:
        raise _refuse(run, f"time {instant!r} is outside the record: {error}") from error


def _clip_window(
    run: Run,
    series: pd.Series,
    numbers: np.ndarray,
    n_periods: int,
    window: tuple[Instant, Instant] | None,
) -> pd.Series:
    """Keep the periods whose START lies in the window, both ends included."""
    if window is None:
        return series
    edges = run_period_edges(run)
    keep = np.ones(len(series), dtype=bool)
    for bound, sign in zip(window, (1, -1), strict=True):
        if isinstance(bound, str) and bound not in TIME_WORDS and edges is not None:
            try:
                starts = edges[numbers]
                keep &= (
                    (starts >= pd.Timestamp(bound)) if sign > 0 else (starts <= pd.Timestamp(bound))
                )
                continue
            except ValueError:
                pass
        keep &= sign * numbers >= sign * _step_of(run, bound, n_periods)
    return series[keep]


def _zone_of(run: Run, station: str) -> str:
    zone = station[len(ZONE_PREFIX) :]
    if zone not in ZONES:
        raise _refuse(run, f"station {station!r} names no zone. Zones are {', '.join(ZONES)}.")
    return zone


def _zone_series(run: Run, variable: str, zone: str) -> tuple[pd.Series, np.ndarray, int]:
    """Return the zone series of a cell field at every period, with its period numbers."""
    descriptor = FIELD_REGISTRY.get(variable) or REBUILT_FIELDS.get(variable)
    if descriptor is None or not descriptor.timed or not run.has_field(variable):
        raise _refuse(run, f"it holds no time-resolved field {variable!r} to sum over a zone.")
    array = run.read(variable)
    cube = _cube(array.values, tuple(str(name) for name in array.dims))
    values = _reduce_layers(cube, _layer_rule(variable, None, run, cube.shape[1]))
    mesh = read_mesh(run)
    mask = mesh.zones[zone]
    cells = values[:, mask]
    seen = np.isfinite(cells)
    if kind_of(variable).extensive:
        result = np.where(seen.any(axis=1), np.nansum(cells, axis=1), np.nan)
    else:
        weights = np.where(seen & np.isfinite(mesh.areas[mask]), mesh.areas[mask], 0.0)
        total = weights.sum(axis=1)
        mean = (np.where(seen, cells, 0.0) * weights).sum(axis=1) / np.where(total > 0, total, 1.0)
        result = np.where(total > 0, mean, np.nan)
    edges = run_period_edges(run)
    count = len(result)
    stamps = edges[1:] if edges is not None and len(edges) - 1 == count else None
    index, numbers, n_periods = _stamps_to_index(run, stamps, count, variable)
    return pd.Series(result, index=index, name=variable), numbers, n_periods


def _station_series(
    run: Run, variable: str, station: str | None
) -> tuple[pd.Series, np.ndarray, int]:
    try:
        raw = run.timeseries(variable, station=station)
    except (KeyError, ValueError) as error:
        held = run.stations(variable)
        if not held:
            raise _refuse(run, f"it holds no series {variable!r}.") from error
        what = "needs a station" if station is None else f"has no station {station!r}"
        raise _refuse(run, f"series {variable!r} {what}. Stations: {_listed(held)}.") from error
    stamps = pd.DatetimeIndex(raw.index)
    index, numbers, n_periods = _stamps_to_index(run, stamps, len(raw), variable)
    series = pd.Series(raw.to_numpy(dtype=float), index=index, name=variable)
    return series, numbers, n_periods


def read_series(
    run: Run,
    variable: str,
    *,
    station: str | None = None,
    window: tuple[Instant, Instant] | None = None,
) -> pd.Series:
    """Return the simulated series of ``variable`` at ``station``, float64, stored unit.

    The index is a naive UTC ``DatetimeIndex`` named ``time``, one entry per period of
    the run: period STARTS for a mean (a flux), period ENDS for a state (``time: point``). A run without dates gets a ``RangeIndex`` of period
    numbers named ``period``. The series is named ``variable``.

    ``station`` is a name ``run.timeseries`` accepts (``lake:1``, a reach, a
    gauge), or a zone of ``request.ZONES`` written ``zone:<name>``. For a zone the variable
    is a cell field read at every period. An ``extensive`` kind (``core/units/kinds.py``) is summed over
    the zone cells and over its layers. Any other kind takes the mean over the zone
    weighted by cell area, so a category of 0 and 1 gives the share of area at 1.
    A ``per_area`` kind stays a sum here, and ``variables.to_display`` divides it by
    the zone area. ``window`` keeps the periods whose START lies between two instants, both included.

    Raises ``FigureNotApplicable`` when the run holds no such series, when
    ``station`` is unknown (the message lists ``run.stations(variable)``), or when
    several stations exist and ``station`` is None.
    """
    if station is not None and station.startswith(ZONE_PREFIX):
        series, numbers, n_periods = _zone_series(run, variable, _zone_of(run, station))
    else:
        series, numbers, n_periods = _station_series(run, variable, station)
    return _clip_window(run, series, numbers, n_periods, window)


def read_column_series(
    run: Run, name: str, *, window: tuple[Instant, Instant] | None = None
) -> pd.Series:
    """Return a column of a run table that holds one row per ``timestep`` as a series.

    The index is that of ``read_series`` for a flux, the period STARTS, and the values are
    as stored. Only the water rows are kept when the table also holds other quantities.

    Raises ``FigureNotApplicable`` when the table has no ``timestep`` or no such column.
    """
    table_name, _, column = name.partition(COLUMN_SEPARATOR)
    table = read_table(run, table_name)
    if column not in table.columns or "timestep" not in table.columns:
        raise _refuse(run, f"table {table_name!r} has no column {column!r} per timestep.")
    if "quantity" in table.columns:
        table = table[table["quantity"] == "water"]
    table = table.sort_values("timestep")
    numbers = table["timestep"].to_numpy(dtype=int)
    edges = run_period_edges(run)
    index = pd.RangeIndex(len(numbers), name="period") if edges is None else edges[numbers]
    if edges is not None:
        index = pd.DatetimeIndex(index, name="time")
    series = pd.Series(table[column].to_numpy(dtype=float), index=index, name=name)
    return _clip_window(run, series, numbers, int(run.n_timesteps), window)


def read_period_seconds(run: Run, index: pd.Index) -> np.ndarray:
    """Return the length in s of the period each entry of a series index stands for.

    The lengths are those of the run periods, from ``run_period_edges``, so unequal
    months and a last short period are exact. ``index`` is a ``read_series`` index,
    period STARTS or period ENDS.

    Raises ``FigureNotApplicable`` for a run without dates.
    """
    edges = run_period_edges(run)
    if edges is None or not isinstance(index, pd.DatetimeIndex):
        raise _refuse(run, "it has no dates, so the length of a period is unknown.")
    lengths = np.diff(edges.values).astype("timedelta64[s]").astype(float)
    place = edges[:-1].get_indexer(index)
    if (place < 0).any():
        place = edges[1:].get_indexer(index)
    if (place < 0).any():
        raise _refuse(run, "a period of the series is not a period of the run.")
    return lengths[place]


def read_observed(run: Run, variable: str, *, station: str | None = None) -> pd.Series:
    """Return the observed record of ``variable`` at ``station`` on the periods of the run.

    The record is the family the descriptor names in ``observed``, else ``variable``.
    It is aligned on the run periods by ``read_pair`` of
    ``results/derive/time_alignment.py``, which applies ``time_method_for`` and the
    first period start. The result has the index of ``read_series`` for the same
    arguments, float64 in the stored unit, NaN for a period without observation,
    and is named ``observed``.

    Raises ``FigureNotApplicable`` when the run holds no observation of that family
    at that station, or when ``station`` is a zone.
    """
    if station is not None and station.startswith(ZONE_PREFIX):
        raise _refuse(run, f"a zone has no observed record, so {station!r} cannot be compared.")
    try:
        pair = read_pair(run, variable, station=station)
    except (KeyError, ValueError) as error:
        raise _refuse(run, f"it holds no observation for {variable!r}: {error}") from error
    index, _, _ = _stamps_to_index(run, pd.DatetimeIndex(pair.index), len(pair), variable)
    observed = pd.Series(pair["observed"].to_numpy(dtype=float), index=index, name="observed")
    if not observed.notna().any():
        raise _refuse(run, f"its observed record of {variable!r} has no value on the run periods.")
    return observed


def read_budget(run: Run, *, station: str | None = None) -> tuple[str, ...]:
    """Return the names of the per-cell budget terms the run kept, in registry order.

    These are the cell fields under ``budget/`` that the run holds, without the mover
    terms of ``NOT_AQUIFER_TERMS``. The station is None or a zone: each term is then
    summed over the zone by ``read_series``. The sign is ``BUDGET_SIGN_RULE``.

    Raises ``FigureNotApplicable`` when the run kept no term, or when ``station`` is
    not a zone. The terms of a lake or a reach are series, asked by name.
    """
    if station is not None:
        if not station.startswith(ZONE_PREFIX):
            raise _refuse(
                run,
                f"the budget is the cell terms summed over a zone, not {station!r}. Write "
                "station='zone:catchment', or list the variables of a lake or a reach by name.",
            )
        _zone_of(run, station)
    held = set(run.array.list_fields())
    terms = tuple(
        name
        for name, descriptor in FIELD_REGISTRY.items()
        if descriptor.zarr_path.startswith(BUDGET_GROUP)
        and name not in NOT_AQUIFER_TERMS
        and name in held
    )
    if not terms:
        raise _refuse(run, "it kept no budget term.")
    return terms


BOUNDS_COLUMNS = ("lower", "upper", "search_space", "units")
NO_UNIT = ("", "-", "1")


def _session_table(session: Session, name: str) -> pd.DataFrame:
    """Return ``trials`` as one row per trial with numbers, or ``bounds`` indexed by parameter."""
    descriptor = session.descriptor
    if name == "bounds":
        rows = {
            key: [bound.lower, bound.upper, bound.search_space, bound.units or ""]
            for key, bound in descriptor.bounds.items()
        }
        frame = pd.DataFrame.from_dict(rows, orient="index", columns=list(BOUNDS_COLUMNS))
        return frame.rename_axis("parameter")
    table = session.table(name)
    if name != TRIALS:
        return table
    table = table.drop_duplicates("trial").reset_index(drop=True)
    labels = _cost_labels(session, table)
    entries = [row if isinstance(row, dict) else {} for row in table["parameters"]]
    names = list(descriptor.bounds)
    names += [key for key in dict.fromkeys(k for row in entries for k in row) if key not in names]
    values = {
        key: [float(row[key]["value"]) if key in row else np.nan for row in entries]
        for key in names
    }
    head = table[["trial", "phase", "status", "cost"]].astype({"cost": float})
    joined = pd.concat([head, pd.DataFrame(values, index=table.index)], axis=1)
    joined.attrs["cost_labels"] = labels
    return joined


def _cost_labels(session: Session, table: pd.DataFrame) -> dict[str, str]:
    """Return what the cost of each phase reads as.

    The session names the cost of its last phase. An earlier phase was scored on
    another output, so it takes the output named by the keys of its ``components``.
    """
    descriptor = session.descriptor
    last = table.loc[table["trial"].idxmax(), "phase"] if len(table) else None
    labels = {}
    for phase, rows in table.groupby("phase", sort=False):
        outputs = [
            key.rsplit(".", 1)[0]
            for key in (rows["components"].iloc[0] or {})
            if key.endswith(".raw_cost")
        ]
        own = f"{outputs[0]} cost" if outputs else str(phase)
        labels[phase] = (descriptor.cost_label or descriptor.cost_name) if phase == last else own
    return labels


def read_table(subject: Run | RunSet | Session, name: str) -> pd.DataFrame:
    """Return the table ``name`` of a run, a run set or a session, as stored.

    A run reads ``run.table(name)``, a run set ``runset.table(name)``. A session reads
    ``trials``, one row per trial with ``trial``, ``phase``, ``status``, ``cost`` and one
    float column per searched parameter holding its value, or ``bounds``, indexed by
    parameter with ``lower``, ``upper``, ``search_space`` and ``units``. Column units are
    those of ``parquet_schemas.py``.

    Raises ``FigureNotApplicable`` when the subject holds no such table, naming the
    tables it holds.
    """
    try:
        if isinstance(subject, Session):
            return _session_table(subject, name)
        return subject.table(name)
    except (FileNotFoundError, KeyError, ValueError) as error:
        label = type(subject).__name__
        if isinstance(getattr(subject, "name", None), str):
            label = f"{label} {subject.name!r}"
        raise FigureNotApplicable(f"{label} holds no table {name!r}: {error}") from error


PHASE_SEPARATOR = "@"
"""``trials.cost@<phase>`` is the cost of the trials of one phase, written by ``render``."""
COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class TrialColumn:
    """One column of the trials of a session, indexed by trial number.

    ``values`` holds the completed trials with a finite value. ``ran`` is the number of
    trials the session ran, all phases included.
    """

    values: pd.Series
    label: str
    log: bool
    ran: int


def trial_phases(session: Session) -> list[str]:
    """Return the phases of a session in the order they ran."""
    return list(dict.fromkeys(read_table(session, TRIALS)["phase"]))


def is_trial_cost(name: str) -> bool:
    """Return True when ``name`` is ``trials.cost``, whatever its phase."""
    return name.split(COLUMN_SEPARATOR, 1)[1].partition(PHASE_SEPARATOR)[0] == "cost"


def read_trial_column(
    session: Session, name: str, scale: str | None = None, only: pd.Index | None = None
) -> TrialColumn:
    """Return the trial column ``trials.<column>``: its values, its label and its axis.

    A trial counts when its status is completed and its value is finite. The cost is
    labelled by the cost of the phase of its trials and is linear. Two phases are scored on
    two outputs, so a cost that spans them is refused: write ``trials.cost@<phase>``, or
    keep the trials of ``only``. A searched parameter takes its name and its stored unit,
    and a log axis when its search space is log. A panel ``scale`` wins. Nothing is
    converted, since the search ran in that unit.
    """
    column, _, phase = name.split(COLUMN_SEPARATOR, 1)[1].partition(PHASE_SEPARATOR)
    table = read_table(session, TRIALS)
    trials = table.set_index("trial")
    held = [key for key in trials.columns if key not in ("phase", "status")]
    if column not in held:
        hint = " Write facet = 'parameter' to draw each one." if column == PARAMETER_TOKEN else ""
        raise FigureNotApplicable(
            f"The trials hold no column {column!r}. They hold: {', '.join(held)}.{hint}"
        )
    descriptor = session.descriptor
    values = trials[column].astype(float)
    keep = np.isfinite(values) & (trials["status"] == COMPLETED)
    if phase:
        keep &= trials["phase"] == phase
    if only is not None:
        keep &= trials.index.isin(only)
    values = values[keep]
    if column == "cost":
        phases = list(dict.fromkeys(trials.loc[values.index, "phase"]))
        if len(phases) > 1:
            raise FigureNotApplicable(
                f"The cost of the phases {', '.join(phases)} is scored on one output each. "
                f"Write {TRIALS}.cost{PHASE_SEPARATOR}<phase>, or draw each parameter with "
                "facet = 'parameter'."
            )
        labels = table.attrs["cost_labels"]
        label = labels[phases[0]] if phases else descriptor.cost_label or descriptor.cost_name
        log = False
    else:
        bound = descriptor.bounds.get(column)
        unit = "" if bound is None else (bound.units or "")
        label = column if unit in NO_UNIT else f"{column} ({unit_text(unit)})"
        log = bound is not None and bound.search_space == "log"
    return TrialColumn(values, label, log if scale is None else scale == "log", len(table))


AGAINST_RUN_FRAMES = ("map",)
"""The frames that subtract a reference run when ``against`` names one."""


@dataclass(frozen=True, slots=True)
class Compared:
    """A run and the reference run it is subtracted from, on one mesh."""

    run: Run
    reference: Run


def compare(run: Run, reference: Run) -> Compared:
    """Return ``run`` against ``reference``, refusing runs that are not on one mesh."""
    if run.sim_id == reference.sim_id:
        raise _refuse(run, "it is its own reference, so the difference is zero.")
    hashes = [read_table(item, "simulation")["mesh_hash"].iloc[0] for item in (run, reference)]
    if hashes[0] != hashes[1]:
        raise _refuse(
            run,
            f"its mesh differs from the mesh of {reference.name!r}, so the two cannot be "
            "subtracted cell by cell.",
        )
    return Compared(run, reference)


def read_network(run: Run, role: str) -> gpd.GeoDataFrame:
    """Return a vector layer of the run in the mesh CRS, one row per feature.

    ``role`` is a hydrographic network role (``reference``,
    ``reference_permanent``, ``generated``, ``simulated_active``) or a persisted
    geographic feature an overlay draws (``watershed``, ``barrier``).
    The frame keeps the columns the store holds, ``geometry`` first.

    Raises ``FigureNotApplicable`` when the run holds no such layer, naming the
    roles it holds.
    """
    held = run.available_hydrographic_network_roles()
    try:
        if role in GEOGRAPHIC_ROLES:
            layer = run.geographic(role)
        else:
            layer = run.hydrographic_network(role)
    except (KeyError, ValueError) as error:
        raise _refuse(
            run,
            f"it holds no layer {role!r}. Network roles held: {', '.join(held) or 'none'}. "
            f"Persisted features an overlay reads: {', '.join(GEOGRAPHIC_ROLES)}.",
        ) from error
    name = layer.geometry.name
    return layer[[name, *[column for column in layer.columns if column != name]]]


def _active_cells(run: Run, n_faces: int) -> np.ndarray:
    if not run.has_field("idomain"):
        return np.ones(n_faces, dtype=bool)
    domain = np.asarray(run.field("idomain"), dtype=float)
    return (domain > 0).any(axis=0) if domain.ndim == 2 else domain > 0


def read_mesh(run: Run) -> MeshView:
    """Return the mesh geometry of the run, its cell areas and its zone masks.

    ``zones["catchment"]`` is ``run.catchment_mask`` when it holds one value per
    face, else every active cell. ``zones["domain"]`` is every active cell.

    Raises ``FigureNotApplicable`` for a run without a mesh, a lumped run for one.
    """
    try:
        mesh = run.mesh
    except RuntimeError as error:
        raise _refuse(run, f"it has no mesh to draw ({error}).") from error
    vertices = np.asarray(mesh.vertices, dtype=float)[:, :2]
    faces = np.asarray(mesh.face_node_connectivity, dtype=int)
    faces = np.where((faces < 0) | (faces >= len(vertices)), -1, faces)
    domain = _active_cells(run, len(faces))
    try:
        mask = np.asarray(run.catchment_mask)
    except (RuntimeError, KeyError, ValueError):
        # No stored basin and no DEM mask: the catchment is the whole domain.
        mask = domain
    catchment = mask.astype(bool) if mask.shape == (len(faces),) else domain
    try:
        outlet = tuple(float(value) for value in run.outlet)
    except RuntimeError:
        outlet = None
    raw = getattr(mesh, "z_interfaces", None)
    interfaces = None if raw is None else np.asarray(raw, dtype=float)
    return MeshView(
        centres=np.asarray(mesh.cell_centers(), dtype=float),
        vertices=vertices,
        faces=faces,
        areas=np.asarray(mesh.cell_areas(), dtype=float),
        zones={"catchment": catchment, "domain": domain},
        crs=mesh.crs,
        n_layers=int(run.n_layers),
        outlet=outlet,
        interfaces=interfaces,
    )
