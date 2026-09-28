"""The network criterion settings a run was scored with, read back from its sealed config.

A figure of the stream network redraws the partition a trial scored. The trial
cut it by the settings of its ``[calibration.outputs.<n>]`` network output: the
seepage threshold, the neighbour graph, the rasterisation of the map, the
weighting, the state it read and, in the two-bound mode, the extent rules and
the years its ``scoring_window`` holds. A figure drawn with the defaults
instead shows another partition than the one the numbers describe, so this
module reads those settings from the configuration the run sealed.

The window is the one of the phase the run was scored in, when that phase
declares one: a phase's ``scoring_window`` replaces the calibration's, and
the protocol writes its default spin-up window on its transient stage. The
phase is the one of the calibration session the run's trial belongs to.

The results layer may not import the calibration layer, so the output is read
as the plain mapping the snapshot holds, with the defaults of
:mod:`hydromodpy.core.stream_criterion_defaults` and
:mod:`hydromodpy.core.stream_extent` where a key is absent. A run that sealed
no network output reads the defaults, and says so.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_criterion_defaults import (
    STREAM_CRITERION_DEFAULTS,
    ObservedRasterization,
)
from hydromodpy.core.stream_extent import DEFAULT_VISIBLE_FLOW, parse_visible_flow
from hydromodpy.core.stream_snap import SnapStreamsConfig
from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.core.time.selection import TimeSelectionError, resolve_state
from hydromodpy.core.units.length import parse_to_m
from hydromodpy.results.calibration_trials import calibration_sessions, calibration_trials
from hydromodpy.results.derive.snapped_network import snap_settings_of_run

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

__all__ = (
    "DEFAULT_CRITERION_SETTINGS",
    "DEFAULT_EXTENT_RULES",
    "NetworkCriterionSettings",
    "NetworkExtentRules",
    "ScoringWindow",
    "network_criterion_settings",
    "network_outputs_of_run",
)

_NETWORK_SUPPORT = "network"
_RASTERIZATIONS = ("crossing", "touch")
_WEIGHTINGS = ("cell", "area")
_TIMESTEP_OF_TIME = {"last": -1, "first": 0}
"""The state a single-state output reads, as the timestep index a run field takes."""

_MISSING_SNAPSHOT = (KeyError, ValueError, FileNotFoundError, RuntimeError)
_NO_TIME_AXIS = (AttributeError, KeyError, ValueError, FileNotFoundError, RuntimeError)
"""What a run without a time axis raises when its periods are asked for."""

ScoringWindow = tuple[pd.Timestamp | None, pd.Timestamp | None]
"""The ``(start, end)`` of a scoring window, naive, either bound None when open."""


@dataclass(frozen=True, slots=True)
class NetworkExtentRules:
    """The rules of ``[calibration.outputs.<n>.extent]``, with its defaults."""

    maximal_flowing_steps: int = 1
    minimal_dry_steps: int = 1
    year_quorum: float = 0.5
    visible_flow: str = DEFAULT_VISIBLE_FLOW


DEFAULT_EXTENT_RULES = NetworkExtentRules()
"""The extent rules a figure reads a run with when the run sealed none."""


@dataclass(frozen=True, slots=True)
class NetworkCriterionSettings:
    """What one network output cut its partition by, or the defaults."""

    output: str | None
    """Name of the calibration output read, None for the defaults."""

    tau_specific_ratio: float = STREAM_CRITERION_DEFAULTS.tau_specific_ratio
    diagonal_neighbors: bool = STREAM_CRITERION_DEFAULTS.diagonal_neighbors
    observed_rasterization: ObservedRasterization = STREAM_CRITERION_DEFAULTS.observed_rasterization
    weighting: Literal["cell", "area"] = "cell"
    observed_position_accuracy_m: float | None = None
    timestep: int = -1
    """The state a single-state output reads: ``-1`` for ``last``, ``0`` for ``first``.

    A date reads the index of the run's period ``[s, e)`` that holds it.
    """

    extent: NetworkExtentRules | None = None
    """The two-bound rules, None when the output reads one state."""

    n_network_outputs: int = 0
    """How many network outputs the run sealed: more than one means a choice was made."""

    scoring_window: ScoringWindow | None = None
    """The scoring window the run was scored with, None when it sealed none.

    The window of the run's phase when that phase declares one, else the
    ``[calibration]`` one. The two-bound mode scores only the complete years it
    holds: a spin-up year outside it is left out of the extents and of the year
    quorum.
    """

    scoring_window_phase: str | None = None
    """The phase whose window :attr:`scoring_window` is, None for the calibration's."""

    snap: SnapStreamsConfig | None = field(default=None, compare=False)
    """The ``[geographic.snap_streams]`` setting the run sealed, None when off."""

    @property
    def extent_rules(self) -> NetworkExtentRules:
        """Return the extent rules of the output, or the defaults."""
        return DEFAULT_EXTENT_RULES if self.extent is None else self.extent

    def note(self) -> str:
        """Say where the settings on the page come from, for a figure note."""
        if self.output is None:
            source = "criterion settings: the defaults, this run sealed no network output"
        elif self.n_network_outputs > 1:
            source = (
                f"criterion settings: calibration output {self.output!r}, "
                f"one of {self.n_network_outputs} network outputs"
            )
        else:
            source = f"criterion settings: calibration output {self.output!r}"
        if self.snap is not None:
            source += f", snap_streams {self.snap.mode}"
        if self.scoring_window is not None:
            start, end = self.scoring_window
            source += f", scoring_window {_date_or_open(start)} to {_date_or_open(end)}"
            if self.scoring_window_phase is not None:
                source += f" of phase {self.scoring_window_phase!r}"
        return source


