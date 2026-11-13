"""The reads a frame or an overlay makes of a subject.

A frame never touches a ``Run``, a ``RunSet`` or a ``Session``. It calls these
functions, which hide the stored layouts: one or two dimensional arrays, stamps that
close their period, steady runs, cell areas held by the mesh. A read raises
``FigureNotApplicable`` with a sentence that says what is missing. Values come back in
the stored unit of the variable, and ``variables.to_display`` converts them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.core.fields.nodata import SENTINEL_ABS_THRESHOLD
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
    budget_terms,
)
from hydromodpy.display.theme import unit_text
from hydromodpy.results.derive.time_alignment import (
    read_pair,
    run_period_edges,
    time_method_for,
)
from hydromodpy.results.field_registry import (
    FIELD_REGISTRY,
    REBUILT_FIELDS,
    kind_of,
)
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session


class FigureNotApplicable(DisplayError, ValueError):
    """A figure, or one of its panels, cannot be drawn from this subject."""


def refuse_fields(frame: str, panel: PanelRequest, used: tuple[str, ...]) -> None:
    """Refuse a set panel field that is not in ``used``. ``type`` belongs to every frame."""
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
    ``areas`` is in m2, NaN for a face with fewer than three corners. ``zones`` maps each
    zone name to a boolean mask over the faces. ``interfaces`` is ``(n_layers + 1,
    n_faces)`` in m, row 0 the model top and row ``k + 1`` the bottom of layer ``k``.
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


def _refuse(run: Run, text: str) -> FigureNotApplicable:
    return FigureNotApplicable(f"Run {run.name!r}: {text}")


def _cube(values: np.ndarray, dims: tuple[str, ...]) -> np.ndarray:
    """Return ``values`` as ``(time, layer, cell)`` float64, a missing axis having length 1."""
    order = [name for name in ("time", "layer", "cell") if name in dims]
    cube = np.transpose(np.asarray(values, dtype=float), [dims.index(name) for name in order])
    for axis, name in enumerate(("time", "layer", "cell")):
        if name not in order:
            cube = np.expand_dims(cube, axis)
    return np.where(np.abs(cube) >= SENTINEL_ABS_THRESHOLD, np.nan, cube)


def _layer_rule(variable: str, layer: int | str | None, run: Run, n_layers: int) -> int | str:
    """Return a layer index or the name of a reduction, after checking it against the run."""
    held = FIELD_REGISTRY.get(variable) or REBUILT_FIELDS.get(variable)
    shape = "" if held is None else held.shape
    if (
        isinstance(layer, bool)
        or not isinstance(layer, int | str | None)
        or (isinstance(layer, str) and layer not in ("sum", "top"))
    ):
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
    """Return ``variable`` at one instant, one float64 value per cell in the stored unit.

    Inactive and dry cells are NaN. A date picks the period ``(start, end]`` that holds
    it, so the first day of a month picks the month before. ``layer`` is an index,
    ``"sum"`` or ``"top"`` (the uppermost finite value). None takes the rule of the
    quantity kind.
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

    ``stamps`` are the END stamps of the entries. A flux is indexed on the period START
    and a state (``time: point``) on the period END. The index is named ``time``, or
    ``period`` for a run without dates.
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
            starts = edges[numbers]
            keep &= (starts >= pd.Timestamp(bound)) if sign > 0 else (starts <= pd.Timestamp(bound))
        else:
            keep &= sign * numbers >= sign * _step_of(run, bound, n_periods)
    return series[keep]


