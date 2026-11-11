"""The linear reservoir: a global flow model on the one-cell catchment mesh.

The adapter solves ``ds/dt = R - s/tau`` exactly, one piece of constant
rate per call, and never reads the store, the configuration or the setup
state. Its option is the time constant of the reservoir; its document may
also hand the pieces of the forcing themselves, cut on the native steps,
through the ``NativeSeries`` of the recharge binder.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd
from pydantic import BaseModel

from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    require_unique_request_ids,
)
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverInputError
from hydromodpy.core.time.window import time_grid_start
from hydromodpy.core.units.quantities import factor_to_m_per_s
from hydromodpy.core.units.time import factor_to_seconds
from hydromodpy.model.forcing.steady_periods import steady_rate
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.observables import (
    ObservableSupport,
    series_observable,
    servable,
    unavailable,
)
from hydromodpy.solver.base.plan import WATER_BUDGET_METRIC, RunSlot, SolverRun
from hydromodpy.solver.linear_reservoir.kernel import run as run_pieces
from hydromodpy.solver.linear_reservoir.options import LinearReservoirOptions

SERIES_FILE = "linear_reservoir_series.csv"
STATE_FILE = "linear_reservoir_final_state.json"


def pieces_of(model: Any) -> tuple[tuple[float, ...], tuple[float, ...], tuple[int, ...]]:
    """The pieces of the forcing, and the period each piece belongs to.

    Returns one rate in m/s, one length in s and one period index per piece.
    The native steps of the recharge carry the pieces when the ``Model``
    holds the series, cut on the periods of the grid; else the periods of
    the grid carry one rate each, and a piece is one period.
    """
    grid = getattr(model.time, "grid", None)
    lengths = getattr(grid, "period_lengths_seconds", None)
    if lengths is None:
        raise SolverInputError(
            "linear_reservoir solves a run of [simulation.time], and the model "
            "carries no time grid."
        )
    lengths = tuple(float(length) for length in lengths)
    series = getattr(model, "native_recharge", None)
    if series is not None:
        return pieces_of_native_series(
            series,
            lengths,
            time_grid_start=time_grid_start(grid),
        )
    recharge = getattr(model, "recharge", None)
    if recharge is None:
        raise SolverInputError(
            "linear_reservoir reads the recharge of the run, and the model carries none."
        )
    values = recharge.values
    if isinstance(values, Mapping):
        ordered = [float(value) for value in values.values()]
    else:
        ordered = [float(value) for value in np.asarray(values, dtype=float).reshape(-1)]
    if len(ordered) != len(lengths):
        raise SolverInputError(
            f"the recharge of the run carries {len(ordered)} rates for "
            f"{len(lengths)} periods of the time grid: one value per period."
        )
    factor = factor_to_m_per_s(str(getattr(recharge, "units", "m/s") or "m/s"))
    rates = tuple(value * factor for value in ordered)
    return rates, lengths, tuple(range(len(lengths)))


def _check_native_series(series: Any) -> None:
    """Refuse a native series the run cannot read: its edges, then its sign.

    The binder hands ``n + 1`` edges, the last drawn by ``record_step`` of
    ``core/time`` and cut to the window, so the run reads the same series
    the model carries.
    """
    values = np.asarray(getattr(series, "values", []), dtype=float)
    starts = getattr(series, "starts", None)
    if starts is not None:
        edges = len(pd.DatetimeIndex(starts))
        if edges != values.size + 1:
            raise SolverInputError(
                "the native recharge of the run carries "
                f"{edges} step edges for {values.size} values: one more edge "
                "than values, cut on the periods of the time grid."
            )
    negative = values.min(initial=0.0)
    if negative < 0.0:
        raise SolverInputError(
            "the recharge of the run goes negative at native step "
            f"{int(np.argmin(values))}, {float(negative)!r} m/s, where the reservoir "
            "stores a deficit that is physical in no reading of the term here. "
            "Clip the series, or name a solver that reads a negative recharge."
        )


def pieces_of_native_series(
    series: Any,
    period_lengths_s: tuple[float, ...],
    *,
    time_grid_start: pd.Timestamp | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[int, ...]]:
    """The pieces the native steps give, cut on the periods of the grid.

    ``starts`` carries the edges of every native step, one more edge than
    values, so the length of a step never has to repeat the one before. A
    step a period boundary crosses is cut there, so every piece belongs to
    one period: the one its end falls in. ``time_grid_start`` is the start
    of the time grid; when given, the native edges lose it first, so the
    compare against the cumulative bounds of the periods reads the same
    clock the grid uses, and not the epoch of the reading.
    """
    _check_native_series(series)
    edges = pd.DatetimeIndex(series.starts)
    rates = tuple(float(rate) for rate in np.asarray(series.values, dtype=float))
    if not period_lengths_s:
        lengths = np.diff(edges.asi8.astype(float) / 1e9)
        return rates, tuple(float(length) for length in lengths), tuple(range(len(rates)))
    if time_grid_start is not None:
        edges = edges - pd.Timestamp(time_grid_start)
    starts_s = edges.asi8.astype(float) / 1e9
    ends_s = starts_s[1:]
    bounds = np.cumsum(np.asarray(period_lengths_s, dtype=float))
    owner = np.minimum(np.searchsorted(bounds, ends_s, side="left"), len(bounds) - 1)
    cut = np.sort(np.unique(np.concatenate(([0.0], bounds))))
    pieces: list[float] = []
    owners: list[int] = []
    for start, end, period in zip(starts_s[:-1], ends_s, owner, strict=True):
        inside = cut[(cut > start) & (cut < end)]
        edges_of_piece = np.concatenate(([start], inside, [end]))
        for left, right in zip(edges_of_piece[:-1], edges_of_piece[1:], strict=True):
            pieces.append(float(right - left))
            owners.append(int(period))
    return rates, tuple(pieces), tuple(owners)


def steady_rate_m_per_s(model: Any) -> float:
    """The recharge rate of the auxiliary steady solve of the run, in m/s.

    The steady variant of the model owns the rule: the duration-weighted mean
    of the rates of the run, or the rate its steady start prescribes. This
    reads that rate and never averages a second time.
    """
    from hydromodpy.model.model import steady_variant

    steady = steady_variant(model)
    series = getattr(steady, "native_recharge", None)
    if series is not None:
        rates, durations, _ = pieces_of_native_series(series, ())
        span = float(np.sum(durations))
        if span <= 0.0:
            return 0.0
        return float(np.sum(np.asarray(rates) * np.asarray(durations))) / span
    recharge = getattr(steady, "recharge", None)
    if recharge is None:
        return 0.0
    values = getattr(recharge, "values", None)
    if isinstance(values, Mapping):
        ordered = [float(value) for value in values.values()]
    elif values is None:
        ordered = []
    else:
        ordered = [float(value) for value in np.asarray(values, dtype=float).reshape(-1)]
    if not ordered:
        return 0.0
    lengths = getattr(getattr(model.time, "grid", None), "period_lengths_seconds", None)
    durations = (
        [float(length) for length in lengths]
        if lengths is not None and len(lengths) == len(ordered)
        else [1.0] * len(ordered)
    )
    rate = steady_rate(ordered, getattr(recharge, "first_clim", "mean"), durations=durations)
    factor = factor_to_m_per_s(str(getattr(recharge, "units", "m/s") or "m/s"))
    return float(np.asarray(rate, dtype=float).reshape(-1)[0]) * factor


@dataclass(frozen=True, slots=True)
class LinearReservoir:
    """The engine one run of the backend solves, frozen for the whole run."""

    tau_seconds: float
    """The time constant the options declare, converted to seconds."""

    area_m2: float
    """The area of the one cell the run reads its recharge on."""

    initial_depth_m: float = 0.0
    """The depth of water the run starts on, the steady state of its recharge."""

    rates_m_per_s: tuple[float, ...] = ()
    """The recharge rate of every piece of the forcing, in m/s."""

    durations_s: tuple[float, ...] = ()
    """The length of every piece, in seconds."""

    owner_of_piece: tuple[int, ...] = ()
    """The period every piece belongs to, which the series of the run follows."""

    period_is_steady: tuple[bool, ...] = ()
    """The flag every period of the run carries: a steady period closes on
    ``tau * R`` (A1) and takes its whole recharge as the rate of that period."""

    period_ends: tuple[pd.Timestamp, ...] = ()
    """The end of every period of the time grid, the stamp of its row."""

    period_lengths_s: tuple[float, ...] = ()
    """The length of every period of the time grid, in seconds."""

    model_name: str = ""
    """The name of the run, the name of its slot."""

    model_folder: str | Path = ""
    """The folder the slot creates the run folder in."""

    full_path: str | Path = ""
    """The folder the run writes its series into, ``model_folder / model_name``."""

    def run(self) -> tuple[np.ndarray, np.ndarray]:
        """Integrate every piece in order, from the state of the run.

        Returns the state at the end of every piece and the depth every
        piece releases at the outlet, in the order the pieces were given. A
        period that ``Model.time`` marks steady closes on the closed form,
        state ``tau * R`` and release ``A * R``, without an integration on
        the pieces of that period (A1). Its reading is mass-closed.
        """
        rates = np.asarray(self.rates_m_per_s, dtype=float)
        durations = np.asarray(self.durations_s, dtype=float)
        steady = tuple(bool(flag) for flag in self.period_is_steady)
        if self.period_is_steady and all(steady):
            closed = self.tau_seconds * rates
            released = self.area_m2 * rates * durations
            return closed, released / self.area_m2

        solved = run_pieces(rates, durations, self.initial_depth_m, self.tau_seconds, self.area_m2)
        return solved.stored_m, solved.released_m3 / self.area_m2


class LinearReservoirFlowAdapter:
    """Solve the flow of one cell exactly, at the steps the forcing carries."""

    name: ClassVar[str] = "linear_reservoir"
    process_type: ClassVar[str] = "flow"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset({"catchment"})
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = ("discharge", "reservoir_storage", "budgets")
    reads: ClassVar[tuple[tuple[str, str], ...]] = ()
    supports: ClassVar[frozenset[str]] = frozenset({"recharge", "steady_start"})
    options: ClassVar[type[BaseModel] | None] = LinearReservoirOptions
    category: ClassVar[str] = "lumped"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = ()

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """Refuse a run the backend cannot solve, before anything is built."""
        cells = getattr(getattr(model, "geometry", None), "cells", None)
        n_cells = getattr(cells, "n_cells", None)
        if n_cells is None:
            raise SolverInputError(
                "A linear reservoir solves one cell, and the model carries no "
                "planar cell mesh. Name a mesh engine that builds one."
            )
        if n_cells != 1:
            raise SolverInputError(
                "A linear reservoir solves one cell, and the mesh builds "
                f"{n_cells}. Name a mesh engine that builds one."
            )
        table = LinearReservoirOptions() if options is None else options
        if table.time_constant is None:
            raise SolverInputError(
                "[solver.linear_reservoir] time_constant is required: the memory "
                "of the reservoir belongs to the site, so the backend sets no "
                "default."
            )
        series = getattr(model, "native_recharge", None)
        if series is not None:
            _check_native_series(series)

    def build(
        self,
        model: Any,
        options: BaseModel | None,
        slot: RunSlot,
        upstream: tuple[SolverRun, ...] = (),
    ) -> SolverRun:
        """Build the engine of the run in memory, under ``slot``."""
        self.validate(model, options, slot)
        return self.build_engine(model, slot, options)

    def build_engine(
        self, model: Any, slot: RunSlot, options: BaseModel | None = None
    ) -> SolverRun:
        """Build the engine of one run, in memory, under ``slot``."""
        table = LinearReservoirOptions() if options is None else options
        self.validate(model, table, slot)
        tau_seconds = table.time_constant * factor_to_seconds("day")
        area_m2 = float(np.sum(model.geometry.cells.geometry.areas))
        rates, durations, owners = pieces_of(model)
        lengths = tuple(float(length) for length in model.time.grid.period_lengths_seconds)
        from hydromodpy.model.forcing.steady_periods import steady_flags

        engine = LinearReservoir(
            tau_seconds=tau_seconds,
            area_m2=area_m2,
            initial_depth_m=steady_rate_m_per_s(model) * tau_seconds,
            rates_m_per_s=rates,
            durations_s=durations,
            owner_of_piece=owners,
            period_is_steady=tuple(
                bool(flag)
                for flag in steady_flags(
                    nper=len(lengths),
                    flow_regime=model.time.regime,
                    first_period_steady=model.time.first_period_steady,
                )
            ),
            period_ends=period_ends_from(time_grid_start(model.time.grid), lengths),
            period_lengths_s=lengths,
            model_name=slot.name,
            model_folder=slot.folder,
            full_path=slot.directory,
        )
        return SolverRun(slot=slot, model=model, options=table, solver_model=engine)

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Solve the built run in its slot, and write the series of the periods."""
        engine = solver_run.solver_model
        if engine is None:
            raise SolverInputError(
                "A linear reservoir run solves the engine its build produced, "
                "and the run carries none: build it again."
            )
        directory = Path(solver_run.slot.directory)
        directory.mkdir(parents=True, exist_ok=True)
        states, drained_depths = engine.run()
        frame = _series_frame(engine, states, drained_depths)
        frame.to_csv(directory / SERIES_FILE, index_label="time")
        closure_m3 = _mass_closed_m3(engine, states, drained_depths)
        (directory / STATE_FILE).write_text(
            json.dumps(
                {
                    "time": str(frame.index[-1]) if frame.index.size else None,
                    "reservoir_storage_m": float(states[-1]),
                    "mass_closed_m3": closure_m3,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return replace(
            solver_run,
            output_dir=directory,
            written=True,
            solved=True,
            metrics={
                **solver_run.metrics,
                WATER_BUDGET_METRIC: _percent_discrepancy(engine, closure_m3),
                "reservoir_mass_closed_m3": closure_m3,
            },
        )

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the series and the budget rows of a solved run into its store."""
        from hydromodpy.solver.linear_reservoir.extractor import LinearReservoirExtractor

        LinearReservoirExtractor().extract(solver_run, store, retention)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the working files of the solve, which the store carries now."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)

    def observables(
        self,
        solver_run: SolverRun,
        requests: Sequence[ObservableRequest],
        *,
        time_index: pd.DatetimeIndex | None = None,
    ) -> dict[str, ObservableResult]:
        """Read the requested observables of one solved run, from its series file."""
        del time_index
        if not requests:
            return {}
        require_unique_request_ids(requests)
        output_dir = solver_run.output_dir
        if output_dir is None:
            raise ObservableNotAvailableError(
                f"No solver output recorded for run {solver_run.slot.name!r}."
            )
        frame = pd.read_csv(Path(output_dir) / SERIES_FILE, index_col="time", parse_dates=True)
        served: dict[str, ObservableResult] = {}
        for request in requests:
            if request.support == "cell":
                # One cell is the whole domain here: a request that names the
                # cell reads the same series a caller asking the domain reads.
                if tuple(request.cell or ()) != (0, 0, 0):
                    raise ObservableNotAvailableError(
                        "The linear reservoir serves one cell, and request "
                        f"{request.id!r} asks cell {request.cell!r}."
                    )
            elif request.support != "domain":
                raise ObservableNotAvailableError(
                    "The linear reservoir serves every observable it has on the "
                    f"whole domain, and {request.id!r} asks support {request.support!r}."
                )
            if request.name == "discharge":
                served[request.id] = series_observable(
                    request, frame["discharge_m3_s"], units="m3 s-1"
                )
            elif request.name == "reservoir_storage":
                served[request.id] = series_observable(
                    request, frame["reservoir_storage_m"], units="m"
                )
            else:
                raise ObservableNotAvailableError(
                    f"The linear reservoir does not produce observable {request.name!r}."
                )
        return served

    def declared_observables(self, active: frozenset[str]) -> tuple[ObservableSupport, ...]:
        """Say what a run of the backend serves, and what stays out of reach.

        ``active`` would say what the document activates. Nothing a run of
        the backend produces depends on it: the reservoir serves its whole
        answer at the station of the catchment, or nothing.
        """
        return (
            servable(
                "discharge", "the mean rate the cell sent to the outlet, one value per period"
            ),
            servable(
                "reservoir_storage",
                "the depth of water the state holds, at the end of every period",
            ),
            unavailable(
                "head",
                "the reservoir stores one depth of water on the cell, and builds no head "
                "field to read at a cell.",
            ),
            unavailable(
                "release_flux",
                "the reservoir sends its water to the outlet and serves it as discharge; it "
                "writes no per-cell saturation excess for the stream-network criterion to read.",
            ),
            unavailable(
                "stage",
                "the reservoir builds no lake, so there is no lake state to read.",
            ),
            unavailable(
                "routed_discharge",
                "the reservoir routes no stream reaches, so no reach outflow exists.",
            ),
        )

    def top_active_layer(self, solver_run: SolverRun, row: int, col: int) -> int | None:
        """Return 0: the reservoir has one layer, so every column starts at layer 0."""
        if solver_run.solver_model is None:
            return None
        if (row, col) != (0, 0):
            raise ValueError(f"the reservoir holds one cell, (0, 0), and ({row}, {col}) is none.")
        return 0

    def locate_cell(self, solver_run: SolverRun, x: float, y: float) -> tuple[int, int, int] | None:
        """Return ``(0, 0, 0)``, the one cell of the run, or ``None`` without a solved engine.

        The port gives a point outside every cell the nearest center, and the
        one cell is the nearest to every point, so the answer reads no polygon.
        """
        if solver_run.solver_model is None:
            return None
        return (0, 0, 0)


def period_ends_from(start: str | None, lengths: tuple[float, ...]):
    """The stamp of every row of the series, from the start of the time grid.

    A grid that dates nothing gives the period ids as integers, so the series
    of the run still reads one row per period, in their order.
    """
    if start is None:
        return tuple(range(len(lengths)))
    clock = pd.Timestamp(start)
    ends = np.cumsum([0.0, *map(float, lengths)])
    return tuple(clock + pd.Timedelta(seconds=float(offset)) for offset in ends[1:])


def _series_frame(
    engine: LinearReservoir, states: np.ndarray, drained_depths: np.ndarray
) -> pd.DataFrame:
    """One row per period of the run: its mean rates and the state at its end.

    The discharge of a period is the volume its pieces sent out, divided by
    the length of the period; the storage is the state at its end.
    """
    owners = np.asarray(engine.owner_of_piece, dtype=int)
    states = np.asarray(states, dtype=float)
    drained = np.asarray(drained_depths, dtype=float)
    lengths = np.asarray(engine.period_lengths_s, dtype=float)
    rates = np.asarray(engine.rates_m_per_s, dtype=float)
    durations = np.asarray(engine.durations_s, dtype=float)
    received = np.zeros(lengths.size)
    released = np.zeros(lengths.size)
    last = np.full(lengths.size, -1)
    for piece, period in enumerate(owners):
        received[period] += rates[piece] * durations[piece]
        released[period] += drained[piece]
        last[period] = piece
    ends = engine.period_ends
    index = (
        pd.DatetimeIndex(ends)
        if ends and isinstance(ends[0], pd.Timestamp)
        else pd.RangeIndex(lengths.size)
    )
    return pd.DataFrame(
        {
            "recharge_m_s": received / lengths,
            "discharge_m3_s": released * engine.area_m2 / lengths,
            "reservoir_storage_m": states[last],
        },
        index=index,
        columns=("recharge_m_s", "discharge_m3_s", "reservoir_storage_m"),
    )


def _mass_closed_m3(
    engine: LinearReservoir, states: np.ndarray, drained_depths: np.ndarray
) -> float:
    """What the water budget of the whole run leaves open, in m3.

    What fell and what the run held, minus what left and what it keeps, is
    zero when every piece closes on the mass, which it does by construction.
    """
    rates = np.asarray(engine.rates_m_per_s, dtype=float)
    durations = np.asarray(engine.durations_s, dtype=float)
    inflow_depth = engine.initial_depth_m + float(np.sum(rates * durations))
    out_depth = float(np.sum(drained_depths)) + float(np.asarray(states)[-1])
    return (inflow_depth - out_depth) * engine.area_m2


def _percent_discrepancy(engine: LinearReservoir, closure_m3: float) -> float:
    """The closure of the budget as the other solvers report it, in percent."""
    rates = np.asarray(engine.rates_m_per_s, dtype=float)
    durations = np.asarray(engine.durations_s, dtype=float)
    through = float(np.sum(rates * durations)) * engine.area_m2
    scale = max(abs(through), abs(engine.initial_depth_m * engine.area_m2))
    if scale <= 0.0:
        return 0.0
    return 100.0 * closure_m3 / scale


__all__ = [
    "SERIES_FILE",
    "STATE_FILE",
    "LinearReservoir",
    "LinearReservoirFlowAdapter",
    "pieces_of",
    "pieces_of_native_series",
    "steady_rate_m_per_s",
]