def _date_or_open(bound: pd.Timestamp | None) -> str:
    """Return one bound of a scoring window for a note."""
    return "open" if bound is None else bound.date().isoformat()


DEFAULT_CRITERION_SETTINGS = NetworkCriterionSettings(output=None)
"""The settings of a run that sealed no network output."""


def network_outputs_of_run(sim: Run) -> dict[str, Mapping[str, Any]]:
    """Return the network outputs a run sealed, by name, in declaration order."""
    outputs = _calibration_section(sim).get("outputs")
    if not isinstance(outputs, Mapping):
        return {}
    return {
        str(name): payload
        for name, payload in outputs.items()
        if isinstance(payload, Mapping) and payload.get("support") == _NETWORK_SUPPORT
    }


def _calibration_section(sim: Run) -> Mapping[str, Any]:
    """Return the ``[calibration]`` table a run sealed, empty when it sealed none."""
    try:
        snapshot = getattr(sim, "config_snapshot", None)
    except _MISSING_SNAPSHOT as exc:
        logger.debug("Run %s: no configuration snapshot (%s).", getattr(sim, "sim_id", "?"), exc)
        return {}
    if not isinstance(snapshot, Mapping):
        return {}
    calibration = snapshot.get("calibration")
    return calibration if isinstance(calibration, Mapping) else {}


def network_criterion_settings(sim: Run, *, output: str | None = None) -> NetworkCriterionSettings:
    """Return the settings the run's network output was scored with.

    ``output`` names the calibration output to read. Left None, the run's only
    network output is read, or its first one when it sealed several, and the
    note says so. A run that sealed none reads the defaults. A named output the
    run does not hold is refused, and so is a sealed value no trial could have
    read.
    """
    outputs = network_outputs_of_run(sim)
    snap = snap_settings_of_run(sim)
    if output is not None and output not in outputs:
        held = ", ".join(repr(name) for name in outputs) or "none"
        raise ValueError(
            f"run {getattr(sim, 'sim_id', '?')} sealed no network output {output!r} "
            f"(network outputs: {held})."
        )
    if not outputs:
        return NetworkCriterionSettings(output=None, snap=snap)
    name = next(iter(outputs)) if output is None else output
    window, phase = _window_of_run(sim)
    return _settings_of_output(
        sim,
        name,
        outputs[name],
        n_outputs=len(outputs),
        snap=snap,
        scoring_window=window,
        scoring_window_phase=phase,
    )