def _zone_series(run: Run, variable: str, station: str) -> tuple[pd.Series, np.ndarray, int]:
    """Return the zone series of a cell field at every period, with its period numbers."""
    zone = station[len(ZONE_PREFIX) :]
    if zone not in ZONES:
        raise _refuse(run, f"station {station!r} names no zone. Zones are {', '.join(ZONES)}.")
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
        shown = ", ".join(held[:10]) + (f" and {len(held) - 10} more" if len(held) > 10 else "")
        raise _refuse(run, f"series {variable!r} {what}. Stations: {shown}.") from error
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

    The index is one entry per period, named ``time``: period STARTS for a flux, period
    ENDS for a state (``time: point``), or ``period`` numbers for a run without dates.
    ``station`` is a name of ``run.timeseries`` or a zone written ``zone:<name>``. A zone
    sums an extensive quantity over its cells and layers, and takes the mean weighted by
    cell area for any other. ``window`` keeps the periods whose START lies between two
    instants, both included.
    """
    if station is not None and station.startswith(ZONE_PREFIX):
        series, numbers, n_periods = _zone_series(run, variable, station)
    else:
        series, numbers, n_periods = _station_series(run, variable, station)
    return _clip_window(run, series, numbers, n_periods, window)


def read_column_series(
    run: Run, name: str, *, window: tuple[Instant, Instant] | None = None
) -> pd.Series:
    """Return a per-``timestep`` column of a run table as a series on the period STARTS."""
    table_name, _, column = name.partition(COLUMN_SEPARATOR)
    table = read_table(run, table_name)
    if column not in table.columns or "timestep" not in table.columns:
        raise _refuse(run, f"table {table_name!r} has no column {column!r} per timestep.")
    if "quantity" in table.columns:
        table = table[table["quantity"] == "water"]
    table = table.sort_values("timestep")
    numbers = table["timestep"].to_numpy(dtype=int)
    edges = run_period_edges(run)
    index = (
        pd.RangeIndex(len(numbers), name="period")
        if edges is None
        else pd.DatetimeIndex(edges[numbers], name="time")
    )
    series = pd.Series(table[column].to_numpy(dtype=float), index=index, name=name)
    return _clip_window(run, series, numbers, int(run.n_timesteps), window)


def read_period_seconds(run: Run, index: pd.Index) -> np.ndarray:
    """Return the length in s of the period each entry of a ``read_series`` index stands for."""
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
    """Return the observed record of ``variable`` at ``station`` on the index of ``read_series``.

    ``read_pair`` aligns it the way calibration scores it. NaN marks a period without
    observation. A zone has no observed record.
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


def read_budget(run: Run) -> tuple[str, ...]:
    """Return the per-cell budget terms the run kept, in registry order."""
    held = set(run.array.list_fields())
    terms = tuple(name for name in budget_terms() if name in held)
    if not terms:
        raise _refuse(run, "it kept no budget term.")
    return terms


BOUNDS_COLUMNS = ("lower", "upper", "search_space", "units")
NO_UNIT = ("", "-", "1")


def _session_table(session: Session, name: str) -> pd.DataFrame:
    """Return ``trials`` as one row per trial, or ``bounds`` indexed by parameter."""
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
    """Return what the cost of each phase reads as: the session names its last phase."""
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

    A session holds ``trials`` (one row per trial, one column per searched parameter)
    and ``bounds`` (indexed by parameter). Column units are those of ``parquet_schemas.py``.
    """
    try:
        if isinstance(subject, Session):
            return _session_table(subject, name)
        return subject.table(name)
    except (FileNotFoundError, KeyError, ValueError) as error:
        name_of = getattr(subject, "name", None)
        label = type(subject).__name__ + (f" {name_of!r}" if isinstance(name_of, str) else "")
        raise FigureNotApplicable(f"{label} holds no table {name!r}: {error}") from error


PHASE_SEPARATOR = "@"
"""``trials.cost@<phase>`` is the cost of the trials of one phase, written by ``render``."""
COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class TrialColumn:
    """One column of the trials of a session, indexed by trial number, with ``ran`` trials run."""

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
    """Return the trial column ``trials.<column>`` with its label and its axis.

    A trial counts when it is completed and its value is finite. A cost that spans two
    phases is refused, since each was scored on its own output. Nothing is converted,
    since the search ran in the stored unit. A panel ``scale`` wins over the search space.
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
    """Return a network role or a ``GEOGRAPHIC_ROLES`` layer in the mesh CRS, ``geometry`` first."""
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
    """Return the mesh of the run with its cell areas and zone masks.

    ``zones["catchment"]`` is ``run.catchment_mask`` when it holds one value per face,
    else every active cell. ``zones["domain"]`` is every active cell.
    """
    try:
        mesh = run.mesh
    except (RuntimeError, KeyError) as error:
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
    return MeshView(
        centres=np.asarray(mesh.cell_centers(), dtype=float),
        vertices=vertices,
        faces=faces,
        areas=np.asarray(mesh.cell_areas(), dtype=float),
        zones={"catchment": catchment, "domain": domain},
        crs=mesh.crs,
        n_layers=int(run.n_layers),
        outlet=outlet,
        interfaces=np.asarray(mesh.z_interfaces, dtype=float),
    )