def _window_of_run(sim: Run) -> tuple[ScoringWindow | None, str | None]:
    """Return the scoring window the run was scored with, and its phase.

    A phase declaring a ``scoring_window`` replaces the calibration's for every
    block it scores, exactly as the staged runner builds that phase. A phase
    declaring none, or a run tied to no phase, reads the calibration's.
    """
    calibration = _calibration_section(sim)
    name = _phase_of_run(sim)
    phase = _sealed_phase(calibration, name) if name is not None else None
    if phase is not None and phase.get("scoring_window") is not None:
        where = f"calibration.phases.{name}.scoring_window"
        return _scoring_window(phase["scoring_window"], where=where), name
    return _scoring_window(calibration.get("scoring_window")), None


def _sealed_phase(calibration: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    """Return the sealed ``[[calibration.phases]]`` entry of that name, or None."""
    for phase in calibration.get("phases") or ():
        if isinstance(phase, Mapping) and phase.get("name") == name:
            return phase
    return None


def _phase_of_run(sim: Run) -> str | None:
    """Return the phase of the calibration session the run's trial belongs to.

    None when the run belongs to no session, to several, or to a session that
    ran no phase. Only the session rows say which phase a run was scored in.
    """
    try:
        trials = calibration_trials(sim)
    except (ValueError, AttributeError):
        # No trial names this run, or a run-shaped view carries no queryable
        # catalog: either way no session says which phase scored it.
        return None
    if "session_id" not in trials.columns:
        return None
    named = {_bare_id(value) for value in trials["session_id"] if value is not None}
    if len(named) != 1:
        return None
    (session,) = named
    sessions = calibration_sessions(sim)
    if sessions.empty or "session_id" not in sessions.columns:
        return None
    for row in sessions.to_dict("records"):
        if _bare_id(row["session_id"]) == session:
            phase = row.get("phase_name")
            return None if phase is None or pd.isna(phase) else str(phase)
    return None


def _bare_id(value: Any) -> str:
    """Return a session id as bare lowercase hex, whatever its spelling."""
    return str(value).replace("-", "").lower()


def _settings_of_output(
    sim: Run,
    name: str,
    payload: Mapping[str, Any],
    *,
    n_outputs: int,
    snap: SnapStreamsConfig | None,
    scoring_window: ScoringWindow | None,
    scoring_window_phase: str | None,
) -> NetworkCriterionSettings:
    """Read one sealed network output, with the defaults for an absent key."""
    where = f"calibration output {name!r}"
    defaults = DEFAULT_CRITERION_SETTINGS
    tau = float(payload.get("tau_specific_ratio", defaults.tau_specific_ratio))
    if not tau >= 0.0:
        raise ValueError(f"{where}: tau_specific_ratio must be positive, got {tau!r}.")
    rasterization = payload.get("observed_rasterization", defaults.observed_rasterization)
    if rasterization not in _RASTERIZATIONS:
        raise ValueError(f"{where}: unknown observed_rasterization {rasterization!r}.")
    weighting = payload.get("weighting", defaults.weighting)
    if weighting not in _WEIGHTINGS:
        raise ValueError(f"{where}: unknown weighting {weighting!r}.")
    timestep = _timestep_of_time(sim, payload.get("time", "last"), where=where)
    return NetworkCriterionSettings(
        output=name,
        tau_specific_ratio=tau,
        diagonal_neighbors=bool(payload.get("diagonal_neighbors", defaults.diagonal_neighbors)),
        observed_rasterization=rasterization,
        weighting=weighting,
        observed_position_accuracy_m=_accuracy_m(
            payload.get("observed_position_accuracy"), where=where
        ),
        timestep=timestep,
        extent=_extent_rules(payload.get("extent"), where=where),
        n_network_outputs=n_outputs,
        snap=snap,
        scoring_window=scoring_window,
        scoring_window_phase=None if scoring_window is None else scoring_window_phase,
    )


def _timestep_of_time(sim: Run, time: Any, *, where: str) -> int:
    """Return the timestep a single-state output reads.

    ``"last"`` and ``"first"`` read ``-1`` and ``0``. A date reads the period
    ``[s, e)`` that holds it, on the run's own period edges, by the rule the
    trials scored the output with
    (:func:`hydromodpy.core.time.selection.resolve_state`). A date the run
    does not hold is refused, as the calibration refused it.
    """
    if isinstance(time, str) and time in _TIMESTEP_OF_TIME:
        return _TIMESTEP_OF_TIME[time]
    if not isinstance(time, str | datetime.date):
        raise ValueError(
            f"{where}: a network output reads 'last', 'first' or one date, got {time!r}."
        )
    edges = _run_edges(sim)
    n_periods = len(edges) - 1 if edges is not None else _stored_steps(sim)
    try:
        return resolve_state(time, edges, n_periods=n_periods)
    except TimeSelectionError as exc:
        raise ValueError(f"{where}: time = {time!r} names no state of this run: {exc}") from exc


def _run_edges(sim: Run) -> pd.DatetimeIndex | None:
    """Return the ``n + 1`` period edges of a run, or None when it carries no dates.

    The edges the catalog places on the calendar, else the ones the end stamps
    imply, as a trial reads a stack served without its time grid.
    """
    try:
        edges = sim.periods.edges
    except _NO_TIME_AXIS:
        edges = None
    if edges is not None and len(edges) >= 2:
        return pd.DatetimeIndex(edges)
    try:
        stamps = sim.time_index
    except _NO_TIME_AXIS:
        return None
    if stamps is None or len(stamps) < 2:
        return None
    return period_edges(stamps)


def _stored_steps(sim: Run) -> int:
    """Return how many states a run without dates stored, one when it cannot say."""
    try:
        count = int(getattr(sim, "n_timesteps", 0) or 0)
    except _NO_TIME_AXIS:
        count = 0
    return count if count > 0 else 1


def _accuracy_m(value: Any, *, where: str) -> float | None:
    """Return a sealed positional accuracy in metres, or None when unset.

    A snapshot dumps a length as its magnitude in metres; a hand-written
    mapping may still carry its unit.
    """
    if value is None:
        return None
    metres, _ = parse_to_m(value, location=f"{where}.observed_position_accuracy")
    return float(metres)


def _extent_rules(payload: Any, *, where: str) -> NetworkExtentRules | None:
    """Return the sealed extent rules, or None for a single-state output."""
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError(f"{where}: the extent table is not a mapping, got {payload!r}.")
    defaults = DEFAULT_EXTENT_RULES
    visible = str(payload.get("visible_flow", defaults.visible_flow))
    parse_visible_flow(visible)
    return NetworkExtentRules(
        maximal_flowing_steps=int(
            payload.get("maximal_flowing_steps", defaults.maximal_flowing_steps)
        ),
        minimal_dry_steps=int(payload.get("minimal_dry_steps", defaults.minimal_dry_steps)),
        year_quorum=float(payload.get("year_quorum", defaults.year_quorum)),
        visible_flow=visible,
    )


def _scoring_window(
    payload: Any, *, where: str = "calibration.scoring_window"
) -> ScoringWindow | None:
    """Return the sealed scoring window as naive timestamps, or None when unset.

    A zoned bound keeps its wall clock, the clock
    :func:`hydromodpy.results.derive.stream_extent.run_step_edges` reads a run
    on. A window with both bounds open is no window.
    """
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError(f"{where} is not a mapping, got {payload!r}.")
    bounds: list[pd.Timestamp | None] = []
    for key in ("start", "end"):
        raw = payload.get(key)
        if raw is None:
            bounds.append(None)
            continue
        try:
            stamp = pd.Timestamp(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{where}.{key} {raw!r} is not a date.") from exc
        bounds.append(stamp.tz_localize(None) if stamp.tz is not None else stamp)
    if bounds[0] is None and bounds[1] is None:
        return None
    return (bounds[0], bounds[1])
